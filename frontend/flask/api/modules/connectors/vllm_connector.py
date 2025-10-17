#!/usr/bin/env python
"""
Connector to a hans vllm service running on slurm with
https://github.com/vllm-project/vllm
"""
__author__ = "Thomas Ranzenberger"
__copyright__ = "Copyright 2024, Technische Hochschule Nuernberg"
__license__ = "Apache 2.0"
__version__ = "1.0.0"
__status__ = "Draft"

import json
import time
import string
import re
import urllib.parse
import requests
from openai import OpenAI
from pydantic import BaseModel, Field
from urllib3.exceptions import RequestError, NewConnectionError

from api.modules.connectors.connector import Connector
from api.modules.message import Message, MessageHistory, MessageContent, TextContent, ImageContent, UrlContent
from api.modules.prompt_base import PromptBase
from api.modules.responses import ErrorResponse


class VLlmConnector(Connector):
    """
    Handle vllm connections.
    See https://docs.vllm.ai/en/latest/
    """

    def __init__(
        self,
        vllm_server,
        vllm_port,
        vllm_user,
        vllm_password,
        vllm_model_id,
        vllm_max_new_tokens,
        orchestrator_server,
        orchestrator_port,
        orchestrator_user,
        orchestrator_password,
        orchestrator_vllm_route,
        use_orchestrator,
    ):
        """
        Initialization

        :param str vllm_server: vllm server name
        :param str vllm_port: vllm port address
        :param str vllm_user: vllm user
        :param str vllm_password: vllm password
        :param str vllm_model_id: vllm model id
        :param str orchestrator_server: orchestrator server name
        :param str orchestrator_port: orchestrator port address
        :param str orchestrator_user: orchestrator user
        :param str orchestrator_password: orchestrator password
        :param str orchestrator_vllm_route: Route to vllm service via orchestrator
        :param bool use_orchestrator: Flag, if orchestrator is used
        """
        self.max_new_tokens = vllm_max_new_tokens
        self.use_orchestrator = use_orchestrator
        self.orchestrator_vllm_route = orchestrator_vllm_route
        self.vllm_model_id = vllm_model_id
        if self.use_orchestrator:
            self.server = orchestrator_server
            self.port = orchestrator_port
            self.user = orchestrator_user
            self.password = orchestrator_password
            self.pre_url = "http://" + self.server + ":" + self.port + "/" + self.orchestrator_vllm_route + "/v1"
        else:
            self.server = vllm_server
            self.port = vllm_port
            self.user = vllm_user
            self.password = vllm_password
            self.pre_url = "http://" + self.server + ":" + self.port + "/v1"

        self.client = OpenAI(api_key="EMPTY", base_url=self.pre_url)

        self.prompts = PromptBase(self.vllm_model_id)

        self.headers = {"Content-Type": "application/json"}
        super().__init__(__class__.__name__)

    def connect(self):
        """
        Connect to vllm
        """
        return self.check_health()

    def disconnect(self):
        """
        Disconnect from vllm
        """
        self.logger.info("disconnected")
        return True

    def _encode_urls_in_text(self, text: str) -> str:
        # Regular expression to text URLs (http/https)
        url_pattern = r"https?://[^\s]+"

        # Function to encode matched URLs
        def encode_match(match):
            return urllib.parse.quote(match.group(0), safe=":/?&=")

        # Find and encode all URLs in the prompt
        encoded_text = re.sub(url_pattern, encode_match, text)

        return encoded_text

    def _gen_messages(
        self,
        system_prompt,
        user_prompt: TextContent,
        images: list[ImageContent] = [],
        history: list[MessageHistory] = [],
        context_sentence=None,
    ):
        """Create openai compat message array"""
        messages = [{"role": "system", "content": system_prompt.strip()}]
        for history_item in history:
            if history_item.isUser is True:
                messages.append({"role": "user", "content": history_item.content[0].text})
            else:
                messages.append({"role": "assistant", "content": history_item.content[0].text})
        user_content = [user_prompt.model_dump()]

        # Add additional context
        if context_sentence is not None and len(context_sentence) > 0:
            user_content[0]["text"] += " " + context_sentence

        # add images here to user_content
        for image_content in images:
            user_content.append(image_content.model_dump())

        messages.append({"role": "user", "content": user_content})
        # print(json.dumps({"messages": messages}))
        return messages

    def _gen_prompt(
        self, message_data: Message, images: list[ImageContent] = [], message_content: MessageContent = None
    ):
        """
        Generate prompt for vllm

        :param Message message_data: message of the user to be sent
        :param list images: Image context
        :param MessageContent message_content: Overwrite used message content for translation mode

        :returns dict messages
        """
        curr_message_content = message_data.content[0]
        if message_content is not None:
            curr_message_content = message_content
        curr_user_prompt = curr_message_content.content[0]
        curr_user_prompt.text = curr_user_prompt.text.replace("\\n", " ").strip()

        system_prompt = self.prompts.base_system_prompt.replace("[INST] ", "")

        if message_data.actAsTutor is True:
            system_prompt = system_prompt + self.prompts.tutor_system_prompt

        if message_data.useContextAndCite is True or message_data.useContext is True:
            if message_data.useContextAndCite is True:
                system_prompt = system_prompt + self.prompts.cite_addon
            elif message_data.useContext is True:
                system_prompt = system_prompt + self.prompts.context_addon

        if curr_message_content.language == "en":
            system_prompt = system_prompt + self.prompts.language_system_prompt_en
        elif curr_message_content.language == "de":
            if message_data.useTranslate is True:
                # If translation service is used we use English only
                system_prompt = system_prompt + self.prompts.language_system_prompt_en
            else:
                system_prompt = system_prompt + self.prompts.language_system_prompt_de

        context_sentence = None
        if message_data.useContextAndCite is True or message_data.useContext is True:
            clean_context = (
                message_data.context.replace("\\\\\\\\n", "\\n")
                .replace("\\\\n\\\\n", "\\n\\n")
                .replace("\\\\n", "\\n")
                .replace("\\\n\\\n", "\\n\\n")
                .replace("\\\n", "\\n")
                .replace('\\"', " ")
                .replace('"', " ")
                .strip()
            )
            # clean_context = ''.join(filter(lambda x: x in string.printable, clean_context)).strip()
            # clean_context = self._encode_urls_in_text(clean_context)
            if message_data.useContextAndCite is True:
                context_sentence = (
                    "Give appropriate citations refering to the following "
                    + self.prompts.prompt_context_tag
                    + f" sections: {clean_context}"
                )
            else:
                context_sentence = "Use the following " + self.prompts.prompt_context_tag + f": {clean_context}"

        return self._gen_messages(system_prompt, curr_user_prompt, images, message_data.history, context_sentence)

    def _query_vllm(self, messages, schema=None, stream=False):
        """
        Query vllm with messages
        """
        if stream is True:
            print("Ask vllm use streaming", flush=True)
            if schema is None:
                response = self.client.chat.completions.create(
                    messages=messages,
                    model=self.vllm_model_id,
                    max_tokens=self.max_new_tokens,
                    n=1,
                    timeout=360.0,
                    stream=stream,
                )
            else:
                response = self.client.chat.completions.create(
                    messages=messages,
                    model=self.vllm_model_id,
                    max_tokens=self.max_new_tokens,
                    n=1,
                    timeout=360.0,
                    response_format={"type": "json_object", "schema": dict(schema)},
                    stream=stream,
                )
            return response
        else:
            print("Ask vllm", flush=True)
            if schema is None:
                start_time = time.time()
                response = self.client.chat.completions.create(
                    messages=messages, model=self.vllm_model_id, max_tokens=self.max_new_tokens, n=1, timeout=360.0
                )
                end_time = time.time()
                el_time = end_time - start_time
                print(f"Elapsed time vllm generation: {el_time:.2f} seconds", flush=True)
            else:
                start_time = time.time()
                response = self.client.chat.completions.create(
                    messages=messages,
                    model=self.vllm_model_id,
                    max_tokens=self.max_new_tokens,
                    n=1,
                    response_format={"type": "json_object", "schema": dict(schema)},
                    timeout=360.0,
                )
                end_time = time.time()
                el_time = end_time - start_time
                print(f"Elapsed time vllm generation: {el_time:.2f} seconds", flush=True)
            if len(response.choices) > 0:
                return response.choices[0].message.content
        return None

    def _create_vllm_result(self, message_data: Message, response_text, language=None) -> dict:
        """
        Parses vllm response and creates LlmResult
        """
        curr_language = message_data.content[0].language
        if language is not None:
            curr_language = language
        result = {
            "data": [
                {
                    "type": "LlmResult",
                    "result": [
                        {
                            "content": [
                                {"language": curr_language, "content": [{"type": "text", "text": response_text}]}
                            ],
                            "isUser": False,
                            "context": message_data.context,
                            "contextUuid": message_data.contextUuid,
                            "useContext": message_data.useContext,
                            "useContextAndCite": message_data.useContextAndCite,
                            "useVision": message_data.useVision,
                            "useVisionSurroundingSlides": message_data.useVisionSurroundingSlides,
                            "useVisionSnapshot": message_data.useVisionSnapshot,
                            "snapshot": message_data.snapshot,
                            "actAsTutor": message_data.actAsTutor,
                            "useTranslate": message_data.useTranslate,
                            "stream": message_data.stream,
                        }
                    ],
                }
            ]
        }
        return result

    def check_health(self):
        """
        Check vllm webservice for health
        """
        try:
            if self.use_orchestrator:
                url = "http://" + self.server + ":" + self.port + "/check_vllm_service"
            else:
                # vllm own health
                url = "http://" + self.server + ":" + self.port + "/health"
            print(f"Health check vllm: {url}")
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()  # Raise HTTPError for bad status codes
            if response.status_code == 200:
                if self.use_orchestrator:
                    json_data = json.loads(response.content)
                    # print(f'json_data {json_data}')
                    if json_data["running"] and json_data["started"]:
                        print(f"Health check vllm - True")
                        return True
                    else:
                        print(f"Health check vllm - False - Reason: {json_data['reason']}")
                        return False
                else:
                    return True
            else:
                return False
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as err:
            self.logger.error(err)
            return False

    def request_service(self):
        """
        Request vllm service run up
        """
        try:
            if self.use_orchestrator:
                url = "http://" + self.server + ":" + self.port + "/demand_vllm_service"
                print(f"Request vllm service via: {url}")
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()  # Raise HTTPError for bad status codes
                if response.status_code == 200:
                    return True
                else:
                    return None
            else:
                return self.check_health()
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as err:
            self.logger.error(err)
            return None

    def get_info(self):
        """
        Get vllm webservice info
        """
        model_sha = "unknown"
        max_new_tokens = 16384
        model_dtype = "torch.float16"
        max_total_tokens = 32768
        try:
            model_list = self.client.models.list()
            for model in model_list.data:
                if model.id == self.vllm_model_id:
                    model_sha = "aaef4baf771761a81ba89465a18e4427f3a105f9"
                    max_new_tokens = self.max_new_tokens
                    model_dtype = "torch.float16"
                    max_total_tokens = 131072
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as err:
            self.logger.error(err)
            return None
        return {
            "model_id": self.vllm_model_id,
            "model_sha": model_sha,
            "model_dtype": model_dtype,
            "max_new_tokens": max_new_tokens,
            "max_total_tokens": max_total_tokens,
        }

    def gen_image_context(self, message_data: Message, assetdb_connector, media_item):
        """
        Generate image context for vllm
        """
        ending = "\\n"
        image_context = []
        image_context_str = ""
        if message_data.useVision is True or message_data.useVisionSurroundingSlides is True:
            slides_images_base_urn = media_item["slides_images_meta"].rsplit("/")[0]
            slide_vector_comp_result = assetdb_connector.get_object(media_item["slides_images_meta"])
            slide_vector_comp_dict = json.loads(slide_vector_comp_result.data)
            p_start = slide_vector_comp_dict["page"]["start"]
            p_end = slide_vector_comp_dict["page"]["end"]
            pattern = r"\[(Slide|Folie|slide|folie) (\d+)\]"
            # Find all matches in the text
            matches = re.findall(pattern, message_data.content[0].content[0].text)
            # Extract and print the numbers
            pages_added = []
            for match in matches:
                slide_type, number = match
                page = int(number)
                if page not in pages_added:
                    slide_vector_urn = slides_images_base_urn + f"/{number}.meta.json"
                    slide_vector_result = assetdb_connector.get_object(slide_vector_urn)
                    slide_vector_dict = json.loads(slide_vector_result.data)
                    url_content = UrlContent(url=slide_vector_dict["data"])
                    curr_content = ImageContent(type="image_url", image_url=url_content)
                    image_context.append(curr_content)
                    text = slide_vector_dict["text"].strip()
                    image_context_str += f" - [{str(page + 100)}] Slide {str(page)}: {text} {ending}"
                    pages_added.append(page)
                    print(f"Added page as image with number: {page}")
                    if message_data.useVisionSurroundingSlides is True:
                        if page > p_start:
                            slide_vector_urn = slides_images_base_urn + f"/{page - 1}.meta.json"
                            slide_vector_result = assetdb_connector.get_object(slide_vector_urn)
                            slide_vector_dict = json.loads(slide_vector_result.data)
                            url_content = UrlContent(url=slide_vector_dict["data"])
                            curr_content = ImageContent(type="image_url", image_url=url_content)
                            image_context.append(curr_content)
                            text = slide_vector_dict["text"].strip()
                            image_context_str += f" - [{str(page - 1 + 100)}] Slide {str(page)}: {text} {ending}"
                            pages_added.append(page - 1)
                            print(f"Added page as image with number: {page - 1}")
                        if page > 1 and page <= p_end:
                            slide_vector_urn = slides_images_base_urn + f"/{page + 1}.meta.json"
                            slide_vector_result = assetdb_connector.get_object(slide_vector_urn)
                            slide_vector_dict = json.loads(slide_vector_result.data)
                            url_content = UrlContent(url=slide_vector_dict["data"])
                            curr_content = ImageContent(type="image_url", image_url=url_content)
                            image_context.append(curr_content)
                            text = slide_vector_dict["text"].strip()
                            image_context_str += f" - [{str(page + 1 + 100)}] Slide {str(page)}: {text} {ending}"
                            pages_added.append(page + 1)
                            print(f"Added page as image with number: {page + 1}")
        elif message_data.useVisionSnapshot is True:
            url_content = UrlContent(url=message_data.snapshot)
            curr_content = ImageContent(type="image_url", image_url=url_content)
            image_context.append(curr_content)
            image_context_str += f" - [999] Snapshot 0: {ending}"

        return (image_context_str, image_context)

    def post_vllm(self, message_data: Message, assetdb_connector, media_item, schema=None):
        """
        Post message to vllm webservice
        """
        print(f"Sending request to vllm: {self.pre_url}")
        (_, images) = self.gen_image_context(message_data, assetdb_connector, media_item)
        # print(f"Context: {message_data.context}")
        # print(f"History: {message_data.history}")
        if message_data.useTranslate is True:
            for message_content in message_data.content:
                if message_content.language == "en":
                    messages = self._gen_prompt(message_data, images, message_content)
                    response = self._query_vllm(messages, schema, message_data.stream)
                    return self._create_vllm_result(message_data, response, message_content.language)
        else:
            messages = self._gen_prompt(message_data, images)
            response = self._query_vllm(messages, schema, message_data.stream)
            return self._create_vllm_result(message_data, response)

    def post_vllm_stream(self, message_data: Message, assetdb_connector, media_item, schema=None):
        """
        Post message to vllm webservice with streaming
        """
        print(f"Sending request to vllm using streaming: {self.pre_url}")
        (_, images) = self.gen_image_context(message_data, assetdb_connector, media_item)
        # print(f"Context: {message_data.context}")
        # print(f"History: {message_data.history}")
        if message_data.useTranslate is True:
            for message_content in message_data.content:
                if message_content.language == "en":
                    messages = self._gen_prompt(message_data, images, message_content)
                    response = self._query_vllm(messages, schema, message_data.stream)
                    if message_data.stream is True:
                        start_time = time.time()
                        final_text_response = ""
                        for chunk in response:
                            if chunk.choices[0].delta.content is not None:
                                final_text_response += chunk.choices[0].delta.content
                                yield chunk.choices[0].delta.content
                        end_time = time.time()
                        el_time = end_time - start_time
                        print(f"Elapsed time vllm generation streaming: {el_time:.2f} seconds", flush=True)
                        return self._create_vllm_result(message_data, final_text_response, message_content.language)
                    else:
                        return self._create_vllm_result(message_data, response, message_content.language)
        else:
            messages = self._gen_prompt(message_data, images)
            response = self._query_vllm(messages, schema, message_data.stream)
            if message_data.stream is True:
                start_time = time.time()
                final_text_response = ""
                for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        final_text_response += chunk.choices[0].delta.content
                        yield chunk.choices[0].delta.content
                end_time = time.time()
                el_time = end_time - start_time
                print(f"Elapsed time vllm generation streaming: {el_time:.2f} seconds", flush=True)
                return self._create_vllm_result(message_data, final_text_response)
            else:
                return self._create_vllm_result(message_data, response)
