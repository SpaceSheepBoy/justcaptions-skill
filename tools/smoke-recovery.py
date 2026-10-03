"""Exercise real MCP cancellation, process death, saved-job discovery and resume."""
import asyncio
import os
import signal
import sqlite3
import sys
import tempfile
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
 with tempfile.TemporaryDirectory(prefix='jc-recovery-') as directory:
  root=Path(directory);env={**os.environ,'JUSTCAPTIONS_STATE_DIR':str(root/'state'),'JUSTCAPTIONS_API_KEY':''};env.pop('JUSTCAPTIONS_METRICS_ID',None)
  params=StdioServerParameters(command=sys.executable,args=['-m','justcaptions.mcp_server'],env=env)
  async def poll(session,identity,terminal=True):
   for _ in range(1000):
    state=(await session.call_tool('get_job',{'job_id':identity})).structuredContent
    if terminal and state['status'] in ('completed','failed','cancelled'):return state
    if not terminal and state['stage']=='rendering':return state
    await asyncio.sleep(.02)
   raise AssertionError('Job did not reach expected state')
  identity=None;killed=False
  try:
   async with stdio_client(params) as streams:
    async with ClientSession(*streams) as session:
     await session.initialize()
     reply=await session.call_tool('run_demo',{'output_dir':str(root/'out'),'style_id':'emoji'});assert not reply.isError,reply;identity=reply.structuredContent['job_id']
     await poll(session,identity,False)
     await session.call_tool('cancel_job',{'job_id':identity})
     assert (await poll(session,identity))['status']=='cancelled'
     assert not list((root/'out').glob('*.mp4'))
     await session.call_tool('resume_job',{'job_id':identity});await poll(session,identity,False)
     with sqlite3.connect(root/'state/jobs.sqlite3') as db:pid=db.execute('SELECT pid FROM jobs WHERE id=?',(identity,)).fetchone()[0]
     killed=True;os.kill(pid,signal.SIGKILL)
     await asyncio.sleep(.1)
  except BaseException:
   if not killed:raise
  async with stdio_client(params) as streams:
   async with ClientSession(*streams) as session:
    await session.initialize();listing=(await session.call_tool('list_jobs',{})).structuredContent
    assert listing['jobs'][0]['job_id']==identity and listing['jobs'][0]['status']=='interrupted',listing
    resumed=await session.call_tool('resume_job',{'job_id':identity});assert not resumed.isError,resumed
    state=await poll(session,identity);assert state['status']=='completed',state;assert state['results'][0]['media_verified']
    for output in state['results'][0]['outputs']:assert Path(output).is_file()
    assert len(state['results'][0]['outputs'])==4
  print('Real MCP demo, cancellation, process restart, durable discovery and verified resumed MP4: PASS')
asyncio.run(main())
