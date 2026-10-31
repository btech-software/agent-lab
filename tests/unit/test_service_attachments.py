import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_lab.domain.exceptions.base import AudioOptimizationError, FileProcessingError
from agent_lab.domain.models import Attachment
from agent_lab.services.attachments import AttachmentService


@pytest.fixture
def attachment_service():
    attachment_repo = MagicMock()
    document_repo = MagicMock()
    lm_service = MagicMock()
    lm_setting_service = MagicMock()
    integration_service = MagicMock()
    vault_client = MagicMock()
    service = AttachmentService(
        attachment_repository=attachment_repo,
        document_repository=document_repo,
        language_model_service=lm_service,
        language_model_setting_service=lm_setting_service,
        integration_service=integration_service,
        vault_client=vault_client,
    )
    return (
        service,
        attachment_repo,
        document_repo,
        lm_service,
        lm_setting_service,
        integration_service,
        vault_client,
    )


class TestAttachmentService:
    def test_get_attachments(self, attachment_service):
        service, repo, *_ = attachment_service
        expected = [MagicMock(spec=Attachment), MagicMock(spec=Attachment)]
        repo.get_all.return_value = expected

        result = service.get_attachments(schema="test")

        assert result == expected
        assert len(result) == 2
        repo.get_all.assert_called_once_with("test")

    def test_get_attachments_empty(self, attachment_service):
        service, repo, *_ = attachment_service
        repo.get_all.return_value = []

        result = service.get_attachments(schema="test")

        assert result == []

    def test_get_attachment_by_id(self, attachment_service):
        service, repo, *_ = attachment_service
        attachment = MagicMock(spec=Attachment)
        repo.get_by_id.return_value = attachment

        result = service.get_attachment_by_id(attachment_id="att-1", schema="test")

        assert result == attachment
        repo.get_by_id.assert_called_once_with("att-1", "test")

    def test_create_attachment_with_content(self, attachment_service):
        service, repo, *_ = attachment_service
        attachment = MagicMock(spec=Attachment)
        repo.add.return_value = attachment

        result = service.create_attachment_with_content(
            file_name="test.pdf",
            raw_content=b"raw bytes",
            parsed_content="parsed text",
            schema="test",
        )

        assert result == attachment
        repo.add.assert_called_once_with(
            file_name="test.pdf",
            raw_content=b"raw bytes",
            parsed_content="parsed text",
            attachment_id=None,
            schema="test",
        )

    def test_create_attachment_with_content_and_id(self, attachment_service):
        service, repo, *_ = attachment_service
        attachment = MagicMock(spec=Attachment)
        repo.add.return_value = attachment

        result = service.create_attachment_with_content(
            file_name="test.pdf",
            raw_content=b"raw bytes",
            parsed_content="parsed text",
            schema="test",
            attachment_id="custom-id",
        )

        assert result == attachment
        repo.add.assert_called_once_with(
            file_name="test.pdf",
            raw_content=b"raw bytes",
            parsed_content="parsed text",
            attachment_id="custom-id",
            schema="test",
        )

    def test_delete_attachment_by_id(self, attachment_service):
        service, repo, *_ = attachment_service

        service.delete_attachment_by_id(attachment_id="att-1", schema="test")

        repo.delete_by_id.assert_called_once_with("att-1", "test")


def _upload_file(content_type: str, filename: str) -> MagicMock:
    file = MagicMock()
    file.read = AsyncMock(return_value=b"raw-bytes")
    file.content_type = content_type
    file.filename = filename
    return file


class TestCreateAttachmentWithFile:
    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.MarkItDown")
    async def test_non_audio_file_is_parsed(self, markitdown_cls, attachment_service):
        service, repo, *_ = attachment_service
        markitdown_cls.return_value.convert.return_value.text_content = "parsed text"
        attachment = MagicMock(spec=Attachment)
        repo.add.return_value = attachment

        result = await service.create_attachment_with_file(
            file=_upload_file("application/pdf", "doc.pdf"), schema="test"
        )

        assert result == attachment
        repo.add.assert_called_once_with(
            file_name="doc.pdf",
            raw_content=b"raw-bytes",
            parsed_content="parsed text",
            attachment_id=None,
            schema="test",
        )

    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.uuid4", return_value="test-uuid")
    @patch("agent_lab.services.attachments.MarkItDown")
    async def test_non_audio_parse_failure_raises(
        self, markitdown_cls, _uuid, attachment_service, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        service, *_ = attachment_service
        markitdown_cls.return_value.convert.side_effect = Exception("bad file")

        upload = _upload_file("application/pdf", "doc.pdf")
        with pytest.raises(FileProcessingError):
            await service.create_attachment_with_file(file=upload, schema="test")

        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.MarkItDown")
    async def test_store_failure_leaves_no_temp_file(
        self, markitdown_cls, attachment_service, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        service, repo, *_ = attachment_service
        markitdown_cls.return_value.convert.return_value.text_content = "parsed"
        repo.add.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            await service.create_attachment_with_file(
                file=_upload_file("application/pdf", "doc.pdf"), schema="test"
            )

        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    async def test_audio_file_is_optimized(self, attachment_service):
        service, repo, *_ = attachment_service
        service.optimize_audio = MagicMock(return_value=b"mp3-bytes")
        attachment = MagicMock(spec=Attachment)
        repo.add.return_value = attachment

        result = await service.create_attachment_with_file(
            file=_upload_file("audio/wav", "memo.wav"), schema="test"
        )

        assert result == attachment
        repo.add.assert_called_once_with(
            file_name="memo.mp3",
            raw_content=b"mp3-bytes",
            parsed_content="",
            attachment_id=None,
            schema="test",
        )


class TestCreateEmbeddings:
    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.TextLoader")
    async def test_create_embeddings(self, loader_cls, attachment_service):
        (
            service,
            repo,
            document_repo,
            lm_service,
            lm_setting_service,
            integration_service,
            vault_client,
        ) = attachment_service
        language_model = MagicMock(id="lm-1", integration_id="int-1")
        lm_service.get_language_model_by_id.return_value = language_model
        lm_setting_service.get_language_model_settings.return_value = [
            MagicMock(setting_key="embeddings", setting_value="bge-m3")
        ]
        integration_service.get_integration_by_id.return_value = MagicMock(id="int-1")
        vault_client.secrets.kv.read_secret_version.return_value = {
            "data": {"data": {"api_endpoint": "http://e", "api_key": "k"}}
        }
        attachment = MagicMock()
        attachment.parsed_content = "parsed markdown"
        repo.get_by_id.return_value = attachment
        documents = [MagicMock()]
        loader_cls.return_value.load_and_split.return_value = documents
        updated = MagicMock(spec=Attachment)
        repo.update_attachment.return_value = updated

        result = await service.create_embeddings(
            attachment_id="att-1",
            language_model_id="lm-1",
            collection_name="kb",
            schema="test",
        )

        assert result == updated
        document_repo.add.assert_called_once()
        assert document_repo.add.call_args.args[1] == "kb"
        assert document_repo.add.call_args.args[2] == documents
        assert document_repo.add.call_args.kwargs["schema"] == "test"
        repo.update_attachment.assert_called_once_with("att-1", "kb", "test")


class TestOptimizeAudio:
    @patch("agent_lab.services.attachments.subprocess.run")
    def test_optimize_audio_success(self, subprocess_run, attachment_service, tmp_path):
        service, *_ = attachment_service
        audio_file = tmp_path / "memo.wav"
        audio_file.write_bytes(b"optimized-audio")

        result = service.optimize_audio(str(audio_file))

        assert result == b"optimized-audio"
        assert subprocess_run.call_count == 2
        ffmpeg_args = subprocess_run.call_args_list[0].args[0]
        mv_args = subprocess_run.call_args_list[1].args[0]
        assert ffmpeg_args[0] == "ffmpeg"
        assert ffmpeg_args[2] == str(audio_file)
        temp_output = ffmpeg_args[-1]
        # written next to the input (the caller's temp dir), never the CWD
        assert os.path.dirname(temp_output) == str(tmp_path)
        assert temp_output.endswith(".mp3")
        assert mv_args == ["mv", temp_output, str(audio_file)]

    @patch("agent_lab.services.attachments.subprocess.run")
    def test_optimize_audio_failure_leaves_no_partial_output(
        self, subprocess_run, attachment_service, tmp_path, monkeypatch
    ):
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        service, *_ = attachment_service
        audio_file = tmp_path / "memo.wav"
        audio_file.write_bytes(b"raw")

        def ffmpeg_fails(args, check):
            open(args[-1], "wb").write(b"partial")
            raise subprocess.CalledProcessError(1, "ffmpeg")

        subprocess_run.side_effect = ffmpeg_fails

        with pytest.raises(AudioOptimizationError):
            service.optimize_audio(str(audio_file))

        assert sorted(p.name for p in tmp_path.iterdir()) == ["cwd", "memo.wav"]
        assert list(cwd.iterdir()) == []

    @patch("agent_lab.services.attachments.subprocess.run")
    def test_optimize_audio_failure_raises(self, subprocess_run, attachment_service):
        service, *_ = attachment_service
        subprocess_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

        with pytest.raises(AudioOptimizationError):
            service.optimize_audio("missing.wav")


class TestEmbeddingsLifecycle:
    def _wire(self, attachment_service, previous_collection=None):
        (
            service,
            repo,
            document_repo,
            lm_service,
            lm_setting_service,
            integration_service,
            vault_client,
        ) = attachment_service
        lm_service.get_language_model_by_id.return_value = MagicMock(
            id="lm-1", integration_id="int-1"
        )
        lm_setting_service.get_language_model_settings.return_value = [
            MagicMock(setting_key="embeddings", setting_value="bge-m3")
        ]
        integration_service.get_integration_by_id.return_value = MagicMock(id="int-1")
        vault_client.secrets.kv.read_secret_version.return_value = {
            "data": {"data": {"api_endpoint": "http://e", "api_key": "k"}}
        }
        attachment = MagicMock()
        attachment.parsed_content = "parsed markdown"
        attachment.embeddings_collection = previous_collection
        repo.get_by_id.return_value = attachment
        return service, repo, document_repo

    async def _embed(self, service):
        return await service.create_embeddings(
            attachment_id="att-1",
            language_model_id="lm-1",
            collection_name="kb",
            schema="test",
        )

    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.TextLoader")
    async def test_empty_content_records_collection_without_vectors(
        self, loader_cls, attachment_service, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        service, repo, document_repo = self._wire(attachment_service)
        loader_cls.return_value.load_and_split.return_value = []

        result = await self._embed(service)

        document_repo.add.assert_not_called()
        repo.update_attachment.assert_called_once_with("att-1", "kb", "test")
        assert result == repo.update_attachment.return_value
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.TextLoader")
    async def test_reembedding_replaces_previous_chunks(
        self, loader_cls, attachment_service, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        service, repo, document_repo = self._wire(
            attachment_service, previous_collection="old_kb"
        )
        documents = [MagicMock(metadata={}), MagicMock(metadata={})]
        loader_cls.return_value.load_and_split.return_value = documents

        await self._embed(service)

        assert all(d.metadata["attachment_id"] == "att-1" for d in documents)
        new_ids = [d.id for d in documents]
        assert len(set(new_ids)) == 2
        deletes = [
            (c.args[1], c.args[2], c.kwargs["schema"], c.kwargs["keep_ids"])
            for c in document_repo.delete_by_attachment.call_args_list
        ]
        assert sorted(deletes) == [
            ("kb", "att-1", "test", new_ids),
            ("old_kb", "att-1", "test", new_ids),
        ]
        # new chunks are written before old ones are removed
        call_names = [c[0] for c in document_repo.mock_calls]
        assert call_names.index("add") < call_names.index("delete_by_attachment")
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    @patch("agent_lab.services.attachments.TextLoader")
    async def test_failed_reembedding_keeps_previous_chunks(
        self, loader_cls, attachment_service, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        service, repo, document_repo = self._wire(
            attachment_service, previous_collection="kb"
        )
        loader_cls.return_value.load_and_split.return_value = [MagicMock(metadata={})]
        document_repo.add.side_effect = RuntimeError("embeddings endpoint down")

        with pytest.raises(RuntimeError):
            await self._embed(service)

        document_repo.delete_by_attachment.assert_not_called()
        repo.update_attachment.assert_not_called()

    def test_delete_attachment_removes_its_chunks(self, attachment_service):
        service, repo, document_repo, *_ = attachment_service
        repo.get_by_id.return_value = MagicMock(embeddings_collection="kb")

        service.delete_attachment_by_id("att-1", "test")

        document_repo.delete_by_attachment.assert_called_once_with(
            None, "kb", "att-1", schema="test"
        )
        repo.delete_by_id.assert_called_once_with("att-1", "test")

    def test_delete_attachment_without_embeddings(self, attachment_service):
        service, repo, document_repo, *_ = attachment_service
        repo.get_by_id.return_value = MagicMock(embeddings_collection=None)

        service.delete_attachment_by_id("att-1", "test")

        document_repo.delete_by_attachment.assert_not_called()
        repo.delete_by_id.assert_called_once_with("att-1", "test")
