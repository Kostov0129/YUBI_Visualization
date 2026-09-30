"""Local, resumable batch screening of cup/phone single-arm trajectories.

Run using the original IK Python environment. Outputs remain under --root.
Existing pose-only labels are never overwritten. G2 dual-arm is not included.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import os
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True)
    p.add_argument('--task',choices=['cup','phone','all'],default='all')
    p.add_argument('--limit',type=int,default=0,help='Number of recordings; 0 means all')
    p.add_argument('--starts',type=int,default=4)
    p.add_argument('--fps',type=float,default=30.)
    p.add_argument('--acceleration',type=float)
    p.add_argument('--workers',type=int,default=4,help='Independent local solver processes')
    a=p.parse_args();root=Path(a.root).resolve()
    if not 1<=a.workers<=16:raise ValueError('workers must be between 1 and 16')
    from storage import Dataset
    dataset=Dataset(root)
    groups=[g for g in dataset.groups if a.task=='all' or g['task']==a.task]
    if a.limit:groups=groups[:a.limit]
    h=hashlib.sha256()
    for path in [Path(__file__),Path(__file__).with_name('scan_ik.py'),Path(__file__).with_name('continuity.py'),
                 root/'controller.py',root/'ik_core.so',root/'models.json',root/'collision_models.json',
                 root/'fr3_limits.yaml',root/'openarm_v2.urdf',root/'incremental_start_refit/used_setup.json',
                 root/'incremental_start_refit/anchors.json']:
        h.update(path.read_bytes())
    h.update(json.dumps(dict(starts=a.starts,fps=a.fps,acceleration=a.acceleration),sort_keys=True).encode())
    # Include actual cached poses, not just file names or timestamps.
    for task in sorted(set(g['task'] for g in groups)):
        h.update(memoryview(dataset.poses[task]).cast('B'))
    signature=h.hexdigest();rows=[];started=time.time()
    out=root/'continuity_diagnostics';out.mkdir(exist_ok=True)
    report_path=out/('batch_'+a.task+'.json')
    def run_one(g,model,side):
                path=out/model/side/(g['uuid']+'.json')
                saved=json.loads(path.read_text()) if path.exists() else {}
                cached=(saved.get('batch_signature')==signature
                        and saved.get('uuid')==g['uuid'] and saved.get('frames')==g['frames'])
                error=None
                if not cached:
                    cmd=[sys.executable,str(Path(__file__).with_name('scan_ik.py')),
                         '--root',str(root),'--uuid',g['uuid'],'--model',model,'--side',side,
                         '--continuous','--starts',str(a.starts),'--fps',str(a.fps)]
                    if a.acceleration is not None:cmd+=['--acceleration',str(a.acceleration)]
                    try:
                        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
                        r=subprocess.run(cmd,capture_output=True,text=True,timeout=3600,env=env)
                        if r.returncode:raise RuntimeError(r.stderr[-1000:])
                        saved=json.loads(path.read_text());saved['batch_signature']=signature
                        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(saved,allow_nan=False));temp.replace(path)
                    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as e:error=str(e)
                row=dict(uuid=g['uuid'],task=g['task'],episodes=[c[2] for c in g['chunks']],
                         model=model,side=side,frames=g['frames'],
                         state='error' if error else 'pass' if saved['all_frames_continuous'] else 'fail',
                         failed_frames=None if error else saved['states'].count('fail'),error=error)
                return row
    def save(state):
        counts={s:sum(x['state']==s for x in rows) for s in ('pass','fail','error')}
        report=dict(reference_only=True,signature=signature,expected_checks=len(groups)*4,
                    completed_checks=len(rows),counts=counts,rows=rows,elapsed_seconds=time.time()-started,
                    state=state,updated_at=time.time(),pid=os.getpid(),workers=a.workers,
                    note='Errors are unchecked, not IK failures. Each row is one arm/recording. G2 is not included.')
        temp=report_path.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False));temp.replace(report_path)
        print(json.dumps(dict(completed=len(rows),total=len(groups)*4,**counts)),flush=True)
    save('running')
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending={pool.submit(run_one,g,m,s) for g in groups for m in ('franka_fr3','openarm_v2') for s in ('left','right')}
        last_save=time.time()
        while pending:
            done,pending=wait(pending,timeout=5,return_when=FIRST_COMPLETED)
            for f in done:rows.append(f.result())
            if time.time()-last_save>=5 or not pending:
                save('running' if pending else 'complete');last_save=time.time()
    print(str(report_path))


if __name__=='__main__':main()
