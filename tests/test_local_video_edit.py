import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


EDITOR = Path(__file__).resolve().parents[1] / "skills/local-video-edit/scripts/edit.py"


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

    def inspect(self):
        return json.loads(subprocess.check_output(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration:stream=codec_type,nb_frames:chapter=start_time",
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
        self.assertAlmostEqual(float(media["format"]["duration"]), 1.8, delta=0.05)
        self.assertGreater(self.frame_color(0.2)[2], 200)
        self.assertGreater(self.frame_color(0.8)[0], 200)
        self.assertGreater(self.frame_color(1.4)[2], 200)
        self.assertEqual(self.source.read_bytes(), original)

        exported = self.output.read_bytes()
        self.assertNotEqual(self.edit().returncode, 0)
        self.assertEqual(self.output.read_bytes(), exported)

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
