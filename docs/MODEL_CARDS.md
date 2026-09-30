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

**Open before production (Phase 4):** detection miss rate by skin tone (Monk scale), age band, and presentation style (glasses, head coverings, facial hair), with 95% confidence intervals. The release gate is a ≤ 3 percentage-point gap between groups (see PLAN §7.3). A detector that misses some groups more often would deny them the service.

## Age estimator: none approved

A mock only (`mock-age-estimator`). MiVOLO v2 is a candidate pending license and provenance review (PLAN §7.1).

## Perceived-presentation estimator: none approved

A mock only (`mock-presentation-estimator`).

## Age transformer: none approved

A mock only (`mock-age-transformer`). No commercially licensed open model was found. The recommended path is a licensed vendor behind the `AgeTransformer` interface.
