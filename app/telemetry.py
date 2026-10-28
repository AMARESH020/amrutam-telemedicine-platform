import os

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(app: FastAPI, engine: Engine) -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")

    # Tracing stays disabled unless an exporter endpoint is configured.
    if not endpoint:
        return False

    resource = Resource.create(
        {
            "service.name": os.getenv(
                "OTEL_SERVICE_NAME",
                "amrutam-telemedicine-api",
            ),
            "deployment.environment": os.getenv(
                "APP_ENV",
                "development",
            ),
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Trace HTTP requests, excluding Prometheus scrapes.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics")

    # Add spans for SQLAlchemy database operations.
    SQLAlchemyInstrumentor().instrument(engine=engine)

    return True
