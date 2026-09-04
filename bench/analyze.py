#!/usr/bin/env python3
"""Explain benchmark results: grammar coverage of ground truth, where the truth
sits in the candidate list, and whether misses are confusable-class errors."""
import json, os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAT_DIR = os.path.join(ROOT, "vendor", "openalpr", "runtime_data", "postprocess")
CONF = {"0": "OQD", "O": "0", "Q": "0", "D": "0", "1": "IL", "I": "1", "L": "1", "2": "Z", "Z": "2",
        "5": "S", "S": "5", "8": "B", "B": "8", "4": "A", "A": "4", "6": "G", "G": "6", "7": "T", "T": "7"}


def load_grammar(country):
    rules = []
    with open(os.path.join(PAT_DIR, country + ".patterns")) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            region, pat = parts[0], parts[1]
            rx, n, i = "", 0, 0
            while i < len(pat):
                c = pat[i]
                if c == "[":
                    j = pat.index("]", i)
                    rx += pat[i:j + 1]; i = j + 1; n += 1; continue
                rx += {"@": "[A-Z]", "#": "[0-9]", "?": "."}.get(c, re.escape(c)); n += 1; i += 1
            rules.append((region, re.compile("^" + rx + "$"), n))
    return rules


def accepts(rules, s):
    return any(len(s) == n and r.match(s) for _, r, n in rules)


def canon(s):
    """Collapse confusable classes so 'O'=='0', 'B'=='8', etc."""
    out = ""
    for c in s:
        if c in "OQD0": out += "0"
        elif c in "IL1": out += "1"
        elif c in "Z2": out += "2"
        elif c in "S5": out += "5"
        elif c in "B8": out += "8"
        elif c in "A4": out += "4"
        elif c in "G6": out += "6"
        elif c in "T7": out += "7"
        else: out += c
    return out


def main(path):
    d = json.load(open(path))
    print(f"== {d['label']}")
    for region, rows in d["rows"].items():
        rules = load_grammar(region)
        n = len(rows)
        gt_in_grammar = sum(accepts(rules, r["gt"]) for r in rows)
        det = [r for r in rows if r["det"]]
        miss = [r for r in det if not r["top1"]]
        ranks = Counter()
        conf_fixable = 0
        gt_matches_but_lost = 0
        read_in_grammar = 0
        for r in miss:
            if r["gt"] in r["cands"]:
                ranks[r["cands"].index(r["gt"]) + 1] += 1
            else:
                ranks["absent"] += 1
            if any(canon(c) == canon(r["gt"]) for c in r["cands"]):
                conf_fixable += 1
            if r["read"] and accepts(rules, r["read"]):
                read_in_grammar += 1
            if r["gt"] in r["cands"] and accepts(rules, r["gt"]):
                gt_matches_but_lost += 1
        print(f"  {region}: n={n} gt_accepted_by_grammar={gt_in_grammar}/{n} ({gt_in_grammar/n:.0%})  "
              f"detected={len(det)} top1_miss={len(miss)}")
        print(f"     truth rank among misses: {dict(sorted(ranks.items(), key=lambda x: str(x[0])))}")
        print(f"     misses where truth is in list and grammar accepts it: {gt_matches_but_lost}")
        print(f"     misses where wrong read is itself grammatical: {read_in_grammar}")
        print(f"     misses fixable by confusable-class canonicalization of some candidate: {conf_fixable}")
        # length stats of misses where GT absent
        absent = [r for r in miss if r["gt"] not in r["cands"] and r["read"]]
        lens = Counter(len(r["read"]) - len(r["gt"]) for r in absent)
        print(f"     truth absent: read-length minus truth-length histogram {dict(sorted(lens.items()))}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
