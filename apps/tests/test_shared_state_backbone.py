from __future__ import annotations

from pathlib import Path

from apps.services.orchestrator.shared_state import (
    ArtifactStore,
    SessionLedger,
    ClaimRegistry,
    DistilledCapsule,
    CapsuleClaim,
    CapsuleArtifact,
)
from apps.services.orchestrator.context_builder import WorkingMemoryConfig, update_working_memory


def test_artifact_store_deduplicates_and_resolves(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    record_a = store.store_text("hello world", metadata={"source": "test"})
    record_b = store.store_text("hello world", metadata={"source": "duplicate"})
    assert record_a.blob_id == record_b.blob_id
    path = store.resolve_path(record_a.blob_id)
    assert path.read_text() == "hello world"


def test_session_ledger_records_events(tmp_path: Path) -> None:
    ledger = SessionLedger(tmp_path / "ledger.db")
    event = ledger.log_event(session_id="sess1", kind="turn.start", turn_id="turn1", payload={"mode": "chat"})
    assert event.session_id == "sess1"
    assert event.payload["mode"] == "chat"
    latest = ledger.latest_event(session_id="sess1")
    assert latest is not None
    assert latest.event_id == event.event_id


def test_claim_registry_delta(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    registry = ClaimRegistry(db_path)
    capsule = DistilledCapsule(
        ticket_id="ticket1",
        status="ok",
        claims=[
            CapsuleClaim(
                claim="Hamsters available at $12.99",
                evidence=["ticket1:purchasing.lookup:0"],
                confidence="high",
                last_verified="2025-11-06T04:41:40Z",
            )
        ],
        caveats=[],
        open_questions=[],
        artifacts=[
            CapsuleArtifact(label="Hamster offers", blob_id="blob://abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        ],
        budget_report={"raw_tokens": 1400, "reduced_tokens": 320},
    )

    delta_first = registry.record_capsule(session_id="sess1", turn_id="turn1", ticket_id="ticket1", capsule=capsule)
    assert len(delta_first.claims) == 1
    assert delta_first.claims[0].claim_id is not None
    assert delta_first.artifacts  # first artifact is new

    # Recording the same capsule again should yield an empty delta
    delta_second = registry.record_capsule(session_id="sess1", turn_id="turn2", ticket_id="ticket1", capsule=capsule)
    assert len(delta_second.claims) == 0
    assert len(delta_second.artifacts) == 0

    # Modifying the claim changes the fingerprint and surfaces a delta
    updated_capsule = DistilledCapsule(
        ticket_id="ticket1",
        status="ok",
        claims=[
            CapsuleClaim(
                claim="Hamsters available at $10.99",
                evidence=["ticket1:purchasing.lookup:0"],
                confidence="medium",
                last_verified="2025-11-06T05:00:00Z",
            )
        ],
        caveats=[],
        open_questions=[],
        artifacts=[],
        budget_report={"raw_tokens": 1400, "reduced_tokens": 320},
    )
    delta_third = registry.record_capsule(session_id="sess1", turn_id="turn3", ticket_id="ticket1", capsule=updated_capsule)
    assert len(delta_third.claims) == 1
    assert delta_third.claims[0].claim.startswith("Hamsters available at $10.99")

def test_working_memory_caps_and_eviction(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    registry = ClaimRegistry(db_path)
    config = WorkingMemoryConfig(max_claims=5)

    for i in range(10):
        capsule = DistilledCapsule(
            ticket_id=f"ticket{i}",
            status="ok",
            claims=[
                CapsuleClaim(
                    claim=f"Claim {i}",
                    evidence=[f"ticket{i}:tool:0"],
                )
            ],
        )
        registry.record_capsule(session_id="sess1", turn_id=f"turn{i}", ticket_id=f"ticket{i}", capsule=capsule)

    active_claims = list(registry.list_active_claims(session_id="sess1"))
    assert len(active_claims) == 10

    snapshot = update_working_memory(registry, session_id="sess1", config=config)
    assert len(snapshot.claims) == config.max_claims
