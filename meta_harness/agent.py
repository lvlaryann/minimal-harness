"""Pi-like stateful tool-calling agent runtime."""

import json
import re
import time
from pathlib import Path
from typing import Any

from .openrouter import OpenRouterClient
from .prompts import load as _load_prompt
from .review import ReviewBlocked, ReviewGate
from .session import Session
from .tools import ToolError, ToolRegistry

_QUESTION_NUDGE = (
    "Ask only one question at a time, and ask it with the ask tool. Give "
    "2 to 5 short options. Ask the single most important question now."
)

_OUTPUTS_HINT = "\n\n## Output files\n\nSave files the user should keep in: "


class Agent:
    """Run a bounded conversation with model-invoked tools."""

    def __init__(
        self,
        root: Path | str = ".",
        client: OpenRouterClient | None = None,
        max_turns: int = 12,
        session: Session | None = None,
        observer=None,
        outputs: Path | str | None = None,
        review: bool = True,
        max_revisions: int = 2,
    ) -> None:
        """Initialize an agent session.

        Parameters
        ----------
        root : pathlib.Path or str
            Workspace root.
        client : OpenRouterClient or None
            Optional model client.
        max_turns : int
            Maximum model turns.
        session : Session or None
            Optional persisted session.
        observer : callable or None
            Optional callback run after each tool call.
        outputs : pathlib.Path or str or None
            Optional folder for files the user should keep.
        review : bool
            Whether final drafts pass through the review gate.
        max_revisions : int
            Number of revision passes allowed after a blocked review.

        Returns
        -------
        None
            This initializer configures the agent.
        """
        self.observer = observer
        self.client = client or OpenRouterClient()
        self.outputs = Path(outputs).resolve() if outputs else None
        self.tools = ToolRegistry(root, outputs=self.outputs)
        self.max_turns = max_turns
        self.session = session
        self.messages: list[dict[str, Any]] = self._initial_messages(session)
        self.steering: list[str] = []
        self.follow_up: list[str] = []
        self._question_nudged = False
        self.review_gate = ReviewGate(self.client) if review else None
        self.max_revisions = max_revisions
        self.tool_log: list[dict[str, Any]] = []
        self.last_review: dict[str, Any] | None = None

    def _initial_messages(
        self, session: Session | None
    ) -> list[dict[str, Any]]:
        """Copy messages from an optional session.

        Parameters
        ----------
        session : Session or None
            Optional persisted session.

        Returns
        -------
        list[dict[str, Any]]
            Initial conversation messages.
        """
        messages = session.messages[:] if session else []
        for message in messages:
            if message.get("role") == "assistant":
                _repair_tool_calls(message)
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = self._system_content()
            return messages
        return [
            {"role": "system", "content": self._system_content()}
        ] + messages

    def _system_content(self) -> str:
        """Return the system prompt with the output folder.

        Returns
        -------
        str
            Agent system instruction.
        """
        content = _load_prompt("agent")
        if self.outputs is None:
            return content
        return (
            content
            + _OUTPUTS_HINT
            + str(self.outputs)
            + "\n\n"
            + _load_prompt("deliverables")
        )

    def set_outputs(self, path: Path | str | None) -> None:
        """Point the agent at a session output folder.

        Parameters
        ----------
        path : pathlib.Path or str or None
            Folder for delivered files.

        Returns
        -------
        None
            Tool access and the system message are updated.
        """
        self.outputs = Path(path).resolve() if path else None
        self.tools.outputs = self.outputs
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self._system_content()

    def run(self, prompt: str) -> str:
        """Run the agent until final text or turn limit.

        Parameters
        ----------
        prompt : str
            User task.

        Returns
        -------
        str
            Final assistant response.
        """
        self._append({"role": "user", "content": prompt})
        self._question_nudged = False
        self.tool_log = []
        before = _file_snapshot(self.outputs)
        draft = self._loop()
        return self._reviewed(prompt, draft, before)

    def _reviewed(
        self, request: str, draft: str, before: dict[Path, int]
    ) -> str:
        """Run the review gate on a draft.

        Parameters
        ----------
        request : str
            Original user request.
        draft : str
            Draft answer.
        before : dict[pathlib.Path, int]
            File snapshot taken before the draft.

        Returns
        -------
        str
            Accepted draft.
        """
        gate = self.review_gate
        if gate is None or not hasattr(self.client, "complete"):
            return draft
        return self._review_loop(gate, request, draft, before)

    def _review_loop(
        self,
        gate: ReviewGate,
        request: str,
        draft: str,
        before: dict[Path, int],
    ) -> str:
        """Review, revise, and re-review until accepted or blocked.

        Parameters
        ----------
        gate : ReviewGate
            Review service.
        request : str
            Original user request.
        draft : str
            Draft answer.
        before : dict[pathlib.Path, int]
            File snapshot taken before the draft.

        Returns
        -------
        str
            Accepted draft.
        """
        for attempt in range(self.max_revisions + 1):
            result = self._review_result(gate, request, draft, before)
            if result.get("passed"):
                return draft
            if attempt == self.max_revisions:
                self._quarantine(before)
                raise ReviewBlocked(result.get("blockers", []), draft)
            draft = self._revise(result)
        return draft

    def _review_result(
        self,
        gate: ReviewGate,
        request: str,
        draft: str,
        before: dict[Path, int],
    ) -> dict[str, Any]:
        """Run one review pass and record it.

        Parameters
        ----------
        gate : ReviewGate
            Review service.
        request : str
            Original user request.
        draft : str
            Draft answer.
        before : dict[pathlib.Path, int]
            File snapshot taken before the draft.

        Returns
        -------
        dict[str, Any]
            Review verdict.
        """
        files = _changed_files(self.outputs, before)
        result = gate.review(request, draft, self.tool_log, files)
        self.last_review = result
        self._log_review(result)
        return result

    def _revise(self, result: dict[str, Any]) -> str:
        """Ask the agent to fix review blockers.

        Parameters
        ----------
        result : dict[str, Any]
            Blocking review verdict.

        Returns
        -------
        str
            Revised draft.
        """
        message = {
            "role": "user",
            "content": _revision(result),
            "hidden": True,
        }
        self._append(message)
        self.tool_log = []
        return self._loop()

    def _log_review(self, result: dict[str, Any]) -> None:
        """Append a review verdict to the session log.

        Parameters
        ----------
        result : dict[str, Any]
            Review verdict.

        Returns
        -------
        None
            The verdict is written when a session exists.
        """
        if self.session is None:
            return
        path = self.session.path.parent / "reviews.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"time": time.time(), "review": result}, default=str)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")

    def _quarantine(self, before: dict[Path, int]) -> None:
        """Move blocked files out of the delivered set.

        Parameters
        ----------
        before : dict[pathlib.Path, int]
            File snapshot taken before the draft.

        Returns
        -------
        None
            Changed files move to a hidden folder.
        """
        if self.outputs is None:
            return
        folder = Path(self.outputs) / ".review-blocked"
        folder.mkdir(parents=True, exist_ok=True)
        for path in _changed_files(self.outputs, before):
            path.replace(_unique(folder, path))

    def steer(self, prompt: str) -> None:
        """Queue a message to guide the next agent turn.

        Parameters
        ----------
        prompt : str
            Steering instruction.

        Returns
        -------
        None
            The instruction is queued.
        """
        self.steering.append(prompt)

    def queue_follow_up(self, prompt: str) -> None:
        """Queue a prompt after the current run completes.

        Parameters
        ----------
        prompt : str
            Follow-up instruction.

        Returns
        -------
        None
            The instruction is queued.
        """
        self.follow_up.append(prompt)

    def compact(self, keep: int = 20) -> list[dict[str, Any]]:
        """Compact the active session context.

        Parameters
        ----------
        keep : int
            Number of newest messages to retain.

        Returns
        -------
        list[dict[str, Any]]
            Discarded messages.
        """
        if not self.session:
            discarded = self.messages[:-keep]
            self.messages = self.messages[-keep:]
            return discarded
        discarded = self.session.compact(keep)
        self.messages = self.session.messages[:]
        return discarded

    def _loop(self) -> str:
        """Process model turns until completion.

        Returns
        -------
        str
            Final response or turn-limit message.
        """
        for _ in range(self.max_turns):
            outcome = self._resolve(self._message())
            if outcome is not None:
                return outcome
        return "Agent stopped after reaching the turn limit."

    def _resolve(self, message: dict[str, Any]) -> str | None:
        """Execute tools or settle on a final response.

        Parameters
        ----------
        message : dict[str, Any]
            One assistant message.

        Returns
        -------
        str or None
            Final text, or ``None`` when the loop should continue.
        """
        if message.get("tool_calls"):
            self._execute_calls(message["tool_calls"])
            return None
        content = str(message.get("content", ""))
        if self._nudge_questions(content):
            return None
        return content

    def _nudge_questions(self, content: str) -> bool:
        """Redirect bundled prose questions back to the ask tool.

        Parameters
        ----------
        content : str
            Assistant response text.

        Returns
        -------
        bool
            ``True`` when a corrective turn was queued.
        """
        if self._question_nudged or _count_questions(content) < 2:
            return False
        self._append({"role": "user", "content": _QUESTION_NUDGE})
        self._question_nudged = True
        return True

    def _message(self) -> dict[str, Any]:
        """Request and append one assistant message.

        Returns
        -------
        dict[str, Any]
            Assistant message.
        """
        self._inject_steering()
        response = self.client.chat(self.messages, self.tools.schema())
        message = response["choices"][0]["message"]
        _repair_tool_calls(message)
        self._append(message)
        return message

    def _inject_steering(self) -> None:
        """Append queued steering messages before a model call.

        Returns
        -------
        None
            Queued steering messages are consumed.
        """
        while self.steering:
            self._append({"role": "user", "content": self.steering.pop(0)})

    def _append(self, message: dict[str, Any]) -> None:
        """Append a message to memory and an optional session.

        Parameters
        ----------
        message : dict[str, Any]
            Message to append.

        Returns
        -------
        None
            Message state is updated.
        """
        self.messages.append(message)
        if self.session:
            self.session.append(message)

    def _execute_calls(self, calls: list[dict[str, Any]]) -> None:
        """Execute tool calls and append their results.

        Parameters
        ----------
        calls : list[dict[str, Any]]
            Model tool calls.

        Returns
        -------
        None
            Tool results are appended to the conversation.
        """
        for call in calls:
            self._append(self._tool_result(call))

    def _tool_result(self, call: dict[str, Any]) -> dict[str, Any]:
        """Execute one tool call safely.

        Parameters
        ----------
        call : dict[str, Any]
            OpenAI-compatible tool call.

        Returns
        -------
        dict[str, Any]
            Tool result message.
        """
        function = call["function"]
        arguments: dict[str, Any] = {}
        try:
            arguments = json.loads(function.get("arguments", "{}"))
            content = self.tools.execute(function["name"], arguments)
        except (ToolError, json.JSONDecodeError, KeyError) as exc:
            content = json.dumps({"error": str(exc)})
        if self.observer is not None:
            self.observer(function["name"], arguments, content)
        self.tool_log.append(
            {
                "name": function["name"],
                "arguments": arguments,
                "result": content,
            }
        )
        return {"role": "tool", "tool_call_id": call["id"], "content": content}


def _count_questions(text: str) -> int:
    """Count question marks outside fenced code blocks.

    Parameters
    ----------
    text : str
        Assistant response text.

    Returns
    -------
    int
        Number of question marks in prose.
    """
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return prose.count("?")


def _file_snapshot(root: Path | None) -> dict[Path, int]:
    """Return modification times for files under a root.

    Parameters
    ----------
    root : pathlib.Path or None
        Folder to scan.

    Returns
    -------
    dict[pathlib.Path, int]
        Files mapped to their modification time.
    """
    if root is None:
        return {}
    return {
        path: path.stat().st_mtime_ns
        for path in Path(root).rglob("*")
        if path.is_file() and ".review-blocked" not in path.parts
    }


def _unique(folder: Path, path: Path) -> Path:
    """Return a non-conflicting destination path.

    Parameters
    ----------
    folder : pathlib.Path
        Destination folder.
    path : pathlib.Path
        Source file.

    Returns
    -------
    pathlib.Path
        Available destination.
    """
    target = folder / path.name
    if not target.exists():
        return target
    return folder / f"{path.stem}-{int(time.time())}{path.suffix}"


def _changed_files(root: Path | None, before: dict[Path, int]) -> list[Path]:
    """Return files created or changed since a snapshot.

    Parameters
    ----------
    root : pathlib.Path or None
        Folder to scan.
    before : dict[pathlib.Path, int]
        Earlier file snapshot.

    Returns
    -------
    list[pathlib.Path]
        Changed files, sorted by path.
    """
    if root is None:
        return []
    current = _file_snapshot(root)
    return sorted(
        path for path, stamp in current.items() if before.get(path) != stamp
    )


def _revision(result: dict[str, Any]) -> str:
    """Build the hidden revision instruction.

    Parameters
    ----------
    result : dict[str, Any]
        Blocking review verdict.

    Returns
    -------
    str
        Instruction sent back to the agent.
    """
    lines = [
        "A reviewer blocked this answer. Fix every blocker and return the "
        "corrected answer."
    ]
    lines += _bullets(result.get("blockers"))
    lines += _fixes(result.get("fixes"))
    lines.append("Do not mention the review or this message in your answer.")
    return "\n".join(lines)


def _bullets(values: Any) -> list[str]:
    """Format blocker or fix entries.

    Parameters
    ----------
    values : Any
        Candidate list.

    Returns
    -------
    list[str]
        Bulleted text lines.
    """
    return [f"- {item}" for item in values or []]


def _fixes(values: Any) -> list[str]:
    """Format suggested fixes with a heading.

    Parameters
    ----------
    values : Any
        Candidate list.

    Returns
    -------
    list[str]
        Heading and bulleted text, or an empty list.
    """
    items = _bullets(values)
    return ["Suggested fixes:"] + items if items else []


def _repair_tool_calls(message: dict[str, Any]) -> None:
    """Replace unparseable tool-call arguments with an empty object.

    Parameters
    ----------
    message : dict[str, Any]
        Assistant message repaired in place.

    Returns
    -------
    None
        Invalid argument strings become ``{}``.
    """
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        try:
            json.loads(function.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            function["arguments"] = "{}"
