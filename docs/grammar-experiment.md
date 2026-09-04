# Experiment 1: does plate grammar beat pixels?

Question: how much of openalpr's error is a ranking problem that jurisdiction
grammar can fix, versus a recognition problem that only a better recognizer
can fix? This tests the "grammar-constrained joint decoding" claim in
`PROJECT.md` on a working system before building anything.

Setup: openalpr 2.3.0 (`736ab0e`) built against OpenCV 4.6 and Tesseract 5.3,
stock cascades, stock Tesseract data, patched only in the postprocess stage
(`bench/openalpr-grammar.patch`). Evaluated on the openalpr end-to-end
benchmark (222 US, 108 EU, 114 BR full frames with plate box and text).
Scoring follows the upstream benchmark script: a result counts only if its
quadrilateral overlaps the truth box at IoU over 0.4. Top-1 is the reported
best plate. Top-N is whether the truth appears anywhere in 10 candidates.

Stock openalpr never applies its grammar in this benchmark, because the
grammar only activates when the caller names a region with `-p`.

## Configurations

| Name | What changes |
|---|---|
| stock | upstream behavior, no region, grammar off |
| union | `-p any`, a new pseudo-region that is the union of every pattern in the country file. Grammar re-ranks the candidate list |
| union+search | beam keeps expanding past top-N until it finds a grammatical string (cap 100x top-N) |
| union+repair | when no candidate matches, flip confusable glyph pairs (O/0, I/1, B/8, S/5, Z/2, ...) in the top candidates until one fits, at a 7 percent score penalty per flip. A match scoring under 75 percent of the best read no longer counts |
| oracle | `-p <region>` where the region is the first one in the pattern file whose grammar accepts the truth. Upper bound for a perfect jurisdiction classifier |

All runs are in `bench/results/`. Reproduce with `bench/run_openalpr.py`.

## Results, top-1 exact match

| Configuration | US | EU | BR |
|---|---|---|---|
| stock | 51.4 | 72.2 | 41.2 |
| union re-rank | 58.6 | 73.1 | 61.4 |
| union + search | 57.7 | 73.1 | 63.2 |
| union + search + repair | 57.7 | 72.2 | 59.6 |
| oracle region re-rank | 66.7 | 81.5 | 62.3 |
| oracle + search | 67.6 | 81.5 | 64.0 |
| oracle + search + repair | 67.6 | 80.6 | 60.5 |
| top-N ceiling (truth in list) | 70.7 | 89.8 | 64.0 |

Detection recall is unchanged by any of this: 90 percent US, 98 EU, 68 BR.

## What the numbers say

**Grammar is worth a lot, and openalpr ships with it switched off.** Adding
the union grammar as a re-ranker, with no change to detection or OCR, is
worth 7 points on US and 20 on Brazil. Brazil goes from 41 to 61 because its
grammar has two formats and discriminates hard.

**Knowing the jurisdiction is worth more than the grammar itself.** The
oracle region gains another 8 points on US and 8 on EU over the union. On
EU the union is worth nothing (218 patterns with wildcards accept almost
any string) but the right country's grammar is worth 9 points. On US, after
union re-ranking, 52 of the 70 remaining wrong reads are themselves
grammatical under some state. The union cannot tell them apart. The right
state can. This is the strongest evidence for joint jurisdiction and text
decoding: a jurisdiction classifier that is right most of the time is worth
about as much as the grammar layer itself.

**Guessing the wrong jurisdiction is worse than no grammar.** Re-scoring
the stock candidate lists under a state that rejects the truth
(`bench/oracle.py`) gives 43.6 on US against 51.4 stock. A jurisdiction
head therefore needs calibrated confidence and a fallback to the union
grammar, not a hard argmax.

**Deeper search is worth about one point, and only with a specific
grammar.** Under the union it finds garbage that matches by dropping
characters. The score floor is what makes it safe.

**Confusable-class repair is dead weight here, and slightly harmful on
Brazil.** Tesseract's choice iterator already puts O/0 and I/1 alternatives
into the beam, so the repair only adds penalized duplicates of candidates
the search already had. The idea is still right for hot-list matching,
where the question is "could this read be that plate", but it is not a
decoder fix. Dropped from the decoder design.

**The rest of the error is not fixable by grammar.** After re-ranking, 43
of the 70 US misses have the truth nowhere in the candidate list, and the
reads are 1 to 3 characters shorter than the truth. That is the
segmentation stage dropping characters before Tesseract ever sees them.
No amount of grammar recovers a character that was never proposed. The
project's CTC recognizer, which reads the whole plate strip without
segmenting, is aimed at exactly this.

**Grammar coverage bounds the gain.** 13 of 222 US truths match no pattern
in the file (vanity plates and gaps). Every one of those is a plate the
grammar can only hurt, and two were lost this way (FZRULZ read as FZRUL2).
Grammar must be a prior, never a constraint.

## Bugs found in openalpr along the way

- Boolean config values parse with `atoi`, so `key = true` is false. The
  first round of these runs was silently the stock configuration.
- `TRexpp.h` and `colorfilter.cpp` are compiled but dead. Regexes are RE2.
- `PipelineData::confidence_weights` is written and never read.
- The FindTesseract module requires internal headers Tesseract 5 does not
  ship. `bench/setup_openalpr.sh` works around it.
- `fromJson` picks candidate 0 as best while the forward path picks the
  first template match, so a JSON round trip can change the best plate.

## What this changes in the plan

Iteration 4 (grammar-constrained decoding) is confirmed as the highest-value
decoding change and now has a target: recover the gap between union and
oracle, which is 8 points on US and EU. The jurisdiction head is promoted
from a nice-to-have to a core component with a calibration requirement.
Confusable repair moves out of the decoder and into iteration 8 (hot-list
matching) only. The 43 truth-absent US failures become the first failure
cluster for iteration 5.
