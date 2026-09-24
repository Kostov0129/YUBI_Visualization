"""Fetch only the selected recording; all persistent output stays local."""
import json, subprocess, threading, tempfile, os
from pathlib import Path
import numpy as np
import video_cache
LOCK=threading.Lock()
INDEX_CODE=r'''
import json,sys
from pathlib import Path
import pyarrow.parquet as pq
root=Path(DATASET)
if json.loads((root/'meta/info.json').read_text())['fps']!=30:raise ValueError('Expected 30 FPS')
tasks={'Place the cup on the plate, then put it back to its original position':'cup','Pack Smartphone into Box':'phone'}
base=['episode_index','uuid','episode_id','length','short_horizon_task']
video=[f'videos/observation.image.{v}/{k}' for v in ['left','right','center'] for k in ['chunk_index','file_index','from_timestamp']]
rows=[];groups={}
paths=sorted((root/'meta/episodes').rglob('*.parquet'))
for i,path in enumerate(paths):
    pf=pq.ParquetFile(path);extra=[k for k in ['data/chunk_index','data/file_index'] if k in pf.schema_arrow.names]
    for batch in pf.iter_batches(batch_size=8192,columns=base+video+extra):
        for m in batch.to_pylist():
            labels=m['short_horizon_task'];labels=[labels] if isinstance(labels,str) else labels
            matched={tasks[t] for t in labels if t in tasks}
            if not matched:continue
            if len(matched)!=1:raise ValueError('Ambiguous task')
            task=matched.pop();uid=m['uuid'];n=int(m['length'])
            if n<=0:raise ValueError('Empty episode')
            g=groups.setdefault(uid,dict(uuid=uid,task=task,chunks=[],frames=0))
            if g['task']!=task:raise ValueError('Ambiguous recording')
            g['chunks'].append([0,n,int(m['episode_index']),int(m['episode_id'].rsplit(':',1)[1])]);g['frames']+=n;rows.append(m)
    print(f'读取记录目录 {i+1}/{len(paths)}',file=sys.stderr,flush=True)
if not rows:raise ValueError('No supported records')
for g in groups.values():g['chunks'].sort(key=lambda c:c[3])
groups=sorted(groups.values(),key=lambda g:(g['task'],g['uuid']))
cols=sorted(set().union(*(m.keys() for m in rows)))
manifest={'recordings':len(groups),'episodes':len(rows),'frames':{t:sum(g['frames'] for g in groups if g['task']==t) for t in set(g['task'] for g in groups)},'fps':30,'lazy':True}
objects={'groups.json':groups,'episode_metadata.json':{'columns':cols,'rows':[[r.get(c) for c in cols] for r in rows]},'lazy.json':{'version':1},'cache_manifest.json':manifest}
for name,obj in objects.items():
    b=json.dumps(obj,ensure_ascii=False).encode();sys.stdout.buffer.write((json.dumps({'file':name,'size':len(b)})+'\n').encode());sys.stdout.buffer.write(b);sys.stdout.buffer.flush()
sys.stdout.buffer.write((json.dumps({'done':manifest})+'\n').encode());sys.stdout.buffer.flush()
'''
RECORD_CODE=r'''
import json,sys
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
root=Path(DATASET);files=sorted((root/'data').rglob('*.parquet'));lookup={str(p.relative_to(root)):i for i,p in enumerate(files)}
posekeys=['observation.pose.left_hand_root.absolute','observation.pose.right_hand_root.absolute'];cols=['episode_index','frame_index',*posekeys,'observation.joint_states'];poses=[];angles=[]
for m in EPISODES:
    ep=int(m['episode_index']);n=int(m['length']);start=0
    if m.get('data/chunk_index') is not None and m.get('data/file_index') is not None:
        name=f"data/chunk-{int(m['data/chunk_index']):03d}/file-{int(m['data/file_index']):03d}.parquet"
        start=lookup[name]
    found=[];count=0
    for path in files[start:]:
        table=pq.read_table(path,columns=cols,filters=[('episode_index','=',ep)])
        if table.num_rows:found.extend(table.to_pylist());count+=table.num_rows
        if count>=n:break
    found.sort(key=lambda r:r['frame_index'])
    if len(found)!=n or [int(r['frame_index']) for r in found]!=list(range(n)):raise ValueError('Missing or duplicate episode frames')
    for r in found:
        left=r[posekeys[0]];right=r[posekeys[1]];q=r['observation.joint_states']
        if len(left)!=7 or len(right)!=7 or len(q)!=2 or not np.isfinite(left+right+q).all():raise ValueError('Invalid pose schema')
        if np.linalg.norm(left[3:])<1e-8 or np.linalg.norm(right[3:])<1e-8:raise ValueError('Invalid rotation')
        poses.append([ep,int(r['frame_index']),*left,*right]);angles.append(q)
sys.stdout.write(json.dumps({'poses':poses,'angles':angles},allow_nan=False))
'''

def record(root,group,config,metadata):
    folder=Path(root)/'records';folder.mkdir(exist_ok=True)
    # Generated UUIDs are validated before being used as paths.
    uid=group['uuid']
    if not uid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in uid):raise ValueError('Invalid record ID')
    target=folder/(uid+'.json')
    with LOCK:
        if target.exists():data=json.loads(target.read_text())
        else:
            rows=[metadata[ep] for _,_,ep,_ in group['chunks']]
            code='DATASET='+repr(config['dataset_root'])+'\nEPISODES='+repr(rows)+'\n'+RECORD_CODE
            video_cache.CONFIG=config
            result=subprocess.run(video_cache.command(code),capture_output=True,timeout=180)
            if result.returncode:raise RuntimeError('Selected recording could not be read over SSH')
            data=json.loads(result.stdout)
            a=np.asarray(data['poses']);q=np.asarray(data['angles'])
            if a.shape!=(group['frames'],16) or q.shape!=(group['frames'],2):raise ValueError('Unexpected recording length')
            fd,name=tempfile.mkstemp(prefix='.record-',dir=folder)
            try:
                with os.fdopen(fd,'w') as f:json.dump(data,f)
                os.replace(name,target)
            finally:
                if Path(name).exists():Path(name).unlink()
    return np.asarray(data['poses']),np.asarray(data['angles'])
