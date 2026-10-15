import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk._logs import LoggingHandler

import agent_lab.infrastructure.metrics.tracer as tracer_module
from agent_lab.infrastructure.metrics import tracing
from agent_lab.infrastructure.metrics.tracer import ExcludePathSampler, Tracer
from agent_lab.infrastructure.metrics.tracing import (
    register_active_backends,
    set_current_trace_io,
    trace_agent_message,
)
from agent_lab.infrastructure.metrics.tracing_backends import (
    LangfuseTracingBackend,
    LangWatchTracingBackend,
    TracingBackend,
)
from opentelemetry.sdk.trace.sampling import Decision


class _RecordingBackend(TracingBackend):
    def __init__(self):
        self.spans = []
        self.io = []

    def configure(self, tracer_provider) -> bool:
        return True

    def message_span(self, name: str):
        @contextmanager
        def span():
            self.spans.append(name)
            yield

        return span()

    def record_io(self, *, input_value, output_value, metadata) -> None:
        self.io.append((input_value, output_value, metadata))


class TestTracingHooks:
    def teardown_method(self):
        register_active_backends([])

    def test_trace_agent_message_fans_out_to_backends(self):
        backend = _RecordingBackend()
        register_active_backends([backend])

        @trace_agent_message
        def handler(value):
            return value * 2

        assert handler(21) == 42
        assert len(backend.spans) == 1
        assert backend.spans[0].endswith("handler")

    def test_set_current_trace_io(self):
        backend = _RecordingBackend()
        register_active_backends([backend])

        set_current_trace_io(input_value="in", output_value="out", metadata={"k": "v"})

        assert backend.io == [("in", "out", {"k": "v"})]

    def test_defaults_are_no_ops(self):
        class MinimalBackend(TracingBackend):
            def configure(self, tracer_provider) -> bool:
                return False

        backend = MinimalBackend()
        with backend.message_span("name"):
            pass  # default message_span is a no-op context manager
        assert backend.record_io(input_value=1, output_value=2, metadata={}) is None


class TestLangfuseTracingBackend:
    def test_configure_disabled_without_env(self, monkeypatch):
        for var in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            monkeypatch.delenv(var, raising=False)

        assert LangfuseTracingBackend().configure(MagicMock()) is False

    @patch("agent_lab.infrastructure.metrics.tracing_backends.BatchSpanProcessor")
    @patch("agent_lab.infrastructure.metrics.tracing_backends.OTLPSpanExporter")
    def test_configure_enabled(self, exporter_cls, processor_cls, monkeypatch):
        monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        provider = MagicMock()

        assert LangfuseTracingBackend().configure(provider) is True

        exporter_kwargs = exporter_cls.call_args.kwargs
        assert (
            exporter_kwargs["endpoint"] == "http://langfuse/api/public/otel/v1/traces"
        )
        provider.add_span_processor.assert_called_once_with(processor_cls.return_value)

    @patch("agent_lab.infrastructure.metrics.tracing_backends.trace.get_current_span")
    def test_record_io_sets_span_attributes(self, get_current_span):
        span = get_current_span.return_value

        LangfuseTracingBackend().record_io(
            input_value="in", output_value="out", metadata={"agent_id": "a1"}
        )

        span.set_attribute.assert_any_call("langfuse.trace.input", "in")
        span.set_attribute.assert_any_call("langfuse.trace.output", "out")
        span.set_attribute.assert_any_call("langfuse.trace.metadata.agent_id", "a1")


class TestLangWatchTracingBackend:
    def _backend(self) -> LangWatchTracingBackend:
        return LangWatchTracingBackend(
            service_name="agent-lab",
            service_version="test",
            excluded_paths=["/status/liveness"],
        )

    def test_configure_disabled_without_env(self, monkeypatch):
        monkeypatch.delenv("LANGWATCH_ENDPOINT", raising=False)
        monkeypatch.delenv("LANGWATCH_API_KEY", raising=False)

        assert self._backend().configure(MagicMock()) is False

    @patch("agent_lab.infrastructure.metrics.tracing_backends.langwatch")
    def test_configure_enabled(self, langwatch_mock, monkeypatch):
        monkeypatch.setenv("LANGWATCH_ENDPOINT", "http://langwatch")
        monkeypatch.setenv("LANGWATCH_API_KEY", "key")
        provider = MagicMock()

        assert self._backend().configure(provider) is True

        setup_kwargs = langwatch_mock.setup.call_args.kwargs
        assert setup_kwargs["endpoint_url"] == "http://langwatch"
        assert setup_kwargs["tracer_provider"] is provider
        assert len(setup_kwargs["span_exclude_rules"]) == 1

    @patch("agent_lab.infrastructure.metrics.tracing_backends.langwatch")
    def test_message_span(self, langwatch_mock):
        result = self._backend().message_span("handler")

        langwatch_mock.trace.assert_called_once_with(name="handler")
        assert result is langwatch_mock.trace.return_value

    @patch("agent_lab.infrastructure.metrics.tracing_backends.langwatch")
    def test_record_io(self, langwatch_mock):
        self._backend().record_io(
            input_value="in", output_value="out", metadata={"k": "v"}
        )

        langwatch_mock.get_current_trace.return_value.update.assert_called_once_with(
            input="in", output="out", metadata={"k": "v"}
        )


class TestExcludePathSampler:
    def test_drops_excluded_paths(self):
        sampler = ExcludePathSampler(["/status/liveness"])

        result = sampler.should_sample(None, 1, "GET /status/liveness")

        assert result.decision == Decision.DROP

    def test_samples_other_paths(self):
        sampler = ExcludePathSampler(["/status/liveness"])

        result = sampler.should_sample(None, 1, "GET /agents")

        assert result.decision == Decision.RECORD_AND_SAMPLE

    def test_get_description(self):
        assert "ExcludePathSampler" in ExcludePathSampler(["/x"]).get_description()


class TestTracer:
    @patch("agent_lab.infrastructure.metrics.tracer.register_active_backends")
    @patch("agent_lab.infrastructure.metrics.tracer.OpenAIInstrumentor")
    @patch("agent_lab.infrastructure.metrics.tracer.SQLAlchemyInstrumentor")
    @patch("agent_lab.infrastructure.metrics.tracer.LangchainInstrumentor")
    @patch("agent_lab.infrastructure.metrics.tracer.HTTPXClientInstrumentor")
    @patch("agent_lab.infrastructure.metrics.tracer.FastAPIInstrumentor")
    def test_setup_filters_active_backends(
        self,
        fastapi_instr,
        httpx_instr,
        langchain_instr,
        sqlalchemy_instr,
        openai_instr,
        register_mock,
    ):
        active = MagicMock()
        active.configure.return_value = True
        inactive = MagicMock()
        inactive.configure.return_value = False
        app = MagicMock()

        Tracer(backends=[active, inactive]).setup(app)

        fastapi_instr.instrument_app.assert_called_once_with(app)
        httpx_instr.return_value.instrument.assert_called_once()
        register_mock.assert_called_once_with([active])


class TestOtelLogHandlerAttachment:
    """agent_lab.app_factory configures the root logger at import time
    (logging.basicConfig(level=DEBUG)), which makes _configure_otel's
    logging.basicConfig a silent no-op. The OTel LoggingHandler must still be
    attached, or application logs never reach Loki via the collector."""

    @pytest.fixture(autouse=True)
    def _preserve_root_logging(self):
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        yield
        root.handlers[:] = handlers
        root.setLevel(level)

    def test_attaches_log_handler_when_root_already_configured(self, monkeypatch):
        monkeypatch.setattr(tracer_module, "collector_endpoint", "http://otel-collector:4318")
        monkeypatch.setattr(tracer_module, "_otel_configured", False)
        monkeypatch.setattr(tracer_module, "tracer_provider", None)
        # keep otel globals untouched by the test run
        monkeypatch.setattr(tracer_module, "trace", MagicMock())
        monkeypatch.setattr(tracer_module, "metrics", MagicMock())

        logging.basicConfig(level=logging.DEBUG)  # simulates app_factory import

        tracer_module._configure_otel()

        log_handlers = [
            h for h in logging.getLogger().handlers if isinstance(h, LoggingHandler)
        ]
        assert log_handlers, "OTel LoggingHandler not attached to the root logger"


def test_module_state_restored():
    """Safety net: ensure no test in this module leaks registered backends."""
    assert tracing._active_backends == []
