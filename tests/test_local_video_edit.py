import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


EDITOR = Path(__file__).resolve().parents[1] / "skills/local-video-edit/scripts/edit.py"
SRT_RETIMER = EDITOR.with_name("retime_srt.py")
SILENCE_DETECTOR = EDITOR.with_name("detect_silence.py")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class LocalVideoEditTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        root = Path(work.name)
        self.cuts = root / "cuts.json"
        self.output = root / "edited.mp4"
        self.source = root / "source.mp4"

    def make_source(self, *, audio):
        ffmpeg = [
            "ffmpeg", "-v", "error",
            "-f", "lavfi", "-i", "color=red:s=64x48:r=25:d=1",
            "-f", "lavfi", "-i", "color=blue:s=64x48:r=25:d=1",
        ]
        if audio:
            ffmpeg += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
        ffmpeg += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"]
        if audio:
            ffmpeg += ["-map", "2:a", "-c:a", "aac"]
        subprocess.run([*ffmpeg, "-c:v", "libx264", str(self.source)], check=True)

    def edit(self, *options):
        return subprocess.run(
            [sys.executable, str(EDITOR), str(self.source), str(self.cuts), str(self.output), *options],
            capture_output=True, text=True,
        )

    def retime(self, source_srt, output_srt):
        return subprocess.run(
            [sys.executable, str(SRT_RETIMER), str(self.source), str(self.cuts), str(source_srt), str(output_srt)],
            capture_output=True, text=True,
        )

    def inspect(self):
        return json.loads(subprocess.check_output(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration:stream=codec_type,nb_frames,width,height,sample_aspect_ratio:chapter=start_time",
             "-of", "json", str(self.output)],
        ))

    def frame_color(self, at):
        return subprocess.check_output(
            ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(self.output),
             "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        )[:3]

    def test_reorders_and_reuses_ranges_with_audio(self):
        self.make_source(audio=True)
        original = self.source.read_bytes()
        self.cuts.write_text('[{"start":1.2,"end":1.8},{"start":0.2,"end":0.8},{"start":1.2,"end":1.8}]')
        preview = self.edit("--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Planned duration: 1.8 s", preview.stdout)
        self.assertFalse(self.output.exists())

        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        media = self.inspect()
        self.assertEqual([s["codec_type"] for s in media["streams"]], ["video", "audio"])
        self.assertEqual((media["streams"][0]["width"], media["streams"][0]["height"]), (64, 48))
        self.assertAlmostEqual(float(media["format"]["duration"]), 1.8, delta=0.05)
        self.assertGreater(self.frame_color(0.2)[2], 200)
        self.assertGreater(self.frame_color(0.8)[0], 200)
        self.assertGreater(self.frame_color(1.4)[2], 200)
        self.assertEqual(self.source.read_bytes(), original)

        exported = self.output.read_bytes()
        self.assertNotEqual(self.edit().returncode, 0)
        self.assertEqual(self.output.read_bytes(), exported)

    def test_portrait_fits_display_aspect_ratio_on_a_single_frame_cut(self):
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x48:r=25:d=1,setsar=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-c:a", "aac", str(self.source),
        ], check=True)
        original = self.source.read_bytes()
        self.cuts.write_text('[{"start":0.2,"end":0.24}]')
        preview = self.edit("--portrait", "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("1080x1920", preview.stdout)
        self.assertFalse(self.output.exists())

        edit = self.edit("--portrait")
        self.assertEqual(edit.returncode, 0, edit.stderr)
        media = self.inspect()
        video, audio = media["streams"]
        self.assertEqual((video["width"], video["height"], video["sample_aspect_ratio"]), (1080, 1920, "1:1"))
        self.assertEqual(int(video["nb_frames"]), 1)
        self.assertEqual(audio["codec_type"], "audio")
        self.assertAlmostEqual(float(media["format"]["duration"]), 0.04, delta=0.005)

        # A 2:1 sample aspect ratio makes the fitted red picture about 405 pixels high.
        frame = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(self.output), "-frames:v", "1",
            "-vf", "scale=90:160", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ])
        self.assertGreater(frame[(80 * 90) * 3], 200)
        self.assertGreater(frame[(65 * 90 + 89) * 3], 200)
        self.assertLess(frame[(58 * 90 + 45) * 3], 10)
        self.assertLess(frame[(102 * 90 + 45) * 3], 10)
        self.assertEqual(self.source.read_bytes(), original)

    def test_silent_video_and_invalid_ranges(self):
        self.make_source(audio=False)
        for example in (
            '[{"start":0.5,"end":2.1}]', '[{"start":true,"end":1}]',
            '[{"start":0.0000001,"end":1}]', '[{"start":NaN,"end":1}]',
        ):
            with self.subTest(example=example):
                self.cuts.write_text(example)
                self.assertNotEqual(self.edit().returncode, 0)
                self.assertFalse(self.output.exists())

        self.cuts.write_text('[{"start":0.2,"end":0.6}]')
        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        media = self.inspect()
        self.assertEqual([s["codec_type"] for s in media["streams"]], ["video"])
        self.assertAlmostEqual(float(media["format"]["duration"]), 0.4, delta=0.05)

    def test_single_frame_ranges_keep_duration_and_discard_source_chapters(self):
        chapter = self.source.with_suffix(".ffmetadata")
        chapter.write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Source\n")
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x48:r=5:d=2",
            "-i", str(chapter), "-map", "0:v", "-map_chapters", "1", "-c:v", "libx264", str(self.source),
        ], check=True)
        self.cuts.write_text('[{"start":0,"end":0.2},{"start":1,"end":1.2},{"start":0.2,"end":0.4}]')

        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        media = self.inspect()
        self.assertEqual([s["codec_type"] for s in media["streams"]], ["video"])
        self.assertEqual(int(media["streams"][0]["nb_frames"]), 3)
        self.assertAlmostEqual(float(media["format"]["duration"]), 0.6, delta=0.001)
        self.assertEqual(media["chapters"], [])

    def test_rejects_a_range_without_a_video_frame(self):
        self.make_source(audio=True)
        original = self.source.read_bytes()
        visible = {"start": 1, "end": 1.2}
        empty = {"start": 0.001, "end": 0.01}
        for cuts in ([empty], [empty, visible], [visible, empty], [visible, empty, visible]):
            with self.subTest(cuts=cuts):
                self.cuts.write_text(json.dumps(cuts))
                edit = self.edit()
                self.assertNotEqual(edit.returncode, 0)
                # Some FFmpeg versions fail at the encoder before writing an entirely empty video.
                if len(cuts) > 1:
                    self.assertIn(f"Range {cuts.index(empty) + 1} contains no video frame", edit.stderr)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.source.read_bytes(), original)

    def test_non_frame_aligned_ranges_on_a_fractional_timeline(self):
        self.make_source(audio=False)
        cuts = [{"start": 1.017, "end": 1.085123}, {"start": 0.003, "end": 0.058}]
        self.cuts.write_text(json.dumps(cuts))
        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        media = self.inspect()
        self.assertEqual(int(media["streams"][0]["nb_frames"]), 3)
        self.assertAlmostEqual(float(media["format"]["duration"]), 0.123123, delta=0.001)


    def test_retimes_existing_captions_across_reordered_and_repeated_cuts(self):
        self.make_source(audio=True)
        self.cuts.write_text('[{"start":1.2,"end":1.8},{"start":0.2,"end":0.8},{"start":1.2,"end":1.8}]')
        source_srt = self.source.with_suffix(".srt")
        output_srt = self.output.with_suffix(".srt")
        original = (
            "10\r\n00:00:00,000 --> 00:00:00,400\r\nRouge\r\n\r\n"
            "11\r\n00:00:00,850 --> 00:00:01,050\r\nRemoved\r\n\r\n"
            "12\r\n00:00:01,100 --> 00:00:01,500\r\nBleu\r\n字幕\r\n\r\n"
            "13\r\n00:00:01,700 --> 00:00:01,900\r\nFin\r\n"
        ).encode("utf-8-sig")
        source_srt.write_bytes(original)

        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        result = self.retime(source_srt, output_srt)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            output_srt.read_text(encoding="utf-8"),
            "1\n00:00:00,000 --> 00:00:00,300\nBleu\n字幕\n\n"
            "2\n00:00:00,500 --> 00:00:00,600\nFin\n\n"
            "3\n00:00:00,600 --> 00:00:00,800\nRouge\n\n"
            "4\n00:00:01,200 --> 00:00:01,500\nBleu\n字幕\n\n"
            "5\n00:00:01,700 --> 00:00:01,800\nFin\n",
        )
        self.assertGreater(self.frame_color(0.1)[2], 200)
        self.assertGreater(self.frame_color(0.7)[0], 200)
        self.assertGreater(self.frame_color(1.3)[2], 200)
        self.assertEqual(source_srt.read_bytes(), original)

        exported = output_srt.read_bytes()
        self.assertNotEqual(self.retime(source_srt, output_srt).returncode, 0)
        self.assertEqual(output_srt.read_bytes(), exported)
        self.assertNotEqual(self.retime(source_srt, source_srt).returncode, 0)
        self.assertEqual(source_srt.read_bytes(), original)

    def test_rejects_invalid_srt_and_drops_cues_with_zero_rounded_duration(self):
        self.make_source(audio=False)
        self.cuts.write_text('[{"start":0,"end":0.0005},{"start":1,"end":1.0395}]')
        source_srt = self.source.with_suffix(".srt")
        output_srt = self.output.with_suffix(".srt")
        source_srt.write_text("1\n00:00:00,001 --> 00:00:00,000\nReversed\n")
        bad = self.retime(source_srt, output_srt)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("SRT cue 1", bad.stderr)
        self.assertFalse(output_srt.exists())

        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:00,001\nToo short\n\n"
            "2\n00:00:01,000 --> 00:00:01,041\nSingle frame\n"
        )
        edit = self.edit()
        self.assertEqual(edit.returncode, 0, edit.stderr)
        self.assertEqual(int(self.inspect()["streams"][0]["nb_frames"]), 2)
        result = self.retime(source_srt, output_srt)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output_srt.read_text(), "1\n00:00:00,000 --> 00:00:00,040\nSingle frame\n")

    def detect_silence(self, source, *options):
        return subprocess.run(
            [sys.executable, str(SILENCE_DETECTOR), str(source), *options],
            capture_output=True, text=True,
        )

    def test_detects_silence_on_the_source_timeline(self):
        self.source = self.source.with_suffix(".mov")
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x48:r=25:d=2.4",
            "-f", "lavfi", "-i",
            "aevalsrc='0.25*sin(2*PI*440*t)*(between(t,0.4,0.7)+between(t,1.3,1.7))':s=48000:d=1.9",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-c:a", "pcm_s16le", str(self.source),
        ], check=True)
        original = self.source.read_bytes()
        result = self.detect_silence(self.source, "--min-duration", "0.3")
        self.assertEqual(result.returncode, 0, result.stderr)
        ranges = json.loads(result.stdout)["silence"]
        self.assertEqual(len(ranges), 3)
        for cut, (start, end) in zip(ranges, [(0, 0.4), (0.7, 1.3), (1.7, 2.4)]):
            self.assertAlmostEqual(cut["start"], start, delta=0.002)
            self.assertAlmostEqual(cut["end"], end, delta=0.002)
        self.assertEqual(self.source.read_bytes(), original)

    def test_silence_scan_handles_short_media_and_invalid_inputs(self):
        self.make_source(audio=True)
        self.cuts.write_text('[{"start":0.2,"end":0.28}]')
        result = self.edit()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.detect_silence(self.output, "--min-duration", "0.02")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"silence": []})

        bad = self.detect_silence(self.output, "--noise-db", "inf")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--noise-db must be", bad.stderr)
        bad = self.detect_silence(self.output, "--min-duration", "0")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--min-duration must be", bad.stderr)

        self.source.unlink()
        self.make_source(audio=False)
        bad = self.detect_silence(self.source)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("needs an audio track", bad.stderr)
        self.assertEqual(bad.stdout, "")
