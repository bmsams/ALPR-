# bench

Real-image benchmark harness around the openalpr CLI.

```
sudo apt-get install libopencv-dev libtesseract-dev tesseract-ocr-eng cmake g++
pip install shapely
bench/setup_openalpr.sh                       # clone, patch, build vendor/openalpr
git clone --depth 1 https://github.com/openalpr/benchmarks.git /tmp/oab
python3 bench/run_openalpr.py --bench /tmp/oab/endtoend --out bench/results/x.json --label x [--pattern any] [--set key=value]
```

Boolean config keys are parsed with `atoi`, so pass `--set key=1`, never `=true`.

`openalpr-grammar.patch` is the whole modification to upstream openalpr. It is
applied on top of upstream commit `736ab0e`. Results in `results/` are
committed runs; `docs/grammar-experiment.md` interprets them.
