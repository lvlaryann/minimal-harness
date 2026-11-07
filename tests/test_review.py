"""Offline tests for the answer review gate."""

import json
import tempfile
import unittest
from pathlib import Path

from meta_harness.agent import Agent
from meta_harness.review import ReviewBlocked, ReviewGate
from meta_harness.session import Session


class ReviewClient:
    """Return scripted answers and review verdicts."""

    def __init__(
        self,
        answers: list[str] | None = None,
        reviews: list[dict | str] | None = None,
    ) -> None:
        """Initialize the scripted client.

        Parameters
        ----------
        answers : list[str] or None
            Draft answers returned by chat calls.
        reviews : list[dict or str] or None
            Reviewer responses in order.

        Returns
        -------
        None
            The scripted client is ready.
        """
        self.answers = answers or ["Draft"]
        self.reviews = list(reviews or [])
        self.chat_calls = 0
        self.reviewer_calls = 0
        self.adjudicator_calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return the next draft answer.

        Parameters
        ----------
        messages : list[dict]
            Conversation messages.
        tools : list[dict]
            Advertised tool schemas.

        Returns
        -------
        dict
            OpenAI-compatible response body.
        """
        self.chat_calls += 1
        index = min(self.chat_calls - 1, len(self.answers) - 1)
        message = {"role": "assistant", "content": self.answers[index]}
        return {"choices": [{"message": message}]}

    def complete(self, system: str, user: str) -> str:
        """Return a scripted reviewer or adjudicator verdict.

        Parameters
        ----------
        system : str
            System prompt.
        user : str
            Review context.

        Returns
        -------
        str
            JSON verdict text.
        """
        if "adjudicator" in system.lower():
            self.adjudicator_calls += 1
            return json.dumps(
                {"passed": True, "blockers": [], "rationale": "ok"}
            )
        self.reviewer_calls += 1
        return self._review_text()

    def _review_text(self) -> str:
        """Return the next reviewer response.

        Returns
        -------
        str
            Raw or encoded verdict text.
        """
        if not self.reviews:
            return json.dumps({"passed": True, "blockers": [], "fixes": []})
        value = self.reviews.pop(0)
        return value if isinstance(value, str) else json.dumps(value)


def blocked_review(blocker: str = "The door does not fit.") -> dict:
    """Build a blocking reviewer verdict.

    Parameters
    ----------
    blocker : str
        Problem text.

    Returns
    -------
    dict
        Blocking verdict.
    """
    return {"passed": False, "blockers": [blocker], "fixes": ["Fix it."]}


class ReviewGateTests(unittest.TestCase):
    """Verify review, revision, and blocking behavior."""

    def test_passing_draft_is_delivered(self) -> None:
        """A passing review and adjudication return the draft.

        Returns
        -------
        None
            Assertions pass when both stages run once.
        """
        client = ReviewClient(answers=["Draft"])
        answer = Agent(".", client=client).run("Do it")
        self.assertEqual(answer, "Draft")
        self.assertEqual(client.chat_calls, 1)
        self.assertEqual(client.reviewer_calls, 1)
        self.assertEqual(client.adjudicator_calls, 1)

    def test_blocked_draft_is_revised(self) -> None:
        """A blocked draft triggers one revision that then passes.

        Returns
        -------
        None
            Assertions pass when the revised draft is delivered.
        """
        client = ReviewClient(
            answers=["Draft one", "Draft two"],
            reviews=[blocked_review(), {"passed": True, "blockers": []}],
        )
        answer = Agent(".", client=client).run("Do it")
        self.assertEqual(answer, "Draft two")
        self.assertEqual(client.chat_calls, 2)
        self.assertEqual(client.reviewer_calls, 2)

    def test_revision_message_is_hidden(self) -> None:
        """The revision instruction is marked for the UI to skip.

        Returns
        -------
        None
            Assertions pass when one hidden message is stored.
        """
        client = ReviewClient(
            answers=["Draft one", "Draft two"],
            reviews=[blocked_review(), {"passed": True, "blockers": []}],
        )
        agent = Agent(".", client=client)
        agent.run("Do it")
        hidden = [item for item in agent.messages if item.get("hidden")]
        self.assertEqual(len(hidden), 1)

    def test_review_verdict_is_logged(self) -> None:
        """A passing verdict is appended to the session review log.

        Returns
        -------
        None
            Assertions pass when reviews.jsonl records the verdict.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "transcript.jsonl")
            client = ReviewClient(answers=["Draft"])
            Agent(".", client=client, session=Session(path)).run("Do it")
            log = Path(directory, "reviews.jsonl").read_text()
        self.assertIn('"passed": true', log)

    def test_blocked_after_revisions_raises(self) -> None:
        """A draft that stays blocked is never delivered.

        Returns
        -------
        None
            Assertions pass when ReviewBlocked carries the blockers.
        """
        client = ReviewClient(
            answers=["Draft one", "Draft two"],
            reviews=[blocked_review("Door too tall"), blocked_review("Still")],
        )
        with self.assertRaises(ReviewBlocked) as caught:
            Agent(".", client=client, max_revisions=1).run("Do it")
        self.assertEqual(caught.exception.blockers, ["Still"])

    def test_invalid_review_json_fails_closed(self) -> None:
        """Unparseable review output blocks the draft.

        Returns
        -------
        None
            Assertions pass when invalid JSON is treated as a blocker.
        """
        client = ReviewClient(answers=["Draft"], reviews=["not json"])
        with self.assertRaises(ReviewBlocked):
            Agent(".", client=client, max_revisions=0).run("Do it")

    def test_empty_file_blocks_before_model_review(self) -> None:
        """The deterministic gate rejects an empty file without a model call.

        Returns
        -------
        None
            Assertions pass when the blocker names the file.
        """
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory, "plan.html")
            empty.write_text("")
            gate = ReviewGate(object())
            result = gate.review("Build", "Done", [], [empty])
        self.assertFalse(result["passed"])
        self.assertTrue(any("empty" in item for item in result["blockers"]))

    def test_invalid_pdf_blocks(self) -> None:
        """A file with a PDF name but no PDF header is rejected.

        Returns
        -------
        None
            Assertions pass when the PDF check fails closed.
        """
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory, "plan.pdf")
            pdf.write_text("not a pdf")
            gate = ReviewGate(object())
            result = gate.review("Build", "Done", [], [pdf])
        self.assertFalse(result["passed"])
        self.assertTrue(any("PDF" in item for item in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
