from unittest.mock import MagicMock, patch

import pytest

from agent_lab.domain.models import Attachment
from agent_lab.domain.repositories.attachments import (
    AttachmentNotFoundError,
    AttachmentRepository,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__ = MagicMock(return_value=session)
    db.session.return_value.__exit__ = MagicMock(return_value=False)
    return db, session


class TestAttachmentRepository:
    def test_get_all(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        expected = [MagicMock(spec=Attachment), MagicMock(spec=Attachment)]
        session.query.return_value.filter.return_value.all.return_value = expected

        result = repo.get_all(schema="test_schema")

        assert result == expected
        assert len(result) == 2
        db.session.assert_called_once_with(schema_name="test_schema")

    def test_get_all_empty(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        session.query.return_value.filter.return_value.all.return_value = []

        result = repo.get_all(schema="test_schema")

        assert result == []

    def test_get_by_id_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        attachment = MagicMock(spec=Attachment)
        session.query.return_value.filter.return_value.first.return_value = attachment

        result = repo.get_by_id(attachment_id="att-1", schema="test_schema")

        assert result == attachment

    def test_get_by_id_not_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AttachmentNotFoundError):
            repo.get_by_id(attachment_id="nonexistent", schema="test_schema")

    @patch("agent_lab.domain.repositories.attachments.uuid4")
    def test_add_without_id(self, mock_uuid, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        mock_uuid.return_value = "generated-uuid"

        repo.add(
            file_name="test.pdf",
            raw_content=b"raw",
            parsed_content="parsed",
            schema="test_schema",
        )

        session.add.assert_called_once()
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_add_with_id(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)

        repo.add(
            file_name="test.pdf",
            raw_content=b"raw",
            parsed_content="parsed",
            schema="test_schema",
            attachment_id="custom-id",
        )

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.id == "custom-id"

    def test_delete_by_id_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        attachment = MagicMock(spec=Attachment)
        session.query.return_value.filter.return_value.first.return_value = attachment

        repo.delete_by_id(attachment_id="att-1", schema="test_schema")

        session.delete.assert_called_once_with(attachment)
        session.commit.assert_called_once()

    def test_delete_by_id_not_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AttachmentNotFoundError):
            repo.delete_by_id(attachment_id="nonexistent", schema="test_schema")

    def test_update_attachment_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        attachment = MagicMock(spec=Attachment)
        session.query.return_value.filter.return_value.first.return_value = attachment

        repo.update_attachment(
            attachment_id="att-1",
            embeddings_collection="my_collection",
            schema="test_schema",
        )

        assert attachment.embeddings_collection == "my_collection"
        session.commit.assert_called_once()
        session.refresh.assert_called_once()

    def test_update_attachment_not_found(self, mock_db):
        db, session = mock_db
        repo = AttachmentRepository(db=db)
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(AttachmentNotFoundError):
            repo.update_attachment(
                attachment_id="nonexistent",
                embeddings_collection="my_collection",
                schema="test_schema",
            )


class TestAttachmentNotFoundError:
    def test_entity_name(self):
        assert AttachmentNotFoundError.entity_name == "Attachment"

    def test_message(self):
        error = AttachmentNotFoundError("test-id")
        assert error.status_code == 404
        assert "Attachment" in error.detail


class TestDocumentRepositoryTenantScope:
    @patch("agent_lab.infrastructure.database.vectors.PGVector")
    def test_collection_is_namespaced_by_schema(self, pgvector_cls):
        from agent_lab.infrastructure.database.vectors import DocumentRepository

        repo = DocumentRepository(db_url="postgresql://x")
        embeddings = MagicMock()

        repo.search(embeddings, "static_document_data", "q", schema="id_tenant_a")
        repo.add(embeddings, "static_document_data", [], schema="id_tenant_b")

        names = [c.kwargs["collection_name"] for c in pgvector_cls.call_args_list]
        assert names == [
            "id_tenant_a/static_document_data",
            "id_tenant_b/static_document_data",
        ]

    @patch("agent_lab.infrastructure.database.vectors.PGVector")
    def test_delete_by_attachment_keeps_listed_ids(self, pgvector_cls):
        from sqlalchemy.dialects import postgresql

        from agent_lab.infrastructure.database.vectors import DocumentRepository
        from langchain_postgres.vectorstores import _get_embedding_collection_store

        store = pgvector_cls.return_value
        store.EmbeddingStore, _ = _get_embedding_collection_store()
        session = store.session_maker.return_value.__enter__.return_value

        DocumentRepository(db_url="postgresql://x").delete_by_attachment(
            None, "kb", "att-1", schema="id_t", keep_ids=["new-1"]
        )

        statement = session.execute.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        assert "NOT IN" in str(compiled)
        assert {"attachment_id", "att-1", ("new-1",)} <= {
            tuple(v) if isinstance(v, list) else v for v in compiled.params.values()
        }

    @pytest.mark.parametrize("schema", ["id_a/b", "id_x; drop", "", "../etc"])
    def test_rejects_invalid_schema_without_touching_the_store(self, schema):
        from agent_lab.infrastructure.database.vectors import DocumentRepository

        with patch(
            "agent_lab.infrastructure.database.vectors.PGVector"
        ) as pgvector_cls:
            with pytest.raises(ValueError):
                DocumentRepository(db_url="postgresql://x").search(
                    MagicMock(), "kb", "q", schema=schema
                )
        pgvector_cls.assert_not_called()

    @patch("agent_lab.infrastructure.database.vectors.PGVector")
    def test_vector_stores_share_one_engine_per_database(self, pgvector_cls):
        from sqlalchemy.engine import Engine

        from agent_lab.infrastructure.database.vectors import DocumentRepository

        DocumentRepository(db_url="postgresql://u@h/vec").search(
            MagicMock(), "kb", "q", schema="id_a"
        )
        DocumentRepository(db_url="postgresql://u@h/vec").add(
            MagicMock(), "kb", [], schema="id_b"
        )

        engines = [c.kwargs["connection"] for c in pgvector_cls.call_args_list]
        assert isinstance(engines[0], Engine)
        assert engines[0] is engines[1]
