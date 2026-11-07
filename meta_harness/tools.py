"""Built-in tools for the Minimal Harness agent runtime."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from .web_search import WebSearchClient
from .browser import BrowserClient
from .deliverables import blueprint_file, render_deliverable
from .evaluator import AppEvaluator
from .provider import ProviderCatalog

TOOL_SCHEMAS = {
    "read": {"path": {"type": "string"}},
    "write": {"path": {"type": "string"}, "content": {"type": "string"}},
    "edit": {
        "path": {"type": "string"},
        "old": {"type": "string"},
        "new": {"type": "string"},
    },
    "bash": {"command": {"type": "string"}, "timeout": {"type": "integer"}},
    "web_search": {"query": {"type": "string"}, "limit": {"type": "integer"}},
    "browser_open": {"url": {"type": "string"}},
    "browser_screenshot": {
        "url": {"type": "string"},
        "path": {"type": "string"},
    },
    "browser_assert": {"url": {"type": "string"}, "text": {"type": "string"}},
    "evaluate_app": {"path": {"type": "string"}},
    "ask": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
    "suggest": {"options": {"type": "array", "items": {"type": "string"}}},
    "list_models": {"free_only": {"type": "boolean"}},
    "make_pdf": {
        "filename": {"type": "string"},
        "title": {"type": "string"},
        "text": {"type": "string"},
    },
    "make_deliverable": {
        "title": {"type": "string"},
        "sections": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "array", "items": {"type": "string"}},
        "style": {"type": "object"},
        "filename": {"type": "string"},
        "subtitle": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "object"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "make_blueprint": {
        "title": {"type": "string"},
        "width_ft": {"type": "number"},
        "depth_ft": {"type": "number"},
        "wall_height_ft": {"type": "number"},
        "pitch": {"type": "string"},
        "door": {"type": "object"},
        "vents": {"type": "array", "items": {"type": "object"}},
        "views": {"type": "array", "items": {"type": "string"}},
        "style": {"type": "object"},
        "filename": {"type": "string"},
    },
}

TOOL_DESCRIPTIONS = {
    "ask": (
        "Ask the user exactly one question. Provide 2 to 5 short options; "
        "the interface also lets the user type a custom answer. Never ask "
        "more than one question in a single call."
    ),
    "suggest": "Offer short optional next steps as clickable buttons.",
    "make_pdf": "Create a PDF in the output folder from a title and text.",
    "make_deliverable": (
        "Render a polished HTML report, plan, guide, or proposal. Sections "
        "are objects with heading plus optional body, bullets, table "
        "({columns, rows, caption}), figure ({kind: blueprint, blueprint: "
        "{...}, caption}), callout ({tone, text}), checklist, code, or "
        "raw_html. Style supports theme (sage|slate|warm|mono), density "
        "(comfortable|compact), font (sans|serif|mono), columns (1|2), "
        "page_size (letter|a4), accent (hex), and custom_css. Use this "
        "instead of hand-writing HTML."
    ),
    "make_blueprint": (
        "Draw a scaled blueprint with plan, front, and side views. Give "
        "width_ft, depth_ft, wall_height_ft, pitch (like 4:12), optional "
        "door ({wall, width_in, height_in}), vents, and views. Writes SVG "
        "to the output folder."
    ),
}


def _tool_schema(name: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI-compatible tool schema.

    Parameters
    ----------
    name : str
        Tool name.
    properties : dict[str, Any]
        Argument properties.

    Returns
    -------
    dict[str, Any]
        Tool schema.
    """
    description = TOOL_DESCRIPTIONS.get(name, f"Minimal Harness {name} tool")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties},
        },
    }


def _inside(target: Path, root: Path | None) -> bool:
    """Return whether a path sits inside a root.

    Parameters
    ----------
    target : pathlib.Path
        Resolved candidate path.
    root : pathlib.Path or None
        Allowed root.

    Returns
    -------
    bool
        ``True`` when the target equals or lives under the root.
    """
    if root is None:
        return False
    return target == root or root in target.parents


class ToolError(RuntimeError):
    """Represent a rejected or failed tool operation."""


class ToolRegistry:
    """Register and execute bounded agent tools."""

    def __init__(
        self,
        root: Path | str = ".",
        questioner: Callable[[str, list[str]], str] | None = None,
        outputs: Path | str | None = None,
    ) -> None:
        """Initialize tools rooted at one workspace.

        Parameters
        ----------
        root : pathlib.Path or str
            Workspace root for file operations.
        questioner : collections.abc.Callable or None
            Optional callback that presents a question with options and
            returns the user's chosen answer. When absent, the ``ask``
            tool is not advertised.
        outputs : pathlib.Path or str or None
            Optional second root for delivered files.

        Returns
        -------
        None
            This initializer configures the registry.
        """
        self.root = Path(root).resolve()
        self.questioner = questioner
        self.outputs = Path(outputs).resolve() if outputs else None
        self.suggestions: list[str] = []
        self.tools = self._tool_map()

    def _tool_map(self) -> dict[str, Callable[..., Any]]:
        """Build the registered tool map.

        Returns
        -------
        dict[str, Callable[..., Any]]
            Tool names and bound implementations.
        """
        return {name: getattr(self, name) for name in TOOL_SCHEMAS}

    def schema(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool schemas.

        Returns
        -------
        list[dict[str, Any]]
            Schemas advertised to the model.
        """
        return [
            self._schema(name)
            for name in self.tools
            if name not in ("ask", "suggest") or self.questioner is not None
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute one named tool.

        Parameters
        ----------
        name : str
            Registered tool name.
        arguments : dict[str, Any]
            Tool arguments.

        Returns
        -------
        str
            JSON result or error message.
        """
        if name not in self.tools:
            raise ToolError(f"Unknown tool: {name}")
        try:
            return json.dumps(self.tools[name](**arguments), default=str)
        except Exception as exc:
            raise ToolError(f"Tool {name} failed: {exc}") from exc

    def read(self, path: str) -> dict[str, str]:
        """Read a workspace file.

        Parameters
        ----------
        path : str
            Relative file path.

        Returns
        -------
        dict[str, str]
            Path and file content.
        """
        target = self._path(path)
        return {"path": path, "content": target.read_text()}

    def write(self, path: str, content: str) -> dict[str, Any]:
        """Write a workspace file.

        Parameters
        ----------
        path : str
            Relative file path.
        content : str
            New file content.

        Returns
        -------
        dict[str, Any]
            Written path and byte count.
        """
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return {"path": path, "bytes": len(content.encode())}

    def edit(self, path: str, old: str, new: str) -> dict[str, Any]:
        """Replace one exact text fragment in a workspace file.

        Parameters
        ----------
        path : str
            Relative file path.
        old : str
            Existing exact text.
        new : str
            Replacement text.

        Returns
        -------
        dict[str, Any]
            Edited path and replacement count.
        """
        target = self._path(path)
        content = target.read_text()
        if content.count(old) != 1:
            raise ToolError("edit requires exactly one matching fragment")
        target.write_text(content.replace(old, new))
        return {"path": path, "replacements": 1}

    def bash(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """Run a shell command in the workspace.

        Parameters
        ----------
        command : str
            Shell command.
        timeout : int
            Maximum execution seconds.

        Returns
        -------
        dict[str, Any]
            Exit code and bounded output.
        """
        if self._is_install(command):
            self._require_install_ok()
        result = self._run_command(command, timeout)
        return self._command_result(result)

    def _is_install(self, command: str) -> bool:
        """Detect package-install commands.

        Parameters
        ----------
        command : str
            Shell command to inspect.

        Returns
        -------
        bool
            Whether the command installs packages.
        """
        text = command.lower()
        return bool(
            re.search(
                r"\b(pip|pip3|npm|apt|apt-get|brew|cargo|go)\s+(install)\b",
                text,
            )
        )

    def _require_install_ok(self) -> None:
        """Ask the user to approve a package install.

        Returns
        -------
        None
            Execution continues only after approval.

        Raises
        ------
        ToolError
            When no questioner exists or approval is denied.
        """
        if self.questioner is None:
            raise ToolError("Installing software needs your approval first.")
        answer = self.questioner(
            "I need to download and install a tool for this. " "Is that okay?",
            ["Yes, install it", "No, don't install"],
        )
        if not answer.lower().startswith("yes"):
            raise ToolError(
                "Install declined. Do not install software without "
                "approval."
            )

    def _run_command(
        self, command: str, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in the workspace.

        Parameters
        ----------
        command : str
            Shell command.
        timeout : int
            Timeout seconds.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Process result.
        """
        return subprocess.run(
            command,
            cwd=self.root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _command_result(
        self, result: subprocess.CompletedProcess[str]
    ) -> dict[str, Any]:
        """Bound process output.

        Parameters
        ----------
        result : subprocess.CompletedProcess[str]
            Process result.

        Returns
        -------
        dict[str, Any]
            Exit code and output.
        """
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    def web_search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """Search the public web.

        Parameters
        ----------
        query : str
            Search query.
        limit : int
            Maximum result count.

        Returns
        -------
        list[dict[str, str]]
            Public search results.
        """
        return WebSearchClient().search(query, limit)

    def browser_open(self, url: str) -> dict[str, str]:
        """Open a page and return visible metadata.

        Parameters
        ----------
        url : str
            Page URL.

        Returns
        -------
        dict[str, str]
            Page URL, title, and visible text.
        """
        return BrowserClient().open(url)

    def browser_screenshot(self, url: str, path: str) -> dict[str, str]:
        """Capture a page screenshot.

        Parameters
        ----------
        url : str
            Page URL.
        path : str
            Screenshot path inside the workspace.

        Returns
        -------
        dict[str, str]
            Page URL and screenshot path.
        """
        target = self._path(path)
        return BrowserClient().screenshot(url, str(target))

    def browser_assert(self, url: str, text: str) -> dict[str, Any]:
        """Assert visible text on a page.

        Parameters
        ----------
        url : str
            Page URL.
        text : str
            Required visible text.

        Returns
        -------
        dict[str, Any]
            Assertion result.
        """
        return BrowserClient().assert_page(url, text)

    def evaluate_app(self, path: str = ".") -> dict[str, Any]:
        """Score a web application deterministically.

        Parameters
        ----------
        path : str
            Application directory inside the workspace.

        Returns
        -------
        dict[str, Any]
            Deterministic app evaluation.
        """
        return AppEvaluator().evaluate(self._path(path))

    def list_models(self, free_only: bool = False) -> list[dict[str, Any]]:
        """List OpenRouter models.

        Parameters
        ----------
        free_only : bool
            Return only zero-priced models.

        Returns
        -------
        list[dict[str, Any]]
            Provider model records.
        """
        catalog = ProviderCatalog()
        return catalog.free_models() if free_only else catalog.list_models()

    def make_pdf(self, filename: str, title: str, text: str) -> dict[str, str]:
        """Create a simple PDF in the output folder.

        Parameters
        ----------
        filename : str
            Destination filename, usually ending in ``.pdf``.
        title : str
            Heading shown at the top of the document.
        text : str
            Plain text body, one paragraph per line.

        Returns
        -------
        dict[str, str]
            Absolute path of the written PDF.
        """
        target = self._output_path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_pdf(target, title, text)
        return {"path": str(target)}

    def _output_path(self, filename: str) -> Path:
        """Resolve a destination under the output folder.

        Parameters
        ----------
        filename : str
            Requested filename.

        Returns
        -------
        pathlib.Path
            Confined destination path.
        """
        base = self.outputs or self.root
        target = (base / filename).resolve()
        if _inside(target, base):
            return target
        raise ToolError("path escapes output folder")

    def _write_pdf(self, target: Path, title: str, text: str) -> None:
        """Render plain text into a PDF file.

        Parameters
        ----------
        target : pathlib.Path
            Destination PDF path.
        title : str
            Document heading.
        text : str
            Plain text body.

        Returns
        -------
        None
            The PDF is written to disk.
        """
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
            )
        except ImportError as exc:
            raise ToolError("PDF support needs reportlab installed.") from exc
        styles = getSampleStyleSheet()
        story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 12)]
        for line in text.splitlines() or [""]:
            story.append(
                Paragraph(escape(line) or "&nbsp;", styles["BodyText"])
            )
        SimpleDocTemplate(str(target), pagesize=letter).build(story)

    def make_deliverable(
        self,
        title: str,
        sections: list[dict[str, Any]],
        summary: list[str] | str | None = None,
        style: dict[str, Any] | None = None,
        filename: str | None = None,
        subtitle: str = "",
        assumptions: list[str] | None = None,
        sources: list[dict[str, str]] | None = None,
        next_steps: list[str] | None = None,
    ) -> dict[str, str]:
        """Render a polished HTML deliverable.

        Parameters
        ----------
        title : str
            Document title.
        sections : list[dict[str, Any]]
            Ordered content sections.
        summary : list[str] or str or None
            At-a-glance points.
        style : dict[str, Any] or None
            Theme, density, font, columns, and other overrides.
        filename : str or None
            Optional output name.
        subtitle : str
            Optional subtitle.
        assumptions : list[str] or None
            Stated assumptions.
        sources : list[dict[str, str]] or None
            Source records with title and url.
        next_steps : list[str] or None
            Concrete follow-up actions.

        Returns
        -------
        dict[str, str]
            Absolute path of the written HTML file.
        """
        spec = {
            "title": title,
            "subtitle": subtitle,
            "sections": sections,
            "summary": summary,
            "style": style,
            "filename": filename,
            "assumptions": assumptions,
            "sources": sources,
            "next_steps": next_steps,
        }
        target = render_deliverable(spec, self.outputs or self.root)
        return {"path": str(target)}

    def make_blueprint(
        self,
        title: str = "Blueprint",
        width_ft: float = 10,
        depth_ft: float = 12,
        wall_height_ft: float = 6,
        pitch: str = "4:12",
        door: dict[str, Any] | None = None,
        vents: list[dict[str, Any]] | None = None,
        views: list[str] | None = None,
        style: dict[str, Any] | None = None,
        filename: str | None = None,
    ) -> dict[str, str]:
        """Draw a scaled blueprint as SVG.

        Parameters
        ----------
        title : str
            Drawing title.
        width_ft : float
            Gable width in feet.
        depth_ft : float
            Ridge length in feet.
        wall_height_ft : float
            Wall height in feet.
        pitch : str
            Roof pitch such as ``4:12``.
        door : dict[str, Any] or None
            Door wall, width, and height.
        vents : list[dict[str, Any]] or None
            Vent sizes.
        views : list[str] or None
            Subset of plan, front, side.
        style : dict[str, Any] or None
            Drawing style overrides.
        filename : str or None
            Optional output name.

        Returns
        -------
        dict[str, str]
            Absolute path of the written SVG.
        """
        spec = {
            "title": title,
            "width_ft": width_ft,
            "depth_ft": depth_ft,
            "wall_height_ft": wall_height_ft,
            "pitch": pitch,
            "door": door,
            "vents": vents,
            "views": views,
            "style": style,
            "filename": filename,
        }
        target = blueprint_file(spec, self.outputs or self.root)
        return {"path": str(target)}

    def ask(
        self, question: str, options: list[str] | None = None
    ) -> dict[str, str]:
        """Ask the interactive user a question.

        Parameters
        ----------
        question : str
            Question to present.
        options : list[str] or None
            Suggested answers. The interface always adds a custom option.

        Returns
        -------
        dict[str, str]
            The question and the chosen answer.
        """
        if self.questioner is None:
            raise ToolError("no interactive user is available to answer")
        answer = self.questioner(question, list(options or []))
        return {"question": question, "answer": answer}

    def suggest(self, options: list[str] | None = None) -> dict[str, bool]:
        """Record short optional next-step suggestions.

        Parameters
        ----------
        options : list[str] or None
            Short action-shaped labels. At most four are kept.

        Returns
        -------
        dict[str, bool]
            Acknowledgement that the suggestions were recorded.
        """
        kept = [str(item)[:40] for item in (options or []) if str(item)]
        self.suggestions = kept[:4]
        return {"ok": True}

    def _path(self, path: str) -> Path:
        """Resolve and confine a workspace path.

        Parameters
        ----------
        path : str
            Relative workspace path.

        Returns
        -------
        pathlib.Path
            Confined absolute path.
        """
        target = (self.root / path).resolve()
        if _inside(target, self.root) or _inside(target, self.outputs):
            return target
        raise ToolError("path escapes workspace")

    def _schema(self, name: str) -> dict[str, Any]:
        """Build one tool schema.

        Parameters
        ----------
        name : str
            Tool name.

        Returns
        -------
        dict[str, Any]
            OpenAI-compatible function schema.
        """
        return _tool_schema(name, TOOL_SCHEMAS[name])
