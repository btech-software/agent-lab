import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_lab.main import app


@pytest.fixture
def client():
    yield TestClient(app)


class TestAttachmentsEndpoint:
    def _create_embeddings(
        self, client, attachment_id, language_model_id, collection_name
    ):
        return client.post(
            url="/attachments/embeddings",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "attachment_id": attachment_id,
                "language_model_id": language_model_id,
                "collection_name": collection_name,
            },
        )

    def _create_llm(self, client):
        # create integration (ollama test container mocking the openai api)
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "integration_type": "openai_api_v1",
                "api_endpoint": os.getenv("EMBEDDINGS_ENDPOINT"),
                "api_key": "ollama",
            },
        )
        integration_id = response.json()["id"]

        # create llm
        llm_response = client.post(
            url="/llms/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "integration_id": integration_id,
                "language_model_tag": "phi3",
            },
        )

        # override the openai default embeddings model with one served by ollama
        client.post(
            url="/llms/update_setting",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "language_model_id": llm_response.json()["id"],
                "setting_key": "embeddings",
                "setting_value": "bge-m3",
            },
        )

        return llm_response

    def _upload_file(self, client, filename: str, content_type: str):
        current_dir = Path(__file__).parent
        file_path = f"{current_dir}/{filename}"

        with open(file_path, "rb") as file:
            upload_response = client.post(
                url="/attachments/upload",
                headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
                files={"file": (filename, file, content_type)},
            )

        return upload_response

    def _download_file(self, client, attachment_id):
        return client.get(
            url=f"/attachments/download/{attachment_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

    @pytest.mark.asyncio
    async def test_upload_no_file_validation_error(self, client):
        response = client.post(
            "/attachments/upload",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_large_file_payload_too_large(self, client):
        # Create a temporary file with large content to simulate a large payload
        large_size = 11 * 1024 * 1024  # 11 MB
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            temp_file.write(b"a" * large_size)
            temp_file.close()
            with open(temp_file.name, "rb") as file:
                response = client.post(
                    url="/attachments/upload",
                    headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
                    files={
                        "file": (
                            os.path.basename(temp_file.name),
                            file,
                            "application/pdf",
                        )
                    },
                )
            assert response.status_code == 413
        finally:
            os.remove(temp_file.name)

    @pytest.mark.asyncio
    async def test_embeddings(self, client):
        # given
        upload_filename = "attachment.zip"
        upload_response = self._upload_file(client, upload_filename, "application/zip")
        attachment_id = upload_response.json()["id"]

        llm_response = self._create_llm(client)
        llm_id = llm_response.json()["id"]

        # when
        response = self._create_embeddings(
            client, attachment_id, llm_id, "static_document_data"
        )

        # then
        assert response.status_code == 201
        embeddings_response = response.json()
        assert embeddings_response["embeddings_collection"] == "static_document_data"

    @pytest.mark.asyncio
    async def test_reembedding_does_not_duplicate_chunks(self, client):
        from sqlalchemy import create_engine, text

        upload_response = self._upload_file(client, "attachment.zip", "application/zip")
        attachment_id = upload_response.json()["id"]
        llm_id = self._create_llm(client).json()["id"]
        engine = create_engine(
            "postgresql://postgres:postgres@localhost:15432/agent_lab_vectors"
        )

        def chunk_count():
            with engine.connect() as conn:
                return conn.execute(
                    text(
                        "SELECT count(*) FROM langchain_pg_embedding "
                        "WHERE cmetadata->>'attachment_id' = :id"
                    ),
                    {"id": attachment_id},
                ).scalar_one()

        assert (
            self._create_embeddings(
                client, attachment_id, llm_id, "reembed_a"
            ).status_code
            == 201
        )
        first = chunk_count()
        assert first > 0

        assert (
            self._create_embeddings(
                client, attachment_id, llm_id, "reembed_a"
            ).status_code
            == 201
        )
        assert chunk_count() == first

        # moving to another collection drops the chunks from the previous one
        assert (
            self._create_embeddings(
                client, attachment_id, llm_id, "reembed_b"
            ).status_code
            == 201
        )
        assert chunk_count() == first

    @pytest.mark.asyncio
    async def test_embeddings_invalid_attachment(self, client):
        # Get a valid LLM for the test
        llm_response = self._create_llm(client)
        llm_id = llm_response.json()["id"]
        # Use a non-existent attachment id to trigger a 404
        response = self._create_embeddings(
            client, "non_existent_attachment", llm_id, "static_document_data"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_embeddings_invalid_language_model(self, client):
        # Upload a file to get a valid attachment id
        upload_filename = "attachment.zip"
        upload_response = self._upload_file(client, upload_filename, "application/zip")
        attachment_id = upload_response.json()["id"]
        # Use an invalid language model id to trigger a 404
        response = self._create_embeddings(
            client, attachment_id, "non_existent_llm", "static_document_data"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_embeddings_unprocessable_entity(self, client):
        response = self._create_embeddings(
            client,
            3,
            2,
            1,  # Start your engines! :D
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_invalid_file_error(self, client):
        large_size = 1 * 1024 * 1024  # 11 MB
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            temp_file.write(b"a" * large_size)
            temp_file.close()
            with open(temp_file.name, "rb") as file:
                response = client.post(
                    url="/attachments/upload",
                    headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
                    files={
                        "file": (
                            os.path.basename(temp_file.name),
                            file,
                            "application/pdf",
                        )
                    },
                )
            assert response.status_code == 422
        finally:
            os.remove(temp_file.name)

    @pytest.mark.asyncio
    async def test_file_downloads(self, client):
        # given
        upload_filename = "attachment.zip"
        upload_response = self._upload_file(client, upload_filename, "application/zip")
        attachment_id = upload_response.json()["id"]

        # when
        download_response = self._download_file(client, attachment_id)

        # then
        assert download_response.status_code == 200

    @pytest.mark.asyncio
    async def test_file_downloads_not_found(self, client):
        # when
        download_response = self._download_file(client, "non_existent_id")

        # then
        assert download_response.status_code == 404
