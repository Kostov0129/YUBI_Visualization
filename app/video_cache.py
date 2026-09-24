"""On-demand, read-only remote video extraction; cache only on this computer."""
import base64,json,pathlib,shlex,subprocess,threading,concurrent.futures,time
P=pathlib.Path(__file__).resolve().parent
CONFIG={};META={};CACHE=P/'.cache/videos'
POOL=concurrent.futures.ThreadPoolExecutor(max_workers=1);LOCK=threading.Lock();JOBS={}
def configure(config,data_root):
 global CONFIG,META,CACHE
 CONFIG=config;raw=json.loads(pathlib.Path(config.get('metadata_path') or data_root/'episode_metadata.json').read_text());cols=raw['columns']
 META={row[cols.index('episode_index')]:dict(zip(cols,row)) for row in raw['rows']}
 CACHE=pathlib.Path(config.get('video_cache') or P/'.cache/videos').expanduser().resolve();CACHE.mkdir(parents=True,exist_ok=True)
REMOTE=r'''
import av,io,json,sys,base64
from fractions import Fraction
spec=json.loads(base64.b64decode(SPEC))
for view,segments in spec.items():
 try:
  buff=io.BytesIO();out=av.open(buff,'w',format='mp4');enc=out.add_stream('libx264',rate=30);enc.width=640;enc.height=480;enc.pix_fmt='yuv420p';enc.options={'preset':'veryfast','crf':'23','threads':'1','g':'30'};count=0
  for seg in segments:
   source=av.open(str(__import__('pathlib').Path(DATASET_ROOT)/seg['path']));stream=source.streams.video[0];stream.thread_type='NONE';stream.codec_context.thread_count=1
   source.seek(max(0,int((seg['start']-.1)/float(stream.time_base))),stream=stream,backward=True,any_frame=False);found=0
   for f in source.decode(stream):
    if f.time is None or f.time < seg['start']-1/60:continue
    if found==0 and abs(f.time-seg['start'])>1/30:raise ValueError('video start timestamp mismatch')
    f=f.reformat(width=640,height=480,format='yuv420p');f.pts=count;f.time_base=Fraction(1,30)
    for pkt in enc.encode(f):out.mux(pkt)
    count+=1;found+=1
    if found==seg['frames']:break
   source.close()
   if found!=seg['frames']:raise ValueError('video frame count mismatch')
  for pkt in enc.encode():out.mux(pkt)
  out.close();b=buff.getvalue();sys.stdout.buffer.write((json.dumps({'view':view,'size':len(b),'frames':count})+'\n').encode());sys.stdout.buffer.write(b);sys.stdout.buffer.flush()
 except Exception as e:
  sys.stdout.buffer.write((json.dumps({'view':view,'error':str(e)})+'\n').encode());sys.stdout.buffer.flush()
'''
def spec_for(group):
 out={}
 for view in ['left','right','center']:
  rows=[];prefix='videos/observation.image.'+view+'/'
  for lo,hi,ep,_ in group['chunks']:
   m=META[ep];assert hi-lo==m['length']
   rows.append({'path':f"videos/observation.image.{view}/chunk-{int(m[prefix+'chunk_index']):03d}/file-{int(m[prefix+'file_index']):03d}.mp4",'start':m[prefix+'from_timestamp'],'frames':hi-lo,'episode':ep})
  out[view]=rows
 return out

def command(code):
 import sys
 bootstrap='import base64;exec(base64.b64decode('+repr(base64.b64encode(code.encode()).decode())+'))'
 if not CONFIG.get('ssh_host'):return [sys.executable,'-c',bootstrap]
 py=CONFIG.get('remote_python','python3')
 inner='PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 nice -n 10 '+shlex.quote(py)+' -c '+shlex.quote(bootstrap)
 for hop in reversed(CONFIG.get('ssh_hops',[])):
  inner='ssh -T -o RemoteCommand=none -o RequestTTY=no -o BatchMode=yes -o ConnectTimeout=15 '+shlex.quote(hop)+' '+shlex.quote(inner)
 args=['ssh','-T','-o','RemoteCommand=none','-o','RequestTTY=no','-o','BatchMode=yes','-o','ConnectTimeout=15']
 if CONFIG.get('ssh_control_path'):args+=['-S',str(pathlib.Path(CONFIG['ssh_control_path']).expanduser())]
 if CONFIG.get('ssh_transport')=='tailscale':
  return ['tailscale','ssh',CONFIG['ssh_host']]+args[1:]+[inner]
 return args+[CONFIG['ssh_host'],inner]

def run(group):
 uid=group['uuid'];folder=CACHE/uid;folder.mkdir(exist_ok=True)
 try:
  spec=spec_for(group);(folder/'source.json').write_text(json.dumps(spec,indent=2))
  missing={v:s for v,s in spec.items() if not (folder/(v+'.mp4')).exists()}
  code='DATASET_ROOT='+repr(CONFIG.get('dataset_root',''))+'\nSPEC='+repr(base64.b64encode(json.dumps(missing).encode()).decode())+'\n'+REMOTE
  with (folder/'transfer.log').open('wb') as err:
   proc=subprocess.Popen(command(code),stdout=subprocess.PIPE,stderr=err)
   watchdog=threading.Timer(240,proc.kill);watchdog.start()
   try:
    for _ in missing:
     line=proc.stdout.readline()
     if not line:raise RuntimeError('视频连接中断，请重新连接视频服务器')
     header=json.loads(line);view=header['view'];assert view in missing
     if 'error' in header:raise RuntimeError(view+': '+header['error'])
     assert header['frames']==group['frames'];remaining=header['size'];assert 0<remaining<512*1024*1024
     target=folder/(view+'.part')
     with target.open('wb') as f:
      while remaining:
       b=proc.stdout.read(min(65536,remaining))
       if not b:raise RuntimeError('视频传输不完整')
       f.write(b);remaining-=len(b)
     target.replace(folder/(view+'.mp4'))
    if proc.wait(timeout=30)!=0:raise RuntimeError('视频传输失败')
   finally:
    watchdog.cancel();proc.stdout.close()
    if proc.poll() is None:proc.kill();proc.wait()
  with LOCK:JOBS[uid]={'state':'ready'}
 except Exception as e:
  with LOCK:JOBS[uid]={'state':'error','error':str(e)}

def status(group):
 uid=group['uuid'];folder=CACHE/uid
 with LOCK:
  all_ready=all((folder/(v+'.mp4')).exists() for v in ['left','right','center'])
  if all_ready:JOBS[uid]={'state':'ready'}
  elif uid not in JOBS:JOBS[uid]={'state':'loading'};POOL.submit(run,group)
  out=dict(JOBS[uid])
 out['videos']={v:f'/video-cache/{uid}/{v}.mp4' for v in ['left','right','center'] if (folder/(v+'.mp4')).exists()};return out
