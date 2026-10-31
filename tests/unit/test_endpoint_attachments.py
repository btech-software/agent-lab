from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from agent_lab.interface.api.attachments.endpoints import get_list, upload_attachment
from agent_lab.interface.api.attachments.schema import Attachment as AttachmentSchema
from agent_lab.domain.exceptions.base import FileToLargeError


def _make_attachment_orm(
    id="att-1",
    file_name="document.pdf",
    parsed_content="Parsed text",
    embeddings_collection=None,
):
    att = MagicMock()
    att.id = id
    att.is_active = True
    att.created_at = datetime(2024, 1, 15, 10, 30, 0)
    att.file_name = file_name
    att.parsed_content = parsed_content
    att.embeddings_collection = embeddings_collection
    return att


def _make_user(user_id="abc-def-123"):
    user = MagicMock()
    user.id = user_id
    return user


class TestGetList:
    @pytest.mark.asyncio
    async def test_returns_attachments(self):
        att1 = _make_attachment_orm(id="att-1", file_name="doc1.pdf")
        att2 = _make_attachment_orm(
            id="att-2", file_name="notes.txt", embeddings_collection="my_col"
        )
        service = MagicMock()
        service.get_attachments.return_value = [att1, att2]
        user = _make_user()

        result = await get_list(attachment_service=service, user=user)

        assert len(result) == 2
        assert isinstance(result[0], AttachmentSchema)
        assert result[0].id == "att-1"
        assert result[0].file_name == "doc1.pdf"
        assert result[1].id == "att-2"
        assert result[1].embeddings_collection == "my_col"
        service.get_attachments.assert_called_once_with("abc_def_123")

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        service = MagicMock()
        service.get_attachments.return_value = []
        user = _make_user()

        result = await get_list(attachment_service=service, user=user)

        assert result == []
        service.get_attachments.assert_called_once_with("abc_def_123")

    @pytest.mark.asyncio
    async def test_schema_derived_from_user_id(self):
        service = MagicMock()
        service.get_attachments.return_value = []
        user = _make_user(user_id="11-22-33-44")

        await get_list(attachment_service=service, user=user)

        service.get_attachments.assert_called_once_with("11_22_33_44")

    @pytest.mark.asyncio
    async def test_public_schema_when_user_none(self):
        service = MagicMock()
        service.get_attachments.return_value = []

        await get_list(attachment_service=service, user=None)

        service.get_attachments.assert_called_once_with("public")


class TestUploadAttachment:
    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self):
        file = MagicMock()
        file.file.tell.return_value = 11 * 1024 * 1024  # 11 MB
        service = MagicMock()
        user = _make_user()

        with pytest.raises(FileToLargeError):
            await upload_attachment(file=file, attachment_service=service, user=user)

    @pytest.mark.asyncio
    async def test_accepts_valid_file(self):
        file = MagicMock()
        file.file.tell.return_value = 5 * 1024 * 1024  # 5 MB
        att_orm = _make_attachment_orm()
        service = MagicMock()
        service.create_attachment_with_file = AsyncMock(return_value=att_orm)
        user = _make_user()

        result = await upload_attachment(
            file=file, attachment_service=service, user=user
        )

        assert isinstance(result, AttachmentSchema)
        assert result.id == "att-1"
        service.create_attachment_with_file.assert_awaited_once()


class TestEmbeddingsRequest:
    @pytest.mark.parametrize("collection_name", ["", "   "])
    def test_rejects_blank_collection_name(self, collection_name):
        from agent_lab.domain.exceptions.base import InvalidFieldError
        from agent_lab.interface.api.attachments.schema import EmbeddingsRequest

        with pytest.raises(InvalidFieldError):
            EmbeddingsRequest(
                attachment_id="a",
                language_model_id="l",
                collection_name=collection_name,
            )

    def test_accepts_named_collection(self):
        from agent_lab.interface.api.attachments.schema import EmbeddingsRequest

        request = EmbeddingsRequest(
            attachment_id="a", language_model_id="l", collection_name="kb"
        )
        assert request.collection_name == "kb"
