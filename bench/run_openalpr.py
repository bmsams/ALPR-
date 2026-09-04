#!/usr/bin/env python3
"""Run the openalpr CLI over the openalpr end-to-end benchmark and score it.

Scoring follows benchmarks/benchmark.py from openalpr/benchmarks: a result
counts only if its plate quadrilateral overlaps the ground-truth box with
IoU > 0.4. Metrics per region:
  det      an overlapping result exists
  top1     overlapping result's best plate == ground truth
  topn     ground truth appears anywhere in the overlapping result's candidates
  pattern  first candidate with matches_template == ground truth (only meaningful with -p)
"""
import argparse, json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from shapely.geometry import Polygon, box
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import load_grammar

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(ROOT, "vendor", "openalpr")


def make_conf(runtime_dir, overrides):
    lines = ["runtime_dir = " + runtime_dir]
    with open(os.path.join(VENDOR, "config", "openalpr.conf.defaults")) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith(";") or s.startswith("[") or s.startswith("runtime_dir"):
                continue
            key = s.split("=")[0].strip()
            if key in overrides:
                continue
            lines.append(s)
    for k, v in overrides.items():
        lines.append(f"{k} = {v}")
    fd, path = tempfile.mkstemp(suffix=".conf")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def read_gt(txt):
    with open(txt) as f:
        parts = f.readline().rstrip("\n").split("\t")
    x, y, w, h = map(int, parts[1:5])
    return {"box": (x, y, w, h), "plate": parts[5].strip().upper()}


def run_one(alpr_bin, conf, country, topn, pattern, img):
    cmd = [alpr_bin, "-c", country, "--config", conf, "-n", str(topn), "-j"]
    if pattern:
        cmd += ["-p", pattern]
    cmd.append(img)
    t0 = time.time()
    out = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    line = [l for l in out.stdout.splitlines() if l.startswith("{")]
    data = json.loads(line[-1]) if line else {"results": []}
    return data, dt, out.stderr


def score(gt, data):
    x, y, w, h = gt["box"]
    g = box(x, y, x + w, y + h)
    best = None
    for r in data.get("results", []):
        p = Polygon([(c["x"], c["y"]) for c in r["coordinates"]])
        if not p.is_valid or p.area == 0:
            continue
        iou = p.intersection(g).area / p.union(g).area
        if iou > 0.4 and (best is None or iou > best[0]):
            best = (iou, r)
    row = {"gt": gt["plate"], "det": best is not None, "top1": False, "topn": False,
           "pattern": False, "read": None, "conf": None, "cands": []}
    if best:
        r = best[1]
        cands = [c["plate"].replace("\n", "") for c in r["candidates"]]
        row.update(read=r["plate"].replace("\n", ""), conf=r["confidence"], cands=cands)
        row["top1"] = row["read"] == gt["plate"]
        row["topn"] = gt["plate"] in cands
        pm = [c for c in r["candidates"] if c.get("matches_template")]
        row["pattern"] = bool(pm) and pm[0]["plate"].replace("\n", "") == gt["plate"]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True, help="path to openalpr/benchmarks/endtoend")
    ap.add_argument("--regions", default="us,eu,br")
    ap.add_argument("--alpr", default=os.path.join(VENDOR, "src", "build", "alpr"))
    ap.add_argument("--runtime", default=os.path.join(VENDOR, "runtime_data"))
    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--pattern", default="", help="value for alpr -p (region/template)")
    ap.add_argument("--pattern-from-truth", action="store_true",
                    help="oracle: per image, -p is the first region in the patterns file whose grammar accepts the truth")
    ap.add_argument("--set", action="append", default=[], help="config override key=value")
    ap.add_argument("--out", required=True, help="write per-image JSON results here")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--label", default="run")
    a = ap.parse_args()

    overrides = dict(s.split("=", 1) for s in a.set)
    conf = make_conf(a.runtime, overrides)
    summary = {}
    allrows = {}
    for region in a.regions.split(","):
        d = os.path.join(a.bench, region)
        imgs = sorted(f for f in os.listdir(d) if f.lower().endswith(".jpg"))
        rules = load_grammar(region) if a.pattern_from_truth else None

        def work(f):
            img = os.path.join(d, f)
            gt = read_gt(img[:-4] + ".txt")
            pattern = a.pattern
            if rules is not None:
                pattern = next((rg for rg, rx, n in rules if len(gt["plate"]) == n and rx.match(gt["plate"])), "")
            data, dt, err = run_one(a.alpr, conf, region, a.topn, pattern, img)
            row = score(gt, data)
            row["file"] = f
            row["region_used"] = pattern
            row["ms"] = round(dt * 1000)
            return row

        with ThreadPoolExecutor(a.jobs) as ex:
            rows = list(ex.map(work, imgs))
        n = len(rows)
        s = {k: sum(r[k] for r in rows) for k in ("det", "top1", "topn", "pattern")}
        s["n"] = n
        s["ms"] = round(sum(r["ms"] for r in rows) / n)
        summary[region] = s
        allrows[region] = rows
        print(f"{a.label:24s} {region:3s} n={n:3d} det={s['det']/n:6.1%} top1={s['top1']/n:6.1%} "
              f"topn={s['topn']/n:6.1%} pattern={s['pattern']/n:6.1%} {s['ms']}ms/img", flush=True)
    with open(a.out, "w") as f:
        json.dump({"label": a.label, "args": vars(a), "summary": summary, "rows": allrows}, f, indent=1)
    os.unlink(conf)


if __name__ == "__main__":
    main()
