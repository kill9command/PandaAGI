from pydantic import ValidationError
import pytest

from libs.gateway.schemas import (
    GuideResponse,
    TaskTicket,
    RawBundle,
    Capsule,
)


def test_task_ticket_enforces_type_literal():
    ok = TaskTicket.model_validate(
        {
            "_type": "TICKET",
            "ticket_id": "ticket-123",
            "user_turn_id": "turn-456",
            "goal": "Validate schema contracts",
        }
    )
    assert ok.ticket_id == "ticket-123"

    with pytest.raises(ValidationError):
        TaskTicket.model_validate(
            {
                "_type": "ANSWER",
                "ticket_id": "bad",
                "user_turn_id": "turn-x",
                "goal": "Should fail",
            }
        )


def test_raw_bundle_requires_bundle_type():
    assert RawBundle.model_validate(
        {
            "_type": "BUNDLE",
            "ticket_id": "ticket-123",
            "status": "ok",
            "items": [],
        }
    )
    with pytest.raises(ValidationError):
        RawBundle.model_validate(
            {
                "_type": "WRONG",
                "ticket_id": "ticket-123",
                "status": "ok",
                "items": [],
            }
        )


def test_capsule_requires_capsule_type():
    assert Capsule.model_validate(
        {
            "_type": "CAPSULE",
            "ticket_id": "ticket-123",
            "status": "ok",
            "claims": [],
            "caveats": [],
            "open_questions": [],
            "artifacts": [],
            "budget_report": {},
        }
    )
    with pytest.raises(ValidationError):
        Capsule.model_validate(
            {
                "_type": "BUNDLE",
                "ticket_id": "ticket-123",
                "status": "ok",
                "claims": [],
                "caveats": [],
                "open_questions": [],
                "artifacts": [],
                "budget_report": {},
            }
        )


def test_guide_response_requires_answer_for_answer_type():
    with pytest.raises(ValidationError):
        GuideResponse.model_validate(
            {
                "_type": "ANSWER",
                "analysis": "Finishing the task",
                "needs_more_context": False,
            }
        )

    resp = GuideResponse.model_validate(
        {
            "_type": "ANSWER",
            "analysis": "Summarizing ticket results",
            "answer": "All tasks complete.",
        }
    )
    assert resp.answer == "All tasks complete."


def test_guide_ticket_allows_missing_answer():
    ticket = GuideResponse.model_validate(
        {
            "_type": "TICKET",
            "analysis": "Need to run Coordinator plan",
            "needs_more_context": False,
            "ticket_id": "ticket-300",
            "user_turn_id": "turn-1",
            "goal": "Collect pricing",
        }
    )
    assert ticket.type_ == "TICKET"
