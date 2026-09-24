# YUBI 视频与轨迹查看器

选一条记录，同时看三个角度的视频和夹爪运动。

**有服务器账号，选「在线查看」；数据已下载到本机，选「本地查看」。**

<details>
<summary>第一次使用：点击展开安装步骤（两种方式都需要）</summary>

在本机终端依次运行：

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

后面的命令也在这个项目目录中运行。

</details>

## ① 在线查看：不用下载全部视频

1. **领取配置。** 向维护者领取 `data` 文件夹、已填好服务器信息的 `config.local.json`，以及 SSH 登录命令。把文件夹和配置文件放进项目目录。
2. **连接服务器。** 在本机终端运行维护者提供的 SSH 登录命令，按提示登录。
3. **打开程序。** 运行：

   ```bash
   source .venv/bin/activate
   python server.py --config config.local.json
   ```

4. **打开页面。** 在本机浏览器访问 **http://127.0.0.1:8768/**。

`data` 只存轨迹和视频索引，不是完整视频库。选哪条记录，程序就从服务器取哪条视频；看过的视频会缓存在本机。已配置过的本机直接执行第 3 步，连接失效时再执行第 2 步。

<details>
<summary>维护者：给同事准备哪些内容？</summary>

- `data/`：`groups.json`、`episode_metadata.json`、`cup_poses.npy`、`cup_angles.npy`、`smartphone_poses.npy`、`smartphone_angles.npy`。
- `config.local.json`：按 `config.example.json` 填写。`data_root` 用 `./data`，`video_cache` 用 `./.cache/videos`；填好服务器数据集路径、跳板机地址和远端 Python 路径（需有 `av`）。当前路线的 `ssh_hops` 是 `["8xA100", "8xA100"]`，后续两跳需可免密连接。
- 若第一跳需要密码，配置 `ssh_control_path` 为 `~/.ssh/yubi-viewer.sock`，提供下面的登录命令，并替换其中的跳板机地址：

  ```bash
  mkdir -p ~/.ssh
  ssh -M -S ~/.ssh/yubi-viewer.sock -o ControlPersist=2h -o RemoteCommand=none -fN steven@跳板机地址
  ```

这些资料私下交给有访问权限的同事，不提交到 GitHub。无需重新部署服务器。

</details>

## ② 本地查看：数据已下载到本机

1. **准备数据。** 下载有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena)，保留 `meta`、`data`、`videos` 三个目录。完整数据约 **2.68 TB**。
2. **填写位置。** 将 `config.example.json` 复制为 `config.local.json`，只把 `dataset_root` 改成数据集所在的完整路径，其他项保持默认。
3. **第一次使用时，读取轨迹。** 将下面的路径换成同一个数据集路径，再运行（只做一次）：

   ```bash
   source .venv/bin/activate
   python prepare_data.py --dataset /数据集所在路径 --output ./data
   ```

   如果已有查看器的 `data` 文件夹，请先确认它是配套缓存，不要重复生成或覆盖。

4. **打开程序和页面：**

   ```bash
   source .venv/bin/activate
   python server.py --config config.local.json
   ```

   在本机浏览器访问 **http://127.0.0.1:8768/**。这种方式不需要 SSH。

## 怎么看？

**选任务 → 选记录 → 等视频加载 → 点「播放」。**

- 记录太多：在选择框里翻页，或输入页码。
- 想看某一刻：拖动下面的进度条，三个视频和轨迹会一起跳转。
- 第一次加载慢：稍等，程序正在准备这条视频。
- 视频加载失败：在线方式先重新连接 SSH，再点「重试加载」。

使用期间保持程序运行。仓库只提供查看器，不包含数据和登录资料。第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
