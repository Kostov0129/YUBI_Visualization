"""Coupled 14-joint tracking with one shared bimanual placement."""
import numpy as np
from scipy.spatial.transform import Rotation
from continuity import windows


class PairArm:
    def __init__(self, controller):
        self.c=controller
        self.lower=np.concatenate([controller.arms[h].lower for h in ('left','right')])
        self.upper=np.concatenate([controller.arms[h].upper for h in ('left','right')])

    def sync_bounds(self):
        # Native dual_solve reads CW->chains, not the Python Arm arrays.
        # Refresh both chains so the local speed bounds actually reach the solver.
        for k,h in enumerate(('left','right')):
            a=self.c.arms[h];a.lower=np.ascontiguousarray(self.lower[k*7:k*7+7]);a.upper=np.ascontiguousarray(self.upper[k*7:k*7+7])
            self.c.lib.collision_chain(k,*a.args(),a.ptr(np.ascontiguousarray(self.c.bases[h])))

    def solve(self,target,seed,lower,upper):
        self.lower=lower.copy();self.upper=upper.copy();self.sync_bounds()
        r=self.c.solve(target[0:1],target[1:2],[seed[:7],seed[7:]],restarts=16,maxiter=160)
        q=np.concatenate([r['left'][0],r['right'][0]])
        errors=[]
        for k,h in enumerate(('left','right')):
            fk=self.c.arms[h].fk(q[k*7:k*7+7])[0]
            errors.extend([float(np.linalg.norm(fk[:3,3]-target[k,:3,3])),
                           float(Rotation.from_matrix(target[k,:3,:3]@fk[:3,:3].T).magnitude())])
        ok=(r['passed'] and np.isfinite(q).all() and np.all(q>=lower-1e-8) and np.all(q<=upper+1e-8)
            and max(errors[::2])<=.00100001 and max(errors[1::2])<=np.deg2rad(.5)+1e-8 and not self.collision(q))
        return q,bool(ok),errors

    def collision(self,q):
        return bool(self.c.collisions(q[:7][None],q[7:][None])[0][0])


def track_pair(arm,targets,seed,velocity,fps=30.,stop_on_failure=True,collision_step=.02):
    lo,hi=arm.lower.copy(),arm.upper.copy();velocity=np.asarray(velocity,float)
    if fps<=0 or np.any(velocity<=0):raise ValueError('Positive timing and velocity required')
    states=[];reasons=[];qs=[];errors=[];recoveries=[];prev=None;warm=np.asarray(seed,float)
    try:
        for i,target in enumerate(targets):
            lower=lo if prev is None else np.maximum(lo,prev-velocity/fps)
            upper=hi if prev is None else np.minimum(hi,prev+velocity/fps)
            q,ok,err=arm.solve(target,np.clip(warm,lower,upper),lower,upper)
            reason=None
            if ok and prev is not None:
                steps=max(1,int(np.ceil(np.max(np.abs(q-prev))/collision_step)))
                if any(arm.collision(prev+(q-prev)*(j/steps)) for j in range(1,steps)):
                    ok=False;reason='transition_collision'
            if not ok:
                restored,found,re=arm.solve(target,warm,lo,hi)
                reason=reason or ('continuity_search' if found and prev is not None else 'search')
                states.append('fail');reasons.append(reason);qs.append(None);errors.append(err)
                if stop_on_failure:break
                prev=restored.copy() if found else None
                if found:warm=prev.copy();recoveries.append(i)
                continue
            if i and prev is None:
                states.append('fail');reasons.append('restart');recoveries.append(i)
            else:states.append('pass');reasons.append(None)
            qs.append(q.tolist());errors.append(err);prev=q.copy();warm=q.copy()
        checked=len(states)
        unknown=len(targets)-checked
        states+=['unknown']*unknown;reasons+=[None]*unknown;qs+=[None]*unknown;errors+=[None]*unknown
        return dict(states=states,reasons=reasons,joints=qs,residuals=errors,checked_frames=checked,
                    recovery_frames=recoveries,all_frames_continuous=all(s=='pass' for s in states),
                    windows=windows(states,fps),fps=fps,velocity_limits=velocity.tolist(),
                    acceleration_limit=None,collision_sample_step_rad=collision_step,
                    early_stop=stop_on_failure,initial_velocity='unspecified',terminal_velocity='unspecified')
    finally:
        arm.lower=lo;arm.upper=hi;arm.sync_bounds()
