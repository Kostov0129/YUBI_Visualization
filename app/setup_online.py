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

GATEWAY_IP = '100.89.168.79'
GATEWAY_USER = 'steven'
DATASET_ROOT = '/mnt/data/benyun/yubi-corl2026-umi-arena'
REMOTE_PYTHON = '/home/benyun/.venvs/umi_arena_pi05/bin/python'

def on_gateway():
    # Check the effective account AND an address assigned to this host.
    # A local account called steven or SSH_CONNECTION alone is insufficient.
    try:
        import pwd
        if pwd.getpwuid(os.geteuid()).pw_name != GATEWAY_USER:return False
    except (ImportError,KeyError):return False
    for command in [['ip','-j','address','show'],['tailscale','ip','-4']]:
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=3,check=True)
            if command[0]=='ip':
                addresses={a.get('local') for interface in json.loads(result.stdout) for a in interface.get('addr_info',[])}
            else:addresses=set(result.stdout.split())
            if GATEWAY_IP in addresses:return True
        except (OSError,subprocess.SubprocessError,ValueError,TypeError,AttributeError):continue
    return False

def route(at_gateway):
    return dict(ssh_host='8xA100' if at_gateway else GATEWAY_USER+'@'+GATEWAY_IP,
                ssh_hops=['8xA100'] if at_gateway else ['8xA100','8xA100'],
                dataset_root=DATASET_ROOT,remote_python=REMOTE_PYTHON)

def preflight(config):
    video_cache.CONFIG=config
    code="import av,numpy,scipy,pyarrow;from pathlib import Path; p=Path("+repr(config['dataset_root'])+"); assert (p/'meta/info.json').is_file() and (p/'data').is_dir() and (p/'videos').is_dir(), 'Dataset missing';print('YUBI connection ready')"
    subprocess.run(video_cache.command(code),check=True,timeout=60)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config.local.json');p.add_argument('--output',default='data');a=p.parse_args()
    conf=Path(a.config).expanduser().resolve();output=Path(a.output).expanduser().resolve()
    if conf.exists() or output.exists():raise ValueError('配置或 data 目录已存在。已有配置可直接启动；重新准备请用 --config 和 --output 指定新路径。')
    at_gateway=on_gateway()
    config=route(at_gateway)
    sockets=Path.home()/'.ssh';sockets.mkdir(mode=0o700,exist_ok=True)
    socket=sockets/('yubi-'+str(os.getpid())+'.sock')
    print('已识别 steven 跳板机，直接免密连接 A100。' if at_gateway else '正在登录 steven@100.89.168.79；若提示密码，请输入 SSH 登录密码（不保存密码）。',flush=True)
    command=['ssh','-M','-S',str(socket),'-o','ControlPersist=2h','-o','ConnectTimeout=20','-o','RemoteCommand=none','-o','RequestTTY=no']
    if at_gateway:command+=['-o','BatchMode=yes']
    command+=['-fN',config['ssh_host']]
    subprocess.run(command,check=True)
    config.update(data_root=os.path.relpath(output,conf.parent),video_cache='./.cache/videos',ssh_control_path=str(socket),host='127.0.0.1',port=8768)
    preflight(config)
    result=download(config,output)
    conf.parent.mkdir(parents=True,exist_ok=True)
    with conf.open('x') as f:json.dump(config,f,ensure_ascii=False,indent=2)
    print(f'完成：{result["recordings"]} 条记录。配置保存到 {conf.name}。')
    print('启动：python viewer.py --config '+shlex.quote(str(conf)))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:sys.exit('未完成：'+str(e))
