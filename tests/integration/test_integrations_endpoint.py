import os
import pytest
from fastapi.testclient import TestClient

from agent_lab.main import app


@pytest.fixture
def client():
    yield TestClient(app)


class TestIntegrationsEndpoints:
    @pytest.mark.asyncio
    async def test_get_list(self, client):
        # when
        response = client.get(
            "/integrations/list",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_create_and_get_by_id_success(self, client):
        # given
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "https://example.com",
                "api_key": "an_invalid_key",
                "integration_type": "openai_api_v1",
            },
        )
        integration_id = response.json()["id"]

        # when
        response_2 = client.get(
            f"/integrations/{integration_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response_2.status_code == 200
        assert "id" in response_2.json()

    @pytest.mark.asyncio
    async def test_create_typesafe_integration_success(self, client):
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "https://api.typesafe.ai",
                "api_key": "an_invalid_key",
                "integration_type": "typesafe_api_v1",
            },
        )

        assert response.status_code == 201
        assert response.json()["integration_type"] == "typesafe_api_v1"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, client):
        # given
        integration_id = "not_existing_id"

        # when
        response = client.get(
            f"/integrations/{integration_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_and_delete_success(self, client):
        # given
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "https://example.com",
                "api_key": "an_invalid_key",
                "integration_type": "openai_api_v1",
            },
        )
        integration_id = response.json()["id"]

        # when
        response_2 = client.delete(
            f"/integrations/delete/{integration_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response_2.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client):
        # given
        integration_id = "not_existing_id"

        # when
        response = client.delete(
            f"/integrations/delete/{integration_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_invalid_endpoint_bad_request(self, client):
        # when
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "an_invalid_endpoint",
                "api_key": "an_invalid_key",
                "integration_type": "openai_api_v1",
            },
        )

        # then
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_invalid_integration_type_bad_request(self, client):
        # when
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "https://example.com",
                "api_key": "an_invalid_key",
                "integration_type": "an_invalid_integration_type",
            },
        )

        # then
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_unprocessable_entity(self, client):
        response = client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": 1,
                "api_key": "raise_value_error",
                "integration_type": "openai_api_v1",
            },
        )
        assert response.status_code == 422
