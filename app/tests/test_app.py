import functools, gzip, json, tempfile, threading, unittest, urllib.request, urllib.error
from pathlib import Path
from fractions import Fraction
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import av
from prepare_data import prepare, TASKS, POSES
from storage import Dataset
from http_server import Handler, ThreadingHTTPServer
import video_cache

class AppTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';(self.source/'meta/episodes').mkdir(parents=True);(self.source/'data').mkdir()
  (self.source/'meta/info.json').write_text('{"fps":30}')
  meta=[];rows=[]
  for ep,(uid,task,start) in enumerate([('cup-record',list(TASKS)[0],.1),('cup-record',list(TASKS)[0],.5),('phone-record',list(TASKS)[1],0)]):
   m=dict(episode_index=ep,uuid=uid,episode_id=uid+':'+str(ep),length=3,tasks=['Atomic instruction'],short_horizon_task=[task])
   for view in ['left','right','center']:
    prefix='videos/observation.image.'+view+'/'
    m.update({prefix+'chunk_index':0,prefix+'file_index':0,prefix+'from_timestamp':start,prefix+'to_timestamp':start+.1})
   meta.append(m)
   for frame in [2,0,1]:rows.append({'episode_index':ep,'frame_index':frame,POSES[0]:[frame*.01,0,0,0,0,0,1],POSES[1]:[0,0,0,0,0,0,1],'observation.joint_states':[.2,.3]})
  pq.write_table(pa.Table.from_pylist(meta),self.source/'meta/episodes/file.parquet');pq.write_table(pa.Table.from_pylist(rows),self.source/'data/file.parquet')
  self.rows=rows;self.out=self.root/'cache'
 def tearDown(self):self.tmp.cleanup()
 def test_import_and_http(self):
  result=prepare(self.source,self.out);self.assertEqual(result['recordings'],2);d=Dataset(self.out);raw=d.data('cup-record');self.assertEqual(raw['frames'],6);self.assertEqual([r[1] for r in raw['episodes']],[0,1,2,0,1,2]);self.assertEqual(len(d.modes()),1)
  video_cache.configure({'dataset_root':str(self.source),'video_cache':str(self.root/'videos')},self.out)
  folder=video_cache.CACHE/'cup-record';folder.mkdir();(folder/'left.mp4').write_bytes(b'0123456789')
  srv=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,dataset=d));thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(srv.server_port)
  try:
   with urllib.request.urlopen(base+'/api/catalog') as r:self.assertEqual(len(json.loads(gzip.decompress(r.read()))),2)
   with urllib.request.urlopen(urllib.request.Request(base+'/video-cache/cup-record/left.mp4',headers={'Range':'bytes=2-5'})) as r:self.assertEqual((r.status,r.read()),(206,b'2345'))
   for path,code in [('/config.local.json',404),('/../storage.py',404),('/video-cache/unknown/left.mp4',404)]:
    with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(base+path)
    self.assertEqual(ctx.exception.code,code)
   with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(urllib.request.Request(base+'/video-cache/cup-record/left.mp4',headers={'Range':'bytes=99-'}))
   self.assertEqual(ctx.exception.code,416)
  finally:srv.shutdown();srv.server_close();thread.join()
 def test_reject_missing_and_duplicate(self):
  for rows in [self.rows[:-1],self.rows+[self.rows[0]]]:
   pq.write_table(pa.Table.from_pylist(rows),self.source/'data/file.parquet')
   with self.assertRaises(ValueError):prepare(self.source,self.out)
   self.assertFalse(self.out.exists())
 def test_online_cache_without_remote_writes(self):
  from setup_online import download
  import hashlib
  def snapshot():return {str(p.relative_to(self.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
  before=snapshot()
  result=download({'dataset_root':str(self.source)},self.out)
  self.assertEqual(result['recordings'],2)
  self.assertEqual(Dataset(self.out).data('cup-record')['frames'],6)
  self.assertEqual(snapshot(),before)
  self.assertFalse(any(self.source.rglob('.yubi*')))
 def test_online_interruption_and_path_rejection(self):
  import io
  from setup_online import receive
  for payload in [b'{"file":"../outside","size":1}\nX',b'{"file":"cup_poses.npy","size":10}\nXX']:
   with self.assertRaises(RuntimeError):receive(io.BytesIO(payload),self.root)
 def test_video_segments(self):
  prepare(self.source,self.out);d=Dataset(self.out)
  for view in ['left','right','center']:
   p=self.source/f'videos/observation.image.{view}/chunk-000/file-000.mp4';p.parent.mkdir(parents=True)
   with av.open(str(p),'w') as out:
    enc=out.add_stream('libx264',rate=30);enc.width=64;enc.height=48;enc.pix_fmt='yuv420p'
    for i in range(30):
     f=av.VideoFrame.from_ndarray(np.full((48,64,3),i*7,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,30)
     for pkt in enc.encode(f):out.mux(pkt)
    for pkt in enc.encode():out.mux(pkt)
  video_cache.configure({'dataset_root':str(self.source),'video_cache':str(self.root/'videos')},self.out);video_cache.run(d.index['cup-record'])
  self.assertEqual(video_cache.JOBS['cup-record']['state'],'ready')
  for view in ['left','right','center']:
   with av.open(str(video_cache.CACHE/f'cup-record/{view}.mp4')) as src:frames=list(src.decode(video=0))
   self.assertEqual(len(frames),6)
   self.assertAlmostEqual(float(frames[0].to_ndarray(format='rgb24').mean()),21,delta=5)
   self.assertAlmostEqual(float(frames[3].to_ndarray(format='rgb24').mean()),105,delta=5)

if __name__=='__main__':unittest.main()
