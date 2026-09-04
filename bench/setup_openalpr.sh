#!/usr/bin/env bash
# Clone openalpr at the pinned commit, apply the grammar patch, build the CLI.
# Requires: libopencv-dev libtesseract-dev tesseract-ocr-eng cmake g++
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$ROOT/vendor/openalpr"
PIN=736ab0e608cf9b20d92f36a873bb1152240daa98
if [ ! -d "$V/.git" ]; then
  git clone -q https://github.com/openalpr/openalpr.git "$V"
fi
cd "$V"
git checkout -q "$PIN"
git checkout -q -- .
git apply "$ROOT/bench/openalpr-grammar.patch"
mkdir -p src/build && cd src/build
cmake -DCMAKE_BUILD_TYPE=Release -DWITH_DAEMON=OFF -DWITH_TESTS=OFF \
  -DWITH_BINDING_JAVA=OFF -DWITH_BINDING_PYTHON=OFF -DWITH_BINDING_GO=OFF \
  -DTesseract_INCLUDE_CCMAIN_DIR=/usr/include/tesseract \
  -DTesseract_INCLUDE_CCUTIL_DIR=/usr/include/tesseract .. > cmake.log
make -j"$(nproc)" > make.log
echo "built: $V/src/build/alpr"
