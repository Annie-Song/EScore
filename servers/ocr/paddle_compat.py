"""paddle Linux wheel 兼容垫片：无 AVX-512 的 CPU 上禁用 IR 图优化。

paddlepaddle 2.6.x 的 Linux wheel 把 IR fusion pass 编译进了 AVX-512(EVEX) 指令，
在熔断 AVX-512 的 CPU（如 Raptor Lake 消费级）上执行到 OptimizeInferenceProgram 的
SelfAttentionFusePass 会触发 SIGILL（非法指令，反汇编可见 vmovss %xmm16 之类 EVEX 编码）。
Windows wheel 无此指令，宿主不受影响；故仅在 Linux 且 CPU 无 AVX-512 时给
paddle.inference.Config 的 switch_ir_optim 打补丁强制关闭 IR 优化。

注意：apply() 会 import paddle.inference，须在 charset_normalizer 已加载之后调用，
否则 requests→charset_normalizer→zlib 与 paddle 捆绑 zlib 的符号插桩会 SIGSEGV
（容器内用 LD_PRELOAD=/lib/x86_64-linux-gnu/libz.so.1 预加载系统 libz 规避，
见 docker/Dockerfile ocr 阶段；Windows 上 apply() 直接 no-op 不碰 paddle）。
"""
import sys

_CPUINFO = "/proc/cpuinfo"


def apply() -> None:
    """按平台与 CPU 特性决定是否禁用 paddle IR 图优化，幂等。

    非 Linux 或 CPU 支持 AVX-512 时保持 paddle 默认行为（IR 优化开启）；
    Linux 且无 AVX-512 时把 Config.switch_ir_optim 替换为强制关闭的包装，
    使 PaddleOCR 构造 predictor 时跳过含 AVX-512 指令的 fusion pass。
    """
    if sys.platform != "linux" or _has_avx512():
        return
    import paddle.inference as paddle_infer

    if getattr(paddle_infer.Config, "_ir_optim_compat_applied", False):
        return
    _original = paddle_infer.Config.switch_ir_optim

    def _force_off(self, flag: bool) -> None:
        _original(self, False)

    paddle_infer.Config.switch_ir_optim = _force_off
    paddle_infer.Config._ir_optim_compat_applied = True


def _has_avx512() -> bool:
    """读取 /proc/cpuinfo 的 flags 行，判断 CPU 是否支持 avx512f。"""
    try:
        with open(_CPUINFO) as fh:
            for line in fh:
                if line.startswith("flags"):
                    return "avx512f" in line
    except OSError:
        return False
    return False
