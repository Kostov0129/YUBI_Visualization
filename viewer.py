"""Single entry point for local and SSH-backed viewing."""
import argparse, json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'app'))

def main():
    if '--setup' in sys.argv:
        sys.argv.remove('--setup')
        from setup_online import main as setup
        setup();return
    if '--local' in sys.argv:
        parser=argparse.ArgumentParser();parser.add_argument('--local',required=True);parser.add_argument('--config',default='config.local.json');parser.add_argument('--output',default='data');a=parser.parse_args()
        conf=Path(a.config).resolve();out=Path(a.output).resolve();source=Path(a.local).expanduser().resolve()
        if conf.exists():raise ValueError('配置已存在；请直接启动，或用 --config 指定新配置文件')
        from prepare_data import prepare
        result=prepare(source,out)
        conf.parent.mkdir(parents=True,exist_ok=True)
        with conf.open('x') as f:json.dump(dict(data_root=os.path.relpath(out,conf.parent),dataset_root=str(source),video_cache='./.cache/videos',host='127.0.0.1',port=8768),f,ensure_ascii=False,indent=2)
        print(f'准备完成：{result["recordings"]} 条记录。运行 python viewer.py 启动。');return
    if '--connect' in sys.argv:
        parser=argparse.ArgumentParser();parser.add_argument('--connect',action='store_true');parser.add_argument('--config',default='config.local.json');a=parser.parse_args()
        from http_server import load_config
        c=load_config(a.config)
        if not c.get('ssh_host') or not c.get('ssh_control_path'):raise ValueError('当前配置不使用 SSH 复用连接')
        check=subprocess.run(['ssh','-S',c['ssh_control_path'],'-O','check',c['ssh_host']],capture_output=True)
        if check.returncode==0:print('SSH 连接可用。');return
        if c.get('shared_connection'):raise ValueError('原共享 SSH 连接已关闭，请在原终端重新建立同一路线的共享连接后重试。')
        subprocess.run(['ssh','-M','-S',c['ssh_control_path'],'-o','ControlPersist=2h','-o','ConnectTimeout=20','-o','RemoteCommand=none','-o','RequestTTY=no','-fN',c['ssh_host']],check=True)
        print('SSH 已连接，可以启动查看器。');return
    from http_server import main as serve
    serve()

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:sys.exit('未完成：'+str(e))
