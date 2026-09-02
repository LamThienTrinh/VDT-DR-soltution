from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from services.netbox_service import (
    InvalidTopologySnapshotError,
    NetBoxService,
    ResourceNotFoundError,
)


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "netbox_mock.json"


def _fixture_payload() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _write_snapshot(tmp_path: Path, payload: object) -> Path:
    snapshot_path = tmp_path / "netbox_mock.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot_path


def _assert_invalid_snapshot(snapshot_path: Path) -> InvalidTopologySnapshotError:
    with pytest.raises(InvalidTopologySnapshotError) as caught:
        NetBoxService.load_snapshot(snapshot_path)

    assert caught.value.code == "INVALID_TOPOLOGY_SNAPSHOT"
    assert caught.value.path == snapshot_path
    assert caught.value.reason
    return caught.value


def test_queries_return_sorted_results_from_the_checkpoint_fixture() -> None:
    service = NetBoxService.load_snapshot(FIXTURE_PATH)

    source = service.get_compute("compute-01")
    affected_vms = service.list_vms_by_compute(source.name)
    candidates = service.list_available_computes(source.name)

    assert source.status == "DOWN"
    assert source.az == "AZ-01"
    assert source.rack == "rack-01"
    assert [vm.name for vm in affected_vms] == ["vm-api-01", "vm-web-01"]
    assert [compute.name for compute in candidates] == ["compute-05", "compute-06"]


def test_ctx_002_unknown_compute_raises_resource_not_found() -> None:
    service = NetBoxService.load_snapshot(FIXTURE_PATH)

    with pytest.raises(ResourceNotFoundError) as caught:
        service.get_compute("compute-does-not-exist")

    assert caught.value.code == "RESOURCE_NOT_FOUND"
    assert caught.value.resource_name == "compute-does-not-exist"


def test_ctx_005_and_006_source_down_disabled_and_exhausted_computes_are_filtered() -> None:
    service = NetBoxService.load_snapshot(FIXTURE_PATH)

    candidates = service.list_available_computes("compute-01")
    candidate_names = [compute.name for compute in candidates]

    assert candidate_names == sorted(candidate_names)
    assert candidate_names == ["compute-05", "compute-06"]
    assert "compute-01" not in candidate_names
    for compute in service.snapshot.computes:
        if (
            compute.name == "compute-01"
            or compute.status != "UP"
            or not compute.enabled
            or any(
                getattr(compute.capacity, dimension)
                - getattr(compute.allocated, dimension)
                <= 0
                for dimension in ("vcpu", "ram_mb", "disk_gb")
            )
        ):
            assert compute.name not in candidate_names


def test_malformed_json_is_rejected_with_a_domain_error(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "malformed.json"
    snapshot_path.write_text('{"schema_version": "1.0",', encoding="utf-8")

    error = _assert_invalid_snapshot(snapshot_path)

    assert "JSON" in error.reason


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload.__setitem__("schema_version", "2.0"),
            id="unsupported-schema-version",
        ),
        pytest.param(
            lambda payload: payload.__setitem__(
                "snapshot_at", "2026-09-01T09:00:00"
            ),
            id="snapshot-without-timezone",
        ),
        pytest.param(
            lambda payload: payload.__setitem__("unexpected", True),
            id="extra-top-level-field",
        ),
        pytest.param(
            lambda payload: payload["computes"][0].pop("capacity"),
            id="missing-required-field",
        ),
    ],
)
def test_invalid_snapshot_schema_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    payload = _fixture_payload()
    mutate(payload)

    _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))


@pytest.mark.parametrize("collection", ["computes", "vms"])
def test_duplicate_compute_and_vm_names_are_rejected(
    tmp_path: Path,
    collection: str,
) -> None:
    payload = _fixture_payload()
    payload[collection].append(copy.deepcopy(payload[collection][0]))

    error = _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))

    assert "duplicate" in error.reason.lower()


@pytest.mark.parametrize("collection", ["computes", "vms"])
def test_blank_compute_and_vm_names_are_rejected(
    tmp_path: Path,
    collection: str,
) -> None:
    payload = _fixture_payload()
    payload[collection][0]["name"] = "   "

    _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))


def test_ctx_007_vm_reference_to_unknown_compute_is_rejected(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["vms"][0]["compute"] = "compute-missing"

    error = _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))

    assert "compute-missing" in error.reason


@pytest.mark.parametrize("dimension", ["vcpu", "ram_mb", "disk_gb"])
def test_allocated_resources_cannot_exceed_capacity(
    tmp_path: Path,
    dimension: str,
) -> None:
    payload = _fixture_payload()
    compute = payload["computes"][1]
    compute["allocated"][dimension] = compute["capacity"][dimension] + 1

    error = _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))

    assert dimension in error.reason


@pytest.mark.parametrize("bucket", ["capacity", "allocated"])
def test_resource_dimensions_cannot_be_negative(
    tmp_path: Path,
    bucket: str,
) -> None:
    payload = _fixture_payload()
    payload["computes"][1][bucket]["vcpu"] = -1

    _assert_invalid_snapshot(_write_snapshot(tmp_path, payload))


@pytest.mark.parametrize("dimension", ["vcpu", "ram_mb", "disk_gb"])
def test_candidate_with_any_exhausted_resource_is_filtered(
    tmp_path: Path,
    dimension: str,
) -> None:
    payload = _fixture_payload()
    candidate = next(
        compute for compute in payload["computes"] if compute["name"] == "compute-05"
    )
    candidate["allocated"][dimension] = candidate["capacity"][dimension]
    service = NetBoxService.load_snapshot(_write_snapshot(tmp_path, payload))

    candidate_names = [
        compute.name for compute in service.list_available_computes("compute-01")
    ]

    assert "compute-05" not in candidate_names
    assert "compute-06" in candidate_names
