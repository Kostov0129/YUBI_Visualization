# YUBI 轨迹与视频查看器

选择任务和记录，同步查看双手轨迹、夹爪以及左腕／中间／右腕三路视频。支持「杯子放上盘子再放回」和「手机装盒」。

**两种使用方式：① 数据在服务器，通过 SSH 在线看；② 数据已下载，设置本地路径看。**

## ① Online：SSH 在线看，不下载整个数据集

查看器运行在数据服务器上，你在自己电脑的浏览器里观看。

### 服务器端：维护者准备一次

在**实际存放数据的最终服务器**上执行。如果团队已经启动了查看器，跳过这一步。

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 替换为服务器上的数据集路径；只读原数据，生成查看器需要的轨迹缓存。
python prepare_data.py --dataset /path/to/dataset --output ./data
cp config.example.json config.local.json
```

将 `config.local.json` 改为：

```json
{
  "data_root": "./data",
  "dataset_root": "/path/to/dataset",
  "video_cache": "./.cache/videos",
  "host": "127.0.0.1",
  "port": 8768
}
```

启动并保持运行：

```bash
python server.py --config config.local.json
```

### 自己电脑：连接 SSH，然后打开浏览器

能直接登录最终服务器时：

```bash
ssh -N -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8768:127.0.0.1:8768 用户名@服务器地址
```

如果使用 **steven → 8xA100 → 8xA100** 的路线，依次执行以下三条命令。每条都在上一条登录成功后的终端里执行：

```bash
# 1. 在自己电脑执行，替换跳板机地址。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8768:127.0.0.1:18768 steven@跳板机地址

# 2. 登录 steven 后执行。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18768:127.0.0.1:18768 8xA100

# 3. 进入中间机器后执行。
ssh -t -o RemoteCommand=none -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18768:127.0.0.1:8768 8xA100
```

保持 SSH 连接，在**自己电脑**打开 **<http://127.0.0.1:8768/>**。

无需下载完整数据集；只传输正在看的记录。视频缓存保存在运行查看器的服务器上，不修改原始数据。

## ② Local：下载数据，设置本地路径

先下载有访问权限的 [YUBI 数据集](https://huggingface.co/datasets/airoa-org/yubi-corl2026-umi-arena)，保留以下目录结构。完整数据约 **2.68 TB**，请先确认磁盘空间。

```text
yubi-corl2026-umi-arena/
├── meta/
├── data/
└── videos/
```

在**自己电脑**执行：

```bash
git clone https://github.com/Kostov0129/YUBI_Visualization.git
cd YUBI_Visualization
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python prepare_data.py --dataset /本地数据集路径 --output ./data
cp config.example.json config.local.json
```

按上面的配置示例，将 `dataset_root` 换成**本地数据集路径**，其他项不变。然后启动：

```bash
python server.py --config config.local.json
```

打开 **<http://127.0.0.1:8768/>**，不需要 SSH。

> `dataset_root` 指向原始数据集；`data_root` 指向导入生成的轨迹缓存。导入只需做一次，`--output` 必须是尚不存在的目录。

## 怎么播放

**选择任务 → 展开“选择记录” → 翻页或输入页码 → 选中记录 → 等三路视频就绪 → 播放。**

进度条和倍速同时控制轨迹与视频。首次加载需要提取片段，之后使用缓存。暂停时也能旋转、缩放三维视角。视频可能是人持 UMI 的示范画面，不一定是固定机械臂执行。

## 遇到问题

- **网页打不开：**确认查看器进程和 SSH 连接仍在运行。
- **端口被占用：**本机 8768 已被使用时，把 SSH 命令的第一个 `8768` 改成 `8769`，浏览器也访问 8769。跳板机 18768 冲突时，整条链路中的 `18768` 一起换成另一空闲端口。
- **有轨迹、没视频：**检查 `dataset_root` 和文件读取权限；查看 `.cache/videos/<记录 UUID>/transfer.log`，修复后点“重试加载”。

仓库只包含程序，不包含数据或登录资料。默认仅监听本机地址，通过 SSH 访问；GitHub 页面本身不能播放服务器视频。Python 3.12 启动流程已验证；第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
