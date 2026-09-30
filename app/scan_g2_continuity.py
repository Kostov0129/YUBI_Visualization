"""All-frame acceptance for the G2 reference pair. No hardware commands."""
import argparse,json,sys
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np


def placement(root,group,world,c):
    rec=json.loads((root/'g2_dual_strict'/group['task']/(group['uuid']+'.json')).read_text())
    if rec.get('dual_ik_all_frames_pass'):
        z=np.load(root/'g2_dual_strict'/group['task']/(group['uuid']+'.npz'))
        return np.array(rec['recorded_to_robot_body']),np.r_[z['q_left'][0],z['q_right'][0]],rec['anchor_id']
    attempt=max(rec['attempts'],key=lambda a:(a.get('stage')=='full',a.get('failure_sequence_frame',-1)))
    aid=attempt['anchor_id']
    if attempt.get('method')=='joint_initial_fit':
        bank=np.load(root/'g2_dual_strict/joint_fit_bank.npz');k=attempt['bank_id'];seed=bank['q'][k].reshape(-1)
        src=np.concatenate([np.concatenate([w[0,:3,3][None],w[0,:3,3][None]+.2*w[0,:3,:3].T]) for w in world])
        dst=bank['points'][k];sc=src.mean(0);dc=dst.mean(0);u,_,vt=np.linalg.svd((src-sc).T@(dst-dc));v=vt.T
        v[:,2]*=np.linalg.det(v@u.T);S=np.eye(4);S[:3,:3]=v@u.T;S[:3,3]=dc-S[:3,:3]@sc
    else:
        pair=np.array(json.loads((root/'g2_dual_strict/anchors.json').read_text())[aid//2]);k=aid%2;h=('left','right')[k]
        seed=pair.reshape(-1);S=c.bases[h]@c.arms[h].fk(pair[k])[0]@np.linalg.inv(world[k][0])
    return S,seed,aid


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--uuid',required=True)
    p.add_argument('--starts',type=int,default=4);p.add_argument('--full',action='store_true',help='Continue local diagnostics after a break')
    a=p.parse_args();root=Path(a.root).resolve();sys.path.insert(0,str(root))
    from storage import Dataset
    from controller import poses_to_matrix
    from g2_controller import DualController
    from g2_continuity import PairArm,track_pair
    ds=Dataset(root);g=ds.index[a.uuid];raw=np.concatenate([ds.poses[g['task']][lo:hi] for lo,hi,_,_ in g['chunks']])
    world=[poses_to_matrix(raw[:,2:9]),poses_to_matrix(raw[:,9:16])];c=DualController();S,seed,aid=placement(root,g,world,c)
    targets=np.stack([np.linalg.inv(c.bases[h])[None]@S[None]@world[k] for k,h in enumerate(('left','right'))],axis=1)
    joints={j.get('name'):j for j in ET.parse(root/'g2_reference/G2.urdf').getroot().findall('joint')}
    velocity=[float(joints[n].find('limit').get('velocity')) for h in ('left','right') for n in c.cfg['models'][h]['joint_names']]
    arm=PairArm(c);rng=np.random.default_rng(20260927);attempts=[];best=None
    for k in range(a.starts):
        r=track_pair(arm,targets,seed if k==0 else rng.uniform(arm.lower,arm.upper),velocity,stop_on_failure=not a.full)
        attempts.append(dict(start=k,passed=r['all_frames_continuous'],checked_frames=r['checked_frames'],failed=r['states'].count('fail')))
        score=(r['all_frames_continuous'],-r['states'].count('fail'),r['checked_frames'])
        if best is None or score>best_score:best=r;best_score=score;best['selected_start']=k
        if r['all_frames_continuous']:break
    best.update(uuid=a.uuid,task=g['task'],model='agibot_g2_reference',side='dual',frames=len(raw),anchor_id=aid,
                attempts=attempts,recorded_to_robot_body=S.tolist(),reference_only=True,TX_G2_verified=False,
                velocity_source='G2.urdf arm joint limits',criterion='Both arms simultaneously: 1 mm / 0.5 deg, joint and speed bounds, sampled whole-body and inter-arm collisions; fixed shared placement',
                limitations=['Uncalibrated virtual TCP; no YUBI gripper meshes, table or objects',
                             'No acceleration or dynamics verification','Finite search failure is not proof of infeasibility',
                             'Bulk rejects a start at its first failed transition; remaining frames stay unknown'])
    out=root/'continuity_diagnostics/agibot_g2_reference/dual'/(a.uuid+'.json');out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(best,allow_nan=False));tmp.replace(out)
    print(json.dumps(dict(uuid=a.uuid,passed=best['all_frames_continuous'],checked=best['checked_frames'],frames=len(raw))))


if __name__=='__main__':main()
