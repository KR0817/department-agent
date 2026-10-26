"""The shell and the exact-prescription page share one offline visual system."""
import re
import unittest

from mingyirx.dashboard_clinical import CSS as SHELL_CSS
from mingyirx.dashboard_exact_rx import CSS as EXACT_CSS, HTML as EXACT_HTML
from mingyirx.ui_tokens import TOKENS


class UiTokenTests(unittest.TestCase):
    def test_small_text_palette_has_readable_contrast(self):
        colors = dict(re.findall(r'--([\w-]+):(#[0-9a-f]{6})', TOKENS))

        def luminance(color):
            values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
            return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))

        for foreground, background in [('gold-ink', 'ground'), ('gold-ink', 'hl-soft'),
                                       ('muted', 'paper'), ('add', 'add-bg'), ('remove', 'remove-bg')]:
            low, high = sorted([luminance(colors[foreground]), luminance(colors[background])])
            self.assertGreaterEqual((high + .05) / (low + .05), 4.5,
                                    (foreground, background))

    def test_both_pages_start_from_the_same_tokens(self):
        self.assertTrue(SHELL_CSS.startswith(TOKENS))
        self.assertTrue(EXACT_CSS.startswith(TOKENS))

    def test_styles_stay_offline(self):
        for css in (TOKENS, SHELL_CSS, EXACT_CSS):
            self.assertNotRegex(css, r"@import|url\(|@font-face")

    def test_type_sizes_stay_on_the_scale(self):
        scale = {12, 14, 16, 18, 20, 24, 30}
        for css in (SHELL_CSS, EXACT_CSS):
            sizes = {int(value) for value in re.findall(r"font-size:(\d+)px", css)}
            sizes |= {int(value) for value in re.findall(r"font:(?:\d+ )?(\d+)px", css)}
            self.assertLessEqual(sizes, scale)

    def test_exact_page_keeps_controller_element_ids(self):
        for element_id in ("mode-note", "totals", "boundary-note", "case-select", "medicine-select",
                           "episode-title", "source-badge", "episode-note", "timeline", "pair-title",
                           "previous-pair", "next-pair", "clinical-grid", "simulation-change",
                           "rx-origin", "membership-changes", "dose-title", "dose-changes",
                           "exact-status", "focus-panel", "raw-prescriptions", "provenance"):
            self.assertEqual(EXACT_HTML.count(f'id="{element_id}"'), 1, element_id)


if __name__ == "__main__":
    unittest.main()
