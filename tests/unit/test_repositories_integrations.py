from unittest.mock import MagicMock, patch

import pytest

from agent_lab.domain.models import Integration
from agent_lab.domain.repositories.integrations import (
    IntegrationNotFoundError,
    IntegrationRepository,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__ = MagicMock(return_value=session)
    db.session.return_value.__exit__ = MagicMock(return_value=False)
    return db, session


@pytest.fixture
def mock_vault():
    return MagicMock()


class TestIntegrationRepository:
    def test_get_all(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        expected = [MagicMock(spec=Integration)]
        session.query.return_value.filter.return_value.all.return_value = expected

        result = repo.get_all(schema="test_schema")

        assert result == expected

    def test_get_by_id_found(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        integration = MagicMock(spec=Integration)
        session.query.return_value.filter.return_value.first.return_value = integration

        result = repo.get_by_id(integration_id="int-1", schema="test_schema")

        assert result == integration

    def test_get_by_id_not_found(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(IntegrationNotFoundError):
            repo.get_by_id(integration_id="nonexistent", schema="test_schema")

    @patch("agent_lab.domain.repositories.integrations.uuid4")
    def test_add(self, mock_uuid, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        mock_uuid.return_value = "generated-uuid"

        repo.add(
            integration_type="openai_api_v1",
            api_endpoint="https://api.openai.com",
            api_key="sk-test",
            schema="test_schema",
        )

        mock_vault.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="integration_generated-uuid",
            secret={
                "api_endpoint": "https://api.openai.com",
                "api_key": "sk-test",
            },
        )
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_delete_by_id_found(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        integration = MagicMock(spec=Integration)
        session.query.return_value.filter.return_value.first.return_value = integration

        repo.delete_by_id(integration_id="int-1", schema="test_schema")

        assert integration.is_active is False
        session.commit.assert_called_once()
        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.assert_called_once_with(
            path="integration_int-1"
        )

    def test_delete_by_id_not_found(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(IntegrationNotFoundError):
            repo.delete_by_id(integration_id="nonexistent", schema="test_schema")
        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.assert_not_called()

    @patch("agent_lab.domain.repositories.integrations.uuid4")
    def test_add_removes_secret_when_insert_fails(self, mock_uuid, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        mock_uuid.return_value = "generated-uuid"
        session.commit.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            repo.add(
                integration_type="openai_api_v1",
                api_endpoint="https://api.openai.com",
                api_key="sk-test",
                schema="test_schema",
            )

        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.assert_called_once_with(
            path="integration_generated-uuid"
        )


class TestIntegrationNotFoundError:
    def test_entity_name(self):
        assert IntegrationNotFoundError.entity_name == "Integration"

    def test_message(self):
        error = IntegrationNotFoundError("test-id")
        assert error.status_code == 404
        assert "Integration" in error.detail


class TestIntegrationSecretCleanupEdges:
    def _add(self, repo):
        return repo.add(
            integration_type="openai_api_v1",
            api_endpoint="https://api.openai.com",
            api_key="sk-test",
            schema="test_schema",
        )

    def test_refresh_failure_after_commit_keeps_secret(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        session.refresh.side_effect = RuntimeError("connection reset")

        with pytest.raises(RuntimeError):
            self._add(repo)

        session.commit.assert_called_once()
        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.assert_not_called()

    def test_cleanup_failure_does_not_mask_insert_error(self, mock_db, mock_vault):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        session.commit.side_effect = RuntimeError("db down")
        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = (
            ConnectionError("vault down")
        )

        with pytest.raises(RuntimeError, match="db down"):
            self._add(repo)

    def test_vault_failure_after_delete_commit_is_logged(
        self, mock_db, mock_vault, caplog
    ):
        db, session = mock_db
        repo = IntegrationRepository(db=db, vault_client=mock_vault)
        integration = MagicMock(spec=Integration)
        session.query.return_value.filter.return_value.first.return_value = integration
        mock_vault.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = (
            ConnectionError("vault down")
        )

        repo.delete_by_id(integration_id="int-1", schema="test_schema")

        assert integration.is_active is False
        assert "integration_int-1" in caplog.text
