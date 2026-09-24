"""Local HTTP application. Serve public assets and named cached videos only."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
import argparse,json,gzip,re,functools
from storage import Dataset
import video_cache
ROOT=Path(__file__).resolve().parent;PUBLIC=ROOT/'public'

def load_config(path):
 p=Path(path).expanduser().resolve();config=json.loads(p.read_text())
 for key in ['data_root','metadata_path','video_cache','ssh_control_path']:
  if config.get(key):
   v=Path(config[key]).expanduser();config[key]=str(v.resolve() if v.is_absolute() else (p.parent/v).resolve())
 if not config.get('data_root'):raise ValueError('config requires data_root')
 if not config.get('ssh_host') and config.get('dataset_root'):
  v=Path(config['dataset_root']).expanduser();config['dataset_root']=str(v.resolve() if v.is_absolute() else (p.parent/v).resolve())
 return config

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,dataset,**kwargs):self.dataset=dataset;super().__init__(*args,directory=str(PUBLIC),**kwargs)
 def do_GET(self):
  u=urlparse(self.path)
  if not u.path.startswith('/api/'):return super().do_GET()
  try:
   if u.path=='/api/config':v={'modes':self.dataset.modes()}
   elif u.path=='/api/catalog':v=self.dataset.catalog()
   elif u.path=='/api/data':
    p=parse_qs(u.query);v=self.dataset.data(p['uuid'][0],p.get('mode',['raw'])[0])
   elif u.path=='/api/videos':
    p=parse_qs(u.query);uid=p['uuid'][0];g=self.dataset.index[uid]
    if p.get('retry')==['1']:
     with video_cache.LOCK:
      if video_cache.JOBS.get(uid,{}).get('state')=='error':video_cache.JOBS.pop(uid,None)
    v=video_cache.status(g)
   else:self.send_error(404);return
   b=gzip.compress(json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode());self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Encoding','gzip');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  except (BrokenPipeError,ConnectionResetError):pass
  except (KeyError,ValueError):self.send_error(400,'Invalid request or unavailable record')
  except Exception:self.send_error(500,'Data unavailable; check configured data files')
 def list_directory(self,path):self.send_error(403);return None
 def send_head(self):
  path=unquote(urlparse(self.path).path)
  if not path.startswith('/video-cache/'):
   target=Path(self.translate_path(self.path)).resolve()
   try:target.relative_to(PUBLIC.resolve())
   except ValueError:self.send_error(403);return None
   return super().send_head()
  match=re.fullmatch(r'/video-cache/([a-zA-Z0-9_-]+)/(left|right|center)\.mp4',path)
  if not match or match[1] not in self.dataset.index:self.send_error(404);return None
  target=(video_cache.CACHE/match[1]/(match[2]+'.mp4')).resolve()
  try:target.relative_to(video_cache.CACHE.resolve())
  except ValueError:self.send_error(403);return None
  if not target.is_file():self.send_error(404);return None
  size=target.stat().st_size;start=0;end=size-1;header=self.headers.get('Range');partial=False
  if header:
   m=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
   if not m or not any(m.groups()):self.send_error(416);return None
   lo,hi=m.groups();start=int(lo) if lo else max(0,size-int(hi));end=min(int(hi),size-1) if lo and hi else size-1
   if start>end or start>=size:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return None
   partial=True
  self.send_response(206 if partial else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
  if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  self.end_headers();f=target.open('rb');f.seek(start);self._remaining=end-start+1;return f
 def copyfile(self,source,output):
  if not hasattr(self,'_remaining'):return super().copyfile(source,output)
  remaining=self._remaining;del self._remaining
  try:
   while remaining:
    b=source.read(min(65536,remaining))
    if not b:break
    output.write(b);remaining-=len(b)
  except (BrokenPipeError,ConnectionResetError):pass
 def log_message(self,*args):pass

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',default='config.local.json');p.add_argument('--host');p.add_argument('--port',type=int);a=p.parse_args();config=load_config(a.config);dataset=Dataset(config['data_root']);video_cache.configure(config,dataset.root)
 host=a.host or config.get('host','127.0.0.1');port=a.port or config.get('port',8768)
 print(f'YUBI viewer: http://{host}:{port}',flush=True);ThreadingHTTPServer((host,port),functools.partial(Handler,dataset=dataset)).serve_forever()
if __name__=='__main__':main()
