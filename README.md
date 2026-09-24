# YUBI 轨迹与同步视频查看器

按任务选择 UMI 记录，查看双手轨迹、YUBI 夹爪和左腕／中间／右腕三路视频。支持杯子放上盘子再放回、手机装盒两个任务。记录选择框内支持上一页、下一页、输入页码跳转；每页 25 条。暂停时也能旋转、缩放。

本项目是数据查看器。官方 replay 子集是官方清单中的记录，视频可能是人持 UMI/YUBI 采集画面；不代表固定机械臂实机执行。参考 IK 是可选的已计算结果，不是在线碰撞检测或实机控制。

## 本机部署（Python 3.12）

先自行获得并下载有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena)。需要 `meta/`、`data/` 和播放时使用的 `videos/`。仓库不附带示范、视频、账户或安装标定数据。

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

## 数据在远程服务器

推荐在本机或挂载目录准备轨迹缓存 `data/`，视频原件保留在数据服务器。远端 Python 需已有 `av`。配置示例（自行填写 SSH 别名）：

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

先在自己的 SSH 配置中设置连接，确保 `ssh -T -o BatchMode=yes dataset-server true` 能成功。可用 SSH `ProxyJump`；若下一跳的密钥只在上一跳机器上，可将后续别名依次放在 `ssh_hops`。登录资料不写入仓库。`ssh_control_path` 可选，支持已有的 SSH 复用连接。

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
