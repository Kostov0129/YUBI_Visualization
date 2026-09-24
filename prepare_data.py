"""Read a local LeRobot v3 dataset into a small, private trajectory cache."""
import argparse, json, re, tempfile, shutil
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

TASKS = {'Place the cup on the plate, then put it back to its original position': 'cup',
         'Pack Smartphone into Box': 'phone'}
POSES = ['observation.pose.left_hand_root.absolute', 'observation.pose.right_hand_root.absolute']

def prepare(dataset, output):
    dataset, output = Path(dataset), Path(output)
    if output.exists():
        raise ValueError('Output must be a new directory; existing data is never overwritten')
    info = json.loads((dataset/'meta/info.json').read_text())
    if info['fps'] != 30:
        raise ValueError('This viewer currently requires a 30 FPS dataset')
    metadata = []
    for path in sorted((dataset/'meta/episodes').rglob('*.parquet')):
        for m in pq.read_table(path).to_pylist():
            tasks = m.get('short_horizon_task', [])
            if isinstance(tasks, str): tasks = [tasks]
            selected = [TASKS[t] for t in tasks if t in TASKS]
            if selected:
                if len(set(selected)) != 1: raise ValueError('Ambiguous task')
                m['_task'] = selected[0]; metadata.append(m)
    if not metadata: raise ValueError('Neither supported task was found')
    metadata.sort(key=lambda m: int(m['episode_index']))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.yubi-import-', dir=output.parent))
    try:
        arrays, angles, seen, offsets, counts = {}, {}, {}, {}, {}
        for m in metadata:
            ep, task = int(m['episode_index']), m['_task']
            if ep in offsets: raise ValueError('Duplicate episode metadata')
            n = int(m['length'])
            if n <= 0: raise ValueError('Empty episode')
            offsets[ep] = (task, counts.get(task, 0), n)
            counts[task] = counts.get(task, 0) + n
        for task, count in counts.items():
            name = 'smartphone' if task == 'phone' else task
            arrays[task] = np.lib.format.open_memmap(staging/(name+'_poses.npy'), mode='w+', dtype='float64', shape=(count,16))
            angles[task] = np.lib.format.open_memmap(staging/(name+'_angles.npy'), mode='w+', dtype='float64', shape=(count,2))
            seen[task] = np.zeros(count, dtype=bool)
        columns = ['episode_index','frame_index',*POSES,'observation.joint_states']
        for path in sorted((dataset/'data').rglob('*.parquet')):
            for batch in pq.ParquetFile(path).iter_batches(batch_size=32768, columns=columns):
                values = batch.to_pydict(); eps = np.asarray(values['episode_index']); frames = np.asarray(values['frame_index'])
                for ep in np.unique(eps):
                    if ep not in offsets: continue
                    task, start, length = offsets[ep]; mask = eps == ep; fi = frames[mask].astype(int); idx = start+fi
                    if np.any(fi<0) or np.any(fi>=length) or len(np.unique(fi))!=len(fi) or np.any(seen[task][idx]):
                        raise ValueError(f'Duplicate or invalid frames in episode {ep}')
                    rows = np.flatnonzero(mask)
                    lp = np.asarray([values[POSES[0]][i] for i in rows]); rp = np.asarray([values[POSES[1]][i] for i in rows])
                    joints = np.asarray([values['observation.joint_states'][i] for i in rows])
                    if lp.shape != (len(rows),7) or rp.shape != lp.shape or joints.shape != (len(rows),2):
                        raise ValueError('Unexpected pose or gripper schema')
                    if not all(np.isfinite(v).all() for v in [lp,rp,joints]) or np.any(np.linalg.norm(lp[:,3:],axis=1)<1e-8) or np.any(np.linalg.norm(rp[:,3:],axis=1)<1e-8):
                        raise ValueError(f'Invalid pose in episode {ep}')
                    arrays[task][idx] = np.column_stack([eps[mask],fi,lp,rp]); angles[task][idx] = joints; seen[task][idx] = True
        if not all(s.all() for s in seen.values()): raise ValueError('Missing frames in selected episodes')
        groups = {}
        for m in metadata:
            ep = int(m['episode_index']); task, start, n = offsets[ep]; uid = str(m['uuid'])
            if not re.fullmatch(r'[a-zA-Z0-9_-]+',uid): raise ValueError('Invalid recording UUID')
            suffix = re.search(r'(\d+)$',str(m['episode_id']))
            if suffix is None: raise ValueError('Missing PA order in episode_id')
            g = groups.setdefault(uid,dict(task=task,uuid=uid,chunks=[],frames=0))
            if g['task']!=task: raise ValueError('Recording spans multiple tasks')
            g['chunks'].append([start,start+n,ep,int(suffix[1])]); g['frames'] += n
        for g in groups.values(): g['chunks'].sort(key=lambda c:c[3])
        for a in [*arrays.values(),*angles.values()]: a.flush()
        (staging/'groups.json').write_text(json.dumps(list(groups.values()),ensure_ascii=False))
        cols = sorted(set().union(*(m.keys() for m in metadata))-{'_task'})
        (staging/'episode_metadata.json').write_text(json.dumps({'columns':cols,'rows':[[m.get(c) for c in cols] for m in metadata]},ensure_ascii=False))
        manifest = dict(recordings=len(groups),episodes=len(metadata),frames=counts,fps=30)
        (staging/'cache_manifest.json').write_text(json.dumps(manifest,indent=2))
        staging.rename(output); return manifest
    except BaseException:
        shutil.rmtree(staging); raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--output',default='data');a=p.parse_args()
    print(json.dumps(prepare(a.dataset,a.output),indent=2))
