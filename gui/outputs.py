"""Output folders for files the agent delivers to the user."""

from pathlib import Path


def session_outputs(session_id: str) -> Path:
    """Return the output folder for one session.

    Parameters
    ----------
    session_id : str
        Session folder name.

    Returns
    -------
    pathlib.Path
        Created output folder.
    """
    folder = Path.home() / "Documents" / "Sage Outputs" / session_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_files(folder: Path | str | None) -> list[Path]:
    """Return delivered files, newest first.

    Parameters
    ----------
    folder : pathlib.Path or str or None
        Output folder to scan.

    Returns
    -------
    list[pathlib.Path]
        Files under the folder.
    """
    if folder is None:
        return []
    root = Path(folder)
    if not root.exists():
        return []
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not _hidden(path, root)
    ]
    files.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return files


def _hidden(path: Path, root: Path) -> bool:
    """Return whether a file sits in a hidden folder.

    Parameters
    ----------
    path : pathlib.Path
        File to inspect.
    root : pathlib.Path
        Output folder root.

    Returns
    -------
    bool
        True when any path part starts with a dot.
    """
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def human_size(size: int) -> str:
    """Format a byte count for display.

    Parameters
    ----------
    size : int
        Size in bytes.

    Returns
    -------
    str
        Short size label.
    """
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return (
                f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            )
        size /= 1024
    return f"{size:.1f} GB"
