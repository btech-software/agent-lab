import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_lab.app_factory import bind_agent_registry
from agent_lab.core.config import default_config_source, load_config
from agent_lab.core.container import Container
from agent_lab.main import app
from agent_lab.services.tasks import TaskProgress


def _websocket_auth_headers():
    # browsers cannot set headers on websockets: fastapi-keycloak-middleware
    # reads the bearer token from the access_token cookie instead
    return {"Cookie": f"access_token=Bearer {os.getenv('ACCESS_TOKEN')}"}


@pytest.fixture
def client():
    yield TestClient(app)


@pytest.fixture
def container():
    cont = Container()
    load_config(cont, default_config_source())
    bind_agent_registry(cont)
    cont.init_resources()
    yield cont


class TestAgentsEndpoints:
    def _create_integration(self, client):
        # create integration
        return client.post(
            url="/integrations/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "api_endpoint": "https://example.com",
                "api_key": "an_invalid_key",
                "integration_type": "openai_api_v1",
            },
        )

    def _create_language_model(self, client, integration_id):
        # create llm
        return client.post(
            url="/llms/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "integration_id": integration_id,
                "language_model_tag": "an_invalid_tag",
            },
        )

    def _create_agent(self, client):
        # create integration
        response = self._create_integration(client)
        integration_id = response.json()["id"]

        # create llm
        response_2 = self._create_language_model(client, integration_id)
        language_model_id = response_2.json()["id"]

        # create agent
        return client.post(
            url="/agents/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "language_model_id": language_model_id,
                "agent_type": "test_echo",
                "agent_name": f"agent-{uuid4()}",
            },
        )

    @pytest.mark.asyncio
    async def test_get_list(self, client):
        # when
        response = client.get(
            "/agents/list",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_create_and_read_success(self, client):
        # given
        create_agent_response = self._create_agent(client)
        agent_id = create_agent_response.json()["id"]

        # when
        read_agent_response = client.get(
            f"/agents/{agent_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert read_agent_response.status_code == 200
        response_json = read_agent_response.json()
        assert "ag_settings" in response_json
        assert isinstance(response_json["ag_settings"], list)

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, client):
        # given
        agent_id = "not_existing_id"

        # when
        response = client.get(
            f"/agents/{agent_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_and_delete_success(self, client):
        # given
        create_agent_response = self._create_agent(client)
        agent_id = create_agent_response.json()["id"]

        # when
        delete_agent_response = client.delete(
            f"/agents/delete/{agent_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert delete_agent_response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client):
        # given
        agent_id = "not_existing_id"

        # when
        response = client.delete(
            f"/agents/delete/{agent_id}",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_invalid_agent_type_bad_request(self, client):
        # given
        create_agent_response = self._create_agent(client)
        language_model_id = create_agent_response.json()["language_model_id"]

        # when
        error_response = client.post(
            url="/agents/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "language_model_id": language_model_id,
                "agent_type": "an_invalid_agent_type",
                "agent_name": f"agent-{uuid4()}",
            },
        )

        # then
        assert error_response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_invalid_language_model_not_found(self, client):
        # given
        language_model_id = "an_invalid_language_model_id"

        # when
        error_response = client.post(
            url="/agents/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "language_model_id": language_model_id,
                "agent_type": "test_echo",
                "agent_name": f"agent-{uuid4()}",
            },
        )

        # then
        assert error_response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_invalid_unprocessable_entity(self, client):
        # when
        error_response = client.post(
            url="/agents/create",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={"foo": "bar"},
        )

        # then
        assert error_response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_invalid_unprocessable_entity(self, client):
        # when
        error_response = client.post(
            url="/agents/update",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={"foo": "bar"},
        )

        # then
        assert error_response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_agent_not_found(self, client):
        # given
        response = self._create_integration(client)
        integration_id = response.json()["id"]
        response_2 = self._create_language_model(client, integration_id)
        language_model_id = response_2.json()["id"]

        agent_id = "not_existing_id"

        # when
        response = client.post(
            url="/agents/update",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "agent_name": "a_name",
                "language_model_id": language_model_id,
            },
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_language_model_not_found(self, client):
        # given
        create_response = self._create_agent(client)
        agent_id = create_response.json()["id"]

        # when
        update_response = client.post(
            url="/agents/update",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "agent_name": "a_modified_name",
                "language_model_id": "not_existing_language_model_id",
            },
        )

        # then
        assert update_response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_invalid_agent_name_bad_request(self, client):
        # given
        create_response = self._create_agent(client)
        agent_id = create_response.json()["id"]
        language_model_id = create_response.json()["language_model_id"]

        # when
        update_response = client.post(
            url="/agents/update",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "agent_name": "a modified_name",
                "language_model_id": language_model_id,
            },
        )

        # then
        assert update_response.status_code == 400

    @pytest.mark.asyncio
    async def test_update_success(self, client):
        # given
        create_response = self._create_agent(client)
        agent_id = create_response.json()["id"]
        language_model_id = create_response.json()["language_model_id"]

        # when
        update_response = client.post(
            url="/agents/update",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "agent_name": "a_modified_name",
                "language_model_id": language_model_id,
            },
        )

        # then
        assert update_response.status_code == 200
        assert "id" in update_response.json()
        assert "a_modified_name" == update_response.json()["agent_name"]

    @pytest.mark.asyncio
    async def test_update_setting_not_found(self, client):
        # given
        agent_id = "not_existing_id"

        # when
        response = client.post(
            url="/agents/update_setting",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "setting_key": "a_key",
                "setting_value": "a_value",
            },
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_setting_key_not_found(self, client):
        # given
        create_response = self._create_agent(client)
        agent_id = create_response.json()["id"]

        # when
        update_response = client.post(
            url="/agents/update_setting",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "setting_key": "a_key",
                "setting_value": "a_value",
            },
        )

        # then
        assert update_response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_setting_success(self, client):
        # given
        client_response = self._create_agent(client)
        agent_id = client_response.json()["id"]

        # when
        update_response = client.post(
            url="/agents/update_setting",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
            json={
                "agent_id": agent_id,
                "setting_key": "dummy_setting",
                "setting_value": "another_dummy_value",
            },
        )

        # then
        assert update_response.status_code == 200
        response_json = update_response.json()
        assert "id" in response_json
        assert any(
            setting["setting_value"] == "another_dummy_value"
            for setting in response_json["ag_settings"]
        )

    @pytest.mark.asyncio
    async def test_reset_settings_success(self, client):
        # given
        create_response = self._create_agent(client)
        agent_id = create_response.json()["id"]

        # when
        reset_response = client.post(
            url=f"/agents/{agent_id}/reset_settings",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert reset_response.status_code == 200
        response_json = reset_response.json()
        assert response_json["id"] == agent_id
        assert "ag_settings" in response_json
        assert isinstance(response_json["ag_settings"], list)

    @pytest.mark.asyncio
    async def test_reset_settings_not_found(self, client):
        # given
        agent_id = "not_existing_id"

        # when
        response = client.post(
            url=f"/agents/{agent_id}/reset_settings",
            headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}"},
        )

        # then
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_notification_websocket_receives_messages(
        self, client, container
    ):
        # the endpoint only streams updates for agents in the caller's tenant
        test_agent_id = self._create_agent(client).json()["id"]
        ws_url = f"/agents/ws/task_updates/{test_agent_id}"

        with client.websocket_connect(
            ws_url,
            timeout=10,
            headers=_websocket_auth_headers(),
        ) as websocket:
            task_notification_service = container.task_notification_service()
            task_notification_service.subscribe()
            test_update = TaskProgress(
                agent_id=test_agent_id,
                status="in_progress",
                message_content="Test Message",
            )
            task_notification_service.publish_update(test_update)

            # The endpoint should receive and send back the published message.
            received = websocket.receive_json()
            assert received["agent_id"] == test_agent_id
            assert received["message_content"] == "Test Message"
            websocket.close()

    @pytest.mark.asyncio
    async def test_task_notification_websocket_rejects_unknown_agent(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as disconnect:
            with client.websocket_connect(
                "/agents/ws/task_updates/agent-of-another-tenant",
                headers=_websocket_auth_headers(),
            ):
                pass
        assert disconnect.value.code == 1008
