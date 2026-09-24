# YUBI 视频查看器

在本机查看 A100 上的任务视频和夹爪轨迹。

## 1. 安装（首次使用）

在本机终端依次运行：

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置（首次使用）

```bash
python viewer.py --setup
```

程序自动连接 A100，使用固定的数据路径，无需填写。若提示密码，输入 SSH 登录密码。只准备记录目录，不下载完整视频库。

## 3. 打开查看器

```bash
python viewer.py
```

在本机浏览器打开终端显示的地址，选择任务和记录即可播放。

以后使用，在本机终端进入 `YUBI_Visualization` 文件夹，先运行 `source .venv/bin/activate`，再运行 `python viewer.py`。
