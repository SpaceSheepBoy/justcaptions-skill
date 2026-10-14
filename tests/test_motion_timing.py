"""Timing contract checks for caption frames, including silent gaps."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/justcaptions/scripts'))
from justcaptions import styles
from justcaptions.grouping import Caption, Word
from justcaptions.render import Renderer


def state_at(states, time):
    return next(active for start, end, active in states if start <= time < end)


class MotionTimingTests(unittest.TestCase):
    def test_typewriter_matches_native_86_percent_completion(self):
        r = Renderer(540, 960, styles.resolve('typewriter'))
        caption = Caption(0, 2, 'Hello world')
        spans = r.states(caption)
        for time in (0, .01, .4, .86, 1.4, 1.72, 1.9):
            expected = max(1, min(11, math.ceil(11 * min(time / 2 / .86, 1))))
            self.assertEqual(state_at(spans, time), expected, time)
        self.assertNotEqual(r.frame(caption, state_at(spans, 1.4)).tobytes(),
                            r.frame(caption, state_at(spans, 1.9)).tobytes())

    def test_typewriter_short_caption_is_fully_visible(self):
        r = Renderer(540, 960, styles.resolve('typewriter'))
        self.assertEqual(r.states(Caption(0, .17, 'Hello')), [(0, .17, 5)])
        self.assertEqual(r.states(Caption(0, 2, 'A')), [(0, 2, 1)])
        self.assertEqual(r.states(Caption(1, 1, 'Hello')), [(1, 1, 5)])
        self.assertGreater(len(r.states(Caption(0, .18, 'Hello'))), 1)

    def test_compact_script_typewriter_has_no_invented_spaces(self):
        r = Renderer(540, 960, styles.resolve('typewriter'))
        c = Caption(0, 2, '你好世界', [Word('你好', 0, .3), Word('世界', 1, 2)])
        self.assertEqual(r.states(c)[-1][2], 4)

    def test_complex_unicode_codepoint_limit_is_explicit(self):
        # No new Unicode dependency: current portable counting differs from Swift
        # graphemes. This documents the remaining boundary, not parity for emoji.
        r = Renderer(540, 960, styles.resolve('typewriter'))
        self.assertEqual(r.states(Caption(0, 2, 'e\u0301'))[-1][2], 2)
        self.assertEqual(r.states(Caption(0, 2, '👨\u200d👩\u200d👧'))[-1][2], 5)

    def test_yellow_highlight_uses_exact_word_interval_and_white_pause(self):
        caption = Caption(0, 2, 'one two', [Word('one', .2, .5), Word('two', 1.5, 1.8)])
        for name in ('word-highlight', 'highlight-box'):
            r = Renderer(540, 960, styles.resolve(name))
            spans = r.states(caption)
            for time, active in ((0, None), (.2, 0), (.499, 0), (.5, None),
                                 (.8, None), (1.5, 1), (1.8, None)):
                self.assertEqual(state_at(spans, time), active, (name, time))
            self.assertEqual(r.style.highlight_color, (255, 227, 77))
            white = r.frame(caption, None)
            self.assertIsNotNone(white.getbbox())
            self.assertNotEqual(white.tobytes(), r.frame(caption, 0).tobytes())
            self.assertNotIn((255, 227, 77, 255), set(white.getdata()))
            self.assertIn((255, 255, 255, 255), set(white.getdata()))

    def test_zero_duration_word_and_clipped_intervals(self):
        r = Renderer(540, 960, styles.resolve('word-highlight'))
        caption = Caption(0, 2, 'one two three',
            [Word('one', -.2, .2), Word('two', .7, .7), Word('three', 1.8, 3)])
        spans = r.states(caption)
        self.assertTrue(all(0 <= a < b <= 2 for a, b, _ in spans))
        self.assertEqual(state_at(spans, .7), None)
        self.assertEqual(state_at(spans, 1.9), 2)


if __name__ == '__main__':
    unittest.main()
