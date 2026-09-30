# Vendored: MiVOLO model definition

- Source: https://github.com/WildChlamydia/MiVOLO (files `mivolo/model/mivolo_model.py`, `mivolo/model/cross_bottleneck_attn.py`)
- Copyright 2023 Irina Tolstykh, Maxim Kuprashevich (Layer Team, SberDevices). The files are based on timm (Apache-2.0, Ross Wightman).
- License: the repository's `LICENSE` file is Apache-2.0 (copied here). Note that the repository's `setup.py` states "Attribution-ShareAlike 4.0". This project is deployed **non-commercially** with attribution, which satisfies either reading. **Re-review before any commercial use.**
- Weights: `iitolstykh/mivolo_v2` on Hugging Face, revision `53393526c220e34cdd7b722b36d22b6f9e5f4241`, `model.safetensors` (SHA-256 pinned in `ml/artifacts.py`), tagged `apache-2.0`.

## Changes from upstream

1. Only the architecture (`MiVOLOModel`, `PatchEmbed`, `CrossBottleneckAttn`) is kept. The timm registry entries, pretrained-download config and the ultralytics/YOLO detector (AGPL-3.0) are **not** included.
2. `VOLO.__init__` is called with **keyword** arguments. Upstream passes them positionally, which misaligns them on timm ≥ 1.0 (a `pos_drop_rate` parameter was inserted).
3. Weights are loaded from safetensors (no pickle), and the Hugging Face `trust_remote_code` wrapper is not used.
