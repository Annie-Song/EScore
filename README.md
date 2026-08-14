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

## 运行

```
python run.py
```

或双击 `run.bat`。启动后浏览器访问 http://127.0.0.1:5000/ 。

## 测试

```
pytest
```

或 `python -m pytest`。测试不依赖网络与模型，DeepSeek、OCR 与向量嵌入均已 mock，可离线运行。

## 架构

系统采用级联两阶段评分：先由离线向量嵌入（sentence-transformers 多语言 MiniLM）粗筛，离线分低于阈值（默认 60 分）或落入边界带时自动路由 DeepSeek 精排。前端勾选「强制 DeepSeek 精排」则跳过粗筛、每次都用 DeepSeek。

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

## 训练数据来源

图像增强实验使用 DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
