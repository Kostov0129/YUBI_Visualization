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

程序会自动识别运行位置：

- 已在 `steven@100.89.168.79` 上运行：直接使用现有免密连接进入 A100。
- 在其他本机运行：先登录 `steven@100.89.168.79`；如果提示密码，输入 SSH 密码，后续自动免密跳转。

**不用填写服务器地址、数据路径或 Python 路径。** 程序已使用团队固定路径，等待准备完成即可。程序会自动生成本机需要的轨迹缓存和配置，**不用领取文件，也不用下载完整视频库**。首次准备会读取服务器轨迹并传回约数百 MB 数据，请耐心等待；不在服务器写入缓存或修改原始文件。

然后启动：

```bash
python viewer.py
```

在本机浏览器打开 [http://127.0.0.1:8768/](http://127.0.0.1:8768/)，选记录即可看视频。

## ② Local：数据已下载到本机

将下面的路径换成数据集所在目录，运行一次：

```bash
python viewer.py --local /本地数据集路径
```

这个目录里应有 `meta`、`data`、`videos` 三个文件夹。程序会自动保存路径并准备轨迹。然后启动：

```bash
python viewer.py
```

在本机浏览器打开 [http://127.0.0.1:8768/](http://127.0.0.1:8768/)。这种方式不需要 SSH。

## 下次使用

进入项目目录后运行：

```bash
source .venv/bin/activate
python viewer.py
```

- **在线连接过期：**先运行 `python viewer.py --connect` 重新登录，再点页面上的“重试加载”。
- **想看某一刻：**拖动进度条，三个视频和轨迹会一起跳转。
- **首次加载慢：**稍等，程序正在准备选中的视频。看过的视频缓存在本机。

<details>
<summary>补充说明（遇到配置问题再看）</summary>

- 团队固定数据路径：`/mnt/data/benyun/yubi-corl2026-umi-arena`；固定 Python：`/home/benyun/.venvs/umi_arena_pi05/bin/python`。密码不写入程序或配置。
- 如果查看器运行在 steven，而浏览器在本机，在本机另开终端运行 `ssh -N -o RemoteCommand=none -L 127.0.0.1:8768:127.0.0.1:8768 steven@100.89.168.79` 并保持连接，再打开同一个网页地址。
- 在线读取要求远端 Python 已有 `numpy`、`scipy`、`pyarrow`、`av`；后续 SSH 跳转沿用服务器已有免密连接。程序不会在远端安装软件。
- `--setup` / `--local` 只需运行一次；默认生成本机 `data/` 和 `config.local.json`。已存在时不会覆盖；需重新配置可用 `--output 新目录 --config 新配置.json`，启动时也加 `--config 新配置.json`。
- `data/` 是查看器轨迹缓存；视频缓存位于 `.cache/videos/`。这些数据和登录配置均不会上传 GitHub。
- 本地数据可从有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena) 获取。完整数据约 2.68 TB，先确认磁盘空间。
- 本机端口 8768 被占用时，运行 `python viewer.py --port 8769`，并访问 8769。
- 视频可能是人持 UMI 的示范画面，不一定是固定机械臂执行。
- 验证程序：`PYTHONPATH=app python -m unittest discover -s app/tests -v`。第三方来源见 [说明](app/THIRD_PARTY_NOTICES.md)。

</details>
