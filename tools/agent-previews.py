"""Render real caption animations as site MP4s/posters and GitHub animated WebPs."""
import argparse
import subprocess
from pathlib import Path
from PIL import Image
from justcaptions import styles
from justcaptions.grouping import Word, group_words
from justcaptions.render import Renderer

parser = argparse.ArgumentParser()
parser.add_argument('--site', type=Path, required=True)
args = parser.parse_args()
folder = args.site / 'assets/agent-styles'
folder.mkdir(parents=True, exist_ok=True)
docs = Path(__file__).resolve().parents[1] / 'docs/styles'
width, height, fps, duration = 360, 480, 12, 6
words = [Word(text, start, end) for text, start, end in [
    ('Make', 0, .8), ('great', .8, 1.7), ('videos', 1.7, 2.7),
    ('Tell', 3, 3.8), ('your', 3.8, 4.7), ('story', 4.7, 5.7)]]
for row in styles.catalog()['styles']:
    style = styles.resolve(row['id'])
    captions = group_words(words, max_words=style.max_words)
    for caption in captions:
        caption.emoji = '✨'
    renderer = Renderer(width, height, style, 'large', .63, 'tiktok')
    spans = [(caption, renderer.states(caption)) for caption in captions]
    frames = []
    for tick in range(fps * duration):
        time = tick / fps
        frame = Image.new('RGBA', (width, height), (43, 48, 60, 255))
        for caption, states in spans:
            if caption.start <= time < caption.end:
                active = next(state for start, end, state in states if start <= time < end)
                frame.alpha_composite(renderer.frame(caption, active))
                break
        frames.append(frame.convert('RGB'))
    # The midpoint of the first phrase is a useful non-blank loading poster.
    frames[fps].save(folder / f'{row["id"]}.webp', quality=86)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24',
        '-video_size', f'{width}x{height}', '-framerate', str(fps), '-i', '-', '-an',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(folder / f'{row["id"]}.mp4')],
        input=b''.join(frame.tobytes() for frame in frames), check=True)
    small = [frame.resize((216, 288), Image.Resampling.LANCZOS) for frame in frames]
    small[0].save(docs / f'{row["id"]}.webp', save_all=True, append_images=small[1:],
        duration=round(1000 / fps), loop=0, quality=82)
    print(row['id'], row['animation'], flush=True)
