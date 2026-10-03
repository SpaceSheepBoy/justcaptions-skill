import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/justcaptions/scripts'))
from justcaptions import cli, styles
from justcaptions.grouping import Caption, Word
from justcaptions.render import Renderer

class AgentTests(unittest.TestCase):
    def test_catalog_and_legacy_aliases(self):
        self.assertEqual(len(styles.catalog()['styles']), 15)
        self.assertEqual(styles.resolve('wordHighlight'), styles.resolve('word-highlight'))
        self.assertEqual(styles.resolve('karaoke').highlight_color, (255, 227, 77))
        self.assertEqual(styles.resolve('white-outline').text_color, (255, 255, 255))

    def test_overrides_validate_instead_of_silently_ignoring(self):
        self.assertEqual(styles.resolve('mega', {'highlight_color':'#123456'}).highlight_color, (18,52,86))
        for changes in [{'random':True},{'font_multiplier':0},{'uppercase':'false'},{'text_color':None},{'max_words':2.5},{'background_opacity':float('nan')}]:
            with self.assertRaises(ValueError): styles.resolve('mega', changes)

    def test_animated_states_and_safe_area_in_all_styles(self):
        caption=Caption(0,2,'Make great videos',[Word('Make',0,.6),Word('great',.6,1.3),Word('videos',1.3,2)],'✨')
        for row in styles.catalog()['styles']:
            renderer=Renderer(540,960,styles.resolve(row['id']),'large',.92,'tiktok')
            states=renderer.states(caption)
            if row['animation'] != 'none': self.assertGreater(len(states),1,row['id'])
            img=renderer.frame(caption,states[-1][2]);box=img.getbbox()
            self.assertIsNotNone(box,row['id'])
            self.assertGreaterEqual(box[1],96,row['id']);self.assertLessEqual(box[3],749,row['id'])
        renderer=Renderer(540,960,styles.resolve('reveal'))
        self.assertNotEqual(renderer.frame(caption,0).tobytes(),renderer.frame(caption,2).tobytes())

    def test_does_not_overwrite_existing_caption(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'clip.srt').write_text('preserve this')
            args=cli.parse_args([])
            with self.assertRaisesRegex(RuntimeError,'already exists'):cli.caption_video(out/'clip.mp4',args,out)
            self.assertEqual((out/'clip.srt').read_text(),'preserve this')

if __name__=='__main__':unittest.main()
