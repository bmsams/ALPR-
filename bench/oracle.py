#!/usr/bin/env python3
"""Re-score stock candidate lists under different grammars without re-running OCR.

  union     first candidate accepted by any pattern in the country file
  oracle    per image, mean over the regions whose grammar accepts the truth
            of 'first candidate accepted by that region' (upper bound for a
            perfect jurisdiction classifier)
  wrong     per image, mean over regions that do NOT accept the truth (what a
            wrong jurisdiction guess costs)
"""
import json, sys
from collections import defaultdict
from analyze import load_grammar

def pick(cands, rules):
    for c in cands:
        if any(len(c) == n and r.match(c) for _, r, n in rules):
            return c
    return cands[0] if cands else None

def main(path):
    d = json.load(open(path))
    for region, rows in d["rows"].items():
        rules = load_grammar(region)
        by_region = defaultdict(list)
        for rg, r, n in rules:
            by_region[rg].append((rg, r, n))
        n = len(rows); stock = union = oracle = wrong = 0.0; covered = 0
        for row in rows:
            if not row["det"]:
                continue
            gt, cands = row["gt"], row["cands"]
            stock += cands[0] == gt
            union += pick(cands, rules) == gt
            acc = [rg for rg, rr in by_region.items() if any(len(gt) == k and x.match(gt) for _, x, k in rr)]
            rej = [rg for rg in by_region if rg not in acc]
            if acc:
                covered += 1
                oracle += sum(pick(cands, by_region[rg]) == gt for rg in acc) / len(acc)
            else:
                oracle += cands[0] == gt
            if rej:
                wrong += sum(pick(cands, by_region[rg]) == gt for rg in rej) / len(rej)
        print(f"{region}: n={n} regions={len(by_region)} truth_covered={covered}  "
              f"stock={stock/n:.1%}  union={union/n:.1%}  oracle_region={oracle/n:.1%}  wrong_region={wrong/n:.1%}")

if __name__ == "__main__":
    main(sys.argv[1])
