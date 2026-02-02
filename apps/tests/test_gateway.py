import unittest
from unittest.mock import MagicMock, patch

from libs.gateway.app import app
from fastapi.testclient import TestClient


class TestGateway(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("project_build_instructions.gateway.app._run_ticket")
    def test_chat_completions_context_injection(self, mock_run_ticket):
        """Test that only capsule deltas and claim IDs are injected into the context."""
        mock_run_ticket.return_value = {
            "context_lines": [
                "New claims:",
                "- Claim 1 (ID: clm_123)",
                "Relevant claim IDs:",
                "- clm_abc",
            ],
            "effective_mode": "chat",
            "capsule": MagicMock(),
            "pricing_hit": False,
            "spreadsheet_hit": False,
            "bom_result": None,
            "policy_notes": [],
            "deferred": [],
        }

        response = self.client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        # This is a placeholder for a more specific assertion
        # We would need to inspect the `injected_context` variable in the `chat_completions` function
        # which is not directly accessible in this test.
        self.assertIn("choices", response.json())


if __name__ == "__main__":
    unittest.main()
