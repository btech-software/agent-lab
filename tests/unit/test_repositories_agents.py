from unittest.mock import MagicMock, patch

import pytest

from agent_lab.domain.models import Agent, AgentSetting
from agent_lab.domain.repositories.agents import (
    AgentNotFoundError,
    AgentRepository,
    AgentSettingNotFoundError,
    AgentSettingRepository,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__ = MagicMock(return_value=session)
    db.session.return_value.__exit__ = MagicMock(return_value=False)
    return db, session


class TestAgentRepository:
    def test_get_all(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        expected = [MagicMock(spec=Agent), MagicMock(spec=Agent)]
        session.query.return_value.filter.return_value.all.return_value = expected

        result = repo.get_all(schema="test_schema")

        assert result == expected
        db.session.assert_called_once_with(schema_name="test_schema")

    def test_get_by_id_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        agent = MagicMock(spec=Agent)
        session.query.return_value.filter.return_value.first.return_value = agent

        result = repo.get_by_id(agent_id="agent-1", schema="test_schema")

        assert result == agent

    def test_get_by_id_not_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AgentNotFoundError):
            repo.get_by_id(agent_id="nonexistent", schema="test_schema")

    @patch("agent_lab.domain.repositories.agents.uuid4")
    def test_add(self, mock_uuid, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        mock_uuid.return_value = "generated-uuid"

        repo.add(
            agent_name="Test Agent",
            agent_type="echo",
            language_model_id="lm-1",
            schema="test_schema",
        )

        session.add.assert_called_once()
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_update_agent_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        agent = MagicMock(spec=Agent)
        session.query.return_value.filter.return_value.first.return_value = agent

        repo.update_agent(
            agent_id="agent-1",
            agent_name="Updated",
            language_model_id="lm-2",
            schema="test_schema",
            agent_summary="new summary",
        )

        assert agent.agent_name == "Updated"
        assert agent.language_model_id == "lm-2"
        assert agent.agent_summary == "new summary"
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_update_agent_not_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AgentNotFoundError):
            repo.update_agent(
                agent_id="nonexistent",
                agent_name="Updated",
                language_model_id="lm-2",
                schema="test_schema",
            )

    def test_update_agent_without_summary(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        agent = MagicMock(spec=Agent)
        agent.agent_summary = "original"
        session.query.return_value.filter.return_value.first.return_value = agent

        repo.update_agent(
            agent_id="agent-1",
            agent_name="Updated",
            language_model_id="lm-2",
            schema="test_schema",
            agent_summary=None,
        )

        assert agent.agent_summary == "original"

    def test_delete_by_id_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        agent = MagicMock(spec=Agent)
        session.query.return_value.filter.return_value.first.return_value = agent

        repo.delete_by_id(agent_id="agent-1", schema="test_schema")

        assert agent.is_active is False
        session.commit.assert_called_once()

    def test_delete_by_id_not_found(self, mock_db):
        db, session = mock_db
        repo = AgentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AgentNotFoundError):
            repo.delete_by_id(agent_id="nonexistent", schema="test_schema")


class TestAgentSettingRepository:
    def test_get_all(self, mock_db):
        db, session = mock_db
        repo = AgentSettingRepository(db=db)
        expected = [MagicMock(spec=AgentSetting)]
        session.query.return_value.filter.return_value.all.return_value = expected

        result = repo.get_all(agent_id="agent-1", schema="test_schema")

        assert result == expected

    @patch("agent_lab.domain.repositories.agents.uuid4")
    def test_add(self, mock_uuid, mock_db):
        db, session = mock_db
        repo = AgentSettingRepository(db=db)
        mock_uuid.return_value = "generated-uuid"

        repo.add(
            agent_id="agent-1",
            setting_key="prompt",
            setting_value="Hello",
            schema="test_schema",
        )

        session.add.assert_called_once()
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_update_by_key_found(self, mock_db):
        db, session = mock_db
        repo = AgentSettingRepository(db=db)
        setting = MagicMock(spec=AgentSetting)
        session.query.return_value.filter.return_value.first.return_value = setting

        repo.update_by_key(
            agent_id="agent-1",
            setting_key="prompt",
            setting_value="Updated",
            schema="test_schema",
        )

        assert setting.setting_value == "Updated"
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_update_by_key_not_found(self, mock_db):
        db, session = mock_db
        repo = AgentSettingRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AgentSettingNotFoundError):
            repo.update_by_key(
                agent_id="agent-1",
                setting_key="prompt",
                setting_value="Updated",
                schema="test_schema",
            )

    def test_delete_by_agent_id(self, mock_db):
        db, session = mock_db
        repo = AgentSettingRepository(db=db)

        repo.delete_by_agent_id(agent_id="agent-1", schema="test_schema")

        session.query.return_value.filter.return_value.delete.assert_called_once_with(
            synchronize_session=False
        )
        session.commit.assert_called_once()


class TestAgentNotFoundError:
    def test_entity_name(self):
        assert AgentNotFoundError.entity_name == "Agent"

    def test_message(self):
        error = AgentNotFoundError("test-id")
        assert error.status_code == 404
        assert "Agent" in error.detail
        assert "test-id" in error.detail


class TestAgentSettingNotFoundError:
    def test_entity_name(self):
        assert AgentSettingNotFoundError.entity_name == "AgentSetting"


class TestDatabaseSchemaName:
    def _db(self):
        from agent_lab.infrastructure.database.sql import Database

        return Database("postgresql://u:p@localhost:1/db")

    def test_uuid_schema_is_kept(self):
        schema = "id_5f0c1e2a-9b7d-4c3e-8a1f-0d2b3c4e5f60"
        assert (
            self._db().sanitize_schema_name(schema)
            == "id_5f0c1e2a_9b7d_4c3e_8a1f_0d2b3c4e5f60"
        )

    @pytest.mark.parametrize(
        "schema",
        [
            "id_x; DROP SCHEMA public CASCADE",
            "id_user@example.com",
            "id_a.b",
            'id_a"b',
            "1abc",
            "",
            "id_" + "a" * 61,
        ],
    )
    def test_non_identifier_schema_is_rejected(self, schema):
        with pytest.raises(ValueError):
            self._db().sanitize_schema_name(schema)
