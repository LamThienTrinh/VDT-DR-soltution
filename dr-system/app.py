from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models.recovery_context import IncidentRequest, RecoveryContext
from services.incident_service import IncidentService, UnsupportedIncidentTypeError
from services.netbox_service import (
    InvalidTopologySnapshotError,
    NetBoxService,
    ResourceNotFoundError,
)

LOGGER = logging.getLogger("dr_system.api")

CORRELATION_ID_HEADER = "X-Correlation-ID"
CORRELATION_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}", flags=re.ASCII)
DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "netbox_mock.json"


def _correlation_id(request: Request) -> str:
    correlation_id = getattr(request.state, "correlation_id", None)
    if isinstance(correlation_id, str):
        return correlation_id
    return str(uuid4())


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": correlation_id,
            }
        },
        headers={CORRELATION_ID_HEADER: correlation_id},
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    snapshot_path: Path = application.state.snapshot_path
    try:
        topology_service = NetBoxService.load_snapshot(snapshot_path)
    except InvalidTopologySnapshotError as exc:
        LOGGER.error(
            "topology_snapshot_startup_failed code=%s path=%s reason=%s",
            exc.code,
            exc.path,
            exc.reason,
        )
        raise

    application.state.topology_service = topology_service
    application.state.incident_service = IncidentService(topology_service)
    LOGGER.info("topology_snapshot_loaded path=%s", snapshot_path)
    yield


def create_app(snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH) -> FastAPI:
    application = FastAPI(
        title="OpenStack DR Recovery Context",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.snapshot_path = Path(snapshot_path)

    @application.middleware("http")
    async def add_correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied_correlation_id = request.headers.get(CORRELATION_ID_HEADER)
        if supplied_correlation_id is not None and CORRELATION_ID_PATTERN.fullmatch(
            supplied_correlation_id
        ):
            correlation_id = supplied_correlation_id
        else:
            correlation_id = str(uuid4())

        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception(
                "request_failed correlation_id=%s method=%s path=%s",
                correlation_id,
                request.method,
                request.url.path,
            )
            raise

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        LOGGER.info(
            "request_complete correlation_id=%s method=%s path=%s status_code=%s",
            correlation_id,
            request.method,
            request.url.path,
            response.status_code,
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        LOGGER.info(
            "request_validation_failed correlation_id=%s error_count=%s",
            _correlation_id(request),
            len(exc.errors()),
        )
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request payload validation failed.",
        )

    @application.exception_handler(UnsupportedIncidentTypeError)
    async def handle_unsupported_incident_type(
        request: Request, exc: UnsupportedIncidentTypeError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code=exc.code,
            message=str(exc),
        )

    @application.exception_handler(ResourceNotFoundError)
    async def handle_resource_not_found(
        request: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=status.HTTP_404_NOT_FOUND,
            code=exc.code,
            message=str(exc),
        )

    @application.exception_handler(Exception)
    async def handle_internal_error(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception(
            "internal_error correlation_id=%s method=%s path=%s",
            _correlation_id(request),
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return _error_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="An unexpected internal error occurred.",
        )

    @application.get("/healthz", status_code=status.HTTP_200_OK)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/incidents",
        response_model=RecoveryContext,
        status_code=status.HTTP_200_OK,
    )
    async def create_recovery_context(
        incident: IncidentRequest, request: Request
    ) -> RecoveryContext:
        incident_service: IncidentService = request.app.state.incident_service
        return incident_service.create_recovery_context(incident.type, incident.resource)

    return application


app = create_app()
