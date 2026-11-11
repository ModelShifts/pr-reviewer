# Evaluation

Figures in the README and on the case page use this measurement: **5 of 5 seeded bugs found**, with Qwen2.5-Coder-7B-Instruct (Q4_K_M) on the API backend, on an 8-core CPU (15 GB RAM, no GPU).

**Command:** `python scripts/evaluate.py`

A finding counts as found when a comment is on the same file and side, the line is within the finding’s window, and the comment body contains one of the expected keywords (and does not agree with the bug instead of reporting it). This is a check against six small fictional diffs in [`samples/diffs`](../samples/diffs), not a quality claim about real pull requests. A seventh outcome is the documentation-only diff, which the default rules ignore and which should produce no comments.

| Diff | Bug | Path | Expected findings |
|---|---|---|---|
| picker-index.diff | off-by-one (`index <= len(bins)`) | picker.py | 1 |
| double-subtract.diff | reserved quantity subtracted twice | stock.py | 1 |
| query-concat.diff | SQL built by string formatting | query.py | 1 |
| total-returns-count.diff | `len(items)` where a total was wanted | totals.py | 1 |
| discount-formula.diff | `price / percent` where a fraction was wanted | billing.py | 1 |
| docs-only.diff | documentation only (ignored) | — | 0 |

Ground truth is in the matching `*.truth.json` files. The samples take about a minute each with the 7B GGUF. A raw per-diff JSON from a fresh re-run of this command on this box is not attached here; run the script to reproduce.
