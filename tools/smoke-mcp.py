"""Exercise the installed local MCP over stdio with synthetic media; no API key required."""
import asyncio,json,subprocess,sys,tempfile,os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
work=tempfile.TemporaryDirectory(prefix='justcaptions-mcp-')
out=Path(work.name)
video=out/'source.mp4';subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=0x2b303c:s=540x960:d=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
cap=out/'input.json';cap.write_text(json.dumps({'language':'en','segments':[{'start':0,'end':2.5,'text':'Make great videos'}],'words':[{'word':'Make','start':0,'end':.5},{'word':'great','start':.5,'end':1.2},{'word':'videos','start':1.2,'end':2.5}]}))
async def main():
 env=dict(os.environ);env['JUSTCAPTIONS_API_KEY']=''
 # Synthetic captions avoid recognition and network access.
 params=StdioServerParameters(command=sys.executable,args=['-m','justcaptions.mcp_server'],env=env)
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as session:
   await session.initialize();listed=await session.list_tools();print('tools', [x.name for x in listed.tools])
   for name in ['check_environment','list_styles']:
    res=await session.call_tool(name,{});assert not res.isError;print(name,'OK')
   res=await session.call_tool('preview_style',{'style_id':'highlight-box'});assert not res.isError;assert any(x.type=='image' for x in res.content);print('preview_style OK')
   for style in ['word-highlight','reveal','pop-in','typewriter','impact','neon','white-box','gray-box','yellow-outline','cinematic','editorial']:
    result=await session.call_tool('caption_video',{'input_path':str(video),'captions_path':str(cap),'output_dir':str(out/style),'style_id':style,'overwrite':True})
    assert not result.isError,result
    result=result.structuredContent;job=result['job_id']
    for _ in range(120):
     await asyncio.sleep(.25);res=await session.call_tool('get_job',{'job_id':job});state=res.structuredContent
     if state['status'] in ['completed','failed']:break
    assert state['status']=='completed',state
    print(style,'completed',state['results'][0]['media_verified'])
   print('MCP end-to-end OK')
asyncio.run(main())

work.cleanup()
