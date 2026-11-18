import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/justcaptions/scripts'))
from justcaptions.grouping import Caption, Word, reconcile_caption_text, split_into_words
from justcaptions import formats


class TimingEditTests(unittest.TestCase):
    def caption(self):
        return Caption(0, 5, 'hello world', [Word('hello', .5, 1, 'a'), Word('world', 3, 4, 'b')], '🙂')

    def test_insert_in_pause_preserves_neighbors(self):
        result = reconcile_caption_text(self.caption(), 'hello beautiful wide world')
        self.assertEqual([(w.start, w.end, w.id) for w in result.words],
                         [(.5, 1, 'a'), (1, 2, None), (2, 3, None), (3, 4, 'b')])
        self.assertEqual(result.emoji, '🙂')

    def test_delete_does_not_retime_remaining_word(self):
        result = reconcile_caption_text(self.caption(), 'world')
        self.assertEqual(result.words, [Word('world', 3, 4, 'b')])

    def test_typo_and_punctuation_preserve_times_and_ids(self):
        result = reconcile_caption_text(self.caption(), 'Hello, worlds!')
        self.assertEqual(result.words, [Word('Hello,', .5, 1, 'a'), Word('worlds!', 3, 4, 'b')])

    def test_repeated_words_tie_break_is_deterministic(self):
        c = Caption(0, 3, 'go go now', [Word('go', 0, 1, 'a'), Word('go', 1, 2, 'b'), Word('now', 2, 3, 'c')])
        result = reconcile_caption_text(c, 'go now')
        self.assertEqual([w.id for w in result.words], ['b', 'c'])

    def test_insertion_without_gap_does_not_move_neighbor(self):
        c = Caption(0, 2, 'hello world', [Word('hello', 0, 1, 'a'), Word('world', 1, 2, 'b')])
        result = reconcile_caption_text(c, 'hello new world')
        self.assertEqual(result.words[1], Word('new', 1, 1))
        self.assertEqual(result.words[2], c.words[1])

    def test_head_and_tail_insertions_use_caption_edges(self):
        result = reconcile_caption_text(self.caption(), 'well hello world today')
        self.assertEqual((result.words[0].start, result.words[0].end), (0, .5))
        self.assertEqual((result.words[-1].start, result.words[-1].end), (4, 5))

    def test_nfc_case_matching(self):
        c = Caption(0, 2, 'café now', [Word('café', 0, .4, 'a'), Word('now', 1, 2, 'b')])
        result = reconcile_caption_text(c, 'CAFE\u0301! yes now')
        self.assertEqual(result.words[0].id, 'a')
        self.assertEqual(result.words[-1].id, 'b')

    def test_translation_remains_whole_caption_inference(self):
        c = self.caption()
        result = split_into_words(Caption(c.start, c.end, 'bonjour monde'))
        self.assertEqual(result.words[0].start, c.start)
        self.assertEqual(result.words[-1].end, c.end)
        self.assertTrue(all(w.id is None for w in result.words))

    def test_multichar_cjk_uses_conservative_fallback(self):
        c = Caption(0, 3, '你好世界', [Word('你好', .5, 1, 'a'), Word('世界', 2, 3, 'b')])
        result = reconcile_caption_text(c, '你好新世界')
        self.assertEqual(len(result.words), 5)
        self.assertTrue(all(w.id is None for w in result.words))

    def test_large_matrix_falls_back_without_unbounded_work(self):
        c = Caption(0, 100, ' '.join(['a']*512), [Word('a', i/10, (i+1)/10, str(i)) for i in range(512)])
        result = reconcile_caption_text(c, ' '.join(['b']*512))
        self.assertEqual(result.words[-1].id, '511')
        result = reconcile_caption_text(c, ' '.join(['b']*513))
        self.assertTrue(all(w.id is None for w in result.words))

    def test_json_roundtrip_keeps_optional_ids(self):
        result = formats.load_captions_json(json.loads(formats.to_json([self.caption()])))
        self.assertEqual(result[0].words, self.caption().words)


    def test_punctuation_only_keys_do_not_collapse(self):
        c = Caption(0, 3, "! ? !", [Word("!", 0, 1, "a"), Word("?", 1, 2, "b"), Word("!", 2, 3, "c")])
        result = reconcile_caption_text(c, "! !")
        self.assertEqual([w.id for w in result.words], ["a", "c"])

    def test_invalid_source_timing_never_uses_zip_fallback(self):
        invalid = [
            [Word("hello", float("nan"), 1, "a"), Word("world", 1, 2, "b")],
            [Word("hello", 0, float("inf"), "a"), Word("world", 1, 2, "b")],
            [Word("hello", 1, 0, "a"), Word("world", 1, 2, "b")],
            [Word("hello", 1, 2, "a"), Word("world", 0, 1, "b")],
        ]
        for words in invalid:
            with self.subTest(words=words):
                result = reconcile_caption_text(Caption(0, 3, "hello world", words), "Hello worlds")
                self.assertTrue(all(w.id is None for w in result.words))
                self.assertEqual((result.words[0].start, result.words[-1].end), (0, 3))
