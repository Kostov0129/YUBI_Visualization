"""Read reference IK evidence without interpreting unknown frames as failures."""
import json
import concurrent.futures
import subprocess
import sys
import threading
from pathlib import Path

POOL=concurrent.futures.ThreadPoolExecutor(max_workers=1)
JOBS={}
LOCK=threading.Lock()

def can_scan(dataset, check):
    if check=='agibot_g2_reference:dual':
        return not getattr(dataset,'lazy',False) and (dataset.root/'g2_controller.py').is_file() and (dataset.root/'g2_reference/g2_core.so').is_file()
    return (check in {m+':'+s for m,s,_ in CHECKS if s!='dual'}
            and not getattr(dataset,'lazy',False) and (dataset.root/'controller.py').is_file()
            and (dataset.root/'ik_core.so').is_file())

def scan_status(dataset, uid, check, kind='pose'):
    with LOCK:return JOBS.get((str(dataset.root),uid,check,kind),{}).copy()

def start_scan(dataset, uid, check, kind='pose'):
    if kind not in ('pose','continuity'):raise ValueError('Invalid criterion')
    from screening_index import running
    if running(dataset):raise ValueError('Batch screening is already running')
    if uid not in dataset.index or not can_scan(dataset,check):
        raise ValueError('Local reference IK controller is not configured')
    key=(str(dataset.root),uid,check,kind)
    with LOCK:
        if JOBS.get(key,{}).get('state')=='running':return JOBS[key].copy()
        JOBS[key]={'state':'running'}
    def work():
        model,side=check.split(':');python=dataset.root/'cad_env/bin/python'
        command=[str(python) if python.is_file() else sys.executable,str(Path(__file__).with_name('scan_ik.py')),
                 '--root',str(dataset.root),'--uuid',uid,'--model',model,'--side',side]
        if kind=='continuity':command.append('--continuous')
        if check=='agibot_g2_reference:dual':
            if kind!='continuity':
                with LOCK:JOBS[key]={'state':'error','message':'G2 支持连续性复查，请切换筛查标准。'}
                return
            command=[command[0],str(Path(__file__).with_name('scan_g2_continuity.py')),'--root',str(dataset.root),'--uuid',uid,'--full']
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=3600)
            status={'state':'ready'} if result.returncode==0 else {'state':'error','message':'逐帧复查失败，请检查本机 IK 环境和模型文件。'}
        except (OSError,subprocess.SubprocessError):status={'state':'error','message':'逐帧复查超时或本机 IK 环境不可用。'}
        with LOCK:JOBS[key]=status
    POOL.submit(work)
    return {'state':'running'}

CHECKS = [('franka_fr3', 'left', 'Franka · 左臂'),
          ('franka_fr3', 'right', 'Franka · 右臂'),
          ('openarm_v2', 'left', 'OpenArm · 左臂'),
          ('openarm_v2', 'right', 'OpenArm · 右臂'),
          ('agibot_g2_reference', 'dual', 'G2 参考 · 双臂')]
CHECK_LABELS = {model+':'+side: label for model, side, label in CHECKS}
REASONS = {'position': '位置误差超限', 'orientation': '姿态误差超限',
           'continuity_search': '单帧有解，但限速衔接搜索失败',
           'transition_collision': '两帧之间的插值姿态发生碰撞',
           'restart': '中断后重新起步，衔接未通过',
           'pose': '位置与姿态误差超限', 'collision': '候选解发生碰撞',
           'search': '参考起点下未找到合格解', 'mixed': '多项 IK 检查未通过'}

def segments(states, reasons, side, fps=30):
    result = []
    for i, state in enumerate(states):
        if state != 'fail':
            continue
        reason = reasons[i] or 'search'
        if result and result[-1]['end'] == i-1:
            result[-1]['end'] = i
            if result[-1]['reason'] != reason:
                pair={result[-1]['reason'],reason}
                result[-1]['reason']='pose' if pair <= {'position','orientation','pose'} else 'mixed'
        else:
            result.append(dict(start=i, end=i, reason=reason, side=side))
    for s in result:
        limb = {'left': '左臂', 'right': '右臂', 'dual': '双臂'}[side]
        s['label'] = f"{limb}{REASONS.get(s['reason'], REASONS['search'])} · {s['start']/fps:.2f}–{s['end']/fps:.2f} 秒（帧 {s['start']+1}–{s['end']+1}）"
    return result

def diagnostic(dataset, uid, check, frames, kind='pose'):
    if kind not in ('pose','continuity'):raise ValueError('Invalid criterion')
    if check == 'all':
        results=[diagnostic(dataset,uid,model+':'+side,frames,kind) for model,side,_ in CHECKS]
        combined=[]
        for result in results:
            label=CHECK_LABELS[result['check']]
            for item in result['segments']:
                sides=('left','right') if item['side']=='dual' else (item['side'],)
                for side in sides:
                    segment=dict(item,side=side)
                    segment['label']=f"{label} · {item['label']}"
                    combined.append(segment)
        combined.sort(key=lambda x:(x['start'],x['side'],x['label']))
        unknown=sum(r['counts']['unknown'] for r in results)
        failed=sum(r['counts']['fail'] for r in results)
        message=('整段五项连续性筛查已完成；左右轨迹中的未通过区段均已标红。'
                 if kind=='continuity' and unknown==0 else
                 '整段汇总：左右轨迹中的已有失败证据均已标红；未知帧不标红。')
        return dict(check='all',side='both',segments=combined,message=message,
                    can_scan=False,scan={},counts=None,failed_evidence=failed,
                    unknown_evidence=unknown)
    if check == 'none':
        return dict(segments=[], message='选择机械臂后查看 IK 标记。')
    valid = {m+':'+s for m, s, _ in CHECKS}
    if check not in valid:
        raise ValueError('Invalid IK check')
    model, side = check.split(':')
    label = dataset.labels.get(uid, {}).get('models', {}).get(model, {})
    if side != 'dual':
        label = label.get(side, {})
    path = dataset.root/('continuity_diagnostics' if kind=='continuity' else 'ik_diagnostics')/model/side/(uid+'.json')
    states = ['unknown']*frames
    reasons = [None]*frames
    anchor = None
    if path.is_file():
        d = json.loads(path.read_text())
        if (d.get('uuid'), d.get('model'), d.get('side'), d.get('frames')) != (uid, model, side, frames):
            raise ValueError('IK diagnostic identity mismatch')
        states, reasons = d['states'], d['reasons']
        if len(states) != frames or len(reasons) != frames or any(s not in ('pass','fail','unknown') for s in states):
            raise ValueError('Invalid IK diagnostic frame coverage')
        anchor = d.get('anchor_id')
        message = '逐帧复查 · 同一参考起点 · 红色为该次搜索失败帧；不代表数学上无解。'
        if kind=='continuity':
            message = ('整条连续检查通过。' if d.get('all_frames_continuous') else '整条连续检查未通过；局部恢复不算全程通过。')+' 同一参考放置，限速求解与插值碰撞采样；未验证动力学。'
            if d.get('early_stop') and 'unknown' in states:message+=' 已定位该次尝试的首个断点，后续未检查帧不标红。'
    elif kind=='continuity':
        message = '尚未做连续检查，旧的逐帧通过标签不能替代。'
    elif label.get('ik_all_frames_pass', label.get('dual_ik_all_frames_pass', False)):
        states = ['pass']*frames
        message = '已保存的全帧 IK 检查通过。参考配置，未认证轨迹连续性。'
    elif label.get('record_file'):
        try:
            d = json.loads(dataset.reference_path(label['record_file']).read_text())
            attempts = [a for a in d.get('attempts', []) if 'failure_frame' in a or 'failure_sequence_frame' in a]
            # Never combine failures from different placements into a false failure map.
            if attempts:
                a = max(attempts, key=lambda x: (x.get('stage') == 'full', x.get('failure_frame', x.get('failure_sequence_frame', -1))))
                i = a.get('failure_frame', a.get('failure_sequence_frame'))
                if 0 <= i < frames:
                    states[i] = 'fail'; reasons[i] = 'search'; anchor = a.get('anchor_id')
            message = '旧筛查仅保存停止时的失败帧，其余帧未知；此处不是完整失败区间。'
        except (OSError, ValueError):
            message = '只有整条记录标签，缺少逐帧结果；不能定位失败区间。'
    else:
        message = '此记录没有逐帧 IK 结果；未检查帧不标红。'
    from screening_index import running
    return dict(check=check, side=side, anchor_id=anchor, states=states,
                can_scan=can_scan(dataset,check) and not running(dataset) and (side!='dual' or kind=='continuity'),scan=scan_status(dataset,uid,check,kind),
                segments=segments(states, reasons, side), message=message,
                counts={s: states.count(s) for s in ('pass','fail','unknown')})
