from unittest.mock import MagicMock, call

import pytest

from agent_lab.domain.models import Integration, LanguageModel
from agent_lab.domain.repositories.integrations import IntegrationNotFoundError
from agent_lab.services.language_models import LanguageModelService


@pytest.fixture
def lm_service():
    repo = MagicMock()
    setting_service = MagicMock()
    integration_service = MagicMock()
    service = LanguageModelService(
        language_model_repository=repo,
        language_model_setting_service=setting_service,
        integration_service=integration_service,
    )
    return service, repo, setting_service, integration_service


class TestLanguageModelService:
    def test_get_language_models(self, lm_service):
        service, repo, _, _ = lm_service
        expected = [MagicMock(spec=LanguageModel)]
        repo.get_all.return_value = expected

        result = service.get_language_models(schema="test")

        assert result == expected
        repo.get_all.assert_called_once_with("test")

    def test_get_language_model_by_id(self, lm_service):
        service, repo, _, _ = lm_service
        lm = MagicMock(spec=LanguageModel)
        repo.get_by_id.return_value = lm

        result = service.get_language_model_by_id(
            language_model_id="lm-1", schema="test"
        )

        assert result == lm
        repo.get_by_id.assert_called_once_with("lm-1", "test")

    def test_create_language_model_openai(self, lm_service):
        service, repo, setting_service, integration_service = lm_service
        integration = MagicMock(spec=Integration)
        integration.id = "int-1"
        integration.integration_type = "openai_api_v1"
        integration_service.get_integration_by_id.return_value = integration

        lm = MagicMock(spec=LanguageModel)
        lm.id = "lm-1"
        repo.add.return_value = lm

        result = service.create_language_model(
            integration_id="int-1",
            language_model_tag="gpt-4",
            schema="test",
        )

        assert result == lm
        integration_service.get_integration_by_id.assert_called_once_with(
            "int-1", "test"
        )
        repo.add.assert_called_once_with(
            integration_id="int-1",
            language_model_tag="gpt-4",
            schema="test",
        )
        assert setting_service.create_language_model_setting.call_count == 4
        setting_service.create_language_model_setting.assert_has_calls(
            [
                call(
                    language_model_id="lm-1",
                    setting_key="embeddings",
                    setting_value="text-embedding-3-large",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="max_tokens",
                    setting_value="16384",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="timeout",
                    setting_value="600",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="structured_output_method",
                    setting_value="default",
                    schema="test",
                ),
            ]
        )

    def test_create_language_model_other_type(self, lm_service):
        service, repo, setting_service, integration_service = lm_service
        integration = MagicMock(spec=Integration)
        integration.id = "int-1"
        integration.integration_type = "custom_api"
        integration_service.get_integration_by_id.return_value = integration

        lm = MagicMock(spec=LanguageModel)
        lm.id = "lm-1"
        repo.add.return_value = lm

        result = service.create_language_model(
            integration_id="int-1",
            language_model_tag="custom-model",
            schema="test",
        )

        assert result == lm
        assert setting_service.create_language_model_setting.call_count == 4
        setting_service.create_language_model_setting.assert_has_calls(
            [
                call(
                    language_model_id="lm-1",
                    setting_key="embeddings",
                    setting_value="bge-m3",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="max_tokens",
                    setting_value="16384",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="timeout",
                    setting_value="600",
                    schema="test",
                ),
                call(
                    language_model_id="lm-1",
                    setting_key="structured_output_method",
                    setting_value="default",
                    schema="test",
                ),
            ]
        )

    def test_delete_language_model_by_id(self, lm_service):
        service, repo, _, _ = lm_service

        service.delete_language_model_by_id(language_model_id="lm-1", schema="test")

        repo.delete_by_id.assert_called_once_with("lm-1", "test")

    def test_update_language_model(self, lm_service):
        service, repo, _, integration_service = lm_service
        integration = MagicMock(spec=Integration)
        integration.id = "int-2"
        integration_service.get_integration_by_id.return_value = integration

        updated = MagicMock(spec=LanguageModel)
        repo.update_language_model.return_value = updated

        result = service.update_language_model(
            language_model_id="lm-1",
            language_model_tag="gpt-4-turbo",
            integration_id="int-2",
            schema="test",
        )

        assert result == updated
        integration_service.get_integration_by_id.assert_called_once_with(
            "int-2", "test"
        )
        repo.update_language_model.assert_called_once_with(
            language_model_id="lm-1",
            language_model_tag="gpt-4-turbo",
            integration_id="int-2",
            schema="test",
        )

    def test_update_language_model_invalid_integration(self, lm_service):
        service, repo, _, integration_service = lm_service
        integration_service.get_integration_by_id.side_effect = (
            IntegrationNotFoundError("bad-int")
        )

        with pytest.raises(IntegrationNotFoundError):
            service.update_language_model(
                language_model_id="lm-1",
                language_model_tag="gpt-4-turbo",
                integration_id="bad-int",
                schema="test",
            )

        repo.update_language_model.assert_not_called()
