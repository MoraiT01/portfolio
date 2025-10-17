import pendulum
from airflow import DAG
from airflow.configuration import conf
from airflow.operators.dummy import DummyOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python import PythonOperator, PythonVirtualenvOperator, BranchPythonOperator

from datetime import datetime, timedelta


now = pendulum.now(tz="UTC")
now_to_the_hour = (now - timedelta(0, 0, 0, 0, 0, 3)).replace(minute=0, second=0, microsecond=0)
START_DATE = now_to_the_hour

default_args = {
    "owner": "airflow",
    "description": "HAnS chapter topics and questionnaires translation for frontend",
    "depend_on_past": False,
    "start_date": START_DATE,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
}

# DAG name is the dag_id and needs to contain a version string at the end.
# The version part is starting with "_v" and uses semantic versioning
# A new major version will result in a new hans python file, e.g. "hans_v2.py"
# A new TaskGroup which is introduced will increase the minor version, e.g. "hans_v1.1.0"
# Fixes will increase the last part of the version number, e.g. "hans_v1.0.1"
# Limit active DAG runs to 1 to not stuck with resources e.g. RAM or CPU on docker,
# see https://www.astronomer.io/guides/airflow-scaling-workers/ and
# https://airflow.apache.org/docs/apache-airflow/stable/faq.html#how-to-improve-dag-performance
DAG_NAME = "translate_topics_quests_v1.0.0"
with DAG(DAG_NAME, default_args=default_args, schedule_interval=None, catchup=False, max_active_runs=1) as dag:
    now = datetime.now()
    time_started = now.strftime("%m_%d_%Y_%H_%M_%S")

    # DEVELOPER CONFIGURATION
    do_use_orchestrator = False
    do_use_nlp_translate_remote = True
    # CONFIGURATION END

    # Used to create unique docker container id
    container_id = time_started

    # TASK GROUPS USED IN GRAPH DEFINITION

    from modules.task_groups.download import download_media_files

    group0 = download_media_files(dag)

    # topic segmentation of video content
    from modules.task_groups.topic_quest_trl import topic_quest_trl

    ts_config = {
        "use_nlp_translate_remote": do_use_nlp_translate_remote,
        "use_orchestrator": do_use_orchestrator,
        "use_gpu": False,
    }
    group6 = topic_quest_trl(dag, "download_media_files", container_id, config=ts_config)

    # PUBLISHING TASK GROUP

    # Artefacts to be uploaded to backend in publishing task group
    from modules.operators.transfer import Artefact, HansType

    # fmt: off
    # Main metadata artefact used to store the metadata in metadb
    meta_artefact = Artefact(dag.dag_id, "download_media_files", "op_download_and_store_local",
            "meta_urn", HansType.META_DATA, "assetdb-temp", "archive", "metadb", "meta:post:id")

    all_artefacts_with_urns = [
        Artefact(dag.dag_id, "download_media_files", "op_download_and_store_local",
            "topic_result_de_urn", HansType.TOPIC_RESULT_DE, "assetdb-temp", "archive", "assetdb", "assets"),
        Artefact(dag.dag_id, "topic_quest_trl", "op_create_new_urn_on_assetdbtemp",
            "topic_result_en_urn", HansType.TOPIC_RESULT_EN, "assetdb-temp", "archive", "assetdb", "assets"),
        Artefact(dag.dag_id, "download_media_files", "op_download_and_store_local",
            "questionnaire_result_de_urn", HansType.QUESTIONNAIRE_RESULT_DE, "assetdb-temp", "archive", "assetdb", "assets"),
        Artefact(dag.dag_id, "topic_quest_trl", "op_create_new_urn_on_assetdbtemp",
            "questionnaire_result_en_urn", HansType.QUESTIONNAIRE_RESULT_EN, "assetdb-temp", "archive", "assetdb", "assets")
    ]

    from modules.task_groups.publish import publish_update_artefacts
    group9 = publish_update_artefacts(
        dag,
        "download_media_files",
        [],
        all_artefacts_with_urns,
        meta_artefact,
        time_started,
        4
    )

    # GRAPH DEFINITION
    group0 >> group6 >> group9
