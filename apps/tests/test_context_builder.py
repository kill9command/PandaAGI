from __future__ import annotations

from pathlib import Path

from apps.services.tool_server.context_builder import (
    WorkingMemoryConfig,
    compile_capsule,
    update_working_memory,
)
from apps.services.tool_server.shared_state import (
    ArtifactStore,
    ClaimRegistry,
    DistilledCapsule,
    RawBundle,
    RawBundleItem,
    BundleUsage,
)
from apps.services.tool_server.shared_state.schema import TaskTicket, CapsuleClaim


def test_compile_capsule_extracts_pricing_claim(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    claim_registry = ClaimRegistry(tmp_path / "ledger.db")
    ticket = TaskTicket.model_validate(
        {
            "_type": "TICKET",
            "ticket_id": "ticket-1",
            "user_turn_id": "turn-1",
            "goal": "Find Syrian hamster vendors",
            "micro_plan": ["Search for hamster offers"],
            "subtasks": [{"kind": "search", "q": "Syrian hamster for sale"}],
            "constraints": {},
            "verification": {},
            "return": {"format": "raw_bundle"},
        }
    )

    handle = "ticket-1:purchasing.lookup:0"
    raw_item = RawBundleItem(
        handle=handle,
        kind="commerce",
        summary="1 offer",
        blob_id=None,
        preview='{"offers":[{"title":"Hamster","price":12.99,"currency":"USD","source":"Example"}]}',
        metadata={"tool": "purchasing.lookup"},
    )
    raw_bundle = RawBundle(
        ticket_id="ticket-1",
        status="ok",
        items=[raw_item],
        notes={},
        usage=BundleUsage(latency_ms=120),
    )
    result = compile_capsule(
        session_id="session-1",
        ticket=ticket,
        raw_bundle=raw_bundle,
        claim_registry=claim_registry,
        artifact_store=artifact_store,
        config=WorkingMemoryConfig(),
        tool_records=[
            {
                "tool": "purchasing.lookup",
                "args": {},
                "response": {
                    "offers": [
                        {
                            "title": "Hamster",
                            "price": 12.99,
                            "currency": "USD",
                            "availability": "In stock",
                            "source": "Example",
                        }
                    ]
                },
                "handle": handle,
                "blob_id": "",
            }
        ],
    )

    assert result.capsule.claims, "Expected at least one claim from purchasing lookup"
    claim = result.capsule.claims[0]
    assert "priced at" in claim.claim
    assert claim.metadata.get("source_tool") == "purchasing.lookup"
    assert result.envelope.claims_topk, "Envelope should reference top claim IDs"


def test_update_working_memory_prunes_to_cap(tmp_path: Path) -> None:
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    claim_registry = ClaimRegistry(tmp_path / "ledger.db")
    config = WorkingMemoryConfig(max_claims=3)
    session_id = "session-prune"

    # Seed registry with more claims than max_claims
    for idx in range(5):
        capsule = DistilledCapsule(
            ticket_id=f"ticket-{idx}",
            status="ok",
            claims=[
                CapsuleClaim(
                    claim=f"Fact {idx}",
                    evidence=[f"handle-{idx}"],
                    confidence="medium",
                    metadata={"score": idx},
                )
            ],
            caveats=[],
            open_questions=[],
            artifacts=[],
            budget_report={},
        )
        claim_registry.record_capsule(
            session_id=session_id,
            turn_id=f"turn-{idx}",
            ticket_id=f"ticket-{idx}",
            capsule=capsule,
        )

    snapshot = update_working_memory(
        claim_registry,
        session_id=session_id,
        config=config,
    )

    assert len(snapshot.claims) == 3
    assert all(claim.claim_id for claim in snapshot.claims)
