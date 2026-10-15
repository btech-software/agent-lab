import logging
import os

from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry import trace, metrics
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, Attributes
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import Sampler, Decision, SamplingResult
from opentelemetry.trace import SpanKind, TraceState, Link
from typing_extensions import Optional, Sequence

from agent_lab.infrastructure.metrics.tracing import register_active_backends

service_name = os.getenv("SERVICE_NAME", "Agent-Lab")
service_version = os.getenv("SERVICE_VERSION", "snapshot")
collector_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
resource = Resource(attributes={SERVICE_NAME: service_name})
excluded_paths = [
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/docs",
    "/favicon.ico",
    "/openapi.json",
    "/status/liveness",
    "/status/readiness",
    "/status/metrics",
]


class ExcludePathSampler(Sampler):
    def __init__(self, paths):
        self.excluded_paths = paths

    def should_sample(
        self,
        parent_context: Optional[Context],
        trace_id: int,
        name: str,
        kind: Optional[SpanKind] = None,
        attributes: Attributes = None,
        links: Optional[Sequence[Link]] = None,
        trace_state: Optional[TraceState] = None,
    ) -> SamplingResult:
        for path in self.excluded_paths:
            if path in name:
                return SamplingResult(Decision.DROP)
        return SamplingResult(Decision.RECORD_AND_SAMPLE)

    def get_description(self) -> str:
        return f"ExcludePathSampler({self.excluded_paths})"


tracer_provider = None
_otel_configured = False


def _configure_otel():  # pragma: no cover - OTel exporter wiring
    """Wires the global OTel providers once, at first Tracer.setup() call.

    Deferred out of import time so importing the library never touches OTel
    globals or opens exporter connections.
    """
    global tracer_provider, _otel_configured
    if _otel_configured or collector_endpoint is None:
        return tracer_provider
    _otel_configured = True

    # traces
    tracer_provider = TracerProvider(
        resource=resource, sampler=ExcludePathSampler(excluded_paths)
    )
    trace.set_tracer_provider(tracer_provider)
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint=f"{collector_endpoint}/v1/traces")
    )
    tracer_provider.add_span_processor(processor)
    trace.set_tracer_provider(tracer_provider)

    # metrics
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{collector_endpoint}/v1/metrics")
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    # logs
    log_exporter = OTLPLogExporter(endpoint=f"{collector_endpoint}/v1/logs")
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    otlp_handler = LoggingHandler(logger_provider=logger_provider)
    otlp_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[console_handler, otlp_handler],
    )
    # basicConfig is a silent no-op when the root logger already has
    # handlers — app_factory.py configures it at import time. Attach the
    # OTel handler unconditionally so application logs still reach Loki.
    root = logging.getLogger()
    if otlp_handler not in root.handlers:
        root.addHandler(otlp_handler)
    return tracer_provider


class Tracer:
    """Coordinates the framework-neutral OpenTelemetry base instrumentation and
    delegates framework-specific wiring to the injected ``TracingBackend`` list.
    Adding or removing a backend is a container change only — this class never
    changes (Open/Closed, Dependency Inversion)."""

    def __init__(self, backends):
        self._backends = backends

    def setup(self, app):
        provider = _configure_otel()

        # Framework-neutral base instrumentation. These bind to the shared
        # (global) TracerProvider, so every backend's exporter receives the same
        # FastAPI/HTTPx/LangChain/SQLAlchemy/OpenAI spans — instrumentation is a
        # shared concern, not owned by any single tracing framework.
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        LangchainInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument()
        OpenAIInstrumentor().instrument()

        active_backends = [
            backend for backend in self._backends if backend.configure(provider)
        ]
        register_active_backends(active_backends)
