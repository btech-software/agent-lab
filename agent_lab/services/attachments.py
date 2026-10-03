import os
from uuid import uuid4
import subprocess
import anyio

import hvac
from fastapi import File
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from markitdown import MarkItDown

from agent_lab.domain.exceptions.base import AudioOptimizationError, FileProcessingError
from agent_lab.domain.models import Attachment
from agent_lab.domain.repositories.attachments import AttachmentRepository
from agent_lab.infrastructure.database.vectors import DocumentRepository
from agent_lab.services.integrations import IntegrationService
from agent_lab.services.language_model_settings import LanguageModelSettingService
from agent_lab.services.language_models import LanguageModelService


class AttachmentService:
    def __init__(
        self,
        attachment_repository: AttachmentRepository,
        document_repository: DocumentRepository,
        language_model_service: LanguageModelService,
        language_model_setting_service: LanguageModelSettingService,
        integration_service: IntegrationService,
        vault_client: hvac.Client,
    ) -> None:
        self.attachment_repository = attachment_repository
        self.document_repository = document_repository
        self.language_model_service = language_model_service
        self.language_model_setting_service = language_model_setting_service
        self.integration_service = integration_service
        self.vault_client = vault_client

    def get_attachments(self, schema: str) -> list[Attachment]:
        return self.attachment_repository.get_all(schema)

    def get_attachment_by_id(self, attachment_id: str, schema: str) -> Attachment:
        return self.attachment_repository.get_by_id(attachment_id, schema)

    async def create_attachment_with_file(self, file: File, schema: str) -> Attachment:
        temp_file_path = f"temp-{uuid4()}"

        async with await anyio.open_file(temp_file_path, "wb") as buffer:
            raw_content = await file.read()
            await buffer.write(raw_content)

        if not file.content_type.startswith("audio/"):
            file_name = file.filename
            try:
                markdown = MarkItDown()
                parsed_content = markdown.convert(temp_file_path).text_content
            except Exception as e:
                raise FileProcessingError(file_name=file_name, reason=str(e))
        else:
            raw_content = self.optimize_audio(temp_file_path)
            file_name = file.filename.replace(file.filename.split(".")[-1], "mp3")
            parsed_content = ""

        attachment = self.create_attachment_with_content(
            file_name=file_name,
            raw_content=raw_content,
            parsed_content=parsed_content,
            schema=schema,
        )

        os.remove(temp_file_path)

        return attachment

    def create_attachment_with_content(
        self,
        file_name: str,
        raw_content: bytes,
        parsed_content: str,
        schema: str,
        attachment_id: str = None,
    ) -> Attachment:
        return self.attachment_repository.add(
            file_name=file_name,
            raw_content=raw_content,
            parsed_content=parsed_content,
            attachment_id=attachment_id,
            schema=schema,
        )

    def delete_attachment_by_id(self, attachment_id: str, schema: str) -> None:
        return self.attachment_repository.delete_by_id(attachment_id, schema)

    async def create_embeddings(
        self,
        attachment_id: str,
        language_model_id: str,
        collection_name: str,
        schema: str,
    ) -> Attachment:
        language_model = self.language_model_service.get_language_model_by_id(
            language_model_id, schema
        )
        lm_settings = self.language_model_setting_service.get_language_model_settings(
            language_model.id, schema
        )
        lm_settings_dict = {
            setting.setting_key: setting.setting_value for setting in lm_settings
        }

        integration = self.integration_service.get_integration_by_id(
            language_model.integration_id, schema
        )
        secrets = self.vault_client.secrets.kv.read_secret_version(
            path=f"integration_{integration.id}", raise_on_deleted_version=False
        )

        api_endpoint = secrets["data"]["data"]["api_endpoint"]
        api_key = secrets["data"]["data"]["api_key"]

        if os.getenv("EMBEDDINGS_ENDPOINT"):
            api_endpoint = os.getenv("EMBEDDINGS_ENDPOINT")

        embeddings_model = OpenAIEmbeddings(
            model=lm_settings_dict["embeddings"],
            openai_api_base=api_endpoint,
            openai_api_key=api_key,
            check_embedding_ctx_length=False,
            chunk_size=100,
        )

        attachment = self.attachment_repository.get_by_id(attachment_id, schema)
        temp_file_path = f"temp-{uuid4()}"
        async with await anyio.open_file(temp_file_path, "wb") as buffer:
            await buffer.write(attachment.parsed_content.encode())

        loader = TextLoader(temp_file_path)
        documents = loader.load_and_split(
            CharacterTextSplitter(chunk_size=512, chunk_overlap=64)
        )
        self.document_repository.add(embeddings_model, collection_name, documents)
        updated_attachment = self.attachment_repository.update_attachment(
            attachment_id, collection_name, schema
        )

        os.remove(temp_file_path)
        return updated_attachment

    def optimize_audio(self, file_path: str) -> bytes:
        try:
            temp_file_path = f"temp-{uuid4()}.mp3"
            # Run the ffmpeg command to optimize the audio
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    file_path,
                    "-b:a",
                    "64k",
                    "-ac",
                    "1",
                    "-ar",
                    "22050",
                    temp_file_path,
                ],
                check=True,
            )
            # Move the output file back to the original file path
            subprocess.run(["mv", temp_file_path, file_path], check=True)

            # Read the optimized audio file as bytes
            with open(file_path, "rb") as file:
                optimized_audio = file.read()

            return optimized_audio
        except subprocess.CalledProcessError as e:
            raise AudioOptimizationError(e)
