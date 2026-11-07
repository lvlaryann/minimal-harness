"""Render polished HTML deliverables and scaled blueprint drawings."""

import html
import re
from datetime import date
from pathlib import Path
from typing import Any

THEMES = {"sage", "slate", "warm", "mono"}
DENSITIES = {"comfortable", "compact"}
FONTS = {"sans", "serif", "mono"}
DEFAULT_STYLE = {
    "theme": "sage",
    "density": "comfortable",
    "font": "sans",
    "columns": 1,
    "page_size": "letter",
    "accent": "",
    "custom_css": "",
}

SVG_W = 1200
MARGIN = 60

BASE_CSS = """
:root {
  --paper: #f7f5ef;
  --ink: #22302a;
  --accent: #3f6b5a;
  --muted: #6b7a72;
  --line: #d8ddd8;
  --font: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
  --text: 1.02rem;
  --lead: 1.7;
  --gap: 2.2rem;
}
* { box-sizing: border-box; }
html { background: #ece9e1; }
body {
  margin: 0;
  background: #ece9e1;
  color: var(--ink);
  font-family: var(--font);
  font-size: var(--text);
  line-height: var(--lead);
}
.page {
  max-width: 900px;
  margin: 32px auto;
  background: var(--paper);
  padding: 56px 64px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .08);
}
.cover {
  border-bottom: 2px solid var(--ink);
  padding-bottom: 1.4rem;
  margin-bottom: var(--gap);
}
.eyebrow {
  text-transform: uppercase;
  letter-spacing: .16em;
  font-size: .72rem;
  color: var(--accent);
  margin: 0 0 .4rem;
}
h1 { font-size: 2.4rem; line-height: 1.1; margin: 0 0 .5rem; }
.subtitle { color: var(--muted); font-size: 1.1rem; margin: 0 0 .6rem; }
.meta { color: var(--muted); font-size: .85rem; margin: 0; }
.summary {
  background: #fff;
  border-left: 4px solid var(--accent);
  padding: 1rem 1.4rem;
  margin-bottom: var(--gap);
}
.summary h2 { margin-top: 0; }
h2 { font-size: 1.3rem; margin: 2rem 0 .6rem; }
.section { break-inside: avoid; margin-bottom: var(--gap); }
p { margin: 0 0 .8rem; }
ul, ol { margin: 0 0 1rem 1.2rem; padding: 0; }
li { margin-bottom: .35rem; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: .6rem 0 1.2rem;
  font-size: .92rem;
}
th, td {
  text-align: left;
  padding: .45rem .6rem;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
th { background: #eef2ee; font-weight: 600; }
figcaption { color: var(--muted); font-size: .82rem; margin-top: .4rem; }
.callout {
  border-left: 3px solid var(--accent);
  background: #fff;
  padding: .7rem 1rem;
  margin: .8rem 0 1.2rem;
}
.callout.warn { border-color: #b46a3a; }
.callout.tip { border-color: #3f7d8c; }
.checklist { list-style: none; margin-left: 0; }
.checklist li::before { content: "\\25a1 "; color: var(--accent); }
.drawing svg {
  width: 100%;
  height: auto;
  border: 1px solid var(--line);
  background: #f7f5ef;
}
.notes {
  border-top: 1px solid var(--line);
  margin-top: var(--gap);
  padding-top: 1rem;
}
a { color: var(--accent); }
pre {
  background: #fff;
  border: 1px solid var(--line);
  padding: .8rem;
  overflow-x: auto;
}
body.theme-slate {
  --paper: #f4f6f8;
  --ink: #1f2a37;
  --accent: #2f5d8a;
  --muted: #5b6b7c;
  --line: #d9e0e7;
}
body.theme-warm {
  --paper: #fbf7ef;
  --ink: #3a2f27;
  --accent: #a2542f;
  --muted: #7b6a5c;
  --line: #e6dccd;
}
body.theme-mono {
  --paper: #fafafa;
  --ink: #111;
  --accent: #333;
  --muted: #666;
  --line: #ddd;
}
body.font-serif { --font: Georgia, "Times New Roman", serif; }
body.font-sans {
  --font: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
}
body.font-mono {
  --font: ui-monospace, SFMono-Regular, Menlo, monospace;
}
body.density-comfortable { --text: 1.02rem; --lead: 1.7; --gap: 2.2rem; }
body.density-compact { --text: .95rem; --lead: 1.5; --gap: 1.4rem; }
body.columns-2 .page { max-width: 1100px; }
body.columns-2 .sections { column-count: 2; column-gap: 2.4rem; }
@media print {
  html, body { background: #fff; }
  .page {
    box-shadow: none;
    margin: 0;
    max-width: none;
    padding: 0;
  }
  .section { break-inside: avoid; }
}
"""

SVG_CSS = """
svg.blueprint .ink {
  fill: none;
  stroke: var(--bp-ink, #1f3a5f);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
svg.blueprint .thin { stroke-width: 1.3; }
svg.blueprint .dash { stroke-dasharray: 7 7; }
svg.blueprint .dim {
  fill: none;
  stroke: var(--bp-dim, #2f6f8f);
  stroke-width: 1.1;
}
svg.blueprint .dimtext {
  font: 13px ui-monospace, SFMono-Regular, Menlo, monospace;
  fill: var(--bp-dim, #2f6f8f);
}
svg.blueprint .label {
  font: 600 15px Inter, system-ui, sans-serif;
  fill: var(--bp-ink, #1f3a5f);
  letter-spacing: .08em;
}
svg.blueprint .title {
  font: 700 34px Georgia, serif;
  fill: var(--bp-ink, #1f3a5f);
}
svg.blueprint .note {
  font: 13px Inter, system-ui, sans-serif;
  fill: var(--bp-dim, #4a6a8a);
}
"""


def slugify(value: str) -> str:
    """Turn a title into a filesystem-safe slug.

    Parameters
    ----------
    value : str
        Source text.

    Returns
    -------
    str
        Lowercase hyphenated slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "deliverable"


def render_deliverable(spec: dict[str, Any], out_dir: Path | str) -> Path:
    """Render one HTML deliverable into an output folder.

    Parameters
    ----------
    spec : dict[str, Any]
        Deliverable description.
    out_dir : pathlib.Path or str
        Folder receiving the file.

    Returns
    -------
    pathlib.Path
        Written HTML path.
    """
    style = _style(spec.get("style"))
    name = Path(spec.get("filename") or slugify(spec.get("title", ""))).name
    if not name.lower().endswith(".html"):
        name += ".html"
    target = Path(out_dir) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_document(spec, style), encoding="utf-8")
    return target


def blueprint_file(spec: dict[str, Any], out_dir: Path | str) -> Path:
    """Render one blueprint SVG into an output folder.

    Parameters
    ----------
    spec : dict[str, Any]
        Blueprint description.
    out_dir : pathlib.Path or str
        Folder receiving the file.

    Returns
    -------
    pathlib.Path
        Written SVG path.
    """
    values = _blueprint_spec(spec)
    default = slugify(values["title"]) + "-blueprint.svg"
    name = Path(spec.get("filename") or default).name
    if not name.lower().endswith(".svg"):
        name += ".svg"
    target = Path(out_dir) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(blueprint_svg(spec), encoding="utf-8")
    return target


def blueprint_svg(spec: dict[str, Any]) -> str:
    """Build a scaled blueprint drawing as SVG.

    Parameters
    ----------
    spec : dict[str, Any]
        Blueprint description.

    Returns
    -------
    str
        Complete SVG document fragment.
    """
    values = _blueprint_spec(spec)
    scale = _draw_scale(values)
    body, height = _views(values, scale)
    return _svg_shell(values, body, height)


def _style(raw: Any) -> dict[str, Any]:
    """Normalize style overrides.

    Parameters
    ----------
    raw : Any
        Raw style mapping.

    Returns
    -------
    dict[str, Any]
        Validated style values.
    """
    style = dict(DEFAULT_STYLE)
    if isinstance(raw, dict):
        style.update({key: raw[key] for key in style if key in raw})
    style["theme"] = _choice(style["theme"], THEMES, "sage")
    style["density"] = _choice(style["density"], DENSITIES, "comfortable")
    style["font"] = _choice(style["font"], FONTS, "sans")
    style["page_size"] = _choice(
        style["page_size"], {"letter", "a4"}, "letter"
    )
    style["columns"] = 2 if str(style["columns"]) == "2" else 1
    return style


def _choice(value: Any, allowed: set[str], default: str) -> str:
    """Pick an allowed lowercase option.

    Parameters
    ----------
    value : Any
        Requested value.
    allowed : set[str]
        Allowed values.
    default : str
        Fallback value.

    Returns
    -------
    str
        Chosen option.
    """
    text = str(value or "").lower()
    return text if text in allowed else default


def _document(spec: dict[str, Any], style: dict[str, Any]) -> str:
    """Assemble the HTML document.

    Parameters
    ----------
    spec : dict[str, Any]
        Deliverable description.
    style : dict[str, Any]
        Validated style values.

    Returns
    -------
    str
        Complete HTML text.
    """
    title = _e(spec.get("title", "Deliverable"))
    body_class = _body_class(style)
    accent = _accent(style)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" '
            'content="width=device-width, initial-scale=1">',
            f"<title>{title}</title>",
            f"<style>{_css(style)}</style>",
            "</head>",
            f'<body class="{body_class}"{accent}>',
            '<main class="page">',
            _header(spec),
            _summary(spec.get("summary")),
            '<div class="sections">',
            _sections(spec.get("sections") or []),
            "</div>",
            _assumptions(spec.get("assumptions")),
            _sources(spec.get("sources")),
            _next_steps(spec.get("next_steps")),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _css(style: dict[str, Any]) -> str:
    """Build the document stylesheet.

    Parameters
    ----------
    style : dict[str, Any]
        Validated style values.

    Returns
    -------
    str
        CSS text with page setup and overrides.
    """
    page = "A4" if style.get("page_size") == "a4" else "Letter"
    custom = str(style.get("custom_css", ""))
    return BASE_CSS + f"\n@page {{ size: {page}; margin: 16mm; }}\n" + custom


def _body_class(style: dict[str, Any]) -> str:
    """Build the body class list from style values.

    Parameters
    ----------
    style : dict[str, Any]
        Validated style values.

    Returns
    -------
    str
        Space-separated class names.
    """
    theme = f"theme-{style['theme']}"
    density = f"density-{style['density']}"
    font = f"font-{style['font']}"
    columns = f"columns-{style['columns']}"
    return " ".join([theme, density, font, columns])


def _accent(style: dict[str, Any]) -> str:
    """Build an inline accent override when requested.

    Parameters
    ----------
    style : dict[str, Any]
        Validated style values.

    Returns
    -------
    str
        Inline style attribute or blank.
    """
    accent = str(style.get("accent", "")).strip()
    return f' style="--accent:{_e(accent)}"' if accent else ""


def _header(spec: dict[str, Any]) -> str:
    """Render the document header.

    Parameters
    ----------
    spec : dict[str, Any]
        Deliverable description.

    Returns
    -------
    str
        Header HTML.
    """
    title = _e(spec.get("title", "Deliverable"))
    subtitle = _e(spec.get("subtitle", ""))
    kind = _e(spec.get("kind", "report")).title()
    stamp = date.today().strftime("%B %d, %Y")
    sub = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
    return (
        '<header class="cover">'
        f'<p class="eyebrow">{kind}</p>'
        f"<h1>{title}</h1>{sub}"
        f'<p class="meta">Prepared {stamp}</p>'
        "</header>"
    )


def _summary(value: Any) -> str:
    """Render the at-a-glance summary.

    Parameters
    ----------
    value : Any
        String or list of summary points.

    Returns
    -------
    str
        Summary HTML or blank.
    """
    items = _items(value)
    if not items:
        return ""
    body = "".join(f"<li>{_e(item)}</li>" for item in items)
    head = "<h2>At a glance</h2>"
    return f'<section class="summary">{head}<ul>{body}</ul></section>'


def _sections(sections: list[dict[str, Any]]) -> str:
    """Render all body sections.

    Parameters
    ----------
    sections : list[dict[str, Any]]
        Section descriptions.

    Returns
    -------
    str
        Section HTML.
    """
    return "".join(
        _section(section, index) for index, section in enumerate(sections, 1)
    )


def _section(section: dict[str, Any], index: int) -> str:
    """Render one body section.

    Parameters
    ----------
    section : dict[str, Any]
        Section description.
    index : int
        One-based section number.

    Returns
    -------
    str
        Section HTML.
    """
    heading = section.get("heading") or f"Section {index}"
    body = _body(section)
    return (
        f'<section class="section"><h2>{_e(heading)}</h2>' f"{body}</section>"
    )


def _body(section: dict[str, Any]) -> str:
    """Render the content blocks of one section.

    Parameters
    ----------
    section : dict[str, Any]
        Section description.

    Returns
    -------
    str
        Block HTML.
    """
    parts = [
        _paragraphs(section.get("body")),
        _bullets(section.get("bullets")),
        _table(section.get("table")),
        _figure(section.get("figure")),
        _callout(section.get("callout")),
        _checklist(section.get("checklist")),
        _code(section.get("code")),
        str(section.get("raw_html", "")),
    ]
    return "".join(part for part in parts if part)


def _items(value: Any) -> list[str]:
    """Normalize a string or list into text items.

    Parameters
    ----------
    value : Any
        Candidate content.

    Returns
    -------
    list[str]
        Non-empty text items.
    """
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _paragraphs(value: Any) -> str:
    """Render one or more paragraphs.

    Parameters
    ----------
    value : Any
        String or list of paragraphs.

    Returns
    -------
    str
        Paragraph HTML.
    """
    return "".join(f"<p>{_e(item)}</p>" for item in _items(value))


def _bullets(value: Any) -> str:
    """Render a bulleted list.

    Parameters
    ----------
    value : Any
        String or list of items.

    Returns
    -------
    str
        List HTML or blank.
    """
    items = _items(value)
    if not items:
        return ""
    body = "".join(f"<li>{_e(item)}</li>" for item in items)
    return f"<ul>{body}</ul>"


def _table(value: Any) -> str:
    """Render a table block.

    Parameters
    ----------
    value : Any
        Table description with columns and rows.

    Returns
    -------
    str
        Table HTML or blank.
    """
    if not isinstance(value, dict):
        return ""
    columns = [str(column) for column in value.get("columns") or []]
    rows = value.get("rows") or []
    if not columns or not rows:
        return ""
    head = "".join(f"<th>{_e(column)}</th>" for column in columns)
    body = "".join(_row(row) for row in rows)
    caption = _caption(value.get("caption"))
    table = (
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )
    return f'<figure class="table">{caption}{table}</figure>'


def _row(row: list[Any]) -> str:
    """Render one table row.

    Parameters
    ----------
    row : list[Any]
        Cell values.

    Returns
    -------
    str
        Row HTML.
    """
    cells = "".join(f"<td>{_e(cell)}</td>" for cell in row)
    return f"<tr>{cells}</tr>"


def _caption(value: Any) -> str:
    """Render an optional caption.

    Parameters
    ----------
    value : Any
        Caption text.

    Returns
    -------
    str
        Caption HTML or blank.
    """
    return f"<figcaption>{_e(value)}</figcaption>" if value else ""


def _figure(value: Any) -> str:
    """Render a blueprint or image figure.

    Parameters
    ----------
    value : Any
        Figure description.

    Returns
    -------
    str
        Figure HTML or blank.
    """
    if not isinstance(value, dict):
        return ""
    caption = _caption(value.get("caption"))
    if value.get("kind") == "blueprint":
        svg = blueprint_svg(value.get("blueprint") or {})
        return f'<figure class="drawing">{svg}{caption}</figure>'
    return ""


def _callout(value: Any) -> str:
    """Render a callout block.

    Parameters
    ----------
    value : Any
        Callout description with tone and text.

    Returns
    -------
    str
        Callout HTML or blank.
    """
    if not isinstance(value, dict):
        return ""
    tone = _choice(value.get("tone", "info"), {"info", "warn", "tip"}, "info")
    return f'<aside class="callout {tone}">{_e(value.get("text", ""))}</aside>'


def _checklist(value: Any) -> str:
    """Render a checklist block.

    Parameters
    ----------
    value : Any
        String or list of checklist items.

    Returns
    -------
    str
        Checklist HTML or blank.
    """
    items = _items(value)
    if not items:
        return ""
    body = "".join(f"<li>{_e(item)}</li>" for item in items)
    return f'<ul class="checklist">{body}</ul>'


def _code(value: Any) -> str:
    """Render a code block.

    Parameters
    ----------
    value : Any
        Code description with text and language.

    Returns
    -------
    str
        Code HTML or blank.
    """
    if not isinstance(value, dict):
        return ""
    language = _e(value.get("language", ""))
    text = _e(value.get("text", ""))
    return f'<pre class="{language}"><code>{text}</code></pre>'


def _assumptions(value: Any) -> str:
    """Render the assumptions section.

    Parameters
    ----------
    value : Any
        String or list of assumptions.

    Returns
    -------
    str
        Notes HTML or blank.
    """
    items = _items(value)
    if not items:
        return ""
    body = "".join(f"<li>{_e(item)}</li>" for item in items)
    head = "<h2>What I assumed</h2>"
    return f'<section class="notes">{head}<ul>{body}</ul></section>'


def _sources(value: Any) -> str:
    """Render the sources section.

    Parameters
    ----------
    value : Any
        List of source records.

    Returns
    -------
    str
        Sources HTML or blank.
    """
    if not isinstance(value, list) or not value:
        return ""
    links = "".join(_source(item) for item in value)
    return f'<section class="notes"><h2>Sources</h2><ul>{links}</ul></section>'


def _source(item: Any) -> str:
    """Render one source entry.

    Parameters
    ----------
    item : Any
        Source record or plain text.

    Returns
    -------
    str
        List item HTML.
    """
    if not isinstance(item, dict):
        return f"<li>{_e(item)}</li>"
    title = _e(item.get("title", item.get("url", "Source")))
    url = _e(item.get("url", ""))
    return (
        f'<li><a href="{url}">{title}</a></li>' if url else f"<li>{title}</li>"
    )


def _next_steps(value: Any) -> str:
    """Render the next-steps section.

    Parameters
    ----------
    value : Any
        String or list of next steps.

    Returns
    -------
    str
        Next-steps HTML or blank.
    """
    items = _items(value)
    if not items:
        return ""
    body = "".join(f"<li>{_e(item)}</li>" for item in items)
    return (
        f'<section class="notes"><h2>Next steps</h2><ul>{body}</ul></section>'
    )


def _blueprint_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize a blueprint description.

    Parameters
    ----------
    spec : dict[str, Any]
        Raw blueprint description.

    Returns
    -------
    dict[str, Any]
        Validated dimensions and features.
    """
    width = _number(spec.get("width_ft"), 10, 4, 80)
    depth = _number(spec.get("depth_ft"), 12, 4, 80)
    wall = _number(spec.get("wall_height_ft"), 6, 4, 20)
    ratio = _pitch_ratio(spec.get("pitch"))
    door = _door(spec.get("door"))
    if door["height_in"] / 12 > wall + 0.02:
        raise ValueError("door height exceeds wall height")
    return {
        "width_ft": width,
        "depth_ft": depth,
        "wall_height_ft": wall,
        "rise_ft": width / 2 * ratio,
        "pitch_ratio": ratio,
        "pitch_label": _pitch_label(spec.get("pitch")),
        "title": str(spec.get("title") or "Blueprint"),
        "door": door,
        "vents": _vents(spec.get("vents")),
        "views": _views_list(spec.get("views")),
        "accent": _accent_color(spec.get("style")),
    }


def _number(value: Any, default: float, low: float, high: float) -> float:
    """Convert a value to a clamped float.

    Parameters
    ----------
    value : Any
        Requested number.
    default : float
        Fallback value.
    low : float
        Minimum.
    high : float
        Maximum.

    Returns
    -------
    float
        Clamped number.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _pitch_ratio(value: Any) -> float:
    """Convert a pitch like ``4:12`` to a rise-over-run ratio.

    Parameters
    ----------
    value : Any
        Pitch text or ratio.

    Returns
    -------
    float
        Rise divided by run.
    """
    if isinstance(value, (int, float)):
        return _number(value, 0.25, 0.05, 1.0)
    text = str(value or "4:12")
    if ":" in text:
        rise, run = text.split(":", 1)
        return _number(rise, 4, 0.1, 12) / max(_number(run, 12, 0.1, 24), 0.1)
    return 0.25


def _pitch_label(value: Any) -> str:
    """Format a pitch label.

    Parameters
    ----------
    value : Any
        Pitch text or ratio.

    Returns
    -------
    str
        Human-readable pitch.
    """
    if isinstance(value, (int, float)):
        return f"{value:g}:12"
    text = str(value or "4:12").strip()
    return text if ":" in text else "4:12"


def _door(value: Any) -> dict[str, Any]:
    """Normalize a door description.

    Parameters
    ----------
    value : Any
        Door description.

    Returns
    -------
    dict[str, Any]
        Door width, height, and wall.
    """
    data = value if isinstance(value, dict) else {}
    walls = {"front", "back", "left", "right", "side"}
    return {
        "width_in": _number(data.get("width_in"), 32, 24, 96),
        "height_in": _number(data.get("height_in"), 72, 60, 120),
        "wall": _choice(data.get("wall", "front"), walls, "front"),
    }


def _vents(value: Any) -> list[dict[str, float]]:
    """Normalize vent descriptions.

    Parameters
    ----------
    value : Any
        Count or list of vent records.

    Returns
    -------
    list[dict[str, float]]
        Vent sizes.
    """
    if isinstance(value, list):
        return [_vent(item) for item in value if isinstance(item, dict)]
    count = int(_number(value, 2, 0, 6))
    return [_vent({}) for _ in range(count)]


def _vent(value: dict[str, Any]) -> dict[str, float]:
    """Normalize one vent size.

    Parameters
    ----------
    value : dict[str, Any]
        Vent record.

    Returns
    -------
    dict[str, float]
        Width and height in inches.
    """
    return {
        "width_in": _number(value.get("width_in"), 24, 6, 60),
        "height_in": _number(value.get("height_in"), 24, 6, 60),
    }


def _views_list(value: Any) -> list[str]:
    """Normalize requested drawing views.

    Parameters
    ----------
    value : Any
        Requested view names.

    Returns
    -------
    list[str]
        Valid view names in order.
    """
    allowed = ("plan", "front", "side")
    if not isinstance(value, list) or not value:
        return list(allowed)
    picked = [str(item).lower() for item in value]
    chosen = [name for name in picked if name in allowed]
    return chosen or list(allowed)


def _accent_color(value: Any) -> str:
    """Return a validated SVG accent color.

    Parameters
    ----------
    value : Any
        Style mapping.

    Returns
    -------
    str
        Hex color or blank.
    """
    data = value if isinstance(value, dict) else {}
    accent = str(data.get("accent", "")).strip()
    return accent if re.fullmatch(r"#[0-9a-fA-F]{3,8}", accent) else ""


def _draw_scale(values: dict[str, Any]) -> float:
    """Choose a pixels-per-foot scale that fits the sheet.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.

    Returns
    -------
    float
        Pixels per foot.
    """
    rise = values["rise_ft"]
    total = values["depth_ft"] + 2 * (values["wall_height_ft"] + rise) + 6
    by_height = 1000 / total
    by_width = 1000 / max(values["width_ft"], values["depth_ft"])
    return max(6.0, min(30.0, by_height, by_width))


def _views(values: dict[str, Any], scale: float) -> tuple[str, float]:
    """Render the requested views in order.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    scale : float
        Pixels per foot.

    Returns
    -------
    tuple[str, float]
        Combined SVG body and sheet height.
    """
    parts = []
    top = 150.0
    for name in values["views"]:
        view = _view(name, values, scale, top)
        parts.append(view["svg"])
        top = view["bottom"] + 70
    return "".join(parts), top + 100


def _view(name: str, values: dict[str, Any], scale: float, top: float) -> dict:
    """Render one named view.

    Parameters
    ----------
    name : str
        View name.
    values : dict[str, Any]
        Blueprint values.
    scale : float
        Pixels per foot.
    top : float
        Top of the view.

    Returns
    -------
    dict
        SVG body and bottom coordinate.
    """
    if name == "plan":
        return _plan_view(values, scale, top)
    if name == "front":
        return _front_view(values, scale, top)
    return _side_view(values, scale, top)


def _plan_view(values: dict[str, Any], scale: float, top: float) -> dict:
    """Render the plan view.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    scale : float
        Pixels per foot.
    top : float
        Top of the view.

    Returns
    -------
    dict
        SVG body and bottom coordinate.
    """
    width = values["width_ft"] * scale
    depth = values["depth_ft"] * scale
    left = (SVG_W - width) / 2
    body = _rect(left, top, width, depth)
    body += _line(
        left + width / 2, top, left + width / 2, top + depth, "ink dash"
    )
    body += _door_plan(values, left, top, width, depth, scale)
    body += _vent_plan(values, left, top, width, depth, scale)
    body += _dim_h(
        left, left + width, top + depth + 28, _ft(values["width_ft"])
    )
    body += _dim_v(
        left + width + 28, top, top + depth, _ft(values["depth_ft"])
    )
    body += _svg_text(left, top - 16, "PLAN", "label")
    return {"svg": body, "bottom": top + depth + 40}


def _door_plan(
    values: dict[str, Any],
    left: float,
    top: float,
    width: float,
    depth: float,
    scale: float,
) -> str:
    """Render a door opening in the plan view.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    left : float
        Left edge.
    top : float
        Top edge.
    width : float
        Plan width in pixels.
    depth : float
        Plan depth in pixels.
    scale : float
        Pixels per foot.

    Returns
    -------
    str
        Door SVG.
    """
    door = values["door"]["width_in"] / 12 * scale
    if door >= width:
        return ""
    hinge = left + (width - door) / 2
    base = top + depth
    body = _paper_rect(hinge, base - 2, door, 4)
    body += _line(hinge, base, hinge, base - door, "ink thin")
    body += _arc(hinge, base, door)
    label = _inches(values["door"]["width_in"])
    body += _svg_text(hinge + door + 8, base - door / 2, label, "dimtext")
    return body


def _vent_plan(
    values: dict[str, Any],
    left: float,
    top: float,
    width: float,
    depth: float,
    scale: float,
) -> str:
    """Render vent markers in the plan view.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    left : float
        Left edge.
    top : float
        Top edge.
    width : float
        Plan width in pixels.
    depth : float
        Plan depth in pixels.
    scale : float
        Pixels per foot.

    Returns
    -------
    str
        Vent SVG.
    """
    if not values["vents"]:
        return ""
    size = max(6.0, values["vents"][0]["width_in"] / 12 * scale)
    center = left + width / 2
    return "".join(
        _rect(
            center - size / 2,
            top + depth * ratio - size / 2,
            size,
            size,
            "ink thin dash",
        )
        for ratio in (0.3, 0.7)
    )


def _front_view(values: dict[str, Any], scale: float, top: float) -> dict:
    """Render the front elevation.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    scale : float
        Pixels per foot.
    top : float
        Apex of the roof.

    Returns
    -------
    dict
        SVG body and bottom coordinate.
    """
    width = values["width_ft"] * scale
    wall = values["wall_height_ft"] * scale
    rise = values["rise_ft"] * scale
    left = (SVG_W - width) / 2
    base = top + wall + rise
    body = _line(left - 12, base, left + width + 12, base, "ink thin")
    body += _rect(left, base - wall, width, wall)
    body += _polygon(
        "ink",
        left,
        base - wall,
        left + width,
        base - wall,
        left + width / 2,
        base - wall - rise,
    )
    body += _door_front(values, left, base, width, scale)
    body += _vents_front(values, left, base, width, wall, rise, scale)
    body += _dim_h(left, left + width, base + 28, _ft(values["width_ft"]))
    body += _dim_v(left - 28, base - wall, base, _ft(values["wall_height_ft"]))
    body += _svg_text(left, top - 16, "FRONT ELEVATION", "label")
    return {"svg": body, "bottom": base + 40}


def _door_front(
    values: dict[str, Any],
    left: float,
    base: float,
    width: float,
    scale: float,
) -> str:
    """Render a door in the front elevation.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    left : float
        Left edge.
    base : float
        Ground line.
    width : float
        Wall width in pixels.
    scale : float
        Pixels per foot.

    Returns
    -------
    str
        Door SVG.
    """
    if values["door"]["wall"] != "front":
        return ""
    door_w = values["door"]["width_in"] / 12 * scale
    door_h = values["door"]["height_in"] / 12 * scale
    x = left + (width - door_w) / 2
    body = _rect(x, base - door_h, door_w, door_h, "ink thin")
    body += _circle(x + door_w * 0.85, base - door_h * 0.5, 2.4, "ink")
    return body


def _vents_front(
    values: dict[str, Any],
    left: float,
    base: float,
    width: float,
    wall: float,
    rise: float,
    scale: float,
) -> str:
    """Render vents in the front gable.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    left : float
        Left edge.
    base : float
        Ground line.
    width : float
        Wall width in pixels.
    wall : float
        Wall height in pixels.
    rise : float
        Roof rise in pixels.
    scale : float
        Pixels per foot.

    Returns
    -------
    str
        Vent SVG.
    """
    count = min(len(values["vents"]), 4)
    if not count:
        return ""
    vent = values["vents"][0]["width_in"] / 12 * scale
    size = max(4.0, min(vent, rise * 0.35, width * 0.12))
    apex = base - wall - rise
    gap = width / (count + 1)
    body = ""
    for index in range(count):
        x = left + gap * (index + 1) - size / 2
        body += _rect(x, apex + rise * 0.45, size, size, "ink thin")
    return body


def _side_view(values: dict[str, Any], scale: float, top: float) -> dict:
    """Render the side elevation.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    scale : float
        Pixels per foot.
    top : float
        Top of the roof band.

    Returns
    -------
    dict
        SVG body and bottom coordinate.
    """
    depth = values["depth_ft"] * scale
    wall = values["wall_height_ft"] * scale
    rise = values["rise_ft"] * scale
    left = (SVG_W - depth) / 2
    base = top + wall + rise
    body = _line(left - 12, base, left + depth + 12, base, "ink thin")
    body += _rect(left, base - wall, depth, wall)
    body += _rect(left, base - wall - rise, depth, rise, "ink thin")
    body += _line(
        left, base - wall, left + depth, base - wall, "ink thin dash"
    )
    body += _door_side(values, left, base, depth, scale)
    body += _svg_text(
        left + depth / 2,
        base - wall - rise / 2 + 4,
        "ROOF SLOPES TO BOTH SIDES",
        "note",
        "middle",
    )
    body += _dim_h(left, left + depth, base + 28, _ft(values["depth_ft"]))
    body += _dim_v(left - 28, base - wall, base, _ft(values["wall_height_ft"]))
    body += _svg_text(left, top - 16, "SIDE ELEVATION", "label")
    return {"svg": body, "bottom": base + 40}


def _door_side(
    values: dict[str, Any],
    left: float,
    base: float,
    depth: float,
    scale: float,
) -> str:
    """Render a door in the side elevation.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    left : float
        Left edge.
    base : float
        Ground line.
    depth : float
        Side wall width in pixels.
    scale : float
        Pixels per foot.

    Returns
    -------
    str
        Door SVG or blank.
    """
    if values["door"]["wall"] not in ("left", "right", "side"):
        return ""
    door_w = values["door"]["width_in"] / 12 * scale
    door_h = values["door"]["height_in"] / 12 * scale
    x = left + (depth - door_w) / 2
    return _rect(x, base - door_h, door_w, door_h, "ink thin")


def _svg_shell(values: dict[str, Any], body: str, height: float) -> str:
    """Wrap drawing content in an SVG document.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.
    body : str
        Drawing SVG.
    height : float
        Sheet height.

    Returns
    -------
    str
        Complete SVG fragment.
    """
    title = _e(values["title"])
    accent = values["accent"]
    style = f' style="--bp-ink:{accent}"' if accent else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_W} '
        f'{height:.0f}" role="img" aria-label="{title} blueprint" '
        f'class="blueprint"{style}>'
        f"<style>{SVG_CSS}</style>"
        f'<rect width="{SVG_W}" height="{height:.0f}" fill="#f7f5ef"/>'
        f"{_title_block(values)}{body}{_notes_block(height - 110)}</svg>"
    )


def _title_block(values: dict[str, Any]) -> str:
    """Render the drawing title block.

    Parameters
    ----------
    values : dict[str, Any]
        Blueprint values.

    Returns
    -------
    str
        Title block SVG.
    """
    size = (
        f"{_ft(values['width_ft'])} x {_ft(values['depth_ft'])} "
        f"x {_ft(values['wall_height_ft'])} walls"
    )
    return (
        _svg_text(MARGIN, 54, values["title"], "title")
        + _svg_text(MARGIN, 80, "PRELIMINARY CONCEPT", "label")
        + _svg_text(
            MARGIN, 104, f"{size}   {values['pitch_label']} pitch", "note"
        )
        + _svg_text(
            SVG_W - MARGIN, 54, "SAGE / MINIMAL HARNESS", "label", "end"
        )
        + _svg_text(
            SVG_W - MARGIN, 78, date.today().isoformat(), "note", "end"
        )
        + _line(MARGIN, 120, SVG_W - MARGIN, 120, "ink thin")
    )


def _notes_block(top: float) -> str:
    """Render the drawing notes.

    Parameters
    ----------
    top : float
        Top of the notes block.

    Returns
    -------
    str
        Notes SVG.
    """
    return (
        _line(MARGIN, top, SVG_W - MARGIN, top, "ink thin")
        + _svg_text(MARGIN, top + 24, "NOTES", "label")
        + _svg_text(
            MARGIN,
            top + 48,
            "Dimensions in feet and inches. Verify all dimensions on site.",
            "note",
        )
        + _svg_text(
            MARGIN,
            top + 68,
            "Preliminary concept only. Not for construction.",
            "note",
        )
        + _svg_text(SVG_W - MARGIN, top + 24, "SCALE: NTS", "note", "end")
        + _svg_text(SVG_W - MARGIN, top + 48, "SHEET 1 OF 1", "note", "end")
    )


def _rect(
    x: float, y: float, width: float, height: float, cls: str = "ink"
) -> str:
    """Render a rectangle.

    Parameters
    ----------
    x : float
        Left edge.
    y : float
        Top edge.
    width : float
        Rectangle width.
    height : float
        Rectangle height.
    cls : str
        CSS classes.

    Returns
    -------
    str
        SVG rectangle.
    """
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" '
        f'height="{_n(height)}" class="{cls}"/>'
    )


def _paper_rect(x: float, y: float, width: float, height: float) -> str:
    """Render a paper-colored eraser rectangle.

    Parameters
    ----------
    x : float
        Left edge.
    y : float
        Top edge.
    width : float
        Rectangle width.
    height : float
        Rectangle height.

    Returns
    -------
    str
        SVG rectangle.
    """
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(width)}" '
        f'height="{_n(height)}" fill="#f7f5ef" stroke="none"/>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, cls: str = "ink") -> str:
    """Render a line.

    Parameters
    ----------
    x1 : float
        Start x.
    y1 : float
        Start y.
    x2 : float
        End x.
    y2 : float
        End y.
    cls : str
        CSS classes.

    Returns
    -------
    str
        SVG line.
    """
    return (
        f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" '
        f'y2="{_n(y2)}" class="{cls}"/>'
    )


def _polygon(cls: str, *points: float) -> str:
    """Render a polygon.

    Parameters
    ----------
    cls : str
        CSS classes.
    *points : float
        Alternating x and y values.

    Returns
    -------
    str
        SVG polygon.
    """
    pairs = " ".join(
        f"{_n(points[index])},{_n(points[index + 1])}"
        for index in range(0, len(points), 2)
    )
    return f'<polygon points="{pairs}" class="{cls}"/>'


def _circle(cx: float, cy: float, radius: float, cls: str = "ink") -> str:
    """Render a circle.

    Parameters
    ----------
    cx : float
        Center x.
    cy : float
        Center y.
    radius : float
        Circle radius.
    cls : str
        CSS classes.

    Returns
    -------
    str
        SVG circle.
    """
    return (
        f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(radius)}" '
        f'class="{cls}"/>'
    )


def _arc(cx: float, cy: float, radius: float) -> str:
    """Render a quarter-circle door swing.

    Parameters
    ----------
    cx : float
        Hinge x.
    cy : float
        Hinge y.
    radius : float
        Swing radius.

    Returns
    -------
    str
        SVG path.
    """
    start = f"M {_n(cx + radius)} {_n(cy)}"
    curve = f"A {_n(radius)} {_n(radius)} 0 0 1 {_n(cx)} {_n(cy - radius)}"
    return f'<path d="{start} {curve}" class="ink thin dash"/>'


def _svg_text(
    x: float,
    y: float,
    text: Any,
    cls: str = "label",
    anchor: str = "start",
) -> str:
    """Render an SVG text node.

    Parameters
    ----------
    x : float
        Text x.
    y : float
        Text y.
    text : Any
        Text content.
    cls : str
        CSS classes.
    anchor : str
        Text anchor.

    Returns
    -------
    str
        SVG text node.
    """
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" class="{cls}" '
        f'text-anchor="{anchor}">{_t(text)}</text>'
    )


def _dim_h(x1: float, x2: float, y: float, label: str) -> str:
    """Render a horizontal dimension line.

    Parameters
    ----------
    x1 : float
        Start x.
    x2 : float
        End x.
    y : float
        Line y.
    label : str
        Dimension text.

    Returns
    -------
    str
        Dimension SVG.
    """
    body = _line(x1, y, x2, y, "dim")
    body += _line(x1, y - 6, x1, y + 6, "dim")
    body += _line(x2, y - 6, x2, y + 6, "dim")
    body += _svg_text((x1 + x2) / 2, y - 8, label, "dimtext", "middle")
    return body


def _dim_v(x: float, y1: float, y2: float, label: str) -> str:
    """Render a vertical dimension line.

    Parameters
    ----------
    x : float
        Line x.
    y1 : float
        Start y.
    y2 : float
        End y.
    label : str
        Dimension text.

    Returns
    -------
    str
        Dimension SVG.
    """
    body = _line(x, y1, x, y2, "dim")
    body += _line(x - 6, y1, x + 6, y1, "dim")
    body += _line(x - 6, y2, x + 6, y2, "dim")
    body += _svg_text(x + 10, (y1 + y2) / 2, label, "dimtext", "start")
    return body


def _ft(value: float) -> str:
    """Format a measurement in feet and inches.

    Parameters
    ----------
    value : float
        Length in feet.

    Returns
    -------
    str
        Feet and inches label.
    """
    feet = int(value)
    inches = round((value - feet) * 12)
    if inches == 12:
        feet += 1
        inches = 0
    return f"{feet}'-{inches}\""


def _inches(value: float) -> str:
    """Format a measurement in inches.

    Parameters
    ----------
    value : float
        Length in inches.

    Returns
    -------
    str
        Inch label.
    """
    return f'{int(round(value))}"'


def _n(value: float) -> str:
    """Format a number for SVG attributes.

    Parameters
    ----------
    value : float
        Number to format.

    Returns
    -------
    str
        Trimmed decimal string.
    """
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def _e(value: Any) -> str:
    """Escape text for HTML or SVG attributes.

    Parameters
    ----------
    value : Any
        Value to escape.

    Returns
    -------
    str
        Escaped text.
    """
    return html.escape(str(value), quote=True)


def _t(value: Any) -> str:
    """Escape text for an SVG text node.

    Parameters
    ----------
    value : Any
        Value to escape.

    Returns
    -------
    str
        Escaped text with quotes preserved.
    """
    return html.escape(str(value), quote=False)
