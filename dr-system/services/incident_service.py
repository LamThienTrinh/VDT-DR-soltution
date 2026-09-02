"""Build a deterministic recovery context from an abstract topology provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from models.recovery_context import (
    Compute,
    Incident,
    RecoveryContext,
    SourceLocation,
    VirtualMachine,
)


SUPPORTED_INCIDENT_TYPE = "COMPUTE_DOWN"


class UnsupportedIncidentTypeError(ValueError):
    """Raised when a v1 request uses an incident type outside its contract."""

    code = "UNSUPPORTED_INCIDENT_TYPE"

    def __init__(self, incident_type: str) -> None:
        self.incident_type = incident_type
        super().__init__(f"incident type {incident_type!r} is not supported")


@runtime_checkable
class TopologyProvider(Protocol):
    """Small read-only interface needed to build a v1 recovery context."""

    def get_compute(self, name: str) -> Compute:
        """Return an exact-name compute or raise a resource-not-found error."""

    def list_vms_by_compute(self, name: str) -> Sequence[VirtualMachine]:
        """Return VMs associated with *name*."""

    def list_available_computes(self, exclude_name: str) -> Sequence[Compute]:
        """Return preliminary candidates, excluding *exclude_name*."""


@dataclass(frozen=True, slots=True)
class IncidentService:
    """Orchestrate topology queries for the only supported v1 incident."""

    provider: TopologyProvider

    def create_recovery_context(
        self, incident_type: str, resource: str
    ) -> RecoveryContext:
        """Build a typed, deterministic context without changing provider state."""

        if incident_type != SUPPORTED_INCIDENT_TYPE:
            raise UnsupportedIncidentTypeError(incident_type)

        normalized_resource = resource.strip()
        if not normalized_resource:
            raise ValueError("resource must not be blank")

        source_compute = self.provider.get_compute(normalized_resource)
        affected_vms = self.provider.list_vms_by_compute(normalized_resource)
        available_computes = self.provider.list_available_computes(normalized_resource)

        return RecoveryContext(
            incident=Incident(
                type=SUPPORTED_INCIDENT_TYPE,
                resource=normalized_resource,
            ),
            affected_vms=tuple(sorted(vm.name for vm in affected_vms)),
            source=SourceLocation(az=source_compute.az, rack=source_compute.rack),
            available_compute=tuple(
                sorted(compute.name for compute in available_computes)
            ),
        )
