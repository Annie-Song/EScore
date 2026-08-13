"""RRDBNet 超分网络结构（迁移自 ESRGAN 官方实现）。

仅包含网络定义，不含模型加载与推理副作用，供 services.enhance 懒加载使用。
注意：属性名（RRDB_trunk、HRconv、RDB1 等）必须与官方预训练权重的
state_dict 键保持一致，否则 load_state_dict(strict=True) 会因键不匹配而失败。
"""
import functools
from typing import Callable

import torch
import torch.nn as nn
import torch.nn.functional as F


def make_layer(block: Callable[[], nn.Module], n_layers: int) -> nn.Sequential:
    """将 block 类重复 n_layers 次堆叠为 Sequential 模块。"""
    layers = [block() for _ in range(n_layers)]
    return nn.Sequential(*layers)


class ResidualDenseBlock_5C(nn.Module):
    """残差稠密块：5 个卷积的稠密连接，输出按 0.2 残差缩放后与输入相加。"""

    def __init__(self, nf: int = 64, gc: int = 32, bias: bool = True) -> None:
        super().__init__()
        # gc: growth channel，即每层卷积的输出通道增量
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1, bias=bias)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1, bias=bias)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1, bias=bias)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1, bias=bias)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1, bias=bias)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """稠密连接前向，返回 x5 * 0.2 + x。"""
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    """Residual in Residual Dense Block：3 个残差稠密块的嵌套残差结构。"""

    def __init__(self, nf: int, gc: int = 32) -> None:
        super().__init__()
        self.RDB1 = ResidualDenseBlock_5C(nf, gc)
        self.RDB2 = ResidualDenseBlock_5C(nf, gc)
        self.RDB3 = ResidualDenseBlock_5C(nf, gc)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """三级稠密块串联后返回 out * 0.2 + x。"""
        out = self.RDB1(x)
        out = self.RDB2(out)
        out = self.RDB3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """RRDBNet 主网络：conv_first → RRDB trunk → 两级 2x 最近邻上采样 → conv_last。

    输入输出均为 3 通道、0-1 归一化的 Tensor，整体放大倍数固定为 4x。
    """

    def __init__(self, in_nc: int, out_nc: int, nf: int, nb: int, gc: int = 32) -> None:
        super().__init__()
        rrdb_block_f = functools.partial(RRDB, nf=nf, gc=gc)
        self.conv_first = nn.Conv2d(in_nc, nf, 3, 1, 1, bias=True)
        self.RRDB_trunk = make_layer(rrdb_block_f, nb)
        self.trunk_conv = nn.Conv2d(nf, nf, 3, 1, 1, bias=True)
        self.upconv1 = nn.Conv2d(nf, nf, 3, 1, 1, bias=True)
        self.upconv2 = nn.Conv2d(nf, nf, 3, 1, 1, bias=True)
        self.HRconv = nn.Conv2d(nf, nf, 3, 1, 1, bias=True)
        self.conv_last = nn.Conv2d(nf, out_nc, 3, 1, 1, bias=True)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向：残差主干特征叠加后经两级最近邻上采样输出 4x 图像。"""
        fea = self.conv_first(x)
        trunk = self.trunk_conv(self.RRDB_trunk(fea))
        fea = fea + trunk
        fea = self.lrelu(self.upconv1(F.interpolate(fea, scale_factor=2, mode='nearest')))
        fea = self.lrelu(self.upconv2(F.interpolate(fea, scale_factor=2, mode='nearest')))
        out = self.conv_last(self.lrelu(self.HRconv(fea)))
        return out
