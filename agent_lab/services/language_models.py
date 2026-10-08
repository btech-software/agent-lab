from typing_extensions import Iterator

from agent_lab.domain.models import LanguageModel
from agent_lab.domain.repositories.language_models import LanguageModelRepository
from agent_lab.services.integrations import IntegrationService
from agent_lab.services.language_model_settings import LanguageModelSettingService


class LanguageModelService:
    def __init__(
        self,
        language_model_repository: LanguageModelRepository,
        language_model_setting_service: LanguageModelSettingService,
        integration_service: IntegrationService,
    ) -> None:
        self.repository: LanguageModelRepository = language_model_repository
        self.setting_service = language_model_setting_service
        self.integration_service = integration_service

    def get_language_models(self, schema: str) -> Iterator[LanguageModel]:
        return self.repository.get_all(schema)

    def get_language_model_by_id(
        self, language_model_id: str, schema: str
    ) -> LanguageModel:
        return self.repository.get_by_id(language_model_id, schema)

    def create_language_model(
        self, integration_id: str, language_model_tag: str, schema: str
    ) -> LanguageModel:
        # get integration
        integration = self.integration_service.get_integration_by_id(
            integration_id, schema
        )

        # create language model
        language_model = self.repository.add(
            integration_id=integration.id,
            language_model_tag=language_model_tag,
            schema=schema,
        )

        # default embeddings model setting
        if integration.integration_type == "openai_api_v1":
            self.setting_service.create_language_model_setting(
                language_model_id=language_model.id,
                setting_key="embeddings",
                setting_value="text-embedding-3-large",
                schema=schema,
            )
        else:
            self.setting_service.create_language_model_setting(
                language_model_id=language_model.id,
                setting_key="embeddings",
                setting_value="bge-m3",
                schema=schema,
            )

        # default generation guardrails: cap runaway generations and hung requests
        self.setting_service.create_language_model_setting(
            language_model_id=language_model.id,
            setting_key="max_tokens",
            setting_value="16384",
            schema=schema,
        )
        self.setting_service.create_language_model_setting(
            language_model_id=language_model.id,
            setting_key="timeout",
            setting_value="600",
            schema=schema,
        )

        # structured output method override (e.g. "function_calling");
        # "default" keeps the provider library default
        self.setting_service.create_language_model_setting(
            language_model_id=language_model.id,
            setting_key="structured_output_method",
            setting_value="default",
            schema=schema,
        )

        return language_model

    def delete_language_model_by_id(self, language_model_id: str, schema: str) -> None:
        return self.repository.delete_by_id(language_model_id, schema)

    def update_language_model(
        self,
        language_model_id: str,
        language_model_tag: str,
        integration_id: str,
        schema: str,
    ) -> LanguageModel:
        integration = self.integration_service.get_integration_by_id(
            integration_id, schema
        )
        return self.repository.update_language_model(
            language_model_id=language_model_id,
            language_model_tag=language_model_tag,
            integration_id=integration.id,
            schema=schema,
        )
