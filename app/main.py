
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import settings
from app.db import engine
from app.telemetry import configure_tracing
from app.routes import router
from app.rate_limit import check_rate_limit, RateLimitBackendUnavailable


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("amrutam.request")

HTTP_REQUESTS = Counter(
    "amrutam_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status_code"],
)

HTTP_DURATION = Histogram(
    "amrutam_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)

app = FastAPI(
    title="Amrutam Telemedicine API",
    version="1.0.0",
    description=(
        "Demo backend for identity, doctor availability, appointments, "
        "consultations, prescriptions and audit events."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started = time.perf_counter()
    status_code = 500
    response = None

    try:
        try:
            limited, retry_after = await check_rate_limit(
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
        except RateLimitBackendUnavailable:
            logger.error("rate_limit_backend_unavailable")
            response = JSONResponse(
                status_code=503,
                content={"detail": "Rate limiting service is temporarily unavailable."},
                headers={"Retry-After": "1"},
            )
        else:
            if limited:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                response = await call_next(request)

        status_code = response.status_code
        return response
    finally:
        duration = time.perf_counter() - started
        route_object = request.scope.get("route")
        route = getattr(route_object, "path", "unmatched")

        # Exclude the scrape endpoint to avoid counting Prometheus polling.
        if route != "/metrics" and request.url.path != "/metrics":
            HTTP_REQUESTS.labels(
                request.method, route, str(status_code)
            ).inc()
            HTTP_DURATION.labels(request.method, route).observe(duration)

            # Do not log request bodies, credentials, tokens, or clinical notes.
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 2),
                    }
                )
            )

        if response is not None:
            response.headers["X-Request-ID"] = request_id


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["operations"])
def health():
    return {
        "status": "ok",
        "service": "amrutam-telemedicine-api",
    }

# Configure tracing only when an OTLP endpoint is configured.
tracing_enabled = configure_tracing(app, engine)
logger.info("distributed_tracing_enabled=%s", tracing_enabled)
