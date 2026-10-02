import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "justcaptions" / "scripts"))

from justcaptions import api, emoji, formats, transcribe  # noqa: E402
from justcaptions.grouping import Caption, Word, group_words, words_from_segments  # noqa: E402


def words(text, start=0.0, step=0.3):
    out = []
    for i, w in enumerate(text.split()):
        out.append(Word(w, start + i * step, start + i * step + step * 0.9))
    return out


class GroupingTests(unittest.TestCase):
    def test_breaks_after_sentence(self):
        caps = group_words(words("Hello there. How are you?"))
        self.assertEqual([c.text for c in caps], ["Hello there.", "How are you?"])

    def test_breaks_on_long_pause(self):
        ws = words("one two") + words("three four", start=5.0)
        caps = group_words(ws)
        self.assertEqual([c.text for c in caps], ["one two", "three four"])
        # No hold across a long silence.
        self.assertAlmostEqual(caps[0].end, ws[1].end)

    def test_short_gap_is_held_until_next_caption(self):
        caps = group_words(words("Hi. Yes", step=0.5))
        self.assertEqual(caps[0].end, caps[1].start)

    def test_character_limit_depends_on_layout(self):
        text = " ".join(["word"] * 30)  # 149 characters
        portrait = group_words(words(text), layout="portrait")
        landscape = group_words(words(text), layout="landscape")
        self.assertTrue(all(len(c.text) <= 68 for c in portrait))
        self.assertTrue(all(len(c.text) <= 98 for c in landscape))
        self.assertGreater(len(portrait), len(landscape))

    def test_max_words_for_emoji_style(self):
        caps = group_words(words("make money fast with this one trick"), max_words=3)
        self.assertEqual([len(c.words) for c in caps], [3, 3, 1])

    def test_compact_script_joins_without_spaces(self):
        ws = [Word("大家", 0, 0.4), Word("好", 0.4, 0.6)]
        self.assertEqual(group_words(ws)[0].text, "大家好")

    def test_segments_spread_into_words(self):
        ws = words_from_segments([{"start": 0, "end": 2, "text": "ab cd"}])
        self.assertEqual([w.text for w in ws], ["ab", "cd"])
        self.assertAlmostEqual(ws[1].end, 2.0)


class FormatTests(unittest.TestCase):
    caps = [Caption(0.0, 1.5, "Hello"), Caption(61.25, 3725.004, "World")]

    def test_srt(self):
        self.assertEqual(
            formats.to_srt(self.caps),
            "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n2\n00:01:01,250 --> 01:02:05,004\nWorld\n",
        )

    def test_vtt(self):
        self.assertTrue(formats.to_vtt(self.caps).startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello\n"))

    def test_parse_round_trip(self):
        segs = formats.parse_subtitles(formats.to_srt(self.caps))
        self.assertEqual(segs[1], {"start": 61.25, "end": 3725.004, "text": "World"})
        self.assertEqual(formats.parse_subtitles(formats.to_vtt(self.caps))[0]["text"], "Hello")


class MultipartTests(unittest.TestCase):
    def test_body_layout(self):
        body, ctype = api.build_multipart({"language": "en"}, {"file": ("a.m4a", b"\x00\x01", "audio/mp4")})
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary=jc-"))
        self.assertIn(f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nen\r\n'.encode(), body)
        self.assertIn(b'name="file"; filename="a.m4a"\r\nContent-Type: audio/mp4\r\n\r\n\x00\x01\r\n', body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_parses_with_stdlib(self):
        from email.parser import BytesParser
        body, ctype = api.build_multipart({"format": "json"}, {"file": ("a.m4a", b"xyz", "audio/mp4")})
        msg = BytesParser().parse(io.BytesIO(f"Content-Type: {ctype}\r\n\r\n".encode() + body))
        parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.get_payload()}
        self.assertEqual(parts, {"format": b"json", "file": b"xyz"})


class ChunkedTranscriptionTests(unittest.TestCase):
    def test_slices_are_shifted_onto_the_full_timeline(self):
        calls = []

        def fake_extract(video, out, start=0.0, duration=0.0):
            out.write_bytes(b"x" * (30 if not duration else 10))
            calls.append((start, duration))
            return out

        def fake_api(audio, name, language, glossary):
            return {"language": "eng", "words": [{"word": "hi", "start": 1.0, "end": 1.5}]}

        with mock.patch.object(api, "MAX_AUDIO_BYTES", 20), \
             mock.patch.object(transcribe.media, "extract_audio", fake_extract), \
             mock.patch.object(api, "transcribe", fake_api):
            with tempfile.TemporaryDirectory() as d:
                ws, lang = transcribe.transcribe_api(Path("v.mp4"), Path(d), 120.0, None, [])
        self.assertEqual(lang, "eng")
        self.assertEqual(len(calls), 3)  # full extract + 2 slices
        self.assertEqual([w.start for w in ws], [1.0, 61.0])


class EmojiTests(unittest.TestCase):
    def test_keyword_match_and_provider_language_spelling(self):
        self.assertEqual(emoji.pick("pizza time", language="eng"), emoji.pick("pizza time", language="en"))
        self.assertNotIn(emoji.pick("pizza time", language="en"), emoji.MOOD)

    def test_always_returns_an_emoji(self):
        self.assertTrue(emoji.pick("qwrtzxv"))


if __name__ == "__main__":
    unittest.main()
