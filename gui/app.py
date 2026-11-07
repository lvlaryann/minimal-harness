"""PySide6 desktop shell with command and ideas panels."""

import sys
import json
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QFrame,
    QFileDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meta_harness.agent import Agent
from meta_harness.session import Session

from .store import SessionRecord, SessionStore
from .context import snapshot
from .outputs import human_size, list_files, session_outputs
from .worker import AgentWorker, QuestionBridge


class Bridge(QObject):
    """Forward agent worker signals to a chat panel."""

    def __init__(self, worker: AgentWorker, panel: "ChatPanel") -> None:
        """Connect worker signals to panel slots.

        Parameters
        ----------
        worker : AgentWorker
            Background agent executor.
        panel : ChatPanel
            Panel receiving the output.

        Returns
        -------
        None
            Signals are wired.
        """
        super().__init__()
        worker.started.connect(panel.on_started)
        worker.tool.connect(panel.on_tool)
        worker.answered.connect(panel.on_answered)
        worker.error.connect(panel.on_error)
        worker.asked.connect(panel.on_asked)


class PromptInput(QPlainTextEdit):
    """Multi-line prompt editor that grows to fit its content."""

    submitted = Signal(str)
    max_height = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        """Prepare a growing prompt editor.

        Parameters
        ----------
        parent : QWidget or None
            Optional parent widget.

        Returns
        -------
        None
            The editor starts at single-line height.
        """
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.document().contentsChanged.connect(self._resize_to_content)
        self.setFixedHeight(self._measure_height())

    def sizeHint(self) -> QSize:  # noqa: N802
        """Report the content-sized height.

        Returns
        -------
        QSize
            Preferred widget size.
        """
        size = super().sizeHint()
        size.setHeight(self._measure_height())
        return size

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Submit on Enter and insert a newline on Shift-Enter.

        Parameters
        ----------
        event : QKeyEvent
            Incoming key event.

        Returns
        -------
        None
            Matching keys submit or insert a line break.
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit(self.toPlainText())
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)

    def _resize_to_content(self) -> None:
        """Fit the editor height to its wrapped lines.

        Returns
        -------
        None
            Height matches content up to the cap.
        """
        height = self._measure_height()
        if height != self.height():
            self.setFixedHeight(height)

    def _measure_height(self) -> int:
        """Compute the height for the current wrapped text.

        Returns
        -------
        int
            Capped pixel height.
        """
        width = self.viewport().width()
        metrics = self.fontMetrics()
        lines = 1
        for text_line in self.toPlainText().splitlines():
            lines += max(1, metrics.horizontalAdvance(text_line) // width)
        height = lines * metrics.lineSpacing() + self.frameWidth() * 2
        return min(self.max_height, height)


class AskDialog(QDialog):
    """Ask one agent question with option buttons and a custom answer box."""

    def __init__(
        self,
        question: str,
        options: list[str],
        parent: QWidget | None = None,
    ) -> None:
        """Build the single-question dialog.

        Parameters
        ----------
        question : str
            Question text for the user.
        options : list[str]
            Suggested answers shown as buttons.
        parent : QWidget or None
            Optional parent widget.

        Returns
        -------
        None
            The dialog is ready to show.
        """
        super().__init__(parent)
        self._answer = "no answer"
        self._custom = QLineEdit(self)
        self._custom.setPlaceholderText("Type your own answer")
        self.setWindowTitle("Minimal Harness")
        self.setLayout(self._compose(question, options))

    def _compose(self, question: str, options: list[str]) -> QVBoxLayout:
        """Lay out the question, option buttons, and custom answer.

        Parameters
        ----------
        question : str
            Question text for the user.
        options : list[str]
            Suggested answers shown as buttons.

        Returns
        -------
        QVBoxLayout
            Arranged dialog body.
        """
        layout = QVBoxLayout()
        layout.addWidget(self._question_label(question))
        for option in options:
            layout.addWidget(self._option_button(option))
        self._custom.returnPressed.connect(self._send_custom)
        layout.addWidget(self._custom)
        layout.addLayout(self._buttons())
        return layout

    def _question_label(self, text: str) -> QLabel:
        """Wrap one question into a label.

        Parameters
        ----------
        text : str
            Question text.

        Returns
        -------
        QLabel
            Word-wrapped label.
        """
        label = QLabel(text, self)
        label.setWordWrap(True)
        return label

    def _option_button(self, option: str) -> QPushButton:
        """Build a button that answers with one option.

        Parameters
        ----------
        option : str
            Suggested answer.

        Returns
        -------
        QPushButton
            Button bound to this option.
        """
        button = QPushButton(option, self)
        button.clicked.connect(
            lambda _=False, value=option: self._choose(value)
        )
        return button

    def _buttons(self) -> QHBoxLayout:
        """Build the send and cancel row.

        Returns
        -------
        QHBoxLayout
            Dialog action row.
        """
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._action("Send", self._send_custom))
        row.addWidget(self._action("Cancel", self.reject))
        return row

    def _action(self, label: str, slot) -> QPushButton:
        """Build one action button.

        Parameters
        ----------
        label : str
            Button text.
        slot : callable
            Handler invoked on click.

        Returns
        -------
        QPushButton
            Connected button.
        """
        button = QPushButton(label, self)
        button.clicked.connect(slot)
        return button

    def _choose(self, answer: str) -> None:
        """Accept one option as the answer.

        Parameters
        ----------
        answer : str
            Selected option.

        Returns
        -------
        None
            The dialog closes with the answer.
        """
        self._answer = answer
        self.accept()

    def _send_custom(self) -> None:
        """Accept the typed answer.

        Returns
        -------
        None
            The dialog closes with the typed text.
        """
        text = self._custom.text().strip()
        self._answer = text or "no answer"
        self.accept()

    def answer(self) -> str:
        """Return the selected answer.

        Returns
        -------
        str
            Chosen option or typed text.
        """
        return self._answer


def _file_detail(path: Path) -> str:
    """Describe one file by type and size.

    Parameters
    ----------
    path : pathlib.Path
        File to describe.

    Returns
    -------
    str
        Short type and size label.
    """
    try:
        size = human_size(path.stat().st_size)
    except OSError:
        size = "missing"
    kind = path.suffix.upper().lstrip(".") or "FILE"
    return f"{kind} · {size}"


class FileCard(QFrame):
    """Show one delivered file with open, reveal, and save actions."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        """Build the card for one file.

        Parameters
        ----------
        path : pathlib.Path
            Delivered file.
        parent : QWidget or None
            Optional parent widget.

        Returns
        -------
        None
            The card is ready to show.
        """
        super().__init__(parent)
        self._path = path
        self.setObjectName("FileCard")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.addWidget(self._label())
        row.addStretch(1)
        row.addWidget(self._action("Open", self._open))
        row.addWidget(self._action("Show in folder", self._reveal))
        row.addWidget(self._action("Save a copy", self._save))

    def _label(self) -> QWidget:
        """Build the filename and detail block.

        Returns
        -------
        QWidget
            Name and size labels.
        """
        box = QWidget(self)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        name = QLabel(self._path.name, box)
        name.setToolTip(str(self._path))
        column.addWidget(name)
        column.addWidget(QLabel(_file_detail(self._path), box))
        return box

    def _action(self, label: str, slot) -> QPushButton:
        """Build one action button.

        Parameters
        ----------
        label : str
            Button text.
        slot : callable
            Handler invoked on click.

        Returns
        -------
        QPushButton
            Connected button.
        """
        button = QPushButton(label, self)
        button.clicked.connect(slot)
        return button

    def _open(self) -> None:
        """Open the file in the default application.

        Returns
        -------
        None
            The desktop opens the file.
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path)))

    def _reveal(self) -> None:
        """Open the file's folder in the file manager.

        Returns
        -------
        None
            The desktop opens the containing folder.
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path.parent)))

    def _save(self) -> None:
        """Copy the file to a location the user chooses.

        Returns
        -------
        None
            The copy is written or an error dialog is shown.
        """
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save a copy",
            str(Path.home() / "Downloads" / self._path.name),
        )
        if not target:
            return
        try:
            shutil.copy2(self._path, target)
        except OSError as exc:
            QMessageBox.critical(self, "Minimal Harness", str(exc))


class FileStrip(QWidget):
    """List the files delivered by the latest run."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty file strip.

        Parameters
        ----------
        parent : QWidget or None
            Optional parent widget.

        Returns
        -------
        None
            The strip starts hidden.
        """
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._heading = QLabel("<b>Files from this run</b>", self)
        self._layout.addWidget(self._heading)
        self._cards = QVBoxLayout()
        self._layout.addLayout(self._cards)
        self.hide()

    def clear(self) -> None:
        """Remove all cards and hide the strip.

        Returns
        -------
        None
            The strip is empty.
        """
        self._clear_cards()
        self.hide()

    def set_files(self, paths: list[Path]) -> None:
        """Show a card for each delivered file.

        Parameters
        ----------
        paths : list[pathlib.Path]
            Files to show.

        Returns
        -------
        None
            Cards are rebuilt in order.
        """
        self._clear_cards()
        for path in paths:
            self._cards.addWidget(FileCard(path, self))
        self.setVisible(bool(paths))

    def _clear_cards(self) -> None:
        """Delete the cards currently shown.

        Returns
        -------
        None
            The card layout is empty.
        """
        while self._cards.count():
            item = self._cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class ChatPanel(QWidget):
    """One agent chat panel with header, log, and input."""

    posted = Signal()
    files_changed = Signal()

    def __init__(
        self,
        agent: Agent,
        title: str = "Minimal Harness",
        context=None,
        show_notes_toggle: bool = False,
        show_tools: bool = False,
    ) -> None:
        """Build the panel and start its background worker.

        Parameters
        ----------
        agent : Agent
            Backend agent for this panel.
        title : str
            Panel header title.
        context : callable or None
            Optional live-workspace snapshot builder.
        show_notes_toggle : bool
            Whether to show the notes context checkbox.
        show_tools : bool
            Whether to render tool activity in the log.

        Returns
        -------
        None
            The panel is ready to show.
        """
        super().__init__()
        self._agent = agent
        self._context = context
        self._show_tools = show_tools
        self._notes_included = False
        self._last_label: str | None = None
        self._outputs: Path | None = None
        self._known: dict[Path, int] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._animate)
        self._worker = AgentWorker(agent)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        Bridge(self._worker, self)
        self._build_ui(title, show_notes_toggle)
        self._thread.start()

    def _build_ui(self, title: str, show_notes_toggle: bool) -> None:
        """Compose the panel layout.

        Parameters
        ----------
        title : str
            Panel header title.
        show_notes_toggle : bool
            Whether to show the notes context checkbox.

        Returns
        -------
        None
            Widgets are arranged in place.
        """
        self._layout = QVBoxLayout(self)
        self._layout.addLayout(self._build_header(title))
        self._status = QLabel("", self)
        self._status.setObjectName("statusLabel")
        self._tick = 0
        self._layout.addWidget(self._status)
        self._log = QTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QTextEdit.WidgetWidth)
        self._log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._files = FileStrip(self)
        self._notes: QCheckBox | None = None
        if show_notes_toggle:
            self._notes = QCheckBox("Include saved notes", self)
            self._notes.setChecked(self._notes_included)
            self._notes.stateChanged.connect(self._on_notes)
        self._input = PromptInput(self)
        self._send = QPushButton("Ask", self)
        row = QHBoxLayout()
        row.addWidget(self._input)
        row.addWidget(self._send)
        self._layout.addWidget(self._log)
        self._layout.addWidget(self._files)
        if self._notes is not None:
            self._layout.addWidget(self._notes)
        self._layout.addLayout(row)
        self._send.clicked.connect(self._submit)
        self._input.submitted.connect(self._submit)
        self._pending: QuestionBridge | None = None

    def set_explanations(self, enabled: bool) -> None:
        """Set or clear tooltips on the panel's own widgets.

        Parameters
        ----------
        enabled : bool
            Whether tooltips should be visible.

        Returns
        -------
        None
            Input, send, and notes tooltips reflect the toggle.
        """
        tips = {
            self._input: "Type your prompt. Enter sends; Shift-Enter is a "
            "new line.",
            self._send: "Send the typed prompt to the agent.",
            self._log: "Conversation and tool activity appear here.",
        }
        if self._notes is not None:
            tips[self._notes] = "Include this session's saved notes."
        for widget, text in tips.items():
            widget.setToolTip(text if enabled else "")

    def _on_notes(self, state: int) -> None:
        """Toggle whether notes join the context.

        Parameters
        ----------
        state : int
            Checkbox check state.

        Returns
        -------
        None
            The note flag is updated.
        """
        self._notes_included = state == Qt.CheckState.Checked.value

    def _build_header(self, title: str) -> QHBoxLayout:
        """Compose the top information bar.

        Parameters
        ----------
        title : str
            Header name.

        Returns
        -------
        QHBoxLayout
            Header layout with name and model labels.
        """
        header = QHBoxLayout()
        header.addWidget(self._header_label("<b>" + title + "</b>"))
        header.addStretch(1)
        header.addWidget(
            self._header_label("Model: " + self._agent.client.model)
        )
        return header

    def _header_label(self, text: str) -> QLabel:
        """Build one header label.

        Parameters
        ----------
        text : str
            Text to display.

        Returns
        -------
        QLabel
            Styled header label.
        """
        label = QLabel(text, self)
        return label

    def _submit(self, prompt: str = "") -> None:
        """Dispatch the typed prompt to the worker thread.

        Returns
        -------
        None
            The prompt is queued for the worker.
        """
        prompt = prompt or self._input.toPlainText()
        prompt = prompt.strip()
        if not prompt:
            return
        self._append_log("you", prompt)
        self._input.clear()
        if self._context is not None:
            prompt = self._context() + "\n\n" + prompt
        self._known = self._snapshot()
        self._files.clear()
        self._worker.prompt_ready.emit(prompt)
        self.posted.emit()

    def switch_session(self, session: Session, outputs=None) -> None:
        """Point the panel agent at a new session.

        Parameters
        ----------
        session : Session
            Session to make active.
        outputs : pathlib.Path or str or None
            Output folder for delivered files.

        Returns
        -------
        None
            The session is bound and the log reloaded.
        """
        self._agent.set_outputs(outputs)
        self._outputs = self._agent.outputs
        self._known = self._snapshot()
        self._files.clear()
        self._agent.session = session
        self._agent.messages = self._agent._initial_messages(session)
        self._log.clear()
        self._last_label = None
        for message in session.messages:
            self._render_message(message)

    def _render_message(self, message: dict) -> None:
        """Render one stored session message as a bubble.

        Parameters
        ----------
        message : dict
            Persisted message dictionary.

        Returns
        -------
        None
            The message is appended to the log.
        """
        role = message.get("role")
        content = message.get("content")
        if message.get("hidden"):
            return
        if role in ("user", "assistant") and isinstance(content, str):
            self._append_log("you" if role == "user" else "agent", content)
        elif role == "tool" and self._show_tools and isinstance(content, str):
            self._append_log("tool", content)

    def _append_log(self, label: str, text: str) -> None:
        """Append a chat bubble and scroll to the newest.

        Parameters
        ----------
        label : str
            Speaker label ("you" or "agent").
        text : str
            Markdown message content to display.

        Returns
        -------
        None
            The bubble is shown and the view follows it.
        """
        user = label == "you"
        tool = label == "tool"
        gap = self._last_label is not None and self._last_label != label
        self._last_label = label
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self._log.document().isEmpty():
            cursor.insertBlock()
        start = cursor.position()
        doc = QTextDocument()
        doc.setMarkdown(text)
        cursor.insertFragment(QTextDocumentFragment(doc))
        end = cursor.position()
        self._apply_bubble(start, end, user, tool, gap)
        self._log.setTextCursor(cursor)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _apply_bubble(
        self,
        start: int,
        end: int,
        user: bool,
        tool: bool = False,
        gap: bool = True,
    ) -> None:
        """Style inserted blocks as an aligned bubble.

        Parameters
        ----------
        start : int
            First inserted block position.
        end : int
            Position after the last inserted block.
        user : bool
            Whether the bubble is the user's.
        tool : bool
            Whether the bubble is a tool step.
        gap : bool
            Whether an extra top margin separates this bubble.

        Returns
        -------
        None
            Block formats are applied in place.
        """
        fmt = QTextBlockFormat()
        if tool:
            fmt.setAlignment(Qt.AlignLeft)
            fmt.setLeftMargin(self._bubble_margin())
        else:
            fmt.setAlignment(Qt.AlignRight if user else Qt.AlignLeft)
            if user:
                fmt.setRightMargin(self._bubble_margin())
            else:
                fmt.setLeftMargin(self._bubble_margin())
        ch = QTextCharFormat()
        ch.setBackground(
            QColor("#EFEFEF" if tool else ("#D2DBD6" if user else "#D6E0E6"))
        )
        block = self._log.document().findBlock(start)
        first = QTextBlockFormat(fmt)
        first.setTopMargin(6 if gap else 0)
        count = 0
        while block.isValid() and block.position() < end:
            cursor = QTextCursor(block)
            cursor.setBlockFormat(first if count == 0 else fmt)
            sel = QTextCursor(block)
            sel.setPosition(block.position())
            sel.setPosition(
                block.position() + block.length() - 1, QTextCursor.KeepAnchor
            )
            sel.mergeCharFormat(ch)
            block = block.next()
            count += 1

    def _bubble_margin(self) -> int:
        """Return the text inset from the viewport edge.

        Returns
        -------
        int
            Fixed inset in pixels.
        """
        return 14

    def on_started(self) -> None:
        """Begin the moving thinking indicator.

        Returns
        -------
        None
            The status animates while the worker runs.
        """
        self._tick = 0
        self._status.setText("thinking")
        self._timer.start()

    def _animate(self) -> None:
        """Advance the thinking indicator dots.

        Returns
        -------
        None
            The status label cycles through dot counts.
        """
        self._tick = (self._tick + 1) % 4
        self._status.setText("thinking" + "." * self._tick)

    def _stop_thinking(self) -> None:
        """Clear the thinking indicator.

        Returns
        -------
        None
            The status label empties.
        """
        self._timer.stop()
        self._status.setText("")

    def on_answered(self, answer: str) -> None:
        """Show the agent's final reply.

        Parameters
        ----------
        answer : str
            Final assistant text.

        Returns
        -------
        None
            The reply is appended to the log.
        """
        self._stop_thinking()
        self._append_log("agent", answer)
        self._mark_reviewed()
        changed = self._changed_files()
        if changed:
            self._files.set_files(changed)
        self.files_changed.emit()

    def _mark_reviewed(self) -> None:
        """Show that the reply passed review.

        Returns
        -------
        None
            The status label reflects the verdict.
        """
        review = getattr(self._agent, "last_review", None)
        if review and review.get("passed"):
            self._status.setText("reviewed")

    def _snapshot(self) -> dict[Path, int]:
        """Return output file timestamps for change detection.

        Returns
        -------
        dict[pathlib.Path, int]
            Files mapped to their modification time.
        """
        return {
            path: path.stat().st_mtime_ns for path in list_files(self._outputs)
        }

    def _changed_files(self) -> list[Path]:
        """Return files created or changed since the last snapshot.

        Returns
        -------
        list[pathlib.Path]
            Newest changed files first.
        """
        current = self._snapshot()
        changed = [
            path
            for path, stamp in current.items()
            if self._known.get(path) != stamp
        ]
        self._known = current
        return changed

    def on_tool(self, name: str, arguments: dict, content: str) -> None:
        """Show tool activity when enabled.

        Parameters
        ----------
        name : str
            Tool name.
        arguments : dict
            Tool arguments.
        content : str
            Tool result content.

        Returns
        -------
        None
            Activity renders only when the toggle is on.
        """
        if not self._show_tools:
            return
        self._append_tool(name, arguments, content)

    def _append_tool(self, name: str, arguments: dict, content: str) -> None:
        """Render one tool step as a compact log line.

        Parameters
        ----------
        name : str
            Tool name.
        arguments : dict
            Tool arguments.
        content : str
            Tool result content.

        Returns
        -------
        None
            The tool step is appended to the log.
        """
        label = f"tool> {name} {json.dumps(arguments)[:120]}"
        label += "\n" + str(content)[:300]
        self._append_log("tool", label)

    def on_error(self, message: str) -> None:
        """Show a backend failure dialog.

        Parameters
        ----------
        message : str
            Human-readable error text.

        Returns
        -------
        None
            An error dialog is displayed.
        """
        self._stop_thinking()
        QMessageBox.critical(self, "Minimal Harness", message)

    def on_asked(
        self, question: str, options: list[str], bridge: QuestionBridge
    ) -> None:
        """Present an agent question and resolve it.

        Parameters
        ----------
        question : str
            Question text for the user.
        options : list[str]
            Suggested answers.
        bridge : QuestionBridge
            Pending prompt awaiting the answer.

        Returns
        -------
        None
            The bridge resolves with the user's choice.
        """
        self._pending = bridge
        dialog = AskDialog(question, options, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._worker.resolve(bridge, "no answer")
            return
        self._worker.resolve(bridge, dialog.answer())

    def stop(self) -> None:
        """Stop the panel worker thread.

        Returns
        -------
        None
            The thread stops.
        """
        self._thread.quit()
        self._thread.wait(2000)


class MainWindow(QMainWindow):
    """Window hosting a session sidebar and two chat panels."""

    def __init__(self, store: SessionStore, root: Path, settings=None) -> None:
        """Build the split window with a session sidebar.

        Parameters
        ----------
        store : SessionStore
            Session backend for listing and switching.
        root : pathlib.Path
            Workspace root used by both agents.
        settings : Settings or None
            Optional persisted interface settings.

        Returns
        -------
        None
            The window is ready to show.
        """
        super().__init__()
        from .settings import Settings

        self._settings = settings or Settings()
        self._store = store
        self._root = root
        self._record: SessionRecord | None = None
        self._outputs: Path | None = None
        self._command_panel = ChatPanel(
            self._make_agent(), show_tools=self._settings.get("show_tools")
        )
        self._command_panel.posted.connect(self._on_posted)
        self._command_panel.files_changed.connect(self._refresh_files)
        ideas_context = self._make_ideas_context
        self._ideas_panel = ChatPanel(
            self._make_agent(),
            title="Ideas",
            context=ideas_context,
            show_notes_toggle=True,
            show_tools=self._settings.get("show_tools"),
        )
        self._ideas_panel.posted.connect(self._on_posted)
        self._ideas_panel.files_changed.connect(self._refresh_files)
        self._ideas_card = self._card(self._ideas_panel)
        self._ideas_card.hide()
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._build_header())
        layout.addLayout(self._build_toggle_bar())
        body = QSplitter(Qt.Horizontal, central)
        body.setHandleWidth(6)
        body.addWidget(self._build_sidebar())
        main = QSplitter(Qt.Horizontal, central)
        main.setHandleWidth(6)
        main.addWidget(self._card(self._command_panel))
        main.addWidget(self._ideas_card)
        body.addWidget(main)
        layout.addWidget(body)
        self.setCentralWidget(central)
        self.setWindowTitle("Minimal Harness")
        self.resize(1440, 640)
        self._refresh_sidebar()
        self._activate(self._store.list()[0])
        self._on_show_explanations(self._settings.get("show_explanations"))

    def _make_agent(self) -> Agent:
        """Build an agent for one panel.

        Returns
        -------
        Agent
            Agent bound to the working session.
        """
        return Agent(
            root=self._root,
            session=Session(self._active_path()),
        )

    def _active_path(self) -> Path:
        """Return the active session transcript path.

        Returns
        -------
        pathlib.Path
            Transcript path for the current session.
        """
        if self._record is None:
            return Path("runs/gui-session.jsonl")
        return self._record.transcript

    def _make_ideas_context(self) -> str:
        """Build the ideas panel live context.

        Returns
        -------
        str
            Workspace snapshot, command tail, and notes.
        """
        first = snapshot(self._root)
        tail = self._command_tail()
        notes = self._notes_text() if self._ideas_panel._notes_included else ""
        return "\n\n".join(part for part in [first, tail, notes] if part)

    def _command_tail(self) -> str:
        """Summarize the recent command conversation.

        Returns
        -------
        str
            Recent user and assistant messages.
        """
        if self._record is None or not self._record.transcript.exists():
            return ""
        return "Recent commands conversation:\n" + self._read_session(
            self._record.transcript
        )

    def _notes_text(self) -> str:
        """Return the current session notes.

        Returns
        -------
        str
            Saved notes for the session.
        """
        if self._record is None or not self._record.notes.exists():
            return ""
        return "Saved notes:\n" + self._read_session(self._record.notes)

    def _read_session(self, path: Path) -> str:
        """Format a session transcript as readable text.

        Parameters
        ----------
        path : pathlib.Path
            JSONL session file.

        Returns
        -------
        str
            Joined speaker lines.
        """
        import json

        lines = []
        for line in path.read_text().splitlines()[-8:]:
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = body.get("role")
            content = body.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                lines.append(role + ": " + content)
        return "\n".join(lines)

    def _build_sidebar(self) -> QWidget:
        """Build the sessions and builds sidebar.

        Returns
        -------
        QWidget
            Sidebar with two sections and new buttons.
        """
        sidebar = QWidget(self)
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        box = QVBoxLayout(sidebar)
        self._sessions_heading = QLabel("<b>Sessions</b>", sidebar)
        box.addWidget(self._sessions_heading)
        self._session_list = QListWidget(sidebar)
        self._session_list.itemClicked.connect(self._select)
        self._session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._session_list.customContextMenuRequested.connect(
            self._menu_session
        )
        box.addWidget(self._session_list)
        self._new_session_button = QPushButton("+ New Session", sidebar)
        self._new_session_button.clicked.connect(self._new_session)
        box.addWidget(self._new_session_button)
        box.addSpacing(12)
        self._builds_heading = QLabel("<b>Builds</b>", sidebar)
        box.addWidget(self._builds_heading)
        self._build_list = QListWidget(sidebar)
        self._build_list.itemClicked.connect(self._select)
        self._build_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._build_list.customContextMenuRequested.connect(self._menu_build)
        box.addWidget(self._build_list)
        self._new_build_button = QPushButton("+ New Build", sidebar)
        self._new_build_button.clicked.connect(self._new_build)
        box.addWidget(self._new_build_button)
        box.addSpacing(12)
        self._files_heading = QLabel("<b>Files</b>", sidebar)
        box.addWidget(self._files_heading)
        self._files_list = QListWidget(sidebar)
        self._files_list.itemDoubleClicked.connect(self._file_open)
        self._files_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._files_list.customContextMenuRequested.connect(self._file_menu)
        box.addWidget(self._files_list)
        return sidebar

    def _refresh_sidebar(self) -> None:
        """Repopulate the session and build lists.

        Returns
        -------
        None
            Both lists reflect the store.
        """
        self._session_list.clear()
        for record in self._store.list(kind="session"):
            self._session_list.addItem(self._item(record))
        self._build_list.clear()
        for record in self._store.list(kind="build"):
            self._build_list.addItem(self._item(record))

    def _refresh_files(self) -> None:
        """Repopulate the delivered-files list.

        Returns
        -------
        None
            The list reflects the active output folder.
        """
        self._files_list.clear()
        for path in list_files(self._outputs):
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self._files_list.addItem(item)

    def _file_open(self, item: QListWidgetItem) -> None:
        """Open the selected delivered file.

        Parameters
        ----------
        item : QListWidgetItem
            Row carrying the file path.

        Returns
        -------
        None
            The default application opens the file.
        """
        path = Path(item.data(Qt.UserRole))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _file_menu(self, pos) -> None:
        """Open the context menu for a delivered file.

        Parameters
        ----------
        pos : QPoint
            Menu request position.

        Returns
        -------
        None
            The menu is shown for the row.
        """
        item = self._files_list.itemAt(pos)
        if item is None:
            return
        path = Path(item.data(Qt.UserRole))
        self._show_file_menu(path, self._files_list.mapToGlobal(pos))

    def _show_file_menu(self, path: Path, point) -> None:
        """Show open, reveal, and save actions for one file.

        Parameters
        ----------
        path : pathlib.Path
            Delivered file.
        point : QPoint
            Global menu position.

        Returns
        -------
        None
            The chosen action runs.
        """
        menu = QMenu(self)
        actions = {
            menu.addAction("Open"): "open",
            menu.addAction("Show in folder"): "reveal",
            menu.addAction("Save a copy"): "save",
        }
        chosen = menu.exec(point)
        self._run_file_action(actions.get(chosen), path)

    def _run_file_action(self, action: str | None, path: Path) -> None:
        """Run one delivered-file action.

        Parameters
        ----------
        action : str or None
            Action name or None when the menu was dismissed.
        path : pathlib.Path
            Delivered file.

        Returns
        -------
        None
            The action runs.
        """
        if action == "open":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif action == "reveal":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        elif action == "save":
            self._save_copy(path)

    def _save_copy(self, path: Path) -> None:
        """Copy a delivered file to a chosen location.

        Parameters
        ----------
        path : pathlib.Path
            Delivered file.

        Returns
        -------
        None
            The copy is written or an error dialog is shown.
        """
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save a copy",
            str(Path.home() / "Downloads" / path.name),
        )
        if not target:
            return
        try:
            shutil.copy2(path, target)
        except OSError as exc:
            QMessageBox.critical(self, "Minimal Harness", str(exc))

    def _menu_session(self, pos) -> None:
        """Open the context menu for a session row.

        Parameters
        ----------
        pos : QPoint
            Menu request position.

        Returns
        -------
        None
            The menu is shown for the row.
        """
        self._item_menu(self._session_list, pos)

    def _menu_build(self, pos) -> None:
        """Open the context menu for a build row.

        Parameters
        ----------
        pos : QPoint
            Menu request position.

        Returns
        -------
        None
            The menu is shown for the row.
        """
        self._item_menu(self._build_list, pos)

    def _item_menu(self, listing: QListWidget, pos) -> None:
        """Show rename and delete actions for an item.

        Parameters
        ----------
        listing : QListWidget
            List containing the row.
        pos : QPoint
            Menu request position.

        Returns
        -------
        None
            Actions run when chosen.
        """
        item = listing.itemAt(pos)
        if item is None:
            return
        record = self._store.load(item.data(Qt.UserRole))
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        chosen = menu.exec(listing.mapToGlobal(pos))
        if chosen is delete:
            self._delete(record)
        elif chosen is rename:
            self._rename(record)

    def _rename(self, record: SessionRecord) -> None:
        """Prompt for and apply a new session title.

        Parameters
        ----------
        record : SessionRecord
            Session to rename.

        Returns
        -------
        None
            The title is updated and lists refresh.
        """
        title, ok = QInputDialog.getText(
            self, "Rename", "Title:", text=record.title
        )
        if not ok or not title.strip():
            return
        self._store.rename(record, title.strip())
        self._refresh_sidebar()
        if self._record.session_id == record.session_id:
            self._mark_active(record)

    def _delete(self, record: SessionRecord) -> None:
        """Delete a session folder after confirming.

        Parameters
        ----------
        record : SessionRecord
            Session to delete.

        Returns
        -------
        None
            The folder is removed and lists refresh.
        """
        answer = QMessageBox.question(
            self,
            "Delete",
            "Delete '%s' permanently?" % record.title,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._remove(record)

    def _remove(self, record: SessionRecord) -> None:
        """Remove a session folder and refresh lists.

        Parameters
        ----------
        record : SessionRecord
            Session to delete.

        Returns
        -------
        None
            The folder is removed and lists refresh.
        """
        import shutil

        shutil.rmtree(record.folder, ignore_errors=True)
        self._refresh_sidebar()

    def _item(self, record: SessionRecord) -> QListWidgetItem:
        """Build a list row for a session.

        Parameters
        ----------
        record : SessionRecord
            Session to display.

        Returns
        -------
        QListWidgetItem
            Row carrying the session id.
        """
        item = QListWidgetItem(record.title)
        item.setData(Qt.UserRole, record.session_id)
        return item

    def _new_session(self) -> None:
        """Create and activate a new session.

        Returns
        -------
        None
            A new session becomes active.
        """
        self._activate(self._store.create())

    def _new_build(self) -> None:
        """Create and activate a new build.

        Returns
        -------
        None
            A new build becomes active.
        """
        self._activate(self._store.create(kind="build"))

    def _select(self, item: QListWidgetItem) -> None:
        """Activate the clicked session.

        Parameters
        ----------
        item : QListWidgetItem
            Clicked session row.

        Returns
        -------
        None
            The session becomes active.
        """
        session_id = item.data(Qt.UserRole)
        self._activate(self._store.load(session_id))

    def _activate(self, record: SessionRecord) -> None:
        """Switch both panels to a session.

        Parameters
        ----------
        record : SessionRecord
            Session to make active.

        Returns
        -------
        None
            Both panels load the session.
        """
        self._record = record
        self._touch_active()
        transcripts = Session(record.transcript)
        notes = Session(record.notes)
        self._outputs = session_outputs(record.session_id)
        self._command_panel.switch_session(transcripts, self._outputs)
        self._ideas_panel.switch_session(notes, self._outputs)
        self._mark_active(record)
        self._refresh_files()

    def _mark_active(self, record: SessionRecord) -> None:
        """Highlight the active row in its list.

        Parameters
        ----------
        record : SessionRecord
            Session now active.

        Returns
        -------
        None
            The matching row is selected.
        """
        target = (
            self._session_list
            if record.kind == "session"
            else self._build_list
        )
        for index in range(target.count()):
            item = target.item(index)
            if item.data(Qt.UserRole) == record.session_id:
                target.setCurrentItem(item)
                return

    def _touch_active(self) -> None:
        """Bump the active session timestamp.

        Returns
        -------
        None
            The session is marked recent.
        """
        if self._record is None:
            return
        self._store.touch(self._record)
        self._refresh_sidebar()

    def _on_posted(self) -> None:
        """Refresh the sidebar after a message posts.

        Returns
        -------
        None
            The session list reflects the update.
        """
        self._touch_active()

    def _build_toggle_bar(self) -> QHBoxLayout:
        """Build the settings and ideas toggle row.

        Returns
        -------
        QHBoxLayout
            Bar with checkboxes and the ideas button.
        """
        bar = QHBoxLayout()
        bar.addStretch(1)
        self._show_commands = QCheckBox("Show commands", self)
        self._show_commands.setChecked(self._settings.get("show_commands"))
        self._show_commands.toggled.connect(self._on_show_commands)
        bar.addWidget(self._show_commands)
        self._show_tools = QCheckBox("Show tool activity", self)
        self._show_tools.setChecked(self._settings.get("show_tools"))
        self._show_tools.toggled.connect(self._on_show_tools)
        bar.addWidget(self._show_tools)
        self._toggle = QPushButton("Open Ideas", self)
        self._toggle.clicked.connect(self.toggle_ideas)
        bar.addWidget(self._toggle)
        self._help = QPushButton("?", self)
        self._help.setCheckable(True)
        self._help.setToolTip("Show or hide hover explanations.")
        self._help.setFixedSize(32, 28)
        self._help.setChecked(self._settings.get("show_explanations"))
        self._help.toggled.connect(self._on_show_explanations)
        bar.addWidget(self._help)
        return bar

    def _on_show_commands(self, checked: bool) -> None:
        """Persist and apply the commands toggle.

        Parameters
        ----------
        checked : bool
            New checkbox state.

        Returns
        -------
        None
            The setting is stored.
        """
        self._settings.set("show_commands", checked)

    def _on_show_tools(self, checked: bool) -> None:
        """Persist and apply the tool activity toggle.

        Parameters
        ----------
        checked : bool
            New checkbox state.

        Returns
        -------
        None
            The setting is stored and panels update.
        """
        self._settings.set("show_tools", checked)
        self._command_panel._show_tools = checked
        self._ideas_panel._show_tools = checked

    def _on_show_explanations(self, checked: bool) -> None:
        """Persist and apply the hover explanation toggle.

        Parameters
        ----------
        checked : bool
            Whether explanation tooltips are visible.

        Returns
        -------
        None
            Tooltips are added or cleared across panels.
        """
        self._settings.set("show_explanations", checked)
        self._apply_explanations(checked)
        self._command_panel.set_explanations(checked)
        self._ideas_panel.set_explanations(checked)

    def _apply_explanations(self, enabled: bool) -> None:
        """Set or clear tooltips on window-level widgets.

        Parameters
        ----------
        enabled : bool
            Whether tooltips should be visible.

        Returns
        -------
        None
            Widget tooltips reflect the toggle.
        """
        tips = self._window_tips()
        for widget, text in tips.items():
            widget.setToolTip(text if enabled else "")

    def _window_tips(self) -> dict:
        """Map window widgets to their help text.

        Returns
        -------
        dict
            Widget-to-explanation entries.
        """
        return {
            self._show_commands: "Show each tool command in the log.",
            self._show_tools: "Show tool activity entries in the log.",
            self._toggle: "Open or close the Ideas panel.",
            self._help: "Show or hide hover explanations.",
            self._sessions_heading: (
                "Saved conversations. Click to open, right-click to rename "
                "or delete."
            ),
            self._build_list: (
                "Saved project builds. Click to open, right-click to rename "
                "or delete."
            ),
            self._new_session_button: "Start a new conversation.",
            self._new_build_button: "Start a new build project.",
        }

    def toggle_ideas(self) -> None:
        """Toggle the ideas panel visibility.

        Returns
        -------
        None
            The ideas card shows or hides.
        """
        if self._ideas_card.isVisible():
            self._ideas_card.hide()
            self._toggle.setText("Open Ideas")
        else:
            self._ideas_card.show()
            self._toggle.setText("Close Ideas")

    def _card(self, panel: QWidget) -> QWidget:
        """Wrap a panel in a buffered card container.

        Parameters
        ----------
        panel : QWidget
            Panel to place inside the card.

        Returns
        -------
        QWidget
            Container with inset margins around the panel.
        """
        card = QWidget(self)
        card.setObjectName("PanelCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.addWidget(panel)
        return card

    def _build_header(self) -> QWidget:
        """Build the fixed-height header region.

        Returns
        -------
        QWidget
            Header with logo and divider line.
        """
        header = QWidget(self)
        header.setFixedHeight(200)
        box = QVBoxLayout(header)
        box.setContentsMargins(5, 0, 5, 0)
        box.setSpacing(0)
        box.addWidget(self._brand_label(), 0, Qt.AlignBottom)
        box.addWidget(self._header_line())
        return header

    def _brand_label(self) -> QLabel:
        """Build the single top-left logo.

        Returns
        -------
        QLabel
            Logo showing the header image.
        """
        path = Path(__file__).parent / "assets" / "sage_logo.png"
        label = QLabel(self)
        pixmap = QPixmap(str(path)).scaledToHeight(
            180, Qt.SmoothTransformation
        )
        label.setPixmap(pixmap)
        label.setFixedSize(pixmap.size())
        return label

    def _header_line(self) -> QFrame:
        """Build the line under the header.

        Returns
        -------
        QFrame
            Horizontal separator frame.
        """
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def closeEvent(self, event) -> None:  # noqa: N802
        """Prompt to save and stop panel threads before closing.

        Parameters
        ----------
        event : QCloseEvent
            Close notification.

        Returns
        -------
        None
            The session is saved or removed, then threads stop.
        """
        choice = QMessageBox.information(
            self,
            "Close",
            "Save this session?",
            buttons=QMessageBox.Save
            | QMessageBox.Discard
            | QMessageBox.Cancel,
            defaultButton=QMessageBox.Save,
        )
        if choice == QMessageBox.Discard:
            self._remove(self._record)
        elif choice != QMessageBox.Save:
            event.ignore()
            return
        self._command_panel.stop()
        self._ideas_panel.stop()
        event.accept()


def main() -> None:
    """Launch the desktop application.

    Returns
    -------
    None
        The application runs until the window closes.
    """
    app = QApplication(sys.argv)
    from .style import apply_palette

    apply_palette(app)
    store = SessionStore(Path("runs/sessions"))
    if not any(store.root.iterdir()):
        store.create(kind="session")
    from .settings import Settings

    window = MainWindow(store, Path("."), Settings())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
