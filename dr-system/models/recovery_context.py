"""Strict, immutable models for the Week 2 topology and API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictFrozenModel(BaseModel):
    """Base model that rejects coercion, unknown fields, and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


class ResourceDimensions(StrictFrozenModel):
    """VCPU, memory, and disk values expressed in fixture units."""

    vcpu: int = Field(ge=0)
    ram_mb: int = Field(ge=0)
    disk_gb: int = Field(ge=0)

    def has_positive_remaining_after(self, allocated: ResourceDimensions) -> bool:
        """Return whether every resource dimension has positive headroom."""

        return (
            self.vcpu - allocated.vcpu > 0
            and self.ram_mb - allocated.ram_mb > 0
            and self.disk_gb - allocated.disk_gb > 0
        )


class Compute(StrictFrozenModel):
    """Aggregate compute topology and runtime capacity."""

    name: str
    status: Literal["UP", "DOWN"]
    enabled: bool
    az: str
    rack: str
    capacity: ResourceDimensions
    allocated: ResourceDimensions

    @field_validator("name", "az", "rack")
    @classmethod
    def validate_non_empty_strings(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _require_non_empty(value, field_name)

    @model_validator(mode="after")
    def validate_allocated_capacity(self) -> Self:
        dimensions = ("vcpu", "ram_mb", "disk_gb")
        for dimension in dimensions:
            allocated = getattr(self.allocated, dimension)
            capacity = getattr(self.capacity, dimension)
            if allocated > capacity:
                raise ValueError(
                    f"compute {self.name!r} has allocated {dimension} "
                    f"({allocated}) greater than capacity ({capacity})"
                )
        return self

    @property
    def has_available_capacity(self) -> bool:
        """Whether the compute has positive headroom in every dimension."""

        return self.capacity.has_positive_remaining_after(self.allocated)


class VirtualMachine(StrictFrozenModel):
    """A VM and its exact source-compute association."""

    name: str
    compute: str
    status: Literal["ACTIVE", "SHUTOFF", "ERROR"]
    resources: ResourceDimensions

    @field_validator("name", "compute")
    @classmethod
    def validate_non_empty_strings(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _require_non_empty(value, field_name)


class TopologySnapshot(StrictFrozenModel):
    """Validated, immutable aggregate fixture snapshot."""

    schema_version: Literal["1.0"]
    snapshot_at: datetime
    computes: tuple[Compute, ...]
    vms: tuple[VirtualMachine, ...]

    @field_validator("snapshot_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_resource_invariants(self) -> Self:
        compute_names = [compute.name for compute in self.computes]
        duplicate_computes = _duplicates(compute_names)
        if duplicate_computes:
            names = ", ".join(duplicate_computes)
            raise ValueError(f"duplicate compute name(s): {names}")

        vm_names = [vm.name for vm in self.vms]
        duplicate_vms = _duplicates(vm_names)
        if duplicate_vms:
            names = ", ".join(duplicate_vms)
            raise ValueError(f"duplicate VM name(s): {names}")

        known_computes = set(compute_names)
        missing_references = sorted(
            {vm.compute for vm in self.vms if vm.compute not in known_computes}
        )
        if missing_references:
            names = ", ".join(missing_references)
            raise ValueError(f"VM references unknown compute(s): {names}")

        return self


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


class IncidentRequest(StrictFrozenModel):
    """Unpersisted v1 incident input."""

    type: str
    resource: str

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("type must not be blank")
        return value

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        return _require_non_empty(value, "resource")


class Incident(StrictFrozenModel):
    """Incident identity echoed in a recovery context."""

    type: Literal["COMPUTE_DOWN"]
    resource: str

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        return _require_non_empty(value, "resource")


class SourceLocation(StrictFrozenModel):
    """Failure-domain location of an incident source."""

    az: str
    rack: str

    @field_validator("az", "rack")
    @classmethod
    def validate_non_empty_strings(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _require_non_empty(value, field_name)


class RecoveryContext(StrictFrozenModel):
    """Deterministic read-only context returned by Checkpoint 1."""

    incident: Incident
    affected_vms: tuple[str, ...]
    source: SourceLocation
    available_compute: tuple[str, ...]

    @field_validator("affected_vms", "available_compute")
    @classmethod
    def validate_sorted_unique_names(
        cls, values: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "values")
        normalized = tuple(_require_non_empty(value, field_name) for value in values)
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError(f"{field_name} must contain sorted unique names")
        return normalized
