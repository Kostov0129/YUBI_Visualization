# YUBI 视频查看器

**选任务 → 选记录 → 播放。** 同时查看三个角度的视频和夹爪轨迹。

**通常在本机终端的 `YUBI_Visualization` 项目目录中运行以下命令。** 如果选择在 steven 上运行，程序和缓存就位于 steven；本机浏览器需通过下方说明的 SSH 转发访问。

在线查看的关系是：**本机浏览器 → 本机查看器 → SSH → A100 数据**。因此页面地址是本机的 `127.0.0.1`；视频原件仍在 A100。

只需用到一个入口：`viewer.py`。其他程序和模型放在 `app/`，不用逐个操作。

## 首次安装

在本机终端运行：

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ① Online：数据在 A100，通过 SSH 看

在本机运行一次：

```bash
python viewer.py --setup
```

程序先查找本机已有的**共享 SSH 连接**，自动判断还需几次跳转才能到 A100。数据路径固定，不需要填写。

普通终端里的 SSH 登录不一定可复用。如果希望复用另一个窗口，请在那个窗口登录时加上共享选项：

```bash
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/yubi-shared.sock -o ControlPersist=2h 用户名@平时登录的地址
```

保持这个窗口连接，再在本机项目目录运行 `--setup`。已有 `-S` 或 `ControlPath` 的连接也会尝试检测。

找不到共享连接时，程序会自动走团队的 steven 路线：已在 steven 上则免密继续，否则按提示登录 steven，后续自动跳转。**密码不保存。**

首次只读取记录目录，不扫描全部轨迹、不下载完整视频库。选择哪条记录，才读取哪条轨迹和视频；读取过的内容缓存在本机。

然后启动：

```bash
python viewer.py
```

打开终端打印的「本机查看地址」，选记录即可看视频。通常是 `http://127.0.0.1:8768/`，端口被占用时会自动选择其他可用端口。

## ② Local：数据已下载到本机

将下面的路径换成数据集所在目录，运行一次：

```bash
python viewer.py --local /本地数据集路径
```

这个目录里应有 `meta`、`data`、`videos` 三个文件夹。程序会自动保存路径并准备轨迹。然后启动：

```bash
python viewer.py
```

打开终端打印的「本机查看地址」。这种方式不需要 SSH。

## 下次使用

进入项目目录后运行：

```bash
source .venv/bin/activate
python viewer.py
```

- **在线连接过期：**复用的 SSH 连接请在原窗口重新连接；由程序建立的连接可运行 `python viewer.py --connect`。然后重试。
- **想看某一刻：**拖动进度条，三个视频和轨迹会一起跳转。
- **首次加载慢：**稍等，程序正在准备选中的视频。看过的视频缓存在本机。

<details>
<summary>补充说明（遇到配置问题再看）</summary>

- 团队固定数据路径：`/mnt/data/benyun/workspace/yubi-corl2026-umi-arena`；固定 Python：`/home/benyun/.venvs/umi_arena_pi05/bin/python`。密码不写入程序或配置。
- 如果查看器运行在 steven，而浏览器在本机，在本机另开终端运行 `ssh -N -o RemoteCommand=none -L 127.0.0.1:8768:127.0.0.1:8768 steven@100.89.168.79` 并保持连接，再打开同一个网页地址。
- 在线读取要求远端 Python 已有 `numpy`、`scipy`、`pyarrow`、`av`；后续 SSH 跳转沿用服务器已有免密连接。程序不会在远端安装软件。
- `--setup` / `--local` 只需运行一次；默认生成本机 `data/` 和 `config.local.json`。已存在时不会覆盖；需重新配置可用 `--output 新目录 --config 新配置.json`，启动时也加 `--config 新配置.json`。
- `data/` 是查看器轨迹缓存；视频缓存位于 `.cache/videos/`。这些数据和登录配置均不会上传 GitHub。
- 本地数据可从有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena) 获取。完整数据约 2.68 TB，先确认磁盘空间。
- 默认自动避开已占用的本机端口；也可用 `python viewer.py --port 8769` 指定端口。`127.0.0.1` 总是指打开浏览器的那台电脑，各人的同名地址互不冲突。
- 视频可能是人持 UMI 的示范画面，不一定是固定机械臂执行。
- 验证程序：`PYTHONPATH=app python -m unittest discover -s app/tests -v`。第三方来源见 [说明](app/THIRD_PARTY_NOTICES.md)。

</details>
