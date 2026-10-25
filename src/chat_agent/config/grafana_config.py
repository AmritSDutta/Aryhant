"""OpenTelemetry and Grafana cloud observability instrumentation."""

import logging
import os
from typing import Any

from chat_agent.config import settings

logger = logging.getLogger(__name__)


def setup_grafana(app: Any) -> None:
    """Configure OTel traces and logs for Grafana if credentials are provided."""
    token = os.getenv("GRAFANA_API_TOKEN") or settings.GRAFANA_API_TOKEN
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or settings.OTEL_EXPORTER_OTLP_ENDPOINT
    user_id = os.getenv("GRAFANA_USER_ID") or settings.grafana_user_id

    if not token or not endpoint or not user_id:
        return

    try:
        import base64
        from opentelemetry import trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        b64 = base64.b64encode(f"{user_id}:{token}".encode()).decode()
        headers = {"Authorization": f"Basic {b64}"}
        resource = Resource.create({"service.name": "slack-email-bot"})

        # Traces
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers))
        )
        trace.set_tracer_provider(provider)

        # Optional HTTP/FastAPI instrumentors if installed
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except ImportError:
            pass

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except ImportError:
            pass

        # Logs
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers))
        )
        set_logger_provider(logger_provider)
        logging.getLogger().addHandler(
            LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        )
        logger.info("Grafana / OpenTelemetry instrumentation initialized.")
    except Exception as e:
        logger.warning("Could not initialize Grafana telemetry: %s", e)
