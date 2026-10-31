import hvac
from dependency_injector import containers, providers

from agent_lab.core.config import vault_tls_verify
from agent_lab.domain.repositories.agents import AgentRepository, AgentSettingRepository
from agent_lab.domain.repositories.attachments import AttachmentRepository
from agent_lab.domain.repositories.integrations import IntegrationRepository
from agent_lab.domain.repositories.language_models import (
    LanguageModelRepository,
    LanguageModelSettingRepository,
)
from agent_lab.domain.repositories.messages import MessageRepository
from agent_lab.infrastructure.database.checkpoints import GraphPersistenceFactory
from agent_lab.infrastructure.database.sql import Database
from agent_lab.infrastructure.database.vectors import DocumentRepository
from agent_lab.infrastructure.metrics.tracer import (
    Tracer,
    service_name,
    service_version,
    excluded_paths,
)
from agent_lab.infrastructure.metrics.tracing_backends import (
    LangfuseTracingBackend,
    LangWatchTracingBackend,
)
from agent_lab.interface.mcp.prompt_registry import PromptRegistry
from agent_lab.interface.mcp.user_prompt_resolver import UserPromptResolver
from agent_lab.services.agent_settings import AgentSettingService
from agent_lab.services.agent_types.base import AgentUtils
from agent_lab.services.agent_types.registry import AgentRegistry
from agent_lab.services.agents import AgentService
from agent_lab.services.attachments import AttachmentService
from agent_lab.services.auth import AuthService
from agent_lab.services.integrations import IntegrationService
from agent_lab.services.language_model_settings import LanguageModelSettingService
from agent_lab.services.language_models import LanguageModelService
from agent_lab.services.messages import MessageService
from agent_lab.services.tasks import TaskNotificationService


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        modules=[
            "agent_lab.interface.api.agents.endpoints",
            "agent_lab.interface.api.attachments.endpoints",
            "agent_lab.interface.api.auth.endpoints",
            "agent_lab.interface.api.integrations.endpoints",
            "agent_lab.interface.api.language_models.endpoints",
            "agent_lab.interface.api.messages.endpoints",
        ]
    )

    # Populated at bootstrap by create_app() via load_config(); declaring the
    # container performs no I/O so the library is import-safe.
    config = providers.Configuration()

    db = providers.Singleton(Database, db_url=config.db.url)

    graph_persistence_factory = providers.Singleton(
        GraphPersistenceFactory, db_checkpoints=config.db.checkpoints
    )

    vault_client = providers.Singleton(
        hvac.Client,
        url=config.vault.url,
        token=config.vault.token,
        verify=providers.Callable(vault_tls_verify),
    )

    document_repository = providers.Factory(
        DocumentRepository, db_url=config.db.vectors
    )

    auth_service = providers.Factory(
        AuthService,
        enabled=config.auth.enabled,
        url=config.auth.url,
        realm=config.auth.realm,
        client_id=config.auth.client_id,
        client_secret=config.auth.client_secret,
    )

    integration_repository = providers.Factory(
        IntegrationRepository,
        db=db,
        vault_client=vault_client,
    )

    integration_service = providers.Factory(
        IntegrationService,
        integration_repository=integration_repository,
    )

    task_notification_service = providers.Factory(
        TaskNotificationService,
        redis_url=config.broker.url,
    )

    language_model_setting_repository = providers.Factory(
        LanguageModelSettingRepository,
        db=db,
    )

    language_model_setting_service = providers.Factory(
        LanguageModelSettingService,
        language_model_setting_repository=language_model_setting_repository,
    )

    language_model_repository = providers.Factory(LanguageModelRepository, db=db)

    language_model_service = providers.Factory(
        LanguageModelService,
        language_model_repository=language_model_repository,
        language_model_setting_service=language_model_setting_service,
        integration_service=integration_service,
    )

    attachment_repository = providers.Factory(AttachmentRepository, db=db)

    attachment_service = providers.Factory(
        AttachmentService,
        attachment_repository=attachment_repository,
        document_repository=document_repository,
        language_model_service=language_model_service,
        language_model_setting_service=language_model_setting_service,
        integration_service=integration_service,
        vault_client=vault_client,
    )

    agent_setting_repository = providers.Factory(AgentSettingRepository, db=db)

    agent_setting_service = providers.Factory(
        AgentSettingService,
        agent_setting_repository=agent_setting_repository,
    )

    agent_repository = providers.Factory(AgentRepository, db=db)

    agent_service = providers.Factory(
        AgentService,
        agent_repository=agent_repository,
        agent_setting_service=agent_setting_service,
        language_model_service=language_model_service,
    )

    message_repository = providers.Factory(MessageRepository, db=db)

    message_service = providers.Factory(
        MessageService,
        message_repository=message_repository,
        agent_service=agent_service,
        attachment_service=attachment_service,
    )

    agent_utils = providers.Factory(
        AgentUtils,
        config=config,
        agent_service=agent_service,
        agent_setting_service=agent_setting_service,
        attachment_service=attachment_service,
        language_model_service=language_model_service,
        language_model_setting_service=language_model_setting_service,
        integration_service=integration_service,
        vault_client=vault_client,
        graph_persistence_factory=graph_persistence_factory,
        document_repository=document_repository,
        task_notification_service=task_notification_service,
    )

    # Agents register themselves via @discoverable_agent and are discovered through
    # scan-packages/entry points. The registry needs the live container
    # instance to resolve each agent's extra_deps, so create_app() binds it
    # via container.agent_registry.override(...) right after instantiation
    # (providers.Self() resolves to the base class under subclassing, so it
    # cannot be used here).
    agent_registry = providers.Singleton(AgentRegistry)

    user_prompt_resolver = providers.Singleton(
        UserPromptResolver,
        agent_service=agent_service,
        agent_setting_service=agent_setting_service,
    )

    prompt_registry = providers.Singleton(PromptRegistry)

    # MCP registrars are contributed via @discoverable_mcp_registrar and instantiated
    # from this container in agent_lab.interface.mcp.bootstrap.build_registrars,
    # resolving each registrar's extra_deps (e.g. prompt_registry,
    # user_prompt_resolver) by provider name — the @discoverable_agent convention.

    # Tracing frameworks are decoupled behind the TracingBackend abstraction and
    # composed here as a list. Adding a framework is a
    # new backend class + one entry below — the Tracer coordinator, the
    # @trace_agent_message decorator and the agent call sites stay untouched.
    langfuse_tracing_backend = providers.Singleton(LangfuseTracingBackend)

    langwatch_tracing_backend = providers.Singleton(
        LangWatchTracingBackend,
        service_name=service_name,
        service_version=service_version,
        excluded_paths=excluded_paths,
    )

    tracing_backends = providers.List(
        langfuse_tracing_backend,
        langwatch_tracing_backend,
    )

    tracer = providers.Singleton(Tracer, backends=tracing_backends)
