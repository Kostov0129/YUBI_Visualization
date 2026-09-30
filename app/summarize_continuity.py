"""Export a complete, validated five-check report and per-record labels locally."""
import argparse,json
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);a=p.parse_args()
    from storage import Dataset
    from screening_index import CHECKS
    root=Path(a.root).resolve();ds=Dataset(root);out=root/'continuity_diagnostics';by={}
    for name in ('batch_all.json','batch_g2.json'):
        d=json.loads((out/name).read_text())
        if d['state']!='complete' or d['completed_checks']!=d['expected_checks']:raise ValueError('Screening is not complete')
        for r in d['rows']:
            key=(r['uuid'],r['model']+':'+r['side'])
            if key in by:raise ValueError('Duplicate result')
            if r['state']=='error':raise ValueError('Resolve execution errors before final export')
            by[key]=r
    names={'franka_fr3:left':'Franka 左臂','franka_fr3:right':'Franka 右臂','openarm_v2:left':'OpenArm 左臂',
           'openarm_v2:right':'OpenArm 右臂','agibot_g2_reference:dual':'G2 参考双臂'}
    records=[];number=Counter();summary={}
    for g in ds.groups:
        checks={c:by[(g['uuid'],c)]['state'] for c in CHECKS}
        if any(v not in ('pass','fail') for v in checks.values()):raise ValueError('Unresolved record')
        number[g['task']]+=1
        records.append(dict(uuid=g['uuid'],task=g['task'],display_record_number=number[g['task']],
                            episode_indices=[x[2] for x in g['chunks']],frames=g['frames'],checks=checks,
                            all_five_pass=all(s=='pass' for s in checks.values())))
    lines=['# 三种参考配置连续性筛查结果','',
           '全部检查完成，无程序错误。通过率按各任务的全部记录数计算。',
           'Franka / OpenArm 为左右单臂分别检查；G2 为参考配置下双臂同时检查，含臂间碰撞。',
           '通过要求同一次尝试全帧连续成功。G2 失败尝试在首个断点停止，后续帧保留未知；记录级判定仍为未通过。',
           '有限搜索未通过不代表数学上无解。G2 不是已确认的 TX-G2，工具变换及安装均属参考配置。','',
           '| 任务 | 检查项 | 通过数 | 通过率 | 未通过数 | 未通过率 |',
           '|---|---|---:|---:|---:|---:|']
    for task in ('cup','phone'):
        rr=[r for r in records if r['task']==task];n=len(rr);title='杯子放盘后放回' if task=='cup' else '手机装盒';summary[task]={}
        for c in (*CHECKS,'intersection'):
            passed=sum(r['all_five_pass'] if c=='intersection' else r['checks'][c]=='pass' for r in rr)
            summary[task][c]=dict(total=n,passed=passed,failed=n-passed,pass_percent=round(passed*100/n,2))
            lines.append(f'| {title} | {names.get(c,"五项交集")} | {passed} | {passed*100/n:.2f}% | {n-passed} | {(n-passed)*100/n:.2f}% |')
    payload=dict(reference_only=True,TX_G2_verified=False,generated_at=datetime.now(timezone.utc).isoformat(),
                 criterion='30 Hz, full-frame continuity, static model speed limits, sampled self/body collision; G2 inter-arm collision included',
                 summary=summary,records=records)
    (out/'labels_three_platforms.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    (out/'summary_three_platforms.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
