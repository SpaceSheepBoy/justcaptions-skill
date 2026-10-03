import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/justcaptions/scripts'))
from justcaptions import jobs, execution, api, cli, media
from justcaptions.grouping import Word

class JobsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'JUSTCAPTIONS_STATE_DIR':self.temp.name});self.env.start()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def row(self,identity):
        return {'job_id':identity,'status':'queued','stage':'queued','results':[],'total':1,'finished':0}
    def test_cross_process_cancel_and_durable_orphan_recovery(self):
        identity='a'*32
        code="from justcaptions import jobs; jobs.claim("+repr(self.row(identity))+")"
        subprocess.run([sys.executable,'-c',code],check=True,env={**os.environ,'PYTHONPATH':str(Path(jobs.__file__).parents[1])})
        self.assertEqual(jobs.get(identity)['status'],'interrupted')
        row=jobs.get(identity);jobs.claim(row,resume=True)
        subprocess.run([sys.executable,'-c',"from justcaptions import jobs;jobs.cancel('"+identity+"')"],check=True,env={**os.environ,'PYTHONPATH':str(Path(jobs.__file__).parents[1])})
        self.assertTrue(jobs.cancelled(identity))
        row.update(status='running');jobs.save(row)
        self.assertEqual(jobs.get(identity)['status'],'cancel_requested')
    def test_concurrency_claims_and_completed_state_survive_reconnection(self):
        jobs.claim(self.row('a'));jobs.claim(self.row('b'))
        with self.assertRaisesRegex(ValueError,'Two jobs'):jobs.claim(self.row('c'))
        row=jobs.get('a');row.update(status='completed');jobs.save(row)
        jobs.claim(self.row('c'))
        self.assertEqual(len(jobs.list_all()),3)
        self.assertEqual((jobs.directory()/'jobs.sqlite3').stat().st_mode&0o777,0o600)
    def test_cloud_checkpoint_reuses_response_and_uncertain_request_identity(self):
        work=Path(self.temp.name)/'work';token=execution.context.set({'work':work,'cancelled':lambda:False})
        ids=[]
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def send(request,**kwargs):
            ids.append(request.get_header('Idempotency-key'));return Response(b'{"captions":["hello"]}')
        try:
            with patch.dict(os.environ,{'JUSTCAPTIONS_API_KEY':'private-test-key'}),patch('urllib.request.urlopen',side_effect=send):
                self.assertEqual(api.correct(['hi']),['hello']);self.assertEqual(api.correct(['hi']),['hello'])
            self.assertEqual(len(ids),1)
            ledger=next((work/'requests').glob('*.json'));data=json.loads(ledger.read_text());self.assertNotIn('private-test-key',ledger.read_text())
            del data['response'];execution.atomic_json(ledger,data)
            with patch.dict(os.environ,{'JUSTCAPTIONS_API_KEY':'private-test-key'}),patch('urllib.request.urlopen',side_effect=send):api.correct(['hi'])
            self.assertEqual(ids[0],ids[1])
        finally:execution.context.reset(token)
    def test_old_uncertain_request_is_not_rebilled(self):
        work=Path(self.temp.name)/'work';token=execution.context.set({'work':work,'cancelled':lambda:False})
        try:
            with patch.dict(os.environ,{'JUSTCAPTIONS_API_KEY':'key'}),patch('urllib.request.urlopen',side_effect=api.urllib.error.URLError('offline')),patch('time.sleep'):
                with self.assertRaises(api.APIError):api.correct(['hi'])
            ledger=next((work/'requests').glob('*.json'));data=json.loads(ledger.read_text());data['started']=0;execution.atomic_json(ledger,data)
            with patch('urllib.request.urlopen') as send:
                with self.assertRaisesRegex(api.APIError,'too old'):api.correct(['hi'])
                send.assert_not_called()
        finally:execution.context.reset(token)
    def test_cancelled_render_resumes_from_cached_transcript(self):
        work=Path(self.temp.name)/'work';source=Path(self.temp.name)/'clip.mp4';source.write_bytes(b'fixture');out=Path(self.temp.name)/'out';out.mkdir()
        flag=[False];token=execution.context.set({'work':work,'cancelled':lambda:flag[0]})
        args=cli.parse_args(['--burn','--formats','srt,json']);args.progress=lambda stage:flag.__setitem__(0,True) if stage=='rendering' else None
        recognize=lambda *a,**k:([Word('Hello',0,1)],'en')
        try:
            with patch.object(media,'video_info',return_value=(360,480,2,'')),patch('justcaptions.cli.transcribe',side_effect=recognize) as transcription:
                with self.assertRaises(execution.JobCancelled):cli.caption_video(source,args,out)
                self.assertEqual(list(out.iterdir()),[])
                flag[0]=False;args.burn=False;args.progress=lambda stage:None
                outputs=cli.caption_video(source,args,out)
                self.assertEqual(transcription.call_count,1);self.assertEqual(len(outputs),2)
                outputs[0].write_text('user changed this')
                with self.assertRaisesRegex(RuntimeError,'already exists'):cli.caption_video(source,args,out)
        finally:execution.context.reset(token)
    def test_audio_checkpoint_retains_exact_request_bytes(self):
        from justcaptions.transcribe import _extract
        work=Path(self.temp.name);token=execution.context.set({'work':work,'cancelled':lambda:False})
        def extract(source,destination,**kwargs):destination.write_bytes(b'exact encoded audio');return destination
        try:
            with patch.object(media,'extract_audio',side_effect=extract) as call:
                first=_extract(work/'video.mp4',work/'audio.m4a');second=_extract(work/'video.mp4',work/'audio.m4a')
                self.assertEqual(call.call_count,1);self.assertEqual(first.read_bytes(),second.read_bytes())
                second.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'Cached audio was changed'):_extract(work/'video.mp4',work/'audio.m4a')
        finally:execution.context.reset(token)
    def test_cancel_terminates_owned_process(self):
        import time
        start=time.monotonic();token=execution.context.set({'work':Path(self.temp.name),'cancelled':lambda:time.monotonic()-start>.3})
        try:
            with self.assertRaises(execution.JobCancelled):media.run([sys.executable,'-c','import time;time.sleep(30)'])
            self.assertLess(time.monotonic()-start,3)
        finally:execution.context.reset(token)

if __name__=='__main__':unittest.main()
