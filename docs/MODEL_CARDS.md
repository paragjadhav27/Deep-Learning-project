# Model cards

Only numbers measured by this project appear here. The UI and API quote nothing else.

## Face detector: OpenCV Zoo YuNet `2026may` (in use)

| | |
|---|---|
| Purpose | Locate faces to (a) enforce the one-face policy and (b) crop and align the input for estimators. It doesn't identify anyone, and no face geometry is stored. |
| Source | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet |
| License | MIT (desk review 2026-09-24; legal sign-off pending) |
| Artifact | `face_detection_yunet_2026may.onnx`, SHA-256 `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` |
| Runtime | OpenCV ≥ 5.0 (ONNX engine, dynamic input), CPU |
| Settings | score ≥ 0.7, NMS 0.3, inputs downscaled to ≤ 640 px (model is trained on ~10–300 px faces), min face side 64 px |
| Training data | WIDER FACE (per upstream). **Its demographic composition hasn't been evaluated by us.** |

**Measured so far (engineering checks only, one public-domain portrait, not a fairness evaluation):**
- It detects 1 face on the fixture at 256, 512 and 2048 px, 2 faces on a side-by-side tile, and 0 on a flat image.
- 5-point landmarks **underestimate in-plane roll**: 30° of roll reads as ~3° with a 45 px face and ~19° with a 160 px face. Alignment therefore re-detects on the crop (up to 2 refinement steps). The remaining tilt after refinement was ≤ 2.7° for rolls of 15°, −20° and 30°.

**FairFace evaluation (2026-09-24, adult test split, n = 4,930; `eval/results/mivolo_v2_fairface.json`):** overall miss rate (`no_face_detected`) 0.1%. Worst gap between groups: 0.44 pp across annotated race (East Asian 0.44% vs. 0%), 0.19 pp across perceived gender, 0.21 pp across age bands. **Release gate (≤ 3 pp): passed.** About 27% of FairFace images are refused as `multiple_faces_detected` because the padded crops often include a second person; this is policy behaviour and isn't gated.

**Still open:** miss rate by skin tone (Monk scale) and presentation style (glasses, head coverings, facial hair). Both need a consented, annotated dataset.

## Shared evaluation method (MiVOLO v2)

- **Data:** FairFace validation split (CC BY 4.0, `HuggingFaceM4/FairFace@54d573cd`, padding 1.25), run through the production path (YuNet policy → crop → model). Race and gender labels are *annotator-perceived* and are used only to slice results.
- **Split:** 40% calibration / 60% test, stratified by race × age band (seed 20260925). Every number below comes from the test split: 3,594 adult faces (age bands 20–29 to 70+).
- **Labels are age bands, not exact ages,** so age error is measured as *MAE-to-bin*: the distance from the prediction to the nearest edge of the labelled band (0 inside it).
- Gates were pre-registered on 2026-09-25 before the full run (PLAN §7.3). 95% bootstrap CIs are in the report.

## Age estimator: MiVOLO v2, face-only (serving locally, **gate failed**)

| | |
|---|---|
| Purpose | Illustrative estimate of apparent age in one adult face photo. Not a verified or legal age. |
| Source | https://huggingface.co/iitolstykh/mivolo_v2, revision `53393526` |
| License | Apache-2.0 (weights tag), research release; see `ml/vendor/mivolo/NOTICE.md`. Served only with `FACELENS_LICENSE_SCOPE=non_commercial`. |
| Artifact | `mivolo_v2.safetensors` (SHA-256 pinned in `ml/artifacts.py`) |
| Architecture | VOLO-D1 vision transformer, 384 × 384 input, two streams (face + body). FaceLens sends the YuNet face box only; the body stream gets a blank image. One network also serves the presentation tool. |
| Training | By the upstream authors (Lagenda and other datasets whose composition isn't fully documented). **FaceLens doesn't train or fine-tune it.** |
| Output | Age = raw × 122 + 61 years, shown with a conformal interval of ± 3.4 years (`ml/calibration/mivolo_v2.json`, 2,408 calibration faces, 80% target coverage). |

**Measured (test split):**

| Metric | Overall | Worst group | Gate | Result |
|---|---|---|---|---|
| MAE-to-bin | 1.90 years | 40–49: 2.95 (1.55 × overall); Black: 2.65 (1.39 ×) | worst ≤ 1.5 × overall | **failed** (age band) |
| Interval coverage | 79.1% | 40–49: 67.9%; Black: 72.5% | worst ≥ 70% | **failed** (age band) |
| Adults wrongly blocked as under 18 | 1.0% | Black: 2.8%; Southeast Asian: 2.5%; Female: 1.8% | ≤ 1% in every group | **failed** |
| Predicted age inside the labelled band | 57.0% | Black: 45.5% | not gated | |

By perceived gender, MAE-to-bin is 1.63 (male) vs. 2.21 (female). The model is least accurate for people in their 30s and 40s.

**Status:** the release gate failed, so the registry refuses this model by default. It serves only in local experiments with `FACELENS_ALLOW_UNGATED_MODELS=true`, which is refused in staging and production. A 400-image calibration-split test (2026-10-03) of looser face crops (+10–30%) and horizontal-flip averaging changed MAE-to-bin by at most 0.13 years, within noise, so the crop is unchanged.

## Perceived-presentation estimator: MiVOLO v2, face-only (serving locally, **gate failed**)

| | |
|---|---|
| Purpose | Illustrative estimate of how a model *perceives* gender presentation in one photo. Not gender identity, not sex. |
| Model | The same MiVOLO v2 network as the age estimator (its binary "gender" head). |
| Output | Feminine-presenting and masculine-presenting scores. Below a fixed 0.75 confidence threshold (not tuned on evaluation data) the outcome is "uncertain". |
| Limitation | The head was trained on binary labels, so it can't represent presentation outside that binary. |

**Measured (test split), against annotator-perceived gender:**

| Metric | Overall | Worst group | Gate | Result |
|---|---|---|---|---|
| Accuracy when it answers | 98.6% | Black: 96.7% (gap 2.9 pp) | gap ≤ 5 pp | passed |
| "Uncertain" rate | 0.47% | up to 3.6 × overall (race), 3.8 × (age band) | worst ≤ 2 × overall | **failed** |

The abstention rate is so low overall that a few extra "uncertain" answers in one group exceed the ratio. **Status:** gate failed; serves only with `FACELENS_ALLOW_UNGATED_MODELS=true`, as above.

## Age transformer: SAM, FFHQ aging (serving locally, **not evaluated**)

| | |
|---|---|
| Purpose | A synthetic illustration of a face at a chosen adult target age. Not a prediction of how anyone looked or will look. |
| Source | https://github.com/yuval-alaluf/SAM (Alaluf et al., 2021, *Only a Matter of Style*) |
| License | Code MIT; weights trained on FFHQ / FFHQ-Aging, **CC BY-NC-SA 4.0 (non-commercial)**. Served only with `FACELENS_LICENSE_SCOPE=non_commercial`. |
| Artifact | `sam_ffhq_aging.safetensors` (SHA-256 pinned in `ml/artifacts.py`) |
| Architecture | pSp-style encoder into a pretrained StyleGAN2 (FFHQ) generator, conditioned on a target-age channel. 256 px input, 1024 px output. |
| Training | By the upstream authors. **FaceLens doesn't train or fine-tune it.** |
| Pipeline | FFHQ alignment from YuNet's 5 landmarks → SAM at the target age (young adult 25, middle-aged 45, older adult 70) → warped back into the photo with a feathered mask → marked as synthetic (visible band, JPEG comment, IPTC `trainedAlgorithmicMedia` in XMP). Child and teen targets are off and hidden in the UI. |
| Cost | About 2.2 GB of RAM per process and about 14 s per image on a 4-thread CPU. |

**Measured:** nothing yet. The aging gates (target attainment, skin-tone preservation, one-face integrity; PLAN §7.3) and the script `eval/run_aging_eval.py` are ready, but it hasn't been run. FFHQ is known to under-represent darker skin tones, so lightening or darkening of particular groups is the main risk to check. **Status:** serves only with `FACELENS_ALLOW_UNGATED_MODELS=true`.
