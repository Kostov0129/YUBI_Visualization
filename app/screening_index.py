"""Small live index for record badges; errors and unchecked results stay distinct."""
import json
import threading
import time

CHECKS=('franka_fr3:left','franka_fr3:right','openarm_v2:left','openarm_v2:right','agibot_g2_reference:dual')
_CACHE={}
_LOCK=threading.Lock()


def report(root,name='batch_all.json'):
    path=root/'continuity_diagnostics'/name
    if not path.exists():return {}
    stamp=path.stat().st_mtime_ns
    with _LOCK:
        if _CACHE.get(str(path),{}).get('stamp')!=stamp:
            _CACHE[str(path)]={'stamp':stamp,'data':json.loads(path.read_text())}
        return _CACHE[str(path)]['data']


def running(dataset):
    return any(d.get('state')=='running' and time.time()-d.get('updated_at',0)<90
               for d in [report(dataset.root),report(dataset.root,'batch_g2.json')])


def index(dataset,check='none'):
    if check not in (*CHECKS,'none','all'):raise ValueError('Invalid check')
    d=report(dataset.root);g2=report(dataset.root,'batch_g2.json');by_id={}
    for row in d.get('rows',[])+g2.get('rows',[]):
        if row['uuid'] not in dataset.index:continue
        by_id.setdefault(row['uuid'],{})[row['model']+':'+row['side']]=row['state']
    selected=CHECKS if check in ('none','all') else (check,)
    states={}
    for uid in dataset.index:
        values=[by_id.get(uid,{}).get(c,'unknown') for c in selected]
        states[uid]='fail' if 'fail' in values else 'error' if 'error' in values else 'pass' if all(v=='pass' for v in values) else 'unknown'
    complete=sum(all(c in v for c in CHECKS) for v in by_id.values())
    return dict(states=states,check=check,kind='continuity',running=running(dataset),
                completed_checks=d.get('completed_checks',0)+g2.get('completed_checks',0),total_checks=len(dataset.index)*5,
                completed_records=complete,total_records=len(dataset.index),
                counts={s:list(states.values()).count(s) for s in ('pass','fail','error','unknown')},
                supported=list(CHECKS))
