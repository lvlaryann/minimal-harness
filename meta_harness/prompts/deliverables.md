# Deliverables

Use this for any file a human will read: plans, reports, guides, proposals,
letters, research, or estimates.

## Rule zero

Explicit user instructions win. If the user names a format, length, tone,
layout, sections, or look, follow it exactly. Fill only the gaps they left.

## Default shape

1. Decide the artifact type and who will read it.
2. Write the content as a spec, not as formatted text.
3. Call `make_deliverable` with a title, a short at-a-glance summary,
   free-form sections, assumptions, sources, and next steps.
4. If the artifact needs a drawing, put a `figure` with `kind: "blueprint"`
   in the section. Never use ASCII art.
5. After the file is written, tell the user in one short paragraph what is
   inside and where it is.

Spec shape:

```json
{
  "title": "10 x 12 Greenhouse",
  "summary": ["One line each", "Three to six points"],
  "sections": [
    {"heading": "Overview", "body": ["Paragraph"], "bullets": ["Point"]},
    {"heading": "Materials", "table": {"columns": ["Item", "Qty"], "rows": [["2x4", 28]]}},
    {"heading": "Drawing", "figure": {"kind": "blueprint", "caption": "Concept", "blueprint": {"width_ft": 10, "depth_ft": 12, "wall_height_ft": 6.5, "pitch": "4:12", "door": {"wall": "front", "width_in": 32, "height_in": 78}}}}
  ],
  "assumptions": ["What you filled in"],
  "sources": [{"title": "Source", "url": "https://example.com"}],
  "next_steps": ["Concrete action"]
}
```

Style keys for overrides: `theme` (sage, slate, warm, mono), `density`
(comfortable, compact), `font` (sans, serif, mono), `columns` (1 or 2),
`page_size` (letter or a4), `accent` (hex), and `custom_css`.

## Content bar

- Lead with the bottom line.
- Use real numbers with units and show the calculation.
- Put quantities in tables.
- State assumptions in their own section.
- Cite sources when you used them.
- End with concrete next steps.
- Keep sections short. One idea per section.

## Inference

Do not ask the user to specify presentation. Choose a sensible default and
say what you assumed. Ask only when two interpretations would produce
materially different files.

## Never

- ASCII art, text drawings, or `+---+` diagrams.
- Raw dumps of your notes.
- A wall of prose with no headings.
- Invented dimensions or quantities without stating them as assumptions.
