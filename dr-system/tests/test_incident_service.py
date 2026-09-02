from __future__ import annotations

from pathlib import Path

import pytest

from services.incident_service import IncidentService, UnsupportedIncidentTypeError
from services.netbox_service import NetBoxService, ResourceNotFoundError


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "netbox_mock.json"


def test_ctx_001_compute_down_builds_the_expected_recovery_context() -> None:
    service = IncidentService(NetBoxService.load_snapshot(FIXTURE_PATH))

    context = service.create_recovery_context("COMPUTE_DOWN", "compute-01")

    assert context.incident.type == "COMPUTE_DOWN"
    assert context.incident.resource == "compute-01"
    assert context.affected_vms == ("vm-api-01", "vm-web-01")
    assert context.source.az == "AZ-01"
    assert context.source.rack == "rack-01"
    assert context.available_compute == ("compute-05", "compute-06")


def test_ctx_003_unsupported_incident_type_is_rejected() -> None:
    service = IncidentService(NetBoxService.load_snapshot(FIXTURE_PATH))

    with pytest.raises(UnsupportedIncidentTypeError) as caught:
        service.create_recovery_context("RACK_DOWN", "rack-01")

    assert caught.value.code == "UNSUPPORTED_INCIDENT_TYPE"
    assert caught.value.incident_type == "RACK_DOWN"


def test_resource_is_trimmed_without_case_folding() -> None:
    service = IncidentService(NetBoxService.load_snapshot(FIXTURE_PATH))

    context = service.create_recovery_context("COMPUTE_DOWN", "  compute-01\t")

    assert context.incident.resource == "compute-01"
    with pytest.raises(ResourceNotFoundError):
        service.create_recovery_context("COMPUTE_DOWN", "COMPUTE-01")


def test_ctx_008_repeated_calls_are_deterministic_and_do_not_mutate_snapshot() -> None:
    topology = NetBoxService.load_snapshot(FIXTURE_PATH)
    service = IncidentService(topology)
    snapshot_before = topology.snapshot.model_dump(mode="json")

    first = service.create_recovery_context("COMPUTE_DOWN", "compute-01")
    second = service.create_recovery_context("COMPUTE_DOWN", "compute-01")

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert topology.snapshot.model_dump(mode="json") == snapshot_before


class _RecordingTopologyProvider:
    def __init__(self, delegate: NetBoxService) -> None:
        self.delegate = delegate
        self.calls: list[tuple[str, str]] = []

    def get_compute(self, name: str):
        self.calls.append(("get_compute", name))
        return self.delegate.get_compute(name)

    def list_vms_by_compute(self, name: str):
        self.calls.append(("list_vms_by_compute", name))
        return self.delegate.list_vms_by_compute(name)

    def list_available_computes(self, exclude_name: str):
        self.calls.append(("list_available_computes", exclude_name))
        return self.delegate.list_available_computes(exclude_name)


def test_incident_service_uses_only_the_topology_provider_contract() -> None:
    provider = _RecordingTopologyProvider(NetBoxService.load_snapshot(FIXTURE_PATH))
    service = IncidentService(provider)

    service.create_recovery_context("COMPUTE_DOWN", "compute-01")

    assert provider.calls == [
        ("get_compute", "compute-01"),
        ("list_vms_by_compute", "compute-01"),
        ("list_available_computes", "compute-01"),
    ]
