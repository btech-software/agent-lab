from unittest.mock import MagicMock

import pytest

from agent_lab.domain.models import Agent, LanguageModel
from agent_lab.domain.repositories.language_models import LanguageModelNotFoundError
from agent_lab.services.agents import AgentService


@pytest.fixture
def agent_service():
    agent_repo = MagicMock()
    agent_setting_service = MagicMock()
    language_model_service = MagicMock()
    service = AgentService(
        agent_repository=agent_repo,
        agent_setting_service=agent_setting_service,
        language_model_service=language_model_service,
    )
    return service, agent_repo, agent_setting_service, language_model_service


class TestAgentService:
    def test_get_agents(self, agent_service):
        service, repo, _, _ = agent_service
        expected = [MagicMock(spec=Agent)]
        repo.get_all.return_value = expected

        result = service.get_agents(schema="test")

        assert result == expected
        repo.get_all.assert_called_once_with("test")

    def test_get_agent_by_id(self, agent_service):
        service, repo, _, _ = agent_service
        agent = MagicMock(spec=Agent)
        repo.get_by_id.return_value = agent

        result = service.get_agent_by_id(agent_id="agent-1", schema="test")

        assert result == agent
        repo.get_by_id.assert_called_once_with("agent-1", "test")

    def test_create_agent(self, agent_service):
        service, repo, _, lm_service = agent_service
        lm = MagicMock(spec=LanguageModel)
        lm.id = "lm-1"
        lm_service.get_language_model_by_id.return_value = lm
        agent = MagicMock(spec=Agent)
        repo.add.return_value = agent

        result = service.create_agent(
            agent_name="Test",
            agent_type="echo",
            language_model_id="lm-1",
            schema="test",
        )

        assert result == agent
        lm_service.get_language_model_by_id.assert_called_once_with("lm-1", "test")
        repo.add.assert_called_once_with(
            agent_name="Test",
            agent_type="echo",
            language_model_id="lm-1",
            schema="test",
        )

    def test_create_agent_without_language_model(self, agent_service):
        service, repo, _, lm_service = agent_service
        agent = MagicMock(spec=Agent)
        repo.add.return_value = agent

        result = service.create_agent(
            agent_name="Test",
            agent_type="echo",
            schema="test",
        )

        assert result == agent
        lm_service.get_language_model_by_id.assert_not_called()
        repo.add.assert_called_once_with(
            agent_name="Test",
            agent_type="echo",
            language_model_id=None,
            schema="test",
        )

    def test_create_agent_invalid_language_model(self, agent_service):
        service, repo, _, lm_service = agent_service
        lm_service.get_language_model_by_id.side_effect = LanguageModelNotFoundError(
            "bad-lm"
        )

        with pytest.raises(LanguageModelNotFoundError):
            service.create_agent(
                agent_name="Test",
                agent_type="echo",
                language_model_id="bad-lm",
                schema="test",
            )

        repo.add.assert_not_called()

    def test_delete_agent_by_id(self, agent_service):
        service, repo, _, _ = agent_service

        service.delete_agent_by_id(agent_id="agent-1", schema="test")

        repo.delete_by_id.assert_called_once_with("agent-1", "test")

    def test_update_agent(self, agent_service):
        service, repo, _, lm_service = agent_service
        lm = MagicMock(spec=LanguageModel)
        lm.id = "lm-2"
        lm_service.get_language_model_by_id.return_value = lm
        updated_agent = MagicMock(spec=Agent)
        repo.update_agent.return_value = updated_agent

        result = service.update_agent(
            agent_id="agent-1",
            agent_name="Updated",
            language_model_id="lm-2",
            schema="test",
            agent_summary="summary",
        )

        assert result == updated_agent
        lm_service.get_language_model_by_id.assert_called_once_with("lm-2", "test")
        repo.update_agent.assert_called_once_with(
            agent_id="agent-1",
            agent_name="Updated",
            language_model_id="lm-2",
            agent_summary="summary",
            schema="test",
        )

    def test_update_agent_without_language_model(self, agent_service):
        service, repo, _, lm_service = agent_service
        updated_agent = MagicMock(spec=Agent)
        repo.update_agent.return_value = updated_agent

        result = service.update_agent(
            agent_id="agent-1",
            agent_name="Updated",
            schema="test",
            agent_summary="summary",
        )

        assert result == updated_agent
        lm_service.get_language_model_by_id.assert_not_called()
        repo.update_agent.assert_called_once_with(
            agent_id="agent-1",
            agent_name="Updated",
            language_model_id=None,
            agent_summary="summary",
            schema="test",
        )

    def test_update_agent_invalid_language_model(self, agent_service):
        service, repo, _, lm_service = agent_service
        lm_service.get_language_model_by_id.side_effect = LanguageModelNotFoundError(
            "bad-lm"
        )

        with pytest.raises(LanguageModelNotFoundError):
            service.update_agent(
                agent_id="agent-1",
                agent_name="Updated",
                language_model_id="bad-lm",
                schema="test",
            )

        repo.update_agent.assert_not_called()


class TestTaskUpdatesWebsocketAuthorization:
    def _websocket(self, user_id):
        from unittest.mock import AsyncMock

        from agent_lab.infrastructure.auth.schema import User

        websocket = MagicMock()
        websocket.scope = {"user": User(id=user_id, email="a@b.c", username="a")}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        return websocket

    @pytest.mark.asyncio
    async def test_foreign_agent_is_rejected_before_streaming(self):
        from fastapi import status

        from agent_lab.domain.repositories.agents import AgentNotFoundError
        from agent_lab.interface.api.agents.endpoints import task_updates_endpoint

        websocket = self._websocket("id_tenant-a")
        agent_service = MagicMock()
        agent_service.get_agent_by_id.side_effect = AgentNotFoundError("agent-b")
        task_notification_service = MagicMock()

        await task_updates_endpoint(
            websocket=websocket,
            agent_id="agent-b",
            task_notification_service=task_notification_service,
            agent_service=agent_service,
        )

        agent_service.get_agent_by_id.assert_called_once_with("agent-b", "id_tenant_a")
        websocket.accept.assert_not_called()
        websocket.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)
        task_notification_service.subscribe.assert_not_called()
