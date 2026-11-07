"""Adversarial review gate for interactive answers and deliverables."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ._json_util import json_value
from .prompts import load as _load_prompt


class ReviewBlocked(RuntimeError):
    """Raised when a draft still fails review after revisions."""

    def __init__(self, blockers: list[str], draft: str) -> None:
        """Store the blockers and rejected draft.

        Parameters
        ----------
        blockers : list[str]
            Concrete problems found by the review.
        draft : str
            Rejected final draft.

        Returns
        -------
        None
            The exception is ready to raise.
        """
        self.blockers = [str(item) for item in blockers]
        self.draft = draft
        super().__init__(_message(self.blockers))


class ReviewGate:
    """Run deterministic checks, an adversarial review, and adjudication."""

    def __init__(self, client: Any) -> None:
        """Configure the gate.

        Parameters
        ----------
        client : Any
            Client with a ``complete(system, user)`` method.

        Returns
        -------
        None
            The gate is ready to use.
        """
        self.client = client

    def review(
        self,
        request: str,
        draft: str,
        tool_log: list[dict[str, Any]],
        files: list[Path],
    ) -> dict[str, Any]:
        """Review one draft and return a verdict.

        Parameters
        ----------
        request : str
            Original user request.
        draft : str
            Assistant draft.
        tool_log : list[dict[str, Any]]
            Tool calls made for this draft.
        files : list[pathlib.Path]
            Files created or changed by the draft.

        Returns
        -------
        dict[str, Any]
            Verdict with passed, blockers, and fixes.
        """
        blockers = _file_blockers(files)
        if blockers:
            return {
                "passed": False,
                "blockers": blockers,
                "fixes": ["Fix the file errors and try again."],
            }
        reviewer = self._reviewer(request, draft, tool_log, files)
        if not reviewer["passed"]:
            return reviewer
        verdict = self._adjudicator(request, draft, reviewer)
        verdict["reviewer"] = reviewer
        return verdict

    def _reviewer(
        self,
        request: str,
        draft: str,
        tool_log: list[dict[str, Any]],
        files: list[Path],
    ) -> dict[str, Any]:
        """Ask the reviewer to inspect one draft.

        Parameters
        ----------
        request : str
            Original user request.
        draft : str
            Assistant draft.
        tool_log : list[dict[str, Any]]
            Tool calls made for this draft.
        files : list[pathlib.Path]
            Files created or changed by the draft.

        Returns
        -------
        dict[str, Any]
            Reviewer verdict.
        """
        data = {
            "request": request,
            "draft": draft,
            "tool_calls": _tool_context(tool_log),
            "files": _file_context(files),
        }
        raw = self.client.complete(
            _load_prompt("answer_reviewer"), _context(data)
        )
        return _verdict(raw)

    def _adjudicator(
        self, request: str, draft: str, review: dict[str, Any]
    ) -> dict[str, Any]:
        """Ask the adjudicator to confirm a reviewed draft.

        Parameters
        ----------
        request : str
            Original user request.
        draft : str
            Revised assistant draft.
        review : dict[str, Any]
            Reviewer verdict.

        Returns
        -------
        dict[str, Any]
            Adjudicator verdict.
        """
        data = {"request": request, "draft": draft, "review": review}
        raw = self.client.complete(
            _load_prompt("answer_adjudicator"), _context(data)
        )
        return _verdict(raw)


def _context(data: dict[str, Any]) -> str:
    """Serialize review context for a model call.

    Parameters
    ----------
    data : dict[str, Any]
        Review payload.

    Returns
    -------
    str
        JSON text trimmed to a safe length.
    """
    return json.dumps(data, default=str)[:16000]


def _tool_context(tool_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize tool calls for the reviewer.

    Parameters
    ----------
    tool_log : list[dict[str, Any]]
        Tool calls recorded by the agent.

    Returns
    -------
    list[dict[str, Any]]
        Trimmed tool records.
    """
    return [
        {
            "name": item.get("name"),
            "arguments": item.get("arguments"),
            "result": str(item.get("result", ""))[:600],
        }
        for item in tool_log[-12:]
    ]


def _file_context(files: list[Path]) -> list[dict[str, Any]]:
    """Summarize files for the reviewer.

    Parameters
    ----------
    files : list[pathlib.Path]
        Files created or changed by the draft.

    Returns
    -------
    list[dict[str, Any]]
        File names, sizes, and excerpts.
    """
    return [_file_item(path) for path in files]


def _file_item(path: Path) -> dict[str, Any]:
    """Summarize one file.

    Parameters
    ----------
    path : pathlib.Path
        File to summarize.

    Returns
    -------
    dict[str, Any]
        Name, byte count, and optional excerpt.
    """
    item = {"name": path.name, "bytes": _size(path)}
    if path.suffix.lower() == ".html":
        item["excerpt"] = _html_text(path)[:3000]
    elif path.suffix.lower() in (".md", ".txt", ".svg"):
        item["excerpt"] = _read_text(path)[:3000]
    return item


def _html_text(path: Path) -> str:
    """Return the visible text of an HTML file.

    Parameters
    ----------
    path : pathlib.Path
        HTML file.

    Returns
    -------
    str
        Whitespace-collapsed body text.
    """
    text = _read_text(path)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _size(path: Path) -> int:
    """Return a file size without raising.

    Parameters
    ----------
    path : pathlib.Path
        File to inspect.

    Returns
    -------
    int
        Size in bytes, or zero.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_text(path: Path) -> str:
    """Read a text file without raising.

    Parameters
    ----------
    path : pathlib.Path
        File to read.

    Returns
    -------
    str
        File text, or blank on error.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _verdict(raw: str) -> dict[str, Any]:
    """Decode a reviewer or adjudicator response.

    Parameters
    ----------
    raw : str
        Model response.

    Returns
    -------
    dict[str, Any]
        Normalized verdict.
    """
    value = _decode(raw)
    if value is None:
        return _blocked("reviewer returned invalid JSON")
    blockers = _strings(value.get("blockers"))
    fixes = _strings(value.get("fixes"))
    rationale = str(value.get("rationale", ""))
    passed = bool(value.get("passed")) and not blockers
    return {
        "passed": passed,
        "blockers": blockers,
        "fixes": fixes,
        "rationale": rationale,
    }


def _decode(raw: str) -> dict[str, Any] | None:
    """Decode the first JSON object in a response.

    Parameters
    ----------
    raw : str
        Model response.

    Returns
    -------
    dict[str, Any] or None
        Decoded object, or None when invalid.
    """
    try:
        value = json_value(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _blocked(message: str) -> dict[str, Any]:
    """Build a fail-closed verdict.

    Parameters
    ----------
    message : str
        Blocker text.

    Returns
    -------
    dict[str, Any]
        Blocking verdict.
    """
    return {"passed": False, "blockers": [message], "fixes": []}


def _strings(value: Any) -> list[str]:
    """Normalize a list of text entries.

    Parameters
    ----------
    value : Any
        Candidate list.

    Returns
    -------
    list[str]
        Non-empty text entries.
    """
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _file_blockers(files: list[Path]) -> list[str]:
    """Run deterministic checks on changed files.

    Parameters
    ----------
    files : list[pathlib.Path]
        Files created or changed by the draft.

    Returns
    -------
    list[str]
        Concrete file problems.
    """
    blockers = []
    for path in files:
        blockers += _path_blockers(path)
    return blockers


def _path_blockers(path: Path) -> list[str]:
    """Check one file for basic delivery problems.

    Parameters
    ----------
    path : pathlib.Path
        File to check.

    Returns
    -------
    list[str]
        Problems found.
    """
    if not path.exists():
        return [f"{path.name} is missing"]
    if _size(path) == 0:
        return [f"{path.name} is empty"]
    return _content_blockers(path)


def _content_blockers(path: Path) -> list[str]:
    """Check file content by type.

    Parameters
    ----------
    path : pathlib.Path
        File to check.

    Returns
    -------
    list[str]
        Problems found.
    """
    suffix = path.suffix.lower()
    if suffix == ".html":
        return _html_blockers(path)
    if suffix == ".svg":
        return _svg_blockers(path)
    if suffix == ".pdf":
        return _pdf_blockers(path)
    return []


def _pdf_blockers(path: Path) -> list[str]:
    """Check that a PDF file has a valid header.

    Parameters
    ----------
    path : pathlib.Path
        PDF file.

    Returns
    -------
    list[str]
        Problems found.
    """
    try:
        with path.open("rb") as stream:
            header = stream.read(5)
    except OSError:
        return [f"{path.name} could not be read"]
    return (
        []
        if header.startswith(b"%PDF")
        else [f"{path.name} is not a valid PDF"]
    )


def _html_blockers(path: Path) -> list[str]:
    """Check that an HTML deliverable is complete.

    Parameters
    ----------
    path : pathlib.Path
        HTML file.

    Returns
    -------
    list[str]
        Problems found.
    """
    text = _read_text(path).lower()
    blockers = []
    if "<html" not in text:
        blockers.append(f"{path.name} is not a complete HTML document")
    if "<h1" not in text and "<h2" not in text:
        blockers.append(f"{path.name} has no headings")
    return blockers


def _svg_blockers(path: Path) -> list[str]:
    """Check that an SVG file parses as a drawing.

    Parameters
    ----------
    path : pathlib.Path
        SVG file.

    Returns
    -------
    list[str]
        Problems found.
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return [f"{path.name} is not valid SVG"]
    if not root.tag.endswith("svg"):
        return [f"{path.name} is not a drawing"]
    return []


def _message(blockers: list[str]) -> str:
    """Build a readable blocked-review message.

    Parameters
    ----------
    blockers : list[str]
        Concrete problems.

    Returns
    -------
    str
        Multi-line message.
    """
    lines = ["Review blocked delivery."]
    lines += [f"- {item}" for item in blockers]
    lines.append("Fix the problems and try again.")
    return "\n".join(lines)
