# Model evaluation

`run_eval.py` measures the **production code path** (YuNet face policy → tight face crop → provider) on held-out data. It produces:

- `eval/results/mivolo_v2_fairface.json`: the committed report, with per-group metrics, 95% bootstrap CIs, and gate verdicts.
- `apps/api/src/facelens_api/ml/calibration/mivolo_v2.json`: the conformal half-width for the age interval, plus the per-tool gate results that the model registry enforces at startup.

## Data

FairFace validation split, padding 1.25 (CC BY 4.0), pinned to [HuggingFaceM4/FairFace](https://huggingface.co/datasets/HuggingFaceM4/FairFace) revision `54d573cd`:

```bash
mkdir -p eval/.data
curl -L -o eval/.data/fairface_val_1.25.parquet \
  "https://huggingface.co/datasets/HuggingFaceM4/FairFace/resolve/54d573cdb8b5af490ba8da9da2799628f6e5c496/1.25/validation-00000-of-00001-09e3e67bb00ab4ec.parquet"
sha256sum eval/.data/fairface_val_1.25.parquet   # ce47863c011f355ef7ab63d70420d9d4b36fce03cf1621a26597955da21968bb
```

The race and gender labels are **annotator-perceived**. They are used only to slice fairness metrics. FaceLens never predicts race, and its presentation output is not a gender identity. The age labels are annotator-perceived apparent-age bins, which matches what the product claims to estimate.

## Run

```bash
cd apps/api && pip install -e ".[eval]" --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
facelens-api fetch-models
cd ../..
python eval/run_eval.py predict             # ~2 CPU-hours for 10,954 images; resumable
python eval/run_eval.py analyze --write-calibration
```

## Method (pre-registered in docs/PLAN.md §7.3)

- A deterministic 40/60 split (seed `20260925`), stratified by race × age bin. The **calibration** split sets the conformal half-width (80% target). **Every reported number comes from the test split.**
- *MAE-to-bin*: the distance from the predicted age to the annotated bin (0 inside it). *Coverage*: the calibrated interval overlaps the bin.
- Presentation uses the product's fixed threshold of 0.75. Abstentions ("uncertain") are excluded from selective accuracy and reported separately.
- The detection gate uses the **miss** rate. Multiple-face and too-small rejections are reported but not gated, because they reflect photo composition.

## Known limitations

- FairFace has no Monk Skin Tone labels, so race categories are only a proxy for skin tone. Presentation-style slices (glasses, head coverings, facial hair) need a consented, annotated set that doesn't exist yet.
- MiVOLO v2's training data is "proprietary and open-source" and undisclosed, so we can't rule out overlap with FairFace. Treat results as possibly optimistic.
- The age labels are 10-year bins, which limits precision: MAE-to-bin is not a year-level MAE.
