"""Offline tests for HTML deliverables and blueprint drawings."""

import tempfile
import unittest
from pathlib import Path

from meta_harness.deliverables import blueprint_svg, render_deliverable
from meta_harness.tools import ToolRegistry


def make_spec(**overrides) -> dict:
    """Return a complete deliverable specification.

    Parameters
    ----------
    **overrides : dict
        Values replacing the defaults.

    Returns
    -------
    dict
        Deliverable specification.
    """
    spec = {
        "title": "Greenhouse Plan",
        "subtitle": "10 x 12 concept",
        "summary": ["Built for cold winters", "Estimated $1,600"],
        "sections": [
            {
                "heading": "Overview",
                "body": ["A small greenhouse."],
                "bullets": ["Cedar frame"],
            },
            {
                "heading": "Materials",
                "table": {
                    "columns": ["Item", "Qty"],
                    "rows": [["2x4", 28]],
                },
            },
            {
                "heading": "Drawing",
                "figure": {
                    "kind": "blueprint",
                    "caption": "Front and side views",
                    "blueprint": {
                        "width_ft": 10,
                        "depth_ft": 12,
                        "wall_height_ft": 6,
                        "pitch": "4:12",
                    },
                },
            },
            {"heading": "Custom", "raw_html": "<h3>Extra</h3>"},
        ],
        "assumptions": ["Wood frame"],
        "sources": [{"title": "Example", "url": "https://example.com"}],
        "next_steps": ["Check permits"],
        "style": {
            "theme": "slate",
            "columns": 2,
            "font": "serif",
            "accent": "#336699",
            "custom_css": ".x { color: red; }",
        },
    }
    spec.update(overrides)
    return spec


class DeliverableTests(unittest.TestCase):
    """Verify structured HTML rendering and style overrides."""

    def test_render_writes_structured_html(self) -> None:
        """A full spec renders summary, table, note, and drawing.

        Returns
        -------
        None
            Assertions pass when every block is present.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = render_deliverable(make_spec(), directory)
            text = path.read_text()
            self.assertTrue(path.exists())
        self.assertIn("Greenhouse Plan", text)
        self.assertIn("At a glance", text)
        self.assertIn("<table>", text)
        self.assertIn("What I assumed", text)
        self.assertIn("Next steps", text)
        self.assertIn("<h3>Extra</h3>", text)
        self.assertIn("<svg", text)

    def test_style_overrides_apply(self) -> None:
        """Theme, columns, font, accent, and CSS reach the document.

        Returns
        -------
        None
            Assertions pass when override values are present.
        """
        with tempfile.TemporaryDirectory() as directory:
            text = render_deliverable(make_spec(), directory).read_text()
        self.assertIn("theme-slate", text)
        self.assertIn("columns-2", text)
        self.assertIn("font-serif", text)
        self.assertIn("--accent:#336699", text)
        self.assertIn(".x { color: red; }", text)


class BlueprintTests(unittest.TestCase):
    """Verify scaled drawing output."""

    def test_blueprint_has_scaled_views(self) -> None:
        """All three views and their dimensions are drawn.

        Returns
        -------
        None
            Assertions pass when the views and labels exist.
        """
        svg = blueprint_svg(
            {"width_ft": 10, "depth_ft": 12, "wall_height_ft": 6}
        )
        self.assertIn("<svg", svg)
        self.assertIn("PLAN", svg)
        self.assertIn("FRONT ELEVATION", svg)
        self.assertIn("SIDE ELEVATION", svg)
        self.assertIn("10'-0\"", svg)
        self.assertIn("12'-0\"", svg)
        self.assertIn("NOT FOR CONSTRUCTION", svg.upper())

    def test_blueprint_views_can_be_limited(self) -> None:
        """A view override drops the unrequested views.

        Returns
        -------
        None
            Assertions pass when only the plan is drawn.
        """
        svg = blueprint_svg(
            {"views": ["plan"], "width_ft": 10, "depth_ft": 12}
        )
        self.assertIn("PLAN", svg)
        self.assertNotIn("FRONT ELEVATION", svg)


class DeliverableToolTests(unittest.TestCase):
    """Verify the tools write into the output folder."""

    def test_tools_write_into_outputs(self) -> None:
        """HTML and SVG land under the configured outputs root.

        Returns
        -------
        None
            Assertions pass when both files exist.
        """
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory, "out")
            registry = ToolRegistry(directory, outputs=outputs)
            html = registry.make_deliverable(
                "Title", [{"heading": "One", "body": ["Text"]}]
            )
            svg = registry.make_blueprint(
                title="Shed", width_ft=8, depth_ft=10
            )
            self.assertTrue(Path(html["path"]).exists())
            self.assertTrue(Path(svg["path"]).exists())
            self.assertEqual(Path(html["path"]).parent, outputs.resolve())


if __name__ == "__main__":
    unittest.main()
