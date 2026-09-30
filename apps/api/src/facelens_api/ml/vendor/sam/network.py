# mypy: ignore-errors
"""SAM (Style-based Age Manipulation) inference network.

Simplified from SAM's `models/psp.py` (MIT, Alaluf et al., SIGGRAPH 2021) for inference
only: no training options, no argparse, no checkpoint pickles (weights come from a
converted safetensors file). See NOTICE.md.
"""

import torch
from torch import nn

from .encoders import GradualStyleEncoder
from .stylegan2 import Generator

N_STYLES = 18  # log2(1024) * 2 - 2
OUTPUT_SIZE = 1024


class SAMNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        # SAM's encoder sees RGB + a constant "target age / 100" channel.
        self.encoder = GradualStyleEncoder(50, "ir_se", N_STYLES, input_nc=4)
        # Frozen pSp encoder: SAM starts from the image's own W+ code (start_from_encoded_w_plus).
        self.pretrained_encoder = GradualStyleEncoder(50, "ir_se", N_STYLES, input_nc=3)
        self.decoder = Generator(OUTPUT_SIZE, 512, 8)
        self.register_buffer("latent_avg", torch.zeros(N_STYLES, 512))

    def forward(self, x):
        """x: (B, 4, 256, 256), RGB in [-1, 1] plus the age channel. Returns (B, 3, 1024, 1024)."""
        codes = self.encoder(x)
        encoded = self.pretrained_encoder(x[:, :-1]) + self.latent_avg
        codes = codes + encoded
        images, _ = self.decoder([codes], input_is_latent=True, randomize_noise=False, return_latents=False)
        return images
