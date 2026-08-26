# syntax=docker/dockerfile:1
# 多目标构建：base(依赖) → code(源码) → embedding/ocr/app 三个运行镜像。
# 模型由 scripts/prepare_docker_models.py 从宿主机拷入 docker/models/，构建期纯 COPY，
# 镜像构建完成后自包含离线，运行时零外网下载（hf-mirror.com 在本机被墙，不可依赖）。
# 三目标共享 base+code 层，torch+paddle+opencv 等重依赖只在磁盘存一份。

FROM python:3.9-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1

WORKDIR /app

# Paddle 需 OpenMP（libgomp1）；OpenCV（paddleocr 传递依赖，非 headless）需 libGL/libglib
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# pypi.org 与清华 tuna 实测均可达；tuna 更稳
RUN python -m pip install \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# ---- 共享代码层（三目标复用同一 COPY 层） ----
FROM base AS code

COPY backend/ ./backend/
COPY servers/ ./servers/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY run.py ./run.py
COPY requirements.txt ./requirements.txt
COPY .env.example ./.env.example

# ---- 向量嵌入微服务 :8765 ----
FROM code AS embedding

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# 拷贝本地 HF 缓存（refs+snapshots，构建期已跟随符号链接展开真实文件）
COPY docker/models/hf_hub/ /root/.cache/huggingface/hub/

# 冒烟：走与运行时完全一致的 snapshot_download(local_files_only=True) 路径
RUN python -c "\
from huggingface_hub import snapshot_download;\
from sentence_transformers import SentenceTransformer;\
p = snapshot_download('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', local_files_only=True);\
m = SentenceTransformer(p);\
assert m.encode(['测试']).shape == (1, 384), 'embedding shape mismatch';\
print('embedding prewarm OK')"

CMD ["python", "-m", "servers.embedding.server"]

# ---- OCR 微服务 :8766 ----
FROM code AS ocr

ENV OCR_DEVICE=cpu OCR_CPU_THREADS=4
# 拷贝本地 PaddleOCR 模型缓存（det/rec/cls，ch/en 齐全）
COPY docker/models/paddleocr/ /root/.paddleocr/
# ESRGAN 权重在构建上下文（仓库内，gitignore 但已在磁盘）；缺失则本行 COPY 失败（fail-fast）
COPY ESRGAN/models/RealESRGAN_x4plus.pth ./ESRGAN/models/RealESRGAN_x4plus.pth

# 冒烟：离线实例化 ch/en 两套 PaddleOCR + 校验 ESRGAN 权重可加载
RUN python -c "\
from paddleocr import PaddleOCR;\
PaddleOCR(show_log=False, use_angle_cls=True, lang='ch', cpu_threads=4, device='cpu');\
PaddleOCR(show_log=False, use_angle_cls=True, lang='en', cpu_threads=4, device='cpu');\
print('paddleocr ch/en prewarm OK')"
RUN python -c "\
from servers.ocr.enhance import is_available;\
assert is_available(), 'ESRGAN weight not loadable';\
print('esrgan prewarm OK')"

CMD ["python", "-m", "servers.ocr.server"]

# ---- Flask 主应用 :5000 ----
FROM code AS app

CMD ["python", "run.py"]
