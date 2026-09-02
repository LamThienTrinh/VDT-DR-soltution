from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import create_app
from services.netbox_service import InvalidTopologySnapshotError, NetBoxService


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "netbox_mock.json"
EXPECTED_CONTEXT = {
    "incident": {"type": "COMPUTE_DOWN", "resource": "compute-01"},
    "affected_vms": ["vm-api-01", "vm-web-01"],
    "source": {"az": "AZ-01", "rack": "rack-01"},
    "available_compute": ["compute-05", "compute-06"],
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(FIXTURE_PATH)) as test_client:
        yield test_client


def _assert_error(
    response,
    *,
    status_code: int,
    code: str,
    correlation_id: str | None = None,
) -> dict[str, str]:
    assert response.status_code == status_code
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert set(error) == {"code", "message", "correlation_id"}
    assert error["code"] == code
    assert error["message"]
    assert response.headers["X-Correlation-ID"] == error["correlation_id"]
    if correlation_id is None:
        UUID(error["correlation_id"])
    else:
        assert error["correlation_id"] == correlation_id
    return error


def test_ctx_001_post_incident_returns_the_exact_v1_contract(
    client: TestClient,
) -> None:
    response = client.post(
        "/incidents",
        json={"type": "COMPUTE_DOWN", "resource": "compute-01"},
    )

    assert response.status_code == 200
    assert response.json() == EXPECTED_CONTEXT
    UUID(response.headers["X-Correlation-ID"])


def test_ctx_002_unknown_compute_returns_standard_404_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/incidents",
        json={"type": "COMPUTE_DOWN", "resource": "compute-404"},
        headers={"X-Correlation-ID": "ctx-002.request"},
    )

    error = _assert_error(
        response,
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        correlation_id="ctx-002.request",
    )
    assert "compute-404" in error["message"]


def test_ctx_003_unsupported_type_returns_standard_422_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/incidents",
        json={"type": "RACK_DOWN", "resource": "rack-01"},
    )

    _assert_error(
        response,
        status_code=422,
        code="UNSUPPORTED_INCIDENT_TYPE",
    )


@pytest.mark.parametrize(
    "request_kwargs",
    [
        pytest.param(
            {"json": {"type": "COMPUTE_DOWN"}},
            id="missing-resource-ctx-004",
        ),
        pytest.param(
            {"json": {"resource": "compute-01"}},
            id="missing-type",
        ),
        pytest.param(
            {"json": {"type": "COMPUTE_DOWN", "resource": "  "}},
            id="blank-resource",
        ),
        pytest.param(
            {"json": {"type": "\t", "resource": "compute-01"}},
            id="blank-type",
        ),
        pytest.param(
            {"json": {"type": "COMPUTE_DOWN", "resource": 1}},
            id="wrong-resource-type",
        ),
        pytest.param(
            {
                "json": {
                    "type": "COMPUTE_DOWN",
                    "resource": "compute-01",
                    "unexpected": True,
                }
            },
            id="extra-field",
        ),
        pytest.param(
            {
                "content": '{"type":"COMPUTE_DOWN",',
                "headers": {"Content-Type": "application/json"},
            },
            id="malformed-json",
        ),
    ],
)
def test_ctx_004_invalid_payloads_return_standard_validation_error(
    client: TestClient,
    request_kwargs: dict[str, Any],
) -> None:
    response = client.post("/incidents", **request_kwargs)

    error = _assert_error(
        response,
        status_code=422,
        code="VALIDATION_ERROR",
    )
    assert error["message"] == "Request payload validation failed."


def test_ctx_008_repeated_api_calls_are_identical_and_do_not_change_fixture(
    client: TestClient,
) -> None:
    fixture_before = FIXTURE_PATH.read_bytes()
    payload = {"type": "COMPUTE_DOWN", "resource": "compute-01"}

    first = client.post("/incidents", json=payload)
    second = client.post("/incidents", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == EXPECTED_CONTEXT
    assert FIXTURE_PATH.read_bytes() == fixture_before


def test_healthz_reports_ready_and_has_a_correlation_header(
    client: TestClient,
) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Correlation-ID"])


def test_snapshot_is_loaded_once_per_application_lifespan(monkeypatch) -> None:
    original_loader = NetBoxService.load_snapshot.__func__
    loaded_paths: list[Path] = []

    def recording_loader(cls, path: str | Path) -> NetBoxService:
        loaded_paths.append(Path(path))
        return original_loader(cls, path)

    monkeypatch.setattr(
        NetBoxService,
        "load_snapshot",
        classmethod(recording_loader),
    )

    with TestClient(create_app(FIXTURE_PATH)) as test_client:
        assert test_client.get("/healthz").status_code == 200
        assert test_client.post(
            "/incidents",
            json={"type": "COMPUTE_DOWN", "resource": "compute-01"},
        ).status_code == 200

    assert loaded_paths == [FIXTURE_PATH]


def test_default_docs_and_openapi_schema_remain_available(client: TestClient) -> None:
    docs_response = client.get("/docs")
    schema_response = client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert "swagger" in docs_response.text.lower()
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert "/incidents" in schema["paths"]
    assert "post" in schema["paths"]["/incidents"]
    assert "/healthz" in schema["paths"]


def test_valid_correlation_id_is_preserved_on_success(client: TestClient) -> None:
    correlation_id = "operator.request_01-abc"

    response = client.get(
        "/healthz",
        headers={"X-Correlation-ID": correlation_id},
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id


@pytest.mark.parametrize(
    "invalid_correlation_id",
    [
        pytest.param("contains a space", id="space"),
        pytest.param("contains:semicolon", id="disallowed-punctuation"),
        pytest.param("a" * 129, id="too-long"),
    ],
)
def test_invalid_correlation_id_is_replaced_with_a_uuid(
    client: TestClient,
    invalid_correlation_id: str,
) -> None:
    response = client.get(
        "/healthz",
        headers={"X-Correlation-ID": invalid_correlation_id},
    )

    generated_id = response.headers["X-Correlation-ID"]
    assert generated_id != invalid_correlation_id
    UUID(generated_id)


def test_invalid_fixture_fails_fast_during_application_startup(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["vms"][0]["compute"] = "compute-missing"
    invalid_path = tmp_path / "invalid-reference.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidTopologySnapshotError) as caught:
        with TestClient(create_app(invalid_path)):
            pass

    assert caught.value.code == "INVALID_TOPOLOGY_SNAPSHOT"
    assert "compute-missing" in caught.value.reason


class _ExplodingIncidentService:
    def create_recovery_context(self, incident_type: str, resource: str):
        raise RuntimeError("secret implementation detail")


def test_unexpected_exception_returns_sanitized_500_error() -> None:
    application = create_app(FIXTURE_PATH)
    with TestClient(application, raise_server_exceptions=False) as test_client:
        application.state.incident_service = _ExplodingIncidentService()
        response = test_client.post(
            "/incidents",
            json={"type": "COMPUTE_DOWN", "resource": "compute-01"},
            headers={"X-Correlation-ID": "safe-error-test"},
        )

    error = _assert_error(
        response,
        status_code=500,
        code="INTERNAL_ERROR",
        correlation_id="safe-error-test",
    )
    assert error["message"] == "An unexpected internal error occurred."
    assert "secret implementation detail" not in response.text
