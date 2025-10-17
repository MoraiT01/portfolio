#!/usr/bin/env python
"""
Opensearch operators for document preparation.
"""
import uuid
from os import access
from urllib.request import urlopen
from airflow import DAG
import requests
from airflow.operators.python import PythonVirtualenvOperator


# Specify minio version to be used in all PythonVirtualenvOperator
PIP_REQUIREMENT_MINIO = "minio"


def create_vector(chunk: str, tei_url: str) -> list[list[float]]:
    # Call embedding service to create chunk vectors
    all_embeddings = []
    payload = {"inputs": [chunk]}
    response = requests.post(tei_url, json=payload)
    embeddings_data = response.json()
    return embeddings_data[0]


def create_opensearch_summary_vector(
    summary_data,
    summary_data_key,
    download_data,
    download_meta_urn_key,
    opensearch_vectors_data,
    opensearch_vectors_urn_key,
    use_orchestrator=False,
):
    """
    Creates the opensearch vector entries (of one video) for the opensearch engine.

    :param str summary_data: XCOM data containing URN for the normalized asr result en json.
    :param str summary_data_key: XCOM Data key to used to determine the URN for the normalized asr result en json.
    :param str download_data: XCOM data containing URN for the meta data.
    :param str download_meta_urn_key: XCOM Data key to used to determine the URN for the meta data.
    :param str opensearch_vectors_data: XCOM data containing URN for the upload of the opensearch document to assetdb-temp
    :param str opensearch_vectors_urn_key: XCOM Data key to used to determine the URN for the upload of the opensearch document.
    :param bool use_orchestrator: Whether to use inference orchestrator for text embedding service or not.
    """
    import json
    import time
    from collections import Counter
    from io import BytesIO
    from copy import deepcopy
    from airflow.exceptions import AirflowFailException
    from modules.connectors.connector_provider import connector_provider
    from modules.operators.connections import get_assetdb_temp_config, get_connection_config
    from modules.operators.transfer import HansType
    from modules.operators.xcom import get_data_from_xcom
    from modules.operators.opensearch_summary_vector import create_vector

    # Get assetdb-temp config from airflow connections
    assetdb_temp_config = get_assetdb_temp_config()

    # Configure connector_provider and connect assetdb_temp_connector
    connector_provider.configure({"assetdb_temp": assetdb_temp_config})

    assetdb_temp_connector = connector_provider.get_assetdbtemp_connector()
    assetdb_temp_connector.connect()

    summary_urn = get_data_from_xcom(summary_data, [summary_data_key])
    summary_response = assetdb_temp_connector.get_object(summary_urn)
    if "500 Internal Server Error" in summary_response.data.decode("utf-8"):
        raise AirflowFailException()
    summary_json = json.loads(summary_response.data)
    summary_response.close()
    summary_response.release_conn()

    # Load metadata File
    metadata_urn = get_data_from_xcom(download_data, [download_meta_urn_key])
    meta_response = assetdb_temp_connector.get_object(metadata_urn)
    if "500 Internal Server Error" in meta_response.data.decode("utf-8"):
        raise AirflowFailException()

    meta_data = json.loads(meta_response.data)
    meta_response.close()
    meta_response.release_conn()

    # Get text embedding service remote config
    tei_config = get_connection_config("text_embedding_remote")
    tei_schema = tei_config["schema"]
    tei_host = tei_config["host"]
    tei_port = str(tei_config["port"])

    tei_url_base = tei_schema + "://" + tei_host + ":" + tei_port
    if use_orchestrator is True:
        tei_url_demand = tei_url_base + "/demand_text_embedding_service"  # Todo: verify url defined by orchestrator
        tei_url_info = tei_url_base + "/info"
        # TODO: call demand and check availability with info until TEI service is available
        tei_url = tei_url_base + "/text_embedding_service/embed"
    else:
        tei_url = tei_url_base + "/embed"

    print("***** TEI URL:", tei_url, flush=True)
    summary_text = summary_json["result"][0]["summary"]
    # sentences_en = [
    #     s["transcript_formatted"].strip() for s in transcript_en_json["result"] if s["transcript_formatted"].strip()
    # ]
    # intervals = [s["interval"] for s in transcript_en_json["result"] if s["transcript_formatted"].strip()]
    # assert len(sentences_en) == len(intervals), "Sentences and intervals have different lengths"
    # print(f"Num sents transcript EN: {len(sentences_en)}")

    out_data = dict()
    # out_data["type"] = "summary_vector"
    out_data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    out_data["title"] = meta_data["title"]
    out_data["course"] = meta_data["description"]["course"]
    out_data["course_acronym"] = meta_data["description"]["course_acronym"]
    out_data["faculty"] = meta_data["description"]["faculty"]
    out_data["faculty_acronym"] = meta_data["description"]["faculty_acronym"]
    out_data["university"] = meta_data["description"]["university"]
    out_data["university_acronym"] = meta_data["description"]["university_acronym"]
    out_data["language"] = meta_data["language"]
    out_data["tags"] = meta_data["tags"]
    out_data["lecturer"] = meta_data["description"]["lecturer"]
    out_data["semester"] = meta_data["description"]["semester"]

    # Add temporary ID fields
    out_data["lecture_id"] = "<undefined>"  # will be added when inserting entry in vector index
    # Create vectors
    vector = create_vector(summary_text, tei_url)
    out_data["embedding"] = vector

    # Store data
    data = json.dumps(out_data).encode("utf-8")
    stream_bytes = BytesIO(data)
    meta_minio = {}
    opensearch_vectors_urn = get_data_from_xcom(opensearch_vectors_data, [opensearch_vectors_urn_key])
    (success, object_name) = assetdb_temp_connector.put_object(
        opensearch_vectors_urn, stream_bytes, HansType.get_mime_type(HansType.SEARCH_SUMMARY_DATA_VECTOR), meta_minio
    )
    if not success:
        print("Error uploading search_summary_data_vector to assetdb-temp!")
        raise AirflowFailException()

    return json.dumps({"result": object_name})


def op_create_opensearch_summary_vector(
    dag,
    dag_id,
    task_id_suffix,
    summary_data,
    summary_data_key,
    download_data,
    download_meta_urn_key,
    opensearch_data,
    opensearch_urn_key,
):
    """
    Provides PythonVirtualenvOperator to create an opensearch document on the assetdb-temp storage.

    :param DAG dag: Airflow DAG which uses the operator.
    :param str dag_id: The Airflow DAG id of the DAG where the operator is executed.
    :param str task_id_suffix: Suffix for the operator task_id.
    :param str summary_data: XCOM data containing URN for the summary result en/de json.
    :param str summary_data_key: XCOM Data key to used to determine the URN for the summary result en/de json.
    :param str download_data: XCOM data containing URN for the meta data.
    :param str download_meta_urn_key: XCOM Data key to used to determine the URN for the meta data.
    :param str opensearch_data: XCOM data containing URN for the upload of the opensearch document to assetdb-temp
    :param str opensearch_urn_key: XCOM Data key to used to determine the URN for the upload of the opensearch document.

    :return: PythonVirtualenvOperator Operator to create opensearch document on the assetdb-temp storage.
    """
    from modules.operators.xcom import gen_task_id

    return PythonVirtualenvOperator(
        task_id=gen_task_id(dag_id, "op_create_opensearch_summary_vector", task_id_suffix),
        python_callable=create_opensearch_summary_vector,
        op_args=[
            summary_data,
            summary_data_key,
            download_data,
            download_meta_urn_key,
            opensearch_data,
            opensearch_urn_key,
        ],
        # requirements=[PIP_REQUIREMENT_MINIO, 'nltk'],
        requirements=[PIP_REQUIREMENT_MINIO],
        python_version="3",
        dag=dag,
    )
