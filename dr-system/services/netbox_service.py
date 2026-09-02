"""Immutable JSON-backed topology provider used by Checkpoint 1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from models.recovery_context import Compute, TopologySnapshot, VirtualMachine


class ResourceNotFoundError(LookupError):
    """Raised when an exact compute name is absent from the snapshot."""

    code = "RESOURCE_NOT_FOUND"

    def __init__(self, resource_name: str) -> None:
        self.resource_name = resource_name
        super().__init__(f"compute {resource_name!r} was not found")


class InvalidTopologySnapshotError(RuntimeError):
    """Raised when the aggregate fixture cannot be read or validated."""

    code = "INVALID_TOPOLOGY_SNAPSHOT"

    def __init__(self, path: str | Path, reason: str) -> None:
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.code}: {self.path}: {reason}")


@dataclass(frozen=True, slots=True)
class NetBoxService:
    """Query an already validated topology snapshot without mutating it."""

    snapshot: TopologySnapshot

    @classmethod
    def load_snapshot(cls, path: str | Path) -> NetBoxService:
        """Read and validate *path* once, returning a ready query service."""

        snapshot_path = Path(path)
        try:
            raw_snapshot = snapshot_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InvalidTopologySnapshotError(snapshot_path, str(exc)) from exc

        try:
            snapshot = TopologySnapshot.model_validate_json(raw_snapshot)
        except ValidationError as exc:
            raise InvalidTopologySnapshotError(
                snapshot_path, _format_validation_error(exc)
            ) from exc

        return cls(snapshot=snapshot)

    def get_compute(self, name: str) -> Compute:
        """Return the compute matching *name* exactly."""

        for compute in self.snapshot.computes:
            if compute.name == name:
                return compute
        raise ResourceNotFoundError(name)

    def list_vms_by_compute(self, name: str) -> tuple[VirtualMachine, ...]:
        """Return VMs on *name* in deterministic name order."""

        return tuple(
            sorted(
                (vm for vm in self.snapshot.vms if vm.compute == name),
                key=lambda vm: vm.name,
            )
        )

    def list_available_computes(self, exclude_name: str) -> tuple[Compute, ...]:
        """Return enabled UP computes with positive capacity in every dimension."""

        return tuple(
            sorted(
                (
                    compute
                    for compute in self.snapshot.computes
                    if compute.name != exclude_name
                    and compute.status == "UP"
                    and compute.enabled
                    and compute.has_available_capacity
                ),
                key=lambda compute: compute.name,
            )
        )


def _format_validation_error(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "snapshot"
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)
