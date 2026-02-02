"""
Shared-state infrastructure for the Guide/Coordinator/Context Manager pipeline.

This package provides small, testable building blocks:

- `ArtifactStore`    → content-addressed blob storage for large tool outputs.
- `SessionLedger`    → append-only ledger tracking sessions, turns, tickets, bundles, and capsules.
- `ClaimRegistry`    → persistent table of verified claims with delta computation helpers.
- `FreshnessOracle`  → heuristics for claim TTLs and staleness checks.
- `schema`           → Pydantic models describing tickets, bundles, and capsules.
"""

from .artifact_store import ArtifactStore, ArtifactRecord
from .ledger import SessionLedger, LedgerEvent
from .claims import ClaimRegistry, ClaimRow
from .freshness import FreshnessOracle
from .schema import (
    TaskTicket,
    RawBundle,
    RawBundleItem,
    BundleUsage,
    DistilledCapsule,
    CapsuleClaim,
    CapsuleArtifact,
    CapsuleDelta,
    QualityReport,
)

__all__ = [
    "ArtifactStore",
    "ArtifactRecord",
    "SessionLedger",
    "LedgerEvent",
    "ClaimRegistry",
    "ClaimRow",
    "FreshnessOracle",
    "TaskTicket",
    "RawBundle",
    "RawBundleItem",
    "BundleUsage",
    "DistilledCapsule",
    "CapsuleClaim",
    "CapsuleArtifact",
    "CapsuleDelta",
    "QualityReport",
]
