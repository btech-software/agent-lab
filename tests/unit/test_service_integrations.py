from unittest.mock import MagicMock

import pytest

from agent_lab.domain.models import Integration
from agent_lab.services.integrations import IntegrationService


@pytest.fixture
def integration_service():
    repo = MagicMock()
    service = IntegrationService(integration_repository=repo)
    return service, repo


class TestIntegrationService:
    def test_get_integrations(self, integration_service):
        service, repo = integration_service
        expected = [MagicMock(spec=Integration)]
        repo.get_all.return_value = expected

        result = service.get_integrations(schema="test")

        assert result == expected
        repo.get_all.assert_called_once_with("test")

    def test_get_integration_by_id(self, integration_service):
        service, repo = integration_service
        integration = MagicMock(spec=Integration)
        repo.get_by_id.return_value = integration

        result = service.get_integration_by_id(integration_id="int-1", schema="test")

        assert result == integration
        repo.get_by_id.assert_called_once_with("int-1", "test")

    def test_create_integration(self, integration_service):
        service, repo = integration_service
        integration = MagicMock(spec=Integration)
        repo.add.return_value = integration

        result = service.create_integration(
            integration_type="openai_api_v1",
            api_endpoint="https://api.openai.com",
            api_key="sk-test",
            schema="test",
        )

        assert result == integration
        repo.add.assert_called_once_with(
            integration_type="openai_api_v1",
            api_endpoint="https://api.openai.com",
            api_key="sk-test",
            schema="test",
        )

    def test_delete_integration_by_id(self, integration_service):
        service, repo = integration_service

        service.delete_integration_by_id(integration_id="int-1", schema="test")

        repo.delete_by_id.assert_called_once_with("int-1", "test")


class TestIntegrationCreateRequestEndpoint:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "file:///etc/passwd",
            "gopher://internal:70/x",
            "ftp://host/v1",
            "redis://cache:6379",
        ],
    )
    def test_rejects_non_http_schemes(self, endpoint):
        from agent_lab.domain.exceptions.base import InvalidFieldError
        from agent_lab.interface.api.integrations.schema import IntegrationCreateRequest

        with pytest.raises(InvalidFieldError):
            IntegrationCreateRequest(
                integration_type="openai_api_v1", api_endpoint=endpoint, api_key="k"
            )

    @pytest.mark.parametrize(
        "endpoint", ["https://api.openai.com/v1", "http://192.168.1.10:11434/v1"]
    )
    def test_accepts_http_and_https(self, endpoint):
        from agent_lab.interface.api.integrations.schema import IntegrationCreateRequest

        request = IntegrationCreateRequest(
            integration_type="openai_api_v1", api_endpoint=endpoint, api_key="k"
        )
        assert request.api_endpoint == endpoint
