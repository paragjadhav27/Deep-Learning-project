# ruff: noqa
# mypy: ignore-errors
"""MiVOLO architecture, vendored. See NOTICE.md for provenance, license, and changes.

Code adapted from timm https://github.com/huggingface/pytorch-image-models
Modifications and additions for mivolo by / Copyright 2023, Irina Tolstykh, Maxim Kuprashevich
"""

import torch
import torch.nn as nn
from timm.layers import trunc_normal_
from timm.layers.bottleneck_attn import PosEmbedRel
from timm.layers.helpers import make_divisible
from timm.layers.mlp import Mlp
from timm.layers.trace_utils import _assert
from timm.models.volo import VOLO


class CrossBottleneckAttn(nn.Module):
    def __init__(
        self,
        dim,
        dim_out=None,
        feat_size=None,
        stride=1,
        num_heads=4,
        dim_head=None,
        qk_ratio=1.0,
        qkv_bias=False,
        scale_pos_embed=False,
    ):
        super().__init__()
        assert feat_size is not None, (
            "A concrete feature size matching expected input (H, W) is required"
        )
        dim_out = dim_out or dim
        assert dim_out % num_heads == 0

        self.num_heads = num_heads
        self.dim_head_qk = dim_head or make_divisible(dim_out * qk_ratio, divisor=8) // num_heads
        self.dim_head_v = dim_out // self.num_heads
        self.dim_out_qk = num_heads * self.dim_head_qk
        self.dim_out_v = num_heads * self.dim_head_v
        self.scale = self.dim_head_qk**-0.5
        self.scale_pos_embed = scale_pos_embed

        self.qkv_f = nn.Conv2d(dim, self.dim_out_qk * 2 + self.dim_out_v, 1, bias=qkv_bias)
        self.qkv_p = nn.Conv2d(dim, self.dim_out_qk * 2 + self.dim_out_v, 1, bias=qkv_bias)

        self.pos_embed = PosEmbedRel(feat_size, dim_head=self.dim_head_qk, scale=self.scale)

        self.norm = nn.LayerNorm([self.dim_out_v * 2, *feat_size])
        mlp_ratio = 4
        self.mlp = Mlp(
            in_features=self.dim_out_v * 2,
            hidden_features=int(dim * mlp_ratio),
            act_layer=nn.GELU,
            out_features=dim_out,
            drop=0,
            use_conv=True,
        )

        self.pool = nn.AvgPool2d(2, 2) if stride == 2 else nn.Identity()
        self.reset_parameters()

    def reset_parameters(self):
        trunc_normal_(self.qkv_f.weight, std=self.qkv_f.weight.shape[1] ** -0.5)
        trunc_normal_(self.qkv_p.weight, std=self.qkv_p.weight.shape[1] ** -0.5)
        trunc_normal_(self.pos_embed.height_rel, std=self.scale)
        trunc_normal_(self.pos_embed.width_rel, std=self.scale)

    def get_qkv(self, x, qvk_conv):
        B, C, H, W = x.shape
        x = qvk_conv(x)
        q, k, v = torch.split(x, [self.dim_out_qk, self.dim_out_qk, self.dim_out_v], dim=1)
        q = q.reshape(B * self.num_heads, self.dim_head_qk, -1).transpose(-1, -2)
        k = k.reshape(B * self.num_heads, self.dim_head_qk, -1)
        v = v.reshape(B * self.num_heads, self.dim_head_v, -1).transpose(-1, -2)
        return q, k, v

    def apply_attn(self, q, k, v, B, H, W, dropout=None):
        if self.scale_pos_embed:
            attn = (q @ k + self.pos_embed(q)) * self.scale
        else:
            attn = (q @ k) * self.scale + self.pos_embed(q)
        attn = attn.softmax(dim=-1)
        if dropout:
            attn = dropout(attn)
        return (attn @ v).transpose(-1, -2).reshape(B, self.dim_out_v, H, W)

    def forward(self, x):
        B, C, H, W = x.shape
        dim = int(C / 2)
        x1 = x[:, :dim, :, :]
        x2 = x[:, dim:, :, :]
        _assert(H == self.pos_embed.height, "")
        _assert(W == self.pos_embed.width, "")
        q_f, k_f, v_f = self.get_qkv(x1, self.qkv_f)
        q_p, k_p, v_p = self.get_qkv(x2, self.qkv_p)
        out_f = self.apply_attn(q_f, k_p, v_p, B, H, W)  # person to face
        out_p = self.apply_attn(q_p, k_f, v_f, B, H, W)  # face to person
        x_pf = torch.cat((out_f, out_p), dim=1)
        x_pf = self.norm(x_pf)
        x_pf = self.mlp(x_pf)
        return self.pool(x_pf)


def _conv_output_size(size, conv):
    return [
        (
            (size[i] + 2 * conv.padding[i] - conv.dilation[i] * (conv.kernel_size[i] - 1) - 1)
            // conv.stride[i]
        )
        + 1
        for i in range(2)
    ]


def _stem_output_size(size, stem):
    for module in stem:
        if isinstance(module, nn.Conv2d):
            size = _conv_output_size(size, module)
    return size


class PatchEmbed(nn.Module):
    """Two-stream (face + person) stem with cross attention. in_chans must be 6."""

    def __init__(
        self, img_size=224, stem_stride=1, patch_size=8, in_chans=6, hidden_dim=64, embed_dim=384
    ):
        super().__init__()
        assert in_chans == 6, "FaceLens only supports the face+person MiVOLO variant"
        self.conv = True  # kept for state-dict compatibility with upstream
        self.conv1 = self._stem(stem_stride, 3, hidden_dim)
        self.conv2 = self._stem(stem_stride, 3, hidden_dim)
        k = patch_size // stem_stride
        self.proj1 = nn.Conv2d(hidden_dim, embed_dim, kernel_size=k, stride=k)
        self.proj2 = nn.Conv2d(hidden_dim, embed_dim, kernel_size=k, stride=k)
        stem_out = _stem_output_size((img_size, img_size), self.conv1)
        self.proj_output_size = _conv_output_size(stem_out, self.proj1)
        self.map = CrossBottleneckAttn(
            embed_dim, dim_out=embed_dim, num_heads=1, feat_size=self.proj_output_size
        )
        self.patch_dim = img_size // patch_size
        self.num_patches = self.patch_dim**2

    @staticmethod
    def _stem(stem_stride, in_chans, hidden_dim):
        return nn.Sequential(
            nn.Conv2d(
                in_chans, hidden_dim, kernel_size=7, stride=stem_stride, padding=3, bias=False
            ),
            nn.BatchNorm2d(hidden_dim),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden_dim, hidden_dim, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(hidden_dim),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden_dim, hidden_dim, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(hidden_dim),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        x1 = self.proj1(self.conv1(x[:, :3]))
        x2 = self.proj2(self.conv2(x[:, 3:]))
        return self.map(torch.cat([x1, x2], dim=1))


class MiVOLOModel(VOLO):
    def __init__(
        self,
        layers,
        img_size=224,
        in_chans=6,
        num_classes=1000,
        patch_size=8,
        stem_hidden_dim=64,
        embed_dims=None,
        num_heads=None,
        **kwargs,
    ):
        # FaceLens change: keyword arguments (timm >= 1.0 inserted pos_drop_rate positionally).
        super().__init__(
            layers=layers,
            img_size=img_size,
            in_chans=in_chans,
            num_classes=num_classes,
            patch_size=patch_size,
            stem_hidden_dim=stem_hidden_dim,
            embed_dims=embed_dims,
            num_heads=num_heads,
            **kwargs,
        )
        im_size = img_size[0] if isinstance(img_size, tuple) else img_size
        self.patch_embed = PatchEmbed(
            img_size=im_size,
            stem_stride=2,
            patch_size=patch_size,
            in_chans=in_chans,
            hidden_dim=stem_hidden_dim,
            embed_dim=embed_dims[0],
        )
        trunc_normal_(self.pos_embed, std=0.02)
        self.apply(self._init_weights)

    def forward_features(self, x):
        x = self.patch_embed(x).permute(0, 2, 3, 1)  # B,C,H,W -> B,H,W,C
        x = self.forward_tokens(x)
        if self.post_network is not None:
            x = self.forward_cls(x)
        return self.norm(x)

    def forward_head(self, x, pre_logits: bool = False):
        if self.global_pool == "avg":
            out = x.mean(dim=1)
        elif self.global_pool == "token":
            out = x[:, 0]
        else:
            out = x
        if pre_logits:
            return out
        out = self.head(out)
        if self.aux_head is not None:
            aux = self.aux_head(x[:, 1:])
            out = out + 0.5 * aux.max(1)[0]
        return out

    def forward(self, x):
        return self.forward_head(self.forward_features(x))


def mivolo_d1_384(num_classes: int = 3, in_chans: int = 6) -> MiVOLOModel:
    return MiVOLOModel(
        layers=(4, 4, 8, 2),
        embed_dims=(192, 384, 384, 384),
        num_heads=(6, 12, 12, 12),
        img_size=384,
        in_chans=in_chans,
        num_classes=num_classes,
    )
