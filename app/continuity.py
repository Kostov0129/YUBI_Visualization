"""Offline sequential IK with bounded transitions; never sends robot commands."""
import numpy as np
from scipy.spatial.transform import Rotation


def windows(states, fps, seconds=1.):
    # Each frame owns its incoming transition, including across window boundaries.
    size=max(1,round(fps*seconds))
    return [dict(start=i,end=min(i+size,len(states))-1,
                 passed=all(s=='pass' for s in states[i:i+size]),
                 failed=sum(s=='fail' for s in states[i:i+size]))
            for i in range(0,len(states),size)]


def track(arm, targets, seed, collision, velocity, fps=30., acceleration=None,
          collision_step=.02, restarts=16, maxiter=160):
    """One fixed placement. Recovery starts a new local chain, never heals a break.

    Limits concern discrete joint velocity (and optional discrete acceleration).
    Intermediate collision checks sample a linear joint-space interpolation.
    This is not a dynamics or exact continuous-collision certificate.
    """
    velocity=np.asarray(velocity,float)
    if fps<=0 or collision_step<=0 or np.any(velocity<=0):
        raise ValueError('Positive timing, speed and sampling limits required')
    if acceleration is not None and acceleration<=0:
        raise ValueError('Acceleration must be positive')
    lo,hi=arm.lower.copy(),arm.upper.copy()
    states=[];reasons=[];qs=[];residuals=[];recoveries=[]
    prev=None;vprev=None;warm=np.asarray(seed,float);dt=1/fps

    def solve(target, start, lower, upper):
        try:
            arm.lower=np.ascontiguousarray(lower);arm.upper=np.ascontiguousarray(upper)
            r=arm.solve(target[None],seed=np.clip(start,lower,upper),
                        restarts=restarts,maxiter=maxiter,stop=True)
        finally:
            arm.lower=lo.copy();arm.upper=hi.copy()
        q=r['q'][0]
        fk=arm.fk(q)[0]
        err=[float(np.linalg.norm(fk[:3,3]-target[:3,3])),
             float(Rotation.from_matrix(target[:3,:3]@fk[:3,:3].T).magnitude())]
        ok=(bool(r['passed']) and np.all(np.isfinite(q))
            and np.all(q>=lower-1e-8) and np.all(q<=upper+1e-8)
            and err[0]<=.00100001 and err[1]<=np.deg2rad(.5)+1e-8
            and not collision(q))
        return q,ok,err

    for i,target in enumerate(targets):
        lower,upper=lo.copy(),hi.copy()
        if prev is not None:
            lower=np.maximum(lower,prev-velocity*dt)
            upper=np.minimum(upper,prev+velocity*dt)
            if acceleration is not None and vprev is not None:
                lower=np.maximum(lower,prev+(vprev-acceleration*dt)*dt)
                upper=np.minimum(upper,prev+(vprev+acceleration*dt)*dt)
        if np.any(lower>=upper):
            q,ok,err=warm.copy(),False,[None,None]
        else:
            q,ok,err=solve(target,warm,lower,upper)
        reason=None
        if ok and prev is not None:
            steps=max(1,int(np.ceil(np.max(np.abs(q-prev))/collision_step)))
            if any(collision(prev+(q-prev)*(j/steps)) for j in range(1,steps)):
                ok=False;reason='transition_collision'
        if not ok:
            # Broad search is diagnostic recovery only. This frame stays failed.
            recovered,found,recovery_err=solve(target,warm,lo,hi)
            reason=reason or ('continuity_search' if found and prev is not None else 'search')
            if found:
                prev=recovered.copy();warm=prev.copy();vprev=None
                recoveries.append(i);q=recovered;err=recovery_err
            else:
                prev=None;vprev=None
            states.append('fail');reasons.append(reason)
        elif i and prev is None:
            # A disconnected local start cannot certify the incoming edge.
            states.append('fail');reasons.append('restart')
            recoveries.append(i);prev=q.copy();warm=q.copy();vprev=None
        else:
            vprev=(q-prev)/dt if prev is not None else None
            prev=q.copy();warm=q.copy();states.append('pass');reasons.append(None)
        qs.append(q.tolist() if prev is not None else None);residuals.append(err)
    return dict(states=states,reasons=reasons,joints=qs,residuals=residuals,
                recovery_frames=recoveries,all_frames_continuous=all(s=='pass' for s in states),
                windows=windows(states,fps),fps=fps,velocity_limits=velocity.tolist(),
                acceleration_limit=acceleration,collision_sample_step_rad=collision_step,
                initial_velocity='unspecified',terminal_velocity='unspecified')
