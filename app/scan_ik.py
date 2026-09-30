"""Optional local full-frame diagnostic using an existing reference controller.

Run with the Python environment used for the original IK screening:
python app/scan_ik.py --root /path/to/umi_ik --uuid UUID --model openarm_v2 --side left
No robot commands or server writes. Original screening labels are not changed.
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True)
    p.add_argument('--uuid',required=True)
    p.add_argument('--model',choices=['franka_fr3','openarm_v2'],required=True)
    p.add_argument('--side',choices=['left','right'],required=True)
    p.add_argument('--anchor',type=int,default=None)
    p.add_argument('--continuous',action='store_true',help='Sequential bounded IK and sampled transition collision checks')
    p.add_argument('--fps',type=float,default=30.,help='Assumed recording rate; verify against dataset metadata')
    p.add_argument('--starts',type=int,default=4,help='Initial joint seeds for one fixed placement')
    p.add_argument('--acceleration',type=float,default=None,help='Optional reference acceleration cap in rad/s^2, not a manufacturer limit')
    a=p.parse_args();root=Path(a.root).resolve()
    from storage import Dataset
    dataset=Dataset(root)
    group=dataset.index[a.uuid]
    label=dataset.labels[a.uuid]['models'][a.model][a.side]
    rec=json.loads(dataset.reference_path(label['record_file']).read_text())
    sys.path.insert(0,str(root))
    from controller import Arm,CollisionController,poses_to_matrix
    cfg=dataset.setup[a.model]
    arms={side:Arm(dataset.models[a.model][side]) for side in ('left','right')}
    for side in arms:arms[side].set_tcp(cfg['flange_to_hand_root'][side])
    collision=CollisionController(a.model,arms,{s:np.array(cfg['world_to_base'][s]) for s in arms})
    collision.hand(a.side);arm=arms[a.side]
    raw=np.concatenate([dataset.poses[group['task']][lo:hi] for lo,hi,_,_ in group['chunks']])
    world=poses_to_matrix(raw[:,2:9] if a.side=='left' else raw[:,9:16])
    delta=np.linalg.inv(world[0])[None]@world
    if a.anchor is None and rec.get('ik_all_frames_pass'):
        t0=np.array(rec['target_start']);seed=np.array(rec['anchor_q']);anchor_id=rec['anchor_id']
    else:
        bank=json.loads((root/'incremental_start_refit/anchors.json').read_text())[a.model][a.side]
        anchor_id=a.anchor
        if anchor_id is None:
            attempts=[x for x in rec.get('attempts',[]) if 'failure_frame' in x]
            anchor_id=max(attempts,key=lambda x:(x.get('stage')=='full',x['failure_frame']))['anchor_id'] if attempts else 0
        if not 0<=anchor_id<len(bank):raise ValueError('Anchor outside reference bank')
        anchor=bank[anchor_id];seed=np.array(anchor['q']);pivot=round(anchor['pivot_fraction']*(len(raw)-1))
        t0=arm.fk(seed)[0]@np.linalg.inv(delta[pivot])
    targets=t0[None]@delta
    if a.continuous:
        if a.starts<1:raise ValueError('starts must be positive')
        from continuity import track
        if a.model=='franka_fr3':
            import yaml
            limits=yaml.safe_load((root/'fr3_limits.yaml').read_text())
            velocity=[limits['joint'+str(i)]['limit']['velocity'] for i in range(1,8)]
            source='fr3_limits.yaml: static velocity limits only; position-dependent limits not modeled'
        else:
            import xml.etree.ElementTree as ET
            joints={j.attrib['name']:j for j in ET.parse(root/'openarm_v2.urdf').getroot().findall('joint')}
            velocity=[float(joints[n].find('limit').attrib['velocity']) for n in arm.config['joint_names']]
            source='openarm_v2.urdf: arm joint velocity limits'
        rng=np.random.default_rng(20260927);attempts=[];best=None
        for k in range(a.starts):
            initial=seed if k==0 else rng.uniform(arm.lower,arm.upper)
            r=track(arm,targets,initial,lambda q:collision.single(q,a.side)[0],velocity,
                    fps=a.fps,acceleration=a.acceleration)
            attempts.append(dict(start=k,failed=r['states'].count('fail'),passed=r['all_frames_continuous']))
            if best is None or r['states'].count('fail')<best['states'].count('fail'):best=r;best['selected_start']=k
            print(json.dumps({'progress':k+1,'starts':a.starts,**attempts[-1]}),flush=True)
            if r['all_frames_continuous']:break
        best.update(uuid=a.uuid,model=a.model,side=a.side,frames=len(raw),anchor_id=anchor_id,
                    target_start=t0.tolist(),reference_only=True,attempts=attempts,velocity_source=source,
                    criterion='1 mm / 0.5 deg; joint bounds; discrete velocity; sampled self/body collision; one placement',
                    limitations=['No torque/dynamics/environment collision verification',
                                 'No acceleration check unless explicitly configured',
                                 'Finite search failure is not proof of infeasibility',
                                 'Recovery starts never certify the entire trajectory'])
        out=root/'continuity_diagnostics'/a.model/a.side/(a.uuid+'.json');out.parent.mkdir(parents=True,exist_ok=True)
        temp=out.with_suffix('.tmp');temp.write_text(json.dumps(best,allow_nan=False));temp.replace(out)
        print(json.dumps(dict(path=str(out),passed=best['all_frames_continuous'],failed_frames=best['states'].count('fail'))))
        return
    result=arm.solve(targets,seed=seed,restarts=16,maxiter=120,stop=False)
    states=[];reasons=[];warm=seed
    for i,(q,ok) in enumerate(zip(result['q'],result['ok'])):
        if not ok:
            for centering in (0.,.03):
                retry=arm.solve(targets[i:i+1],seed=warm,restarts=64,maxiter=200,centering=centering)
                if retry['passed']:q=retry['q'][0];ok=True;break
        if ok:
            hit,_=collision.single(q,a.side)
            if not hit:states.append('pass');reasons.append(None);warm=q;continue
            reason='collision'
        else:
            # Residuals describe the best candidate, not a proof of physical cause.
            from scipy.spatial.transform import Rotation
            fk=arm.fk(q)[0]
            pos=np.linalg.norm(fk[:3,3]-targets[i,:3,3])>.001
            rot=Rotation.from_matrix(targets[i,:3,:3]@fk[:3,:3].T).magnitude()>np.deg2rad(.5)
            reason='pose' if pos and rot else 'position' if pos else 'orientation' if rot else 'search'
        states.append('fail');reasons.append(reason)
    assert len(states)==len(raw)
    out=root/'ik_diagnostics'/a.model/a.side/(a.uuid+'.json');out.parent.mkdir(parents=True,exist_ok=True)
    payload=dict(uuid=a.uuid,model=a.model,side=a.side,frames=len(raw),anchor_id=anchor_id,
                 target_start=t0.tolist(),states=states,reasons=reasons,reference_only=True,
                 continuity_certified=False,criterion='1 mm / 0.5 deg, bounded IK and modeled self/body collision; one fixed placement')
    temp=out.with_suffix('.tmp');temp.write_text(json.dumps(payload));temp.replace(out)
    from ik_diagnostics import segments
    print(json.dumps(dict(path=str(out),passed=states.count('pass'),failed=states.count('fail'),segments=segments(states,reasons,a.side)),ensure_ascii=False))

if __name__=='__main__':main()
