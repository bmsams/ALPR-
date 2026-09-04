# openalpr pipeline map

Trace of one frame through openalpr 2.3.0 (upstream commit `736ab0e`,
vendored by `bench/setup_openalpr.sh`). Paths are relative to
`vendor/openalpr/src/openalpr/` unless noted. Written to find the seams
where the zero-real-data project's ideas can be tested against a working
system.

## Frame in

The CLI (`../main.cpp`) and daemon both call the raw-pixel overload
`Alpr::recognize(pixelData, bpp, w, h, rois)` (`alpr.cpp:78`), which wraps
the buffer in a `cv::Mat` (`alpr_impl.cpp:443-467`) and injects a full-frame
region of interest when none is given. Everything real happens in
`AlprImpl::recognizeFullDetails` (`alpr_impl.cpp:86-215`):

1. Clamp regions of interest to the image (`:97`).
2. Convert to gray (`:118`). Only the gray image is prewarped (`:123`); the
   color image is unwarped again later at crop time.
3. Loop over loaded countries (`:129`), and inside that loop over
   `analysis_count` re-analyses of the same frame with imperceptible
   micro-rotations (`result_aggregator.cpp:49-81`). Inner results merge with
   `MERGE_COMBINE`, outer with `MERGE_PICK_BEST`.

### Motion gating is CLI-only

`MotionDetector` (`motiondetector.cpp`) is MOG2 background subtraction,
erode 6x6, contours, and the union of every contour's bounding box into one
rectangle (`:56-72`). It is used only by `alpr --motion` (`../main.cpp:344-352`):
the motion box becomes the sole region of interest, and when there is no
motion, `recognize` is skipped entirely. The daemon never uses it, and the
library has no notion of frames. So "how it handles a car arriving and
leaving" is: nothing. Each frame is independent. There is no tracker, no
cross-frame fusion, and `AlprResults::frame_number` is always -1.

## Plate detection (`detection/`)

`createDetector` (`detection/detectorfactory.cpp:7-43`) picks by config key
`detector`: `lbpcpu` (default), `lbpgpu`, `lbpopencl`, or `morphcpu`, a
training-free morphological white-rectangle finder. The LBP cascades live in
`runtime_data/region/<country>.xml`, despite the directory name.

`Detector::detect` (`detection/detector.cpp:65-172`) per region of interest:
skip if smaller than `min_plate_size_*_px`, downscale to
`max_detection_input_width/height` (1280x720 by default), run
`detectMultiScale` with `equalizeHist` first (`detectorcpu.cpp:62-67`),
rescale boxes back, then `aggregateRegions` (`detector.cpp:209-259`) nests
smaller boxes inside larger ones as children. Children are only analyzed if
the parent produced no plate (`alpr_impl.cpp:386-394`). A `PlateRegion` is
just a rect and its children. No detection score is kept.

## Per-candidate stages (`licenseplatecandidate.cpp:44-139`)

Shared state is `PipelineData` (`pipeline_data.h`). Note its
`confidence_weights` score keeper is written once and never read.

1. Crop and resize to `template_max_width_px` x `template_max_height_px`
   (us 120x60, eu 184x46).
2. `CharacterAnalysis` (`textdetection/characteranalysis.cpp:49-275`): three
   adaptive thresholds (two Wolf-Jolion, one Sauvola, `utility.cpp:122-162`),
   contour filtering by height bands (`char_analysis_*` keys), the best
   threshold is the one with the most surviving contours, then `LineFinder`
   fits the text line. Disqualifies on fewer than two good contours, angle
   over `max_plate_angle_degrees`, or no lines.
3. `EdgeFinder` (`edges/edgefinder.cpp:42-61`): high-contrast plates go
   through morphology plus Otsu plus contour rejection; everything else goes
   through Canny, Hough (`platelines.cpp:44-130`, sensitivity keys
   `plateline_sensitivity_*`), and `PlateCorners` (`platecorners.cpp:50-132`)
   which brute-forces every pair of horizontal and vertical lines against a
   weighted score using `plate_width_mm`, `plate_height_mm`, `char_height_mm`.
4. `Transformation`: perspective deskew of the color crop at
   `ocr_img_size_percent` times template size.

`colorfilter.cpp` is compiled but never instantiated. `TRexpp.h` is dead;
regexes are RE2.

## OCR (`ocr/`)

`CharacterSegmenter` (`ocr/segmentation/charactersegmenter.cpp:57-215`) uses
vertical histograms per threshold, expected character width from
`char_height_mm / char_width_mm`, then edge and empty-box filters.

`TesseractOcr::recognize_line` (`ocr/tesseract_ocr.cpp:61-160`) runs Tesseract
in `PSM_SINGLE_CHAR` with `save_blob_choices` on, for every threshold times
every character box. Each symbol and each `ChoiceIterator` alternative becomes
an `OcrChar` vote at that position, and the top choice is deliberately
double-counted (`:123-131`). Font size below `ocr_min_font_point` is dropped.

## Postprocess (`postprocess/`)

This is the grammar layer, and the part the experiment modifies.

- Patterns load from `runtime_data/postprocess/<country>.patterns`
  (`postprocess.cpp:31-63`), one `region pattern` pair per line. `@` is a
  letter, `#` a digit, `?` any character, `[...]` a class. Compiled to RE2
  with an exact-length requirement (`regexrule.cpp:32-141`).
- `addLetter` (`postprocess.cpp:85-102`) rejects votes under
  `postprocess_min_confidence` (65), and for votes under
  `postprocess_confidence_skip_level` (80) also inserts a skip token, so the
  search can drop a doubtful character. Repeat votes for the same letter at
  the same position add their scores (`insertLetter`).
- `findAllPermutations` (`postprocess.cpp:296-345`) is a best-first beam over
  per-position alternatives, stopping when `topn` candidates exist or after
  `2*topn` consecutive rejects.
- `analyzePermutation` (`:347-414`) applies the length gate
  (`postprocess_min/max_characters`) and sets `matchesTemplate` by testing
  every rule for the requested region.
- `analyze` (`:164-255`) picks `bestChars` as the first template match in
  score order, else the top candidate. Scores are rescaled to a percentage
  from the mean per-vote confidence.

Two properties matter for the experiment. The grammar is consulted only
after the search, as a re-ranker over whatever the beam happened to
produce. And it is only consulted at all when the caller passes a region
via `-p`, which the stock benchmark never does, so stock openalpr runs with
its grammar switched off.

## Aggregation and output

`ResultAggregator` (`result_aggregator.cpp`) clusters plates by centroid and
area overlap (`:366-407`). `MERGE_COMBINE` scores each candidate string
across the micro-rotation passes with a bonus of 150 for a template match
(`:164-166`). Nothing persists between calls.

JSON (`alpr_impl.cpp:495-604`) carries `plate`, `confidence`,
`matches_template`, `region`, `coordinates`, and `candidates`. Per-character
corners and `frame_number` exist in memory but are not serialized.

## Seams for the project

| Project idea | Where it would plug in |
|---|---|
| Grammar-constrained decoding | `findAllPermutations` and `analyzePermutation`; today grammar is post-hoc |
| Confusable-class resolution | between the beam and `bestChars` selection in `analyze` |
| Jurisdiction head | `StateDetector` slot in `analyzeSingleCountry`, compiled out by default |
| Multi-frame fusion | nothing exists; would wrap `recognize` calls in the CLI loop |
| Synthetic-trained recognizer | replace `TesseractOcr` behind the `OCR` interface (`ocr/ocr.h:35-50`) |
| Hot-list privacy layer | after `bestPlate` in the CLI, before any output |
