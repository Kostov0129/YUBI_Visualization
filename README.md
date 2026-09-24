# YUBI 轨迹与同步视频查看器

按任务选择 UMI 记录，查看双手轨迹、YUBI 夹爪和左腕／中间／右腕三路视频。支持杯子放上盘子再放回、手机装盒两个任务。记录选择框内支持上一页、下一页、输入页码跳转；每页 25 条。暂停时也能旋转、缩放。

本项目是数据查看器。官方 replay 子集是官方清单中的记录，视频可能是人持 UMI/YUBI 采集画面；不代表固定机械臂实机执行。参考 IK 是可选的已计算结果，不是在线碰撞检测或实机控制。

## 先选使用方式：无需下载完整数据集

| 场景 | 查看器运行在哪里 | 本机需要保存什么 |
|---|---|---|
| 团队成员通过 SSH 看服务器数据（下面的主流程） | 数据所在服务器 | 浏览器播放缓冲；不用下载 parquet 或完整视频库 |
| 当前已有本机轨迹缓存的使用者 | 本机，SSH 按需取远端视频 | 派生轨迹缓存 + 看过的记录视频 |
| 已经有本地数据集 | 本机 | 原有数据及派生缓存 |

GitHub 是代码和说明入口，不能直接在 GitHub 页面播放服务器上的视频。观看时始终在**自己电脑的浏览器**打开 `http://127.0.0.1:8768/`。完整数据集约 2.68 TB，不需要为了看视频先复制它。

## 团队推荐：服务器运行，SSH 转发到本机浏览器

### 1. 一次性准备（由维护者在最终数据服务器完成）

如果团队已经启动了查看器，直接向维护者确认监听地址、端口和 SSH 路线，跳到步骤 2。**不要每人重复导入或启动相同端口。**

下面命令运行在最后一跳、实际能读取数据集的服务器上，而不是 steven 跳板机。项目和缓存放自己的工作目录，原数据只读；不需要 sudo，也不改系统服务。这里是部署说明，不表示仓库已自动替你在服务器部署。

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 替换为服务器已有数据集的真实路径，不重新下载数据集。
python prepare_data.py --dataset /path/to/yubi-corl2026-umi-arena --output ./data
cp config.example.json config.local.json
```

修改 `config.local.json`：

```json
{
  "data_root": "./data",
  "dataset_root": "/path/to/yubi-corl2026-umi-arena",
  "video_cache": "./.cache/videos",
  "host": "127.0.0.1",
  "port": 8768,
  "ssh_host": "",
  "ssh_hops": []
}
```

这里 `ssh_host` 留空：后端已在最终服务器，直接读取当地视频，不再嵌套 SSH。首次导入会扫描 parquet 并生成两项任务的派生轨迹缓存；有磁盘读取开销，但不会复制全部视频。团队准备一次后共用即可；已有兼容缓存可直接将 `data_root` 指向它，跳过导入。原始 parquet 保持不变。

```bash
python server.py --config config.local.json
```

保持这个进程运行（可使用已有的 tmux 会话）。缓存按看过的记录增长，写在部署机器的 `.cache/videos/`，不是原始数据目录；由维护者按需清理。此流程只需 CPU 解码，无需占用 A100 GPU。

### 2. 从本机建立 SSH 隧道

**能直接 SSH 到最终服务器时**，在本机终端运行：

```bash
ssh -N -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8768:127.0.0.1:8768 dataset-server
```

`dataset-server` 是你自己已配置、可登录最终服务器的 SSH 别名。若本机可通过 `ProxyJump` 到达最终服务器，也可以使用该别名。保持 SSH 终端连接，然后在本机浏览器打开 <http://127.0.0.1:8768/>。

**只有 steven 能免密进入下一跳，且两次 `ssh 8xA100` 才到数据机时**，使用分段转发，沿用各台机器自己的密钥和 SSH 别名。以下三条命令依次在登录后出现的 shell 中执行：

```bash
# A：自己电脑 → steven 跳板机。先替换 GATEWAY_HOST。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8768:127.0.0.1:18768 steven@GATEWAY_HOST

# B：现在在 steven 上 → 中间机器。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18768:127.0.0.1:18768 8xA100

# C：现在在中间机器上 → 最终数据服务器。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18768:127.0.0.1:8768 8xA100
```

这里两个 `8xA100` 分别由所在机器解析，并非本机连续调用同一个别名。`RemoteCommand=none` 用来取消别名里自动跳转的命令，避免额外跳转；`-t` 保留交互 shell，方便输入下一条 SSH。最终后端仍只监听 `127.0.0.1:8768`，无需开放服务器防火墙或公网端口。

保持整条连接存活，在**本机浏览器**打开 <http://127.0.0.1:8768/>。如果尚未启动后端，可在 C 的最终 shell 中进入项目并启动它。关闭 SSH 后页面无法继续取数据。团队成员应选未占用的转发端口；若共用跳板账号，18768 冲突时请将 B、C 的监听端口及上一跳对应目标端口一起改成自己的一组空闲端口。本机已有查看器占用 8768 时，只将 A 的本地端口改成 8769，并在浏览器访问 8769。

### 3. 如何在页面看视频

1. 选“数据范围”（全部或官方 replay 子集），再选任务。
2. 展开“选择记录”，在同一个框内翻页或输入页码，点击要看的记录。
3. 等下方出现“三路视频 · 与轨迹同步”，点击“播放”。左腕、中间、右腕画面与夹爪轨迹同步。
4. 拖动帧进度可定位画面；改变倍速会同步改变视频速度。翻页只浏览选项，选中记录才加载。

第一次选某条记录需等待视频提取，之后命中缓存会更快。“无需下载全量数据”不等于没有网络传输：当前记录视频仍需传到浏览器，浏览器会产生正常的播放缓冲。

### 常见问题

- **网页打不开**：确认隧道仍连接、最终服务器后端仍运行、端口一致。`Address already in use` 表示端口冲突，不要终止其他人的进程，换自己的转发端口。
- **有轨迹但没有视频**：检查最终服务器的 `dataset_root`、读取权限和 Python `av` 是否可用；查看 `.cache/videos/<uuid>/transfer.log`。修复后点“重试加载”。
- **SSH 登录成功但转发报错**：SSH 服务可能禁用了端口转发，需服务器维护者确认；普通 SSH shell 可用并不保证转发可用。
- **视频里是人手拿 UMI**：这是示范采集视频。官方 replay 子集并不意味着画面一定是固定机械臂实机执行。

## 可选：已有本地数据时部署（Python 3.12）

仅适用于已经持有本地数据的使用者。使用有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena)。需要 `meta/`、`data/` 和播放时使用的 `videos/`。仓库不附带示范、视频、账户或安装标定数据。

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python prepare_data.py --dataset /path/to/yubi-corl2026-umi-arena --output ./data
cp config.example.json config.local.json
```

将 `config.local.json` 的 `dataset_root` 改成自己的数据集目录，然后启动：

```bash
python server.py --config config.local.json
```

访问 <http://127.0.0.1:8768/>。数据导入只读原始文件，扫描两项任务所有记录，按 UUID 和 PA 顺序组织；不是质量筛选。导入会检查缺帧、重复帧、位姿维度和数值。派生数组、元数据和清单写入 `data/`，输出目录必须尚不存在。当前支持该数据集的 30 FPS、xyz+xyzw 四元数、两路夹爪角度格式；其他数据格式应先适配。

## 视频如何播放

1. 选择记录后，后端用 episode 元数据找到各相机 MP4 文件、片段起始时间和帧数。
2. 将该记录的各 PA 片段按轨迹顺序拼接为三路 640×480、30 FPS MP4。按需处理，一次处理一条，不预下载全部视频。
3. 生成的视频存入部署机器的 `.cache/videos/<uuid>/`。已缓存的记录直接播放；首次加载需等待解码和传输。
4. 浏览器通过 HTTP Range 播放视频。三路视频共用轨迹的播放／暂停、倍速和进度条，以 `帧号 / 30` 对齐，定期纠偏。浏览器解码和网络可能带来短暂同步误差，不是硬件同步测量工具。

源数据更新后应清理对应 UUID 的派生视频缓存再加载。默认每条转换超时 240 秒，超长记录可能需要调整 `video_cache.py` 中的限制。

## 可选：本机查看器 + SSH 按需取视频（当前本机使用方式）

本方式需要本机已有兼容的派生轨迹缓存 `data/`；仅 clone 仓库和填 SSH 地址还不能启动。可由维护者私下提供缓存，或按前述服务器流程使用远端查看器，免去本机缓存准备。当前已有缓存的本机打开 <http://127.0.0.1:8768/> 即可观看，无需再导入或往 U 盘复制。视频原件保留在数据服务器。远端 Python 需已有 `av`。配置示例（自行填写 SSH 别名）：

```json
{
  "data_root": "./data",
  "dataset_root": "/path/on/server/to/dataset",
  "video_cache": "./.cache/videos",
  "ssh_host": "dataset-server",
  "ssh_hops": [],
  "remote_python": "/path/to/python-with-av",
  "port": 8768
}
```

两次 `ssh 8xA100` 的路线可填写 `"ssh_host": "steven@GATEWAY_HOST"`、`"ssh_hops": ["8xA100", "8xA100"]`，`remote_python` 填最终机器上能导入 `av` 的 Python 路径。上面所有路径和主机名都是占位符，请向维护者获取实际值。

先在自己的 SSH 配置中设置连接，确保 `ssh -T -o BatchMode=yes dataset-server true` 能成功。可用 SSH `ProxyJump`；若下一跳的密钥只在上一跳机器上，可将后续别名依次放在 `ssh_hops`。登录资料不写入仓库。`ssh_control_path` 可选，支持已有的 SSH 复用连接。若第一跳需要交互登录，先在本机手动建立连接，再让后端复用它：

```bash
mkdir -p ~/.ssh
ssh -M -S ~/.ssh/yubi-viewer.sock -o ControlPersist=2h \
  -o RemoteCommand=none -fN steven@GATEWAY_HOST
```

将 `ssh_control_path` 设为 `~/.ssh/yubi-viewer.sock`。后续两跳仍须能免密执行；后台视频请求不能弹出密码输入。复用连接失效后重新建立，再点页面“重试加载”。

远端仅解码当前记录，MP4 在内存生成后传回；缓存和转换日志都写到运行查看器的机器，不向数据服务器写入文件。无需将整个视频库复制到本机。轨迹导入本身需要能读取原始 parquet 的本地／挂载目录，也可由持有数据的同事准备派生 `data/` 后私下传给其他成员。

## Docker（本地或挂载数据）

先按上述步骤生成 `data/`，然后：

```bash
cp config.docker.example.json config.docker.local.json
export YUBI_DATASET_ROOT=/absolute/path/to/yubi-corl2026-umi-arena
docker compose up --build -d
```

仍访问 <http://127.0.0.1:8768/>。Compose 只绑定本机端口；原始数据与轨迹缓存只读挂载，视频缓存可写。Docker 配置已提供，当前验证的是 Python 启动流程，未在本机运行 Docker 构建。

团队成员可分别部署；如共享一台部署服务器，可通过 SSH 端口转发访问。应用本身不带登录鉴权，不应直接将数据接口开放到公网。GitHub Pages 只能托管静态页面，不能替代此 Python 数据／视频后端。

## 可选参考 IK

普通部署只显示原始双手轨迹。已有参考 IK 的使用者可在私有 `data/ik/` 下提供 `models.json`、`used_setup.json`、`group_labels.jsonl`，以及标签所引用的关节解文件。模型格式须符合 `storage.py`；引用文件路径应相对 `data_root`。已兼容旧缓存的 `incremental_start_refit/` 等布局。法兰到夹爪工具变换和初始安装配置是否已标定由数据提供者负责；可视化不重新解 IK，不将旧参考解宣称为实机可达。

## 开发与验证

```bash
python -m unittest discover -s tests -v
```

测试包含乱序帧重排、缺帧／重复帧拒绝、跨片段视频提取及画面对齐、HTTP Range 和非公开文件访问隔离。前端 Three.js 已内置，无需 npm 或运行时 CDN；不支持 WebGL 的浏览器会使用 SVG 回退。

`config.local.json`、`config.*.local.json`、`data/`、`.cache/`、视频和数组均已忽略，不提交到 Git。第三方模型及代码来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
