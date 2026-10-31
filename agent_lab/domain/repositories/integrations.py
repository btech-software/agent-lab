from datetime import datetime
from uuid import uuid4

import hvac
from typing_extensions import Iterator

from agent_lab.domain.exceptions.base import NotFoundError
from agent_lab.domain.models import Integration
from agent_lab.infrastructure.database.sql import Database


class IntegrationRepository:
    def __init__(
        self,
        db: Database,
        vault_client: hvac.Client,
    ) -> None:
        self.db = db
        self.vault_client = vault_client

    def get_all(self, schema: str) -> Iterator[Integration]:
        with self.db.session(schema_name=schema) as session:
            return session.query(Integration).filter(Integration.is_active).all()

    def get_by_id(self, integration_id: str, schema: str) -> Integration:
        with self.db.session(schema_name=schema) as session:
            integration = (
                session.query(Integration)
                .filter(Integration.id == integration_id, Integration.is_active)
                .first()
            )
            if not integration:
                raise IntegrationNotFoundError(integration_id)
            return integration

    def add(
        self, integration_type: str, api_endpoint: str, api_key: str, schema: str
    ) -> Integration:
        gen_id = uuid4()
        self.vault_client.secrets.kv.v2.create_or_update_secret(
            path=f"integration_{gen_id}",
            secret={"api_endpoint": api_endpoint, "api_key": api_key},
        )

        try:
            with self.db.session(schema_name=schema) as session:
                integration = Integration(
                    id=str(gen_id),
                    created_at=datetime.now(),
                    is_active=True,
                    integration_type=integration_type,
                )
                session.add(integration)
                session.commit()
                session.refresh(integration)
                return integration
        except Exception:
            self._delete_secret(str(gen_id))
            raise

    def delete_by_id(self, integration_id: str, schema: str) -> None:
        with self.db.session(schema_name=schema) as session:
            entity: Integration = (
                session.query(Integration)
                .filter(Integration.id == integration_id, Integration.is_active)
                .first()
            )
            if not entity:
                raise IntegrationNotFoundError(integration_id)

            entity.is_active = False
            session.commit()
        self._delete_secret(integration_id)

    def _delete_secret(self, integration_id: str) -> None:
        self.vault_client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=f"integration_{integration_id}"
        )


class IntegrationNotFoundError(NotFoundError):
    entity_name: str = "Integration"
