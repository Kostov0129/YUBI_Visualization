"""One-time local setup: read remote trajectories through SSH, without remote writes."""
import argparse, io, json, os, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path
import video_cache

ALLOWED = {'cup_poses.npy','cup_angles.npy','smartphone_poses.npy','smartphone_angles.npy','groups.json','episode_metadata.json','cache_manifest.json','lazy.json'}
def remote_code(dataset):
    from lazy_reader import INDEX_CODE
    return 'DATASET='+repr(dataset)+'\n'+INDEX_CODE

def receive(stream, folder):
    seen=set()
    while True:
        line=stream.readline(16384)
        if not line: raise RuntimeError('连接中断；轨迹缓存尚未完成，请重试')
        header=json.loads(line)
        if 'done' in header:
            needed={'groups.json','episode_metadata.json','cache_manifest.json'}
            if header['done'].get('lazy'):needed.add('lazy.json')
            for task in ([] if header['done'].get('lazy') else header['done']['frames']):
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
        Dataset(folder,config=config)
        folder.rename(output);return manifest
    finally:
        if proc is not None:
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()
        if folder.exists():shutil.rmtree(folder)

GATEWAY_IP = '100.89.168.79'
GATEWAY_USER = 'steven'
DATASET_ROOT = '/mnt/data/benyun/workspace/yubi-corl2026-umi-arena'
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

def shared_sockets():
    candidates=[Path.home()/'.ssh/yubi-shared.sock',Path.home()/'.cache/umi-video.sock']
    candidates+=sorted((Path.home()/'.ssh').glob('yubi-*.sock'),key=lambda p:p.stat().st_mtime,reverse=True)
    # Include explicit ControlPath sockets used by existing local SSH windows.
    try:
        output=subprocess.run(['ps','-u',str(os.getuid()),'-o','args='],capture_output=True,text=True,timeout=3,check=True).stdout
        for line in output.splitlines():
            try:args=shlex.split(line)
            except ValueError:continue
            if not args or Path(args[0]).name!='ssh':continue
            for i,arg in enumerate(args):
                if arg=='-S' and i+1<len(args):candidates.append(Path(args[i+1]).expanduser())
                elif arg.startswith('ControlPath='):candidates.append(Path(arg.split('=',1)[1]).expanduser())
                elif arg.startswith('-oControlPath='):candidates.append(Path(arg.split('=',1)[1]).expanduser())
    except (OSError,subprocess.SubprocessError):pass
    out=[]
    for p in candidates:
        try:
            if p.is_socket() and p.stat().st_uid==os.getuid() and str(p) not in out:out.append(str(p))
        except OSError:pass
    return out[:8]

def find_shared():
    for socket in shared_sockets():
        host=GATEWAY_USER+'@'+GATEWAY_IP
        try:
            result=subprocess.run(['ssh','-S',socket,'-O','check',host],capture_output=True,timeout=2)
            if result.returncode:continue
        except (OSError,subprocess.SubprocessError):continue
        for hops in [[],['8xA100'],['8xA100','8xA100']]:
            config=dict(ssh_host=host,ssh_control_path=socket,ssh_hops=hops,remote_python=REMOTE_PYTHON,dataset_root=DATASET_ROOT,shared_connection=True)
            video_cache.CONFIG=config
            try:
                probe="from pathlib import Path; assert (Path("+repr(DATASET_ROOT)+")/'meta/info.json').is_file(); print('YUBI_SHARED_READY')"
                result=subprocess.run(video_cache.command(probe),capture_output=True,text=True,timeout=8)
                if result.returncode==0 and result.stdout.strip()=='YUBI_SHARED_READY':return config
            except (OSError,subprocess.SubprocessError):pass
    return None

def discover(config):
    # A login alone is insufficient: find the host with the actual dataset.
    for hops in [[], ['8xA100'], ['8xA100','8xA100']]:
        candidate=dict(config,ssh_hops=hops)
        video_cache.CONFIG=candidate
        probe="from pathlib import Path; p=Path("+repr(DATASET_ROOT)+"); assert (p/'meta/info.json').is_file() and (p/'data').is_dir() and (p/'videos').is_dir(); print('YUBI_READY')"
        try:
            result=subprocess.run(video_cache.command(probe),stdin=subprocess.DEVNULL,
                                  capture_output=True,text=True,timeout=8)
            if result.returncode==0 and result.stdout.strip()=='YUBI_READY':return candidate
            # Authentication/name resolution failures cannot be fixed by extra hops.
            if result.returncode==255:break
        except (OSError,subprocess.SubprocessError):break
    return None

def connection_candidates():
    common=dict(remote_python=REMOTE_PYTHON,dataset_root=DATASET_ROOT)
    candidates=[dict(common,ssh_host='8xA100'),
                dict(common,ssh_host=GATEWAY_USER+'@'+GATEWAY_IP)]
    if shutil.which('tailscale'):
        candidates.append(dict(common,ssh_host='8xA100',ssh_transport='tailscale'))
    return candidates

def find_direct():
    return discover(connection_candidates()[0])

def login(config):
    """Keep authentication in the SSH terminal; persist only a control socket."""
    sockets=Path.home()/'.ssh';sockets.mkdir(mode=0o700,exist_ok=True)
    import uuid
    socket=sockets/('yubi-'+uuid.uuid4().hex[:12]+'.sock')
    flags=['-M','-S',str(socket),'-o','ControlPersist=2h','-o','ConnectTimeout=8',
           '-o','ConnectionAttempts=1','-o','NumberOfPasswordPrompts=1',
           '-o','LogLevel=QUIET','-o','RemoteCommand=none','-o','RequestTTY=no','-fN']
    command=(['tailscale','ssh',config['ssh_host']]+flags if config.get('ssh_transport')=='tailscale'
             else ['ssh']+flags+[config['ssh_host']])
    candidate=dict(config,ssh_control_path=str(socket))
    keep=False
    try:
        result=subprocess.run(command,timeout=120)
        if result.returncode:return None
        found=discover(candidate)
        if found:keep=True;return found
    except (OSError,subprocess.SubprocessError):pass
    finally:
        if not keep:
            try:subprocess.run(['ssh','-S',str(socket),'-O','exit',config['ssh_host']],capture_output=True,timeout=3)
            except (OSError,subprocess.SubprocessError):pass
    return None

def connect():
    shared=find_shared()
    if shared:return shared
    candidates=connection_candidates()
    for candidate in candidates:
        found=discover(candidate)
        if found:return found
    print('需要验证登录时，请按提示操作；密码不会保存。',flush=True)
    for candidate in candidates:
        found=login(candidate)
        if found:return found
    print('自动连接未成功。请先确认能通过 SSH 登录数据所在服务器。',flush=True)
    if not sys.stdin.isatty():
        raise RuntimeError('请在本机交互式终端重新运行 python viewer.py --setup。')
    host=input('请输入登录地址（如 用户名@IP，直接回车退出）：').strip()
    if not host:raise RuntimeError('未连接到数据服务器，请确认 SSH 登录后重试。')
    if host.startswith('-') or any(ch.isspace() for ch in host):
        raise ValueError('只输入主机别名或 用户名@IP，不要输入整条命令。')
    custom=dict(ssh_host=host,remote_python=REMOTE_PYTHON,dataset_root=DATASET_ROOT)
    found=discover(custom) or login(custom)
    if not found:raise RuntimeError('无法登录或读取数据目录，请确认该账号的数据访问权限。')
    return found

def preflight(config):
    video_cache.CONFIG=config
    code="import av,numpy,scipy,pyarrow;from pathlib import Path; p=Path("+repr(config['dataset_root'])+"); assert (p/'meta/info.json').is_file() and (p/'data').is_dir() and (p/'videos').is_dir(), 'Dataset missing';print('YUBI connection ready')"
    result=subprocess.run(video_cache.command(code),capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError('无法读取 A100 数据，请确认 SSH 连接和数据访问权限。')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config.local.json');p.add_argument('--output',default='data');a=p.parse_args()
    conf=Path(a.config).expanduser().resolve();output=Path(a.output).expanduser().resolve()
    if conf.exists() or output.exists():raise ValueError('配置或 data 目录已存在。已有配置可直接启动；重新准备请用 --config 和 --output 指定新路径。')
    print('正在连接 A100…',flush=True)
    config=connect()
    print('A100 已连接。',flush=True)
    config.update(data_root=os.path.relpath(output,conf.parent),video_cache='./.cache/videos',host='127.0.0.1',port=8768)
    preflight(config)
    result=download(config,output)
    conf.parent.mkdir(parents=True,exist_ok=True)
    with conf.open('x') as f:json.dump(config,f,ensure_ascii=False,indent=2)
    print(f'完成：{result["recordings"]} 条记录。配置保存到 {conf.name}。')
    print('启动：python viewer.py'+('' if a.config=='config.local.json' else ' --config '+shlex.quote(str(conf))))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:sys.exit('未完成：'+str(e))
