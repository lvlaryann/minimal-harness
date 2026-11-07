"""Tests for the Pi-like interactive tool runtime."""

import json
import tempfile
import unittest
from pathlib import Path

from meta_harness.agent import Agent
from meta_harness.tools import ToolError, ToolRegistry


class AgentTests(unittest.TestCase):
    """Verify model-driven tool execution and workspace safety."""

    def test_agent_executes_write_then_returns_final_text(self) -> None:
        """Execute a model-requested write before final response.

        Returns
        -------
        None
            Assertions pass when the tool loop completes.
        """
        client = ToolCallClient()
        with tempfile.TemporaryDirectory() as directory:
            answer = Agent(directory, client=client).run("Build an app")
            content = Path(directory, "index.html").read_text()
        self.assertEqual(answer, "App created")
        self.assertEqual(content, "<h1>Minimal Harness</h1>")
        self.assertEqual(client.calls, 2)

    def test_registry_rejects_path_escape(self) -> None:
        """Reject file operations outside the workspace root.

        Returns
        -------
        None
            Assertions pass when traversal is blocked.
        """
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ToolError):
                ToolRegistry(directory).write("../escape.txt", "bad")

    def test_agent_starts_with_ask_prompt(self) -> None:
        """The agent begins with the ask-don't-assume system prompt.

        Returns
        -------
        None
            Assertions pass when the system message is present.
        """
        agent = Agent(".", client=ToolCallClient())
        self.assertEqual(agent.messages[0]["role"], "system")
        self.assertIn("ask", agent.messages[0]["content"].lower())

    def test_ask_tool_uses_questioner(self) -> None:
        """The ask tool returns the questioner's chosen answer.

        Returns
        -------
        None
            Assertions pass when the answer is returned.
        """
        registry = ToolRegistry(".", questioner=lambda q, opts: "beta")
        raw = registry.execute(
            "ask", {"question": "Pick", "options": ["alpha", "beta"]}
        )
        self.assertEqual(json.loads(raw)["answer"], "beta")

    def test_ask_tool_hidden_without_questioner(self) -> None:
        """The ask tool is only advertised with a questioner wired.

        Returns
        -------
        None
            Assertions pass when visibility tracks the questioner.
        """
        bare = ToolRegistry(".")
        self.assertNotIn("ask", self._names(bare))
        self.assertNotIn("suggest", self._names(bare))
        wired = ToolRegistry(".", questioner=lambda q, opts: "x")
        self.assertIn("ask", self._names(wired))
        self.assertIn("suggest", self._names(wired))

    def test_suggest_tool_records_short_options(self) -> None:
        """The suggest tool stores short clickable labels.

        Returns
        -------
        None
            Assertions pass when suggestions are recorded.
        """
        registry = ToolRegistry(".", questioner=lambda q, opts: "")
        registry.execute(
            "suggest",
            {"options": ["Find local experts", "Find local class"]},
        )
        self.assertEqual(
            registry.suggestions,
            ["Find local experts", "Find local class"],
        )

    def test_ask_schema_states_one_question(self) -> None:
        """The advertised ask tool describes a single question.

        Returns
        -------
        None
            Assertions pass when the description is explicit.
        """
        registry = ToolRegistry(".", questioner=lambda q, opts: "")
        ask = next(
            item
            for item in registry.schema()
            if item["function"]["name"] == "ask"
        )
        self.assertIn("one question", ask["function"]["description"])

    def test_bundled_questions_are_redirected_to_ask_tool(self) -> None:
        """Bundled prose questions trigger one corrective ask turn.

        Returns
        -------
        None
            Assertions pass when the questioner sees one question.
        """
        client = BundledQuestionClient()
        agent = Agent(".", client=client)
        asked = []
        agent.tools.questioner = lambda q, o: asked.append((q, o)) or "8x10"
        answer = agent.run("Build a greenhouse")
        self.assertEqual(answer, "Plan ready")
        self.assertEqual(asked, [("Which size?", ["8x10", "12x20"])])
        self.assertEqual(client.calls, 3)

    def test_malformed_tool_arguments_are_repaired(self) -> None:
        """Truncated tool arguments do not poison later requests.

        Returns
        -------
        None
            Assertions pass when invalid arguments become an empty object.
        """
        client = MalformedToolClient()
        answer = Agent(".", client=client).run("Write a plan")
        assistant = next(
            item for item in client.last_messages if item.get("tool_calls")
        )
        self.assertEqual(answer, "Recovered")
        self.assertEqual(
            assistant["tool_calls"][0]["function"]["arguments"], "{}"
        )

    def test_outputs_folder_accepts_delivered_files(self) -> None:
        """The outputs folder is writable without widening the workspace.

        Returns
        -------
        None
            Assertions pass when delivery writes succeed.
        """
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory, "out")
            outputs.mkdir()
            registry = ToolRegistry(directory, outputs=outputs)
            registry.write(str(outputs / "plan.txt"), "hello")
            self.assertEqual(Path(outputs, "plan.txt").read_text(), "hello")

    def test_make_pdf_writes_into_outputs(self) -> None:
        """The PDF tool saves under the output folder.

        Returns
        -------
        None
            Assertions pass when the PDF file exists.
        """
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory, "out")
            registry = ToolRegistry(directory, outputs=outputs)
            result = registry.make_pdf("plan.pdf", "Plan", "Hello")
            self.assertTrue(Path(result["path"]).exists())

    def test_agent_prompt_names_output_folder(self) -> None:
        """The system prompt tells the agent where to save deliverables.

        Returns
        -------
        None
            Assertions pass when the folder path is present.
        """
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(".", client=ToolCallClient(), outputs=directory)
            prompt = agent.messages[0]["content"]
            self.assertIn(str(Path(directory).resolve()), prompt)

    def _names(self, registry: ToolRegistry) -> list[str]:
        """Return advertised tool names.

        Parameters
        ----------
        registry : ToolRegistry
            Tool registry to inspect.

        Returns
        -------
        list[str]
            Advertised tool names.
        """
        return [item["function"]["name"] for item in registry.schema()]


class InstallGuardTests(unittest.TestCase):
    """Verify package-install commands prompt for approval."""

    def test_install_command_detected(self) -> None:
        """Common install commands are recognized.

        Returns
        -------
        None
            Assertions pass when both forms are detected.
        """
        registry = ToolRegistry(".")
        self.assertTrue(registry._is_install("pip install reportlab"))
        self.assertTrue(registry._is_install("npm install axios"))

    def test_plain_command_not_detected(self) -> None:
        """Non-install commands are not flagged.

        Returns
        -------
        None
            Assertions pass when the command is ignored.
        """
        registry = ToolRegistry(".")
        self.assertFalse(registry._is_install("python script.py"))
        self.assertFalse(registry._is_install("ls -la"))

    def test_install_requires_approval(self) -> None:
        """An install command asks the questioner first.

        Returns
        -------
        None
            Assertions pass when approval is requested.
        """
        asked = []

        def questioner(question, options):
            asked.append((question, options))
            return "No, don't install"

        registry = ToolRegistry(".", questioner=questioner)
        with self.assertRaises(ToolError):
            registry.bash("pip install reportlab")
        self.assertEqual(len(asked), 1)
        self.assertIn("install", asked[0][0].lower())
        self.assertIn("Yes, install it", asked[0][1])

    def test_install_approval_missing_raises(self) -> None:
        """Without a questioner the install is rejected.

        Returns
        -------
        None
            Assertions pass when a ToolError is raised.
        """
        registry = ToolRegistry(".")
        with self.assertRaises(ToolError):
            registry.bash("pip install reportlab")


class ToolCallClient:
    """Return one write call followed by final text."""

    def __init__(self) -> None:
        """Initialize the call counter.

        Returns
        -------
        None
            This initializer configures the fake client.
        """
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return a deterministic tool-call sequence.

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
        self.calls += 1
        if self.calls == 1:
            return {"choices": [{"message": self._write_message()}]}
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "App created"}}
            ]
        }

    def _write_message(self) -> dict:
        """Build the write tool-call message.

        Returns
        -------
        dict
            Assistant message containing one write call.
        """
        arguments = (
            '{"path": "index.html", "content": "<h1>Minimal Harness</h1>"}'
        )
        call = {
            "id": "call-1",
            "function": {"name": "write", "arguments": arguments},
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}


class BundledQuestionClient:
    """Return bundled prose, then one ask call, then final text."""

    def __init__(self) -> None:
        """Initialize the call counter.

        Returns
        -------
        None
            This initializer configures the fake client.
        """
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return a deterministic question sequence.

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
        self.calls += 1
        return {"choices": [{"message": self._message()}]}

    def _message(self) -> dict:
        """Build the message for the current call.

        Returns
        -------
        dict
            Assistant message.
        """
        if self.calls == 1:
            return {"role": "assistant", "content": "Which size? Budget?"}
        if self.calls == 2:
            return self._ask_message()
        return {"role": "assistant", "content": "Plan ready"}

    def _ask_message(self) -> dict:
        """Build a single ask tool call.

        Returns
        -------
        dict
            Assistant message with one ask call.
        """
        arguments = '{"question": "Which size?", "options": ["8x10", "12x20"]}'
        call = {
            "id": "call-1",
            "function": {"name": "ask", "arguments": arguments},
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}


class MalformedToolClient:
    """Return one truncated tool call followed by final text."""

    def __init__(self) -> None:
        """Initialize the call counter.

        Returns
        -------
        None
            This initializer configures the fake client.
        """
        self.calls = 0
        self.last_messages: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return a deterministic malformed-then-fixed sequence.

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
        self.calls += 1
        self.last_messages = messages
        return {"choices": [{"message": self._message()}]}

    def _message(self) -> dict:
        """Build the message for the current call.

        Returns
        -------
        dict
            Assistant message.
        """
        if self.calls == 1:
            return self._broken_message()
        return {"role": "assistant", "content": "Recovered"}

    def _broken_message(self) -> dict:
        """Build a truncated write tool call.

        Returns
        -------
        dict
            Assistant message with invalid argument JSON.
        """
        call = {
            "id": "call-1",
            "function": {"name": "write", "arguments": '{"path": "x"'},
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}


if __name__ == "__main__":
    unittest.main()
