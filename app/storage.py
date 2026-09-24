"""Pose cache and optional reference IK. No native IK library is needed for playback."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

def poses_to_matrix(v):
 out=np.tile(np.eye(4),(len(v),1,1));out[:,:3,3]=v[:,:3];out[:,:3,:3]=Rotation.from_quat(v[:,3:]).as_matrix();return out

class Dataset:
 def __init__(self,root):
  self.root=Path(root).expanduser().resolve()
  def choose(*paths):return next((self.root/p for p in paths if (self.root/p).is_file()),None)
  group_path=choose('groups.json','incremental_start_refit/groups.json')
  if not group_path:raise ValueError('Missing groups.json: run prepare_data.py first')
  self.groups=json.loads(group_path.read_text());self.index={g['uuid']:g for g in self.groups}
  self.poses={t:np.load(self.root/(f+'_poses.npy'),mmap_mode='r') for t,f in [('cup','cup'),('phone','smartphone')] if any(g['task']==t for g in self.groups)}
  self.angles={t:np.load(self.root/(f+'_angles.npy'),mmap_mode='r') for t,f in [('cup','cup'),('phone','smartphone')] if t in self.poses}
  self.labels={};self.models={};self.setup={}
  labels=choose('ik/group_labels.jsonl','platform_labels_start_refit/group_labels.jsonl');models=choose('ik/models.json','models.json');setup=choose('ik/used_setup.json','incremental_start_refit/used_setup.json')
  if all([labels,models,setup]):
   self.labels={x['uuid']:x for x in map(json.loads,labels.read_text().splitlines())};self.models=json.loads(models.read_text())['models'];self.setup=json.loads(setup.read_text())['models']
 def reference_path(self,path):
  p=Path(path)
  if not p.is_absolute():candidate=self.root/p
  else:
   try:p.relative_to(self.root);candidate=p
   except ValueError:
    markers=['incremental_start_refit','incremental_strict','single_arm_strict','ik']
    marker=next((x for x in markers if x in p.parts),None)
    if marker is None:raise ValueError('Reference path is outside configured data_root')
    candidate=self.root/Path(*p.parts[p.parts.index(marker):])
  candidate=candidate.resolve();candidate.relative_to(self.root)
  return candidate
 def modes(self):
  out=[{'value':'raw','label':'原始双手轨迹'}]
  for n,label in [('franka_fr3','Franka'),('openarm_v2','OpenArm')]:
   if n in self.models and n in self.setup:
    out.extend({'value':n+':'+side,'label':label+' · '+cn+'手参考 IK'} for side,cn in [('left','左'),('right','右')])
  return out
 def catalog(self):return [{'uuid':g['uuid'],'task':g['task'],'frames':g['frames'],'episodes':[x[2] for x in g['chunks']]} for g in self.groups]
 def data(self,uid,mode='raw'):
  g=self.index[uid];a=np.concatenate([self.poses[g['task']][lo:hi] for lo,hi,_,_ in g['chunks']]);angles=np.concatenate([self.angles[g['task']][lo:hi] for lo,hi,_,_ in g['chunks']])
  out={'uuid':uid,'task':g['task'],'frames':len(a),'fps':30,'episodes':a[:,:2].astype(int).tolist(),'poses':a[:,2:].round(7).tolist(),'angles':angles.round(7).tolist(),'mode':mode,'status':'原始双手 · table_origin · 轨迹单位 m','boundaries':np.cumsum([hi-lo for lo,hi,_,_ in g['chunks']]).tolist()}
  if mode=='raw':return out
  if mode not in [m['value'] for m in self.modes()]:raise ValueError('Reference IK is not configured')
  name,side=mode.split(':');label=self.labels.get(uid,{}).get('models',{}).get(name,{}).get(side,{})
  if not label.get('ik_all_frames_pass'):
   out.update(mode='raw',status='该臂无已保存的全帧参考解；显示原始双手轨迹');return out
  rec=json.loads(self.reference_path(label['record_file']).read_text());q=np.load(self.reference_path(rec['joint_file']))['q'];assert len(q)==len(a)
  conf=self.models[name][side];tcp=np.array(self.setup[name]['flange_to_hand_root'][side]);raw=poses_to_matrix(a[:,2:9] if side=='left' else a[:,9:16]);target=np.array(rec['target_start'])[None]@np.linalg.inv(raw[:1])@raw
  out['target']=np.column_stack([target[:,:3,3],Rotation.from_matrix(target[:,:3,:3]).as_quat()]).round(7).tolist();chain=[];hand=[]
  for joints in q:
   t=np.eye(4);pts=[t[:3,3].copy()]
   for origin,axis,v in zip(conf['joint_origins'],conf['joint_axes'],joints):
    r=np.eye(4);r[:3,:3]=Rotation.from_rotvec(np.array(axis)*v).as_matrix();t=t@origin@r;pts.append(t[:3,3].copy())
   t=t@conf['joint7_to_flange'];pts.append(t[:3,3].copy());t=t@tcp;pts.append(t[:3,3].copy());chain.append(pts);hand.append(list(t[:3,3])+list(Rotation.from_matrix(t[:3,:3]).as_quat()))
  out.update(chain=np.round(chain,7).tolist(),hand=np.round(hand,7).tolist(),side=side,status=f'{name} {side} · 旧参考工具变换，未标定 · 单臂基座坐标 · 最大相邻关节跳变 {rec.get("max_adjacent_joint_step_rad",0):.2f} rad')
  return out
