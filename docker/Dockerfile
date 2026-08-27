# 注意：本机 docker.io 被墙，`# syntax=docker/dockerfile:1` 指令会触发从 registry 拉取
# dockerfile 前端镜像而失败，故不使用该指令，直接依赖 BuildKit 内置前端（等价）。
# 多目标构建：base(依赖) → code(源码) → embedding/ocr/app 三个运行镜像。
# 模型由 scripts/prepare_docker_models.py 从宿主机拷入 docker/models/，构建期纯 COPY，
# 镜像构建完成后自包含离线，运行时零外网下载（hf-mirror.com 在本机被墙，不可依赖）。
# 三目标共享 base+code 层，torch+paddle+opencv 等重依赖只在磁盘存一份。

# paddlepaddle 2.6.2 按 2023 年基线（glibc 2.31/zlib 1.2.11 时代）构建；
# Debian bookworm（glibc 2.36/zlib 1.2.13）下 PaddleOCR 实例化会 SIGSEGV（inflateReset2 崩溃），
# 故基础镜像用 bullseye（glibc 2.31）与之匹配
FROM python:3.9-slim-bullseye AS base

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
COPY requirements.txt ./requirements.txt
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

ENV OCR_DEVICE=cpu \
    OCR_CPU_THREADS=4 \
    LD_PRELOAD=/lib/x86_64-linux-gnu/libz.so.1
# LD_PRELOAD 系统 libz：paddle 2.6.x Linux wheel 把自有 zlib 静态编进 libpaddle.so
# 并导出 inflate* 符号，会插桩系统 libz；后加载的 charset_normalizer(cd, Cython) 经
# Python zlib 初始化时 inflateInit2_ 内部调用 inflateReset2 被解析到 paddle 版本，
# 流布局不匹配 → free 垃圾指针 SIGSEGV。预加载系统 libz 抢先绑定符号规避之。

# 拷贝本地 PaddleOCR 模型缓存（det/rec/cls，ch/en 齐全）
COPY docker/models/paddleocr/ /root/.paddleocr/
# ESRGAN 权重在构建上下文（仓库内，gitignore 但已在磁盘）；缺失则本行 COPY 失败（fail-fast）
COPY ESRGAN/models/RealESRGAN_x4plus.pth ./ESRGAN/models/RealESRGAN_x4plus.pth

# 冒烟：走真实识别路径（含 paddle_compat 在无 AVX-512 CPU 上禁用 IR 图优化的兜底）
# + ESRGAN 权重可加载校验。fail-fast：任一失败则镜像构建中止。
RUN python -c "\
import cv2;\
import numpy as np;\
img = np.zeros((64, 256, 3), np.uint8);\
cv2.putText(img, 'Hello 123', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2);\
cv2.imwrite('/tmp/prewarm.png', img);\
from servers.ocr import core;\
text = core.recognize_single('/tmp/prewarm.png', lang='ch');\
assert 'Hello' in text, f'OCR prewarm failed: {text!r}';\
from servers.ocr.enhance import is_available;\
assert is_available(), 'ESRGAN weight not loadable';\
print('ocr prewarm OK:', text)"

CMD ["python", "-m", "servers.ocr.server"]

# ---- Flask 主应用 :5000 ----
FROM code AS app

CMD ["python", "run.py"]
