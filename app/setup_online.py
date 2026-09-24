"""One-time local setup: read remote trajectories through SSH, without remote writes."""
import argparse, io, json, os, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path
import video_cache

ALLOWED = {'cup_poses.npy','cup_angles.npy','smartphone_poses.npy','smartphone_angles.npy','groups.json','episode_metadata.json','cache_manifest.json'}
REMOTE_END = r'''
import io, sys, av
import pyarrow
pyarrow.set_cpu_count(2)
def send(name, obj):
    if isinstance(obj,np.ndarray):
        header=io.BytesIO()
        np.lib.format.write_array_header_1_0(header,dict(descr=np.lib.format.dtype_to_descr(obj.dtype),fortran_order=False,shape=obj.shape))
        prefix=header.getvalue(); payload=memoryview(obj).cast('B')
    else:
        prefix=b'';payload=json.dumps(obj,ensure_ascii=False).encode()
    sys.stdout.buffer.write((json.dumps({'file':name,'size':len(prefix)+len(payload)})+'\n').encode())
    sys.stdout.buffer.write(prefix);sys.stdout.buffer.write(payload);sys.stdout.buffer.flush()
print('正在扫描服务器轨迹，原始视频不会下载。请等待完成。',file=sys.stderr,flush=True)
manifest=prepare(DATASET,emit=send)
sys.stdout.buffer.write((json.dumps({'done':manifest})+'\n').encode());sys.stdout.buffer.flush()
'''

def remote_code(dataset):
    source=Path(__file__).with_name('prepare_data.py').read_text()
    return "__name__='yubi_remote'\nDATASET="+repr(dataset)+'\n'+source+'\n'+REMOTE_END

def receive(stream, folder):
    seen=set()
    while True:
        line=stream.readline(16384)
        if not line: raise RuntimeError('连接中断；轨迹缓存尚未完成，请重试')
        header=json.loads(line)
        if 'done' in header:
            needed={'groups.json','episode_metadata.json','cache_manifest.json'}
            for task in header['done']['frames']:
                name='smartphone' if task=='phone' else task
                needed.update({name+'_poses.npy',name+'_angles.npy'})
            if seen!=needed: raise RuntimeError('缓存文件不完整')
            return header['done']
        name,size=header['file'],header['size']
        if name not in ALLOWED or name in seen or not isinstance(size,int) or not 0<size<4*1024**3:
            raise RuntimeError('服务器返回的缓存格式不正确')
        if shutil.disk_usage(folder).free<size+256*1024**2: raise RuntimeError('本机磁盘空间不足')
        with (folder/name).open('wb') as f:
            remaining=size
            while remaining:
                chunk=stream.read(min(1024**2,remaining))
                if not chunk: raise RuntimeError('传输中断，请重新运行')
                f.write(chunk);remaining-=len(chunk)
        seen.add(name);print('已准备 '+name,flush=True)

def download(config, output):
    output=Path(output).resolve()
    if output.exists(): raise ValueError('目标缓存目录已存在；不会覆盖，请选择新目录')
    output.parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='.yubi-online-',dir=output.parent));proc=None
    try:
        video_cache.CONFIG=config
        proc=subprocess.Popen(video_cache.command(remote_code(config['dataset_root'])),stdout=subprocess.PIPE)
        manifest=receive(proc.stdout,folder)
        if proc.wait(timeout=30)!=0: raise RuntimeError('SSH 执行失败，未保存配置')
        from storage import Dataset
        Dataset(folder)
        folder.rename(output);return manifest
    finally:
        if proc is not None:
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()
        if folder.exists():shutil.rmtree(folder)

def ask(label,default=''):
    value=input(label+(f' [{default}]' if default else '')+'：').strip()
    return value or default

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config.local.json');p.add_argument('--output',default='data');a=p.parse_args()
    conf=Path(a.config).expanduser().resolve();output=Path(a.output).expanduser().resolve()
    if conf.exists() or output.exists():raise ValueError('配置或 data 目录已存在。已有配置可直接启动；重新准备请用 --config 和 --output 指定新路径。')
    host=ask('本机平时 SSH 登录的入口（用户名@地址，或 SSH 别名）')
    hops=ask('登录入口后依次执行的 SSH 别名，用空格分隔；直连最终服务器填 -','8xA100 8xA100')
    dataset=ask('最终服务器上的数据集完整路径')
    python=ask('最终服务器的 Python（需有 numpy、scipy、pyarrow、av）','python3')
    if not host or host.startswith('-') or not dataset:raise ValueError('请填写 SSH 入口和数据集路径')
    hops=[] if hops=='-' else shlex.split(hops)
    if any(h.startswith('-') for h in hops):raise ValueError('SSH 别名不应以 - 开头')
    sockets=Path.home()/'.ssh';sockets.mkdir(mode=0o700,exist_ok=True)
    socket=sockets/('yubi-'+str(os.getpid())+'.sock')
    print('按平时方式登录第一跳；若询问密码，请直接输入（不保存密码）。',flush=True)
    subprocess.run(['ssh','-M','-S',str(socket),'-o','ControlPersist=2h','-o','ConnectTimeout=20','-o','RemoteCommand=none','-o','RequestTTY=no','-fN',host],check=True)
    config=dict(data_root=os.path.relpath(output,conf.parent),dataset_root=dataset,video_cache='./.cache/videos',ssh_host=host,ssh_hops=hops,remote_python=python,ssh_control_path=str(socket),host='127.0.0.1',port=8768)
    result=download(config,output)
    conf.parent.mkdir(parents=True,exist_ok=True)
    with conf.open('x') as f:json.dump(config,f,ensure_ascii=False,indent=2)
    print(f'完成：{result["recordings"]} 条记录。配置保存到 {conf.name}。')
    print('启动：python viewer.py --config '+shlex.quote(str(conf)))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:sys.exit('未完成：'+str(e))
