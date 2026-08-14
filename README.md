# 试卷题目打分器（智能作业批改系统）

基于多模态 AI 的中英文作业自动批改系统：上传学生作业图片与参考答案，自动完成 OCR 文字提取与语义评分。

## 拉取项目

```
git clone git@github.com:yeteye/Grade-your-homework.git
cd Grade-your-homework
```

## 环境配置

推荐 Python 3.9。使用 conda 创建独立环境并安装依赖：

```
conda create -n ggrade python=3.9 -y
conda activate ggrade
pip install -r requirements.txt
```

关键版本说明：paddlepaddle 2.6.2 针对 numpy 1.x 编译，requirements.txt 已锁定 numpy==1.26.4，请勿升级到 numpy 2.x，否则会出现 ABI 不兼容错误。

## 配置密钥

复制 `.env.example` 为 `.env` 并填入 DeepSeek API Key：

```
cp .env.example .env   # Windows: copy .env.example .env
```

`.env` 中可配置项：

| 变量 | 说明 |
| --- | --- |
| DEEPSEEK_API_KEY | DeepSeek API 密钥（在线评分必需） |
| FLASK_DEBUG | 调试模式开关，生产环境保持 0 |
| EMBEDDING_SERVICE_URL | 向量嵌入微服务地址，默认 http://127.0.0.1:8765 |

## 运行

2.5.0 起向量嵌入已拆为独立 FastAPI 微服务，需要先启动嵌入服务，再启动主应用（同一 conda 环境两个进程）：

```
# 终端 1：启动向量嵌入微服务（默认监听 127.0.0.1:8765）
python -m services.embedding_server

# 终端 2：启动主应用
python run.py
```

或双击 `run.bat`。启动后浏览器访问 http://127.0.0.1:5000/ 。嵌入服务未启动时，离线评分会明确报错并提示启动命令（fail-fast，不静默降级）；`EMBEDDING_SERVICE_URL` 环境变量可指向其他主机上的嵌入服务。

## 测试

```
pytest
```

或 `python -m pytest`。测试不依赖网络与模型，DeepSeek、OCR 与向量嵌入均已 mock，可离线运行。

## 架构

系统采用级联两阶段评分：先由离线向量嵌入（sentence-transformers 多语言 MiniLM）粗筛，离线分低于阈值（默认 60 分）或落入边界带时自动路由 DeepSeek 精排。前端勾选「强制 DeepSeek 精排」则跳过粗筛、每次都用 DeepSeek。

2.5.0 起向量嵌入拆为独立 FastAPI 微服务（services/embedding_server.py，进程隔离，避免在单体里堆模型），主应用经 HTTP 客户端（services/embedding.py）调用，接口契约不变、业务调用方零改动。嵌入模型与参考答案缓存只在服务进程常驻，主应用进程内存与启动速度得到释放。

| 模式 | 评分引擎 | 适用场景 |
| --- | --- | --- |
| 自动级联（默认） | 离线粗筛 + 低置信度自动转 DeepSeek 精排 | 精度与成本平衡 |
| 强制在线 | DeepSeek 大模型精排 | 高精度评分 |

路由策略与阈值在 utils/config.py 配置：ROUTING_MODE 取 threshold（低分路由）/ band（中段边界带）/ off（关闭路由），对应 LOW_THRESHOLD、BAND_LOW、BAND_HIGH。在线评分失败时自动降级为离线评分，并在结果中通过 degraded 字段标记。

离线评分首次调用会从 HuggingFace 下载多语言嵌入模型（约 118MB），需联网一次。之后模型已缓存时加载走本地快照路径，完全离线、不发网络请求。国内访问 huggingface.co 超时时，在 `.env` 中设 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。

## ESRGAN 图像增强（备选）

当上传的作业图片质量较低、首次 OCR 识别的平均置信度低于阈值（默认 0.6，见 `utils/config.py` 的 `ENHANCE_CONFIDENCE_THRESHOLD`）时，系统会自动调用 ESRGAN 对图片做 4x 超分并重新识别；若增强后的识别置信度更高则采用增强结果，否则维持原识别文本。该功能为备选增强，不影响 OCR 主流程。

增强使用 Real-ESRGAN 官方预训练权重 `RealESRGAN_x4plus.pth`（real-world 退化训练，对模糊/噪点/JPEG 压缩的作业图片效果优于原版 ESRGAN）。该文件不在代码仓库内，需从 [Real-ESRGAN GitHub Releases](https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth) 下载，放入 `ESRGAN/models/` 目录。国内直连 GitHub Releases 超时时，可用代理镜像 `https://gh-proxy.com/https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth`（`curl -C -` 支持断点续传）。权重文件缺失或加载失败时，系统自动降级为普通识别，仅在日志中记录一次警告，OCR 主流程不受影响。

注意增强在 CPU 上运行较慢（每张图需数秒到数十秒），且仅低置信度图片会触发；如需完全跳过增强，可删除权重文件或将 `ENHANCE_CONFIDENCE_THRESHOLD` 调低。

## 批量批改与统计报告（2.4.0）

首页点击「前往批量批改页」进入 `/batch`，一次上传一份参考答案图片与多份作业图片，系统自动逐份识别并评分，产出每题得分明细与统计报告。

- **异步批改**：提交即返回任务 ID，后台线程执行，前端轮询进度，长耗时批改不阻塞请求。
- **作业智能分区**：勾选「智能分区」后，对一张图含多道题的作业先用水平投影按题号答案切分为独立区域，逐区域 OCR 与评分，实现一图多题分别打分。
- **错因归类**：默认按分数规则分档（未作答/概念错误/要点遗漏/部分正确/掌握良好）；进阶可开启「AI 错因归类」，对 30-85 分模糊带的题目调 DeepSeek 结构化归类并给出一句话原因。
- **持久化与统计**：批改记录落 SQLite（`output/grades.db`），可按题查看人数/平均分/最高/最低/及格率/未作答数，按错因查看分布，并下载 HTML/Word 统计报告。

批量评分对参考答案嵌入做预计算缓存，同一参考对多份作业只编码一次参考向量，全部答案一次批量编码（N=20 时较逐对评分快约 4.7 倍）。

## 训练数据来源

图像增强实验使用 DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
