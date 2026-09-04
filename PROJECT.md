# ALPR from zero real training data

A CPU-only license plate recognition engine trained entirely on procedurally
rendered plates, with real photographs used only to measure the sim-to-real
gap, never to train. Every iteration is judged by one number: exact-match
accuracy on real plates the model has never seen a single example of.

## Why this is the hard version

Every open ALPR project trains or fine-tunes on real plate photos. Real US
plate data is scarce, jurisdiction-skewed, and legally uncomfortable to
collect. The thesis here: a renderer that models plates well enough, plus
decoding that knows plate grammar, plus fusion across frames, beats a
recognizer that memorized a few thousand real crops. Proving that is a
research-grade problem with a hard, honest metric. Failing it visibly is
still useful: the ledger at the bottom records exactly where sim-to-real
breaks.

Nothing open combines these four pieces as one system:

1. **Procedural plate renderer with closed-loop domain search.** Not just
   augmentation. The renderer's parameters (blur kernels, perspective
   range, exposure, compression, dirt, plate frames, bolts, stickers,
   font mix) are tuned automatically against a small real validation split,
   and the test split stays frozen and untouched.
2. **Grammar-constrained joint decoding.** The CTC recognizer's posteriors
   are decoded through per-jurisdiction format automata (state serial
   formats, EU country formats, Mercosur/BR). Jurisdiction and text are
   decoded jointly, so "O" vs "0" resolves from position and format, not
   from pixels alone.
3. **Multi-frame fusion.** A plate seen across N video frames yields one
   read with a calibrated confidence, by aligning and combining per-frame
   posteriors rather than voting on strings.
4. **Privacy-preserving hot-list matching.** The engine can answer "is this
   plate on a watch list" without storing plaintext reads, and tolerates
   one or two OCR character errors, using confusable-class canonicalization
   plus deletion-neighborhood keyed hashing. Non-hits are never retained.

## Hard constraints

- No GPU. Training must finish in hours on 4 cores. Models stay small
  enough to commit (target under 10 MB per ONNX file).
- Real images are evaluation-only. The openalpr benchmark set is split
  once: US images into a validation third (renderer tuning) and a frozen
  test two-thirds; EU and BR are test-only and measure zero-shot transfer
  to formats the renderer was not tuned on.
- No proprietary plate typefaces. Fonts are open (Google Fonts via GitHub).
  Font invariance is a modeling problem, not a licensing shortcut.
- Hugging Face is unreachable from the build environment. PyPI and GitHub
  are the only sources.
- Everything reproducible from `make eval` on a clean clone. Every ledger
  entry is a committed run.

## Metrics

| Metric | Definition |
|---|---|
| EM | Plate exact match on real test crops (ground-truth boxes) |
| CER | Character error rate on real test crops |
| E2E | Exact match on real full frames, detection included |
| Det R@0.5 | Detection recall at IoU 0.5 on real frames |
| ECE | Expected calibration error of the reported plate confidence |
| ms/frame | Single-core CPU latency, 720p frame, ONNX Runtime |
| FMR | Hot-list false-match rate per query at tolerance k |

## Repository layout

```
alpr/
  render/      procedural plate renderer, jurisdiction templates, domain params
  data/        synthetic dataset generation, real benchmark fetch and split
  models/      recognizer (CRNN/CTC), detector, export to ONNX
  decode/      format automata, constrained beam search, jurisdiction head
  fuse/        multi-frame posterior fusion, confidence calibration
  privacy/     hot-list hashing and tolerant matching
  eval/        metrics, ledger writer, benchmark runner
  cli/         plate reading CLI and streaming entrypoint
tests/
docs/
```

## Iterations

Each iteration ships code, a ledger row, and a short note on what broke.
Exit criteria are numbers, not feelings. If an iteration misses its exit,
the next iteration is chosen to attack the failure, not the plan.

### 0. Harness before model
Build the evaluation harness first so every later change is measured the
same way. Fetch openalpr benchmark images, make the one-time split, write
the metric code, write the ledger format, add CI that runs unit tests and
a smoke evaluation on CPU.
Exit: `make eval` runs end to end on a dummy recognizer and reports EM 0.

### 1. Renderer v1 and a baseline recognizer
One generic plate template, a handful of open condensed fonts, mild
augmentation. Train a small CRNN with CTC on 200k synthetic crops on CPU.
This establishes the raw sim-to-real gap.
Exit: synthetic holdout EM above 95 percent. Real EM is recorded, expected
to be poor. That number is the baseline everything else is measured
against.

### 2. Renderer v2: jurisdictions and physical realism
Per-state templates: serial formats, background art classes, stacked
small text, registration stickers, plate frames that occlude edges, bolt
heads, embossing shadows, retroreflective night appearance, dirt and
scratches, motion blur with direction, perspective from realistic camera
geometry, resolution down to 20 pixel plate height, JPEG artifacts.
Retrain.
Exit: real US validation EM at least doubles from iteration 1.

### 3. Closed-loop domain search
Parameterize the renderer, then search its parameter space against the
US validation split (random search first, then a bandit over parameter
groups). The test split is never read during search. Report validation
versus test EM to expose overfitting to the 74 validation plates.
Exit: test EM improves and the validation-to-test gap stays under 5
points.

### 4. Grammar-constrained joint decoding
Jurisdiction classification head on the recognizer. Format automata per
jurisdiction compiled to weighted FSTs. Beam search over CTC posteriors
intersected with the automata, scored jointly with the jurisdiction
prior.
Exit: real test EM gains at least 5 points over greedy decoding at equal
model weights. Report where the grammar hurts, since vanity plates exist.

### 5. Failure mining and the second grind
Cluster real failures by cause: blur, angle, low resolution, frame
occlusion, unusual font, two-line plates. Extend the renderer for each
cluster, rerun the domain search, retrain.
Exit: each failure cluster shrinks, and total test EM rises. This
iteration repeats until gains fall below one point per cycle.

### 6. Detection from synthetic composites
Paste rendered plates into procedurally generated scenes and real
license-free background photos, with realistic scale and placement.
Train a small anchor-free detector. Compare against a classical
edge and morphology detector as the floor.
Exit: Det R@0.5 above 90 percent on real US frames, and E2E EM within
5 points of crop EM.

### 7. Multi-frame fusion
Render synthetic tracks: a plate approaching the camera over 10 to 60
frames with consistent motion, changing blur and scale. Fuse per-frame
CTC posteriors by alignment, not string voting. Calibrate confidence with
temperature scaling on synthetic tracks and report ECE on real crops.
Exit: fused EM on synthetic tracks beats best-single-frame EM, and ECE
below 0.05.

### 8. Privacy-preserving hot-list matching
Canonicalize reads over OCR confusable classes, generate the deletion
neighborhood at tolerance k, HMAC each key with a deployment secret, and
match against a pre-hashed list. Measure false-match rate against 10
million random plates per query and the recall against real OCR errors
from the ledger. Write the threat model plainly, including what a secret
compromise exposes.
Exit: recall above 99 percent on single-character errors at FMR below
1e-6 for a 10k-entry list.

### 9. Zero-shot transfer to EU and BR
Add EU and Mercosur templates to the renderer, with no tuning against EU
or BR images at all. Evaluate.
Exit: EU and BR EM reported. Any gap versus US is analyzed, not hidden.

### 10. Edge packaging
ONNX export, int8 quantization, single-core latency budget, a CLI that
reads images, directories, and video, and a small streaming server.
Model card with the full ledger.
Exit: under 40 ms per 720p frame on one core with accuracy loss under one
point from quantization.

## What will probably break

- Fonts. Real plates use a few proprietary typefaces the renderer cannot
  legally ship. If font invariance does not emerge from training on many
  open condensed fonts, iteration 5 will add a learned glyph-warping
  augmentation.
- Two-line and stacked plates. CTC assumes one line. Iteration 5 may need
  a line-split stage or a 2D attention decoder.
- 74 validation plates is a small target for domain search. The
  validation-to-test gap check in iteration 3 exists to catch this early.
- CPU training time. The recognizer budget is under two hours per
  training run so the search loop in iteration 3 stays feasible.

## Ledger

Every row is a committed run. `make eval` reproduces it.

| Iter | Commit | Synth EM | US val EM | US test EM | EU EM | BR EM | E2E | ECE | ms/frame |
|---|---|---|---|---|---|---|---|---|---|
| 0 | | | | | | | | | |
