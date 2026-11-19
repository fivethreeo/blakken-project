"""Regression checks for inline SVG sprite generation."""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ASSETS = Path(__file__).parent
sys.path.insert(0, str(ASSETS))

import make_svg_icon_sprites as sprites


class IconSpriteRegressionTest(unittest.TestCase):
    def test_empty_master_generates_an_empty_sprite_without_inkscape(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            master = directory / "master.svg"
            master.write_text(
                f'<svg xmlns="{sprites.SVG_NAMESPACE}"><g id="layer1"/><g id="layer2"/></svg>'
            )
            output = directory / "includes/icons.svg"
            with patch.object(sprites.subprocess, "run") as run:
                sprites.compile_precise_spritesheet_by_layer_input(master, output, "layer2")
            run.assert_not_called()
            self.assertEqual(len(ET.parse(output).getroot().find(f"{sprites.SVG}defs")), 0)

    def test_both_layers_require_matching_id_and_label_and_exclude_rect_numbers(self):
        for layer_id, label in (("layer1", "Artwork"), ("layer2", "ViewBoxes")):
            with self.subTest(layer=label):
                root = ET.fromstring(f'''
                    <svg xmlns="{sprites.SVG_NAMESPACE}"
                      xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
                      <g id="{layer_id}" inkscape:label="{label}" transform="translate(10 20)">
                        <g transform="scale(2)">
                          <rect id="edit" inkscape:label="edit" x="1" y="2" width="3" height="4"/>
                          <rect id="rect12x" inkscape:label="rect12x" width="5" height="6"/>
                          <rect id="unlabelled"/>
                          <rect id="mismatch" inkscape:label="different"/>
                          <rect id="rect123" inkscape:label="rect123"/>
                          <rect inkscape:label="missing-id"/>
                          <rect/>
                        </g>
                      </g>
                      <g inkscape:label="Unrelated">
                        <rect id="ignored" inkscape:label="ignored"/>
                      </g>
                    </svg>
                ''')
                self.assertEqual(sprites._guide_rectangles(root, "layer2"), [
                    ("edit", 12, 24, 6, 8),
                    ("rect12x", 10, 20, 10, 12),
                ])

    def test_guides_are_collected_from_both_layers_in_one_master(self):
        root = ET.fromstring(f'''
            <svg xmlns="{sprites.SVG_NAMESPACE}"
              xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
              <g id="layer1" inkscape:label="Artwork">
                <rect id="edit" inkscape:label="edit" width="16" height="16"/>
              </g>
              <g id="layer2" inkscape:label="ViewBoxes">
                <rect id="save" inkscape:label="save" width="24" height="24"/>
              </g>
            </svg>
        ''')
        self.assertEqual(sprites._guide_rectangles(root, "layer2"), [
            ("edit", 0, 0, 16, 16), ("save", 0, 0, 24, 24),
        ])

    def test_sprite_is_inline_ready_and_references_preserve_icon_geometry(self):
        icons = [("sample", 24, 16, "M 0 0 H 24 V 16 Z")]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "icons.svg"
            sprites._write_svg_sprite(icons, output)
            contents = output.read_text()
            root = ET.fromstring(contents)
            self.assertNotIn("<?xml", contents)
            self.assertEqual(root.get("style"), "display: none")
            self.assertEqual(root.get("aria-hidden"), "true")
            self.assertEqual(root.get("focusable"), "false")
            symbol = root.find(f".//{sprites.SVG}symbol[@id='sample']")
            self.assertEqual(symbol.get("viewBox"), "0 0 24 16")
            path = symbol.find(f"{sprites.SVG}path")
            self.assertEqual(path.get("d"), icons[0][3])
            self.assertEqual(path.get("fill"), "currentColor")
            before = output.stat().st_mtime_ns
            sprites._write_svg_sprite(icons, output)
            self.assertEqual(output.stat().st_mtime_ns, before)

    def test_missing_guide_layer_still_fails(self):
        root = ET.fromstring(f'<svg xmlns="{sprites.SVG_NAMESPACE}"/>')
        with self.assertRaisesRegex(ValueError, "Could not find guide layer"):
            sprites._guide_rectangles(root, "layer2")


if __name__ == "__main__":
    unittest.main()
