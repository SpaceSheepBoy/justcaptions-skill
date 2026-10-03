"""Build a real human-narration demo from attributed LibriSpeech audio."""
import argparse
import json
import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from justcaptions import api, media, cli, formats
from justcaptions.grouping import Word, group_words

p=argparse.ArgumentParser();p.add_argument('audio',type=Path);p.add_argument('--site',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];folder=root/'skills/justcaptions/assets/demo';folder.mkdir(parents=True,exist_ok=True)
duration=float(media.probe(a.audio)['format']['duration']);w,h,fps=540,960,24
font_path=root/'skills/justcaptions/assets/fonts/Inter-Bold.ttf'
if not font_path.exists():font_path=next((root/'skills/justcaptions/assets/fonts').rglob('*.ttf'))
font=ImageFont.truetype(str(font_path),42);small=ImageFont.truetype(str(font_path),21)
proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}','-framerate',str(fps),'-i','-','-i',str(a.audio),'-c:v','libx264','-crf','23','-preset','fast','-c:a','aac','-b:a','96k','-pix_fmt','yuv420p','-shortest','-movflags','+faststart',str(folder/'story.mp4')],stdin=subprocess.PIPE)
for tick in range(math.ceil(duration*fps)):
    t=tick/fps;im=Image.new('RGB',(w,h),(24,30,43));d=ImageDraw.Draw(im)
    d.rounded_rectangle((36,40,300,80),radius=20,fill=(255,227,76));d.text((52,50),'JUST CAPTIONS',font=small,fill=(20,20,20))
    d.text((42,145),'Every word.',font=font,fill='white');d.text((42,200),'Your story.',font=font,fill='white')
    d.text((42,268),'A HUMAN VOICE. A LOCAL EXPORT.',font=small,fill=(155,167,186))
    for i in range(36):
        amplitude=12+65*abs(math.sin(i*.77+t*4))*abs(math.sin(t*2+.4))
        x=43+i*13;d.rounded_rectangle((x,475-amplitude,x+6,475+amplitude),radius=3,fill=(255,227,76) if i<18 else (105,132,177))
    d.text((42,820),'LibriSpeech / LibriVox narration',font=small,fill=(155,167,186))
    proc.stdin.write(im.tobytes())
    if tick==fps:im.save(folder/'poster.webp',quality=88)
proc.stdin.close()
if proc.wait():raise RuntimeError('Demo encoding failed')
caption_file=folder/'story.json'
if not caption_file.exists():
    audio=Path('/tmp/jc-demo.m4a');media.extract_audio(folder/'story.mp4',audio)
    result=api.transcribe(audio.read_bytes(),language='en')
    words=[Word(row['word'],row['start'],row['end']) for row in result['words']]
    caption_file.write_text(formats.to_json(group_words(words,'portrait'),result.get('language')),encoding='utf-8')
args=cli.parse_args(['--captions',str(caption_file),'--burn','--style','word-highlight','--safe-area','tiktok','--size','large','--formats','srt,vtt','--overwrite'])
cli.caption_video(folder/'story.mp4',args,folder)
subprocess.run(['ffmpeg','-y','-v','error','-ss','1.6','-i',str(folder/'story.captioned.mp4'),'-frames:v','1',str(folder/'captioned-poster.png')],check=True)
Image.open(folder/'captioned-poster.png').save(folder/'captioned-poster.webp',quality=88)
(folder/'captioned-poster.png').unlink()
(folder/'CREDITS.md').write_text('''# Demo credits\n\nHuman narration: LibriSpeech sample 1272-128104-0000, derived from public-domain LibriVox audiobooks. Dataset authors: Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur.\n\nSource: https://www.openslr.org/12/\nMirror: https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy\nLicense: Creative Commons Attribution 4.0 — https://creativecommons.org/licenses/by/4.0/\nChanges: AAC encoding, illustrated waveform video, punctuation and animated captions. The narrator does not endorse Just Captions.\n\nIllustration and generated subtitle files: Just Captions, MIT. Fonts retain their included licenses.\n''')
import shutil
site=a.site/'assets/agent-demo';site.mkdir(parents=True,exist_ok=True)
for file in folder.iterdir():shutil.copyfile(file,site/file.name)
print('Demo built:',round(duration,2),'seconds')
