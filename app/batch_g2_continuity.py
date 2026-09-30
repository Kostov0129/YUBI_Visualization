"""Resume G2 reference dual-arm screening locally; preserve other robot results."""
import argparse,json,hashlib,os,sys,time,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True)
    p.add_argument('--workers',type=int,default=6);p.add_argument('--limit',type=int,default=0)
    a=p.parse_args();root=Path(a.root).resolve()
    from storage import Dataset
    ds=Dataset(root);groups=ds.groups[:a.limit] if a.limit else ds.groups
    h=hashlib.sha256()
    for path in [Path(__file__),Path(__file__).with_name('scan_g2_continuity.py'),Path(__file__).with_name('g2_continuity.py'),
                 root/'g2_controller.py',root/'g2_reference/g2_core.so',root/'g2_reference/model.json',root/'g2_reference/G2.urdf',
                 root/'g2_dual_strict/anchors.json',root/'g2_dual_strict/joint_fit_bank.npz']:
        h.update(path.read_bytes())
    for t in sorted(ds.poses):h.update(memoryview(ds.poses[t]).cast('B'))
    for g in groups:h.update((root/'g2_dual_strict'/g['task']/(g['uuid']+'.json')).read_bytes())
    signature=h.hexdigest();out=root/'continuity_diagnostics';rows=[];started=time.time()
    def run(g):
        path=out/'agibot_g2_reference/dual'/(g['uuid']+'.json');d=json.loads(path.read_text()) if path.exists() else {};error=None
        if d.get('batch_signature')!=signature or d.get('frames')!=g['frames']:
            try:
                cmd=[sys.executable,str(Path(__file__).with_name('scan_g2_continuity.py')),'--root',str(root),'--uuid',g['uuid']]
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=3600,
                                      env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                if result.returncode:raise RuntimeError(result.stderr[-1000:])
                d=json.loads(path.read_text());d['batch_signature']=signature
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(d,allow_nan=False));tmp.replace(path)
            except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as e:error=str(e)
        return dict(uuid=g['uuid'],task=g['task'],episodes=[x[2] for x in g['chunks']],model='agibot_g2_reference',side='dual',
                    frames=g['frames'],state='error' if error else 'pass' if d['all_frames_continuous'] else 'fail',
                    failed_frames=None if error else d['states'].count('fail'),checked_frames=None if error else d['checked_frames'],error=error)
    def save(state):
        counts={s:sum(r['state']==s for r in rows) for s in ('pass','fail','error')}
        d=dict(state=state,rows=rows,counts=counts,signature=signature,reference_only=True,TX_G2_verified=False,
               expected_checks=len(groups),completed_checks=len(rows),updated_at=time.time(),elapsed_seconds=time.time()-started,
               note='G2 reference dual-arm; passing attempts cover every frame; rejected attempts stop at first failure')
        path=out/'batch_g2.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(d));tmp.replace(path)
        print(json.dumps(dict(completed=len(rows),total=len(groups),**counts)),flush=True)
    save('running')
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending={pool.submit(run,g) for g in groups};last=time.time()
        while pending:
            done,pending=wait(pending,timeout=5,return_when=FIRST_COMPLETED)
            rows.extend(f.result() for f in done)
            if time.time()-last>=5 or not pending:save('running' if pending else 'complete');last=time.time()


if __name__=='__main__':main()
