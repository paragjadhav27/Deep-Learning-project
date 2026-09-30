# Vendored: SAM (Style-based Age Manipulation)

- Source: https://github.com/yuval-alaluf/SAM at commit `c1895aef275e702fba7560284dc16df60d65210e`
  - `models/encoders/helpers.py`, `models/encoders/psp_encoders.py`: pSp encoder (MIT, Richardson & Alaluf)
  - `models/stylegan2/model.py`: StyleGAN2 generator by rosinality (MIT)
  - `models/psp.py`: simplified into `network.py`
- Code license: MIT (the `LICENSE` file here).
- **Weights: `sam_ffhq_aging.pt`**, from the authors' link in the SAM README. The model is trained on **FFHQ / FFHQ-Aging, licensed CC BY-NC-SA 4.0 (non-commercial)**. FaceLens marks this model `license_scope="non_commercial"`, and the registry refuses it in commercial deployments.

## Changes from upstream

1. `ops.py` replaces SAM's `op/` package. Upstream compiles NVIDIA CUDA kernels at import time (under NVIDIA's non-commercial source-code license, and needing a CUDA toolchain). We use the pure-PyTorch reference formulations instead, verified numerically against direct convolutions (`tests/test_aging.py`).
2. The encoder takes `input_nc` instead of an argparse `opts` object.
3. `network.py` keeps inference only: it starts from the encoded W+ (as SAM's aging checkpoint was trained), and it has no noise randomization and no training paths.
4. Weights are converted once from the pickle checkpoint to safetensors by `facelens-api fetch-models`, loading the pickle with `torch.load(weights_only=True)`. The service itself only loads safetensors, and both files are SHA-256 pinned.
