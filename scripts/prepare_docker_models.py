"""Docker 构建前置：从宿主机模型缓存拷贝模型到 docker/models/ 构建上下文。

背景：hf-mirror.com 与 huggingface.co 在本机网络均被阻断（实测 000 超时），
Dockerfile 若在构建期联网下载模型会失败。改为把宿主机已下载完整的模型缓存
（MiniLM 在 ~/.cache/huggingface/hub、PaddleOCR 在 ~/.paddleocr、ESRGAN 权重
在仓库 ESRGAN/models/）拷入 docker/models/，构建期纯 COPY，镜像自包含离线。

HF 缓存快照文件是指向 blobs/ 的符号链接；本脚本跟随符号链接拷真实内容并跳过
blobs/（省约 458MB）。snapshot_download(local_files_only=True) 只需 refs/ +
snapshots/<rev> 即可解析模型。PaddleOCR 离线判定只需 inference.pdmodel +
inference.pdiparams 存在，无版本标记文件。

用法：python scripts/prepare_docker_models.py [--hf-cache DIR] [--paddle-home DIR]
默认源：HF_HUB_CACHE 或 HF_HOME 或 ~/.cache/huggingface/hub；~/.paddleocr。
必须在 docker compose build 之前运行；幂等（重复运行先清空目标再拷）。
"""
import argparse
import os
import shutil
from pathlib import Path

# 目标舞台目录（相对仓库根，随 build 上下文进入镜像；docker/models/.gitignore 排除内容入库）
STAGE = Path(__file__).resolve().parent.parent / "docker" / "models"

# 需从 HF 缓存拷入镜像的模型仓库（目录名即缓存目录名）
HF_MODEL = "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"


def copy_tree(src: Path, dst: Path) -> int:
    """拷贝目录到目标（跟随符号链接拷真实内容），返回拷贝文件数。

    src 不存在时抛 FileNotFoundError（fail-fast，让缺失的模型源尽早暴露）。
    """
    if not src.exists():
        raise FileNotFoundError(f"模型源不存在: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    count = 0
    for root, dirs, files in os.walk(src, followlinks=False):
        rel = Path(root).relative_to(src)
        for name in dirs:
            (dst / rel / name).mkdir(parents=True, exist_ok=True)
        for name in files:
            s = Path(root) / name
            t = dst / rel / name
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, t)  # 跟随符号链接拷贝真实内容
            count += 1
    return count


def prepare_hf(hf_cache: Path) -> None:
    """拷贝 MiniLM 的 refs/snapshots（跳过 blobs/ 符号链接目标）到舞台。"""
    src = hf_cache / HF_MODEL
    out = STAGE / "hf_hub" / HF_MODEL
    for sub in ("refs", "snapshots"):
        n = copy_tree(src / sub, out / sub)
        print(f"hf {sub}: {n} files -> {out / sub}")
    if not (src / "refs" / "main").exists():
        raise FileNotFoundError(f"HF 缓存缺 refs/main 标记: {src}")


def prepare_paddle(paddle_home: Path) -> None:
    """拷贝 PaddleOCR 模型缓存（~/.paddleocr/whl）到舞台。"""
    src = paddle_home / "whl"
    out = STAGE / "paddleocr" / "whl"
    n = copy_tree(src, out)
    print(f"paddleocr whl: {n} files -> {out}")
    if not (out / "det" / "ch").is_dir():
        raise FileNotFoundError(f"PaddleOCR 缓存缺 ch 检测模型: {src}")


def check_esrgan() -> None:
    """校验 ESRGAN 权重存在（已属 build 上下文，无需拷贝）。"""
    weight = Path(__file__).resolve().parent.parent / "ESRGAN" / "models" / "RealESRGAN_x4plus.pth"
    if not weight.is_file():
        raise FileNotFoundError(f"ESRGAN 权重缺失: {weight}（OCR 增强将降级跳过）")
    print(f"esrgan weight OK: {weight.name}")


def main() -> None:
    """准备 docker/models/ 舞台：拷贝三个模型源并校验。"""
    parser = argparse.ArgumentParser(description="准备 Docker 构建上下文模型目录")
    parser.add_argument("--hf-cache", default=os.environ.get("HF_HUB_CACHE") or os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface" / "hub"))
    parser.add_argument("--paddle-home", default=os.environ.get("PADDLE_HOME") or str(Path.home() / ".paddleocr"))
    args = parser.parse_args()

    prepare_hf(Path(args.hf_cache))
    prepare_paddle(Path(args.paddle_home))
    check_esrgan()
    print(f"done: docker/models/ 已就绪（{sum(f.stat().st_size for f in STAGE.rglob('*') if f.is_file()) / 1024 / 1024:.0f} MB），可 docker compose build")


if __name__ == "__main__":
    main()
