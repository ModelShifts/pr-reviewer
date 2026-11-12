# Evaluation

Figures in the README and on the case page use this measurement: **5 of 5 seeded bugs found**, with Qwen2.5-Coder-7B-Instruct (Q4_K_M) on the API backend.

**Measured:** 12 November 2026, Asia/Singapore.

**Model:** Qwen2.5-Coder-7B-Instruct (Q4_K_M), file `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, served by a local llama.cpp server (`n_ctx` 4096, 8 threads, no GPU layers).

**Machine:** 8-core CPU (Intel Xeon), 15 GB RAM, no GPU.

**Command:** `python scripts/evaluate.py --out docs/eval.json`

**Backend:** `MS_BACKEND=api`, `MS_API_BASE=http://127.0.0.1:8001/v1`, `MS_MODEL=qwen2.5-coder-7b`.

Raw per-diff JSON: [`eval.json`](eval.json).

A finding counts as found when a comment is on the same file and side, the line is within the finding’s window, and the comment body contains one of the expected keywords (and does not agree with the bug instead of reporting it). This is a check against six small fictional diffs in [`samples/diffs`](../samples/diffs), not a quality claim about real pull requests. A seventh outcome is the documentation-only diff, which the default rules ignore and which should produce no comments. Ground truth is in the matching `*.truth.json` files.

| Sample | Found | Comments | True positives | Time (s) | Missed | Extra |
|---|---|---|---|---|---|---|
| picker-index | 1/1 | 1 | 1 | 29.3 | - | - |
| double-subtract | 1/1 | 1 | 1 | 33.4 | - | - |
| query-concat | 1/1 | 1 | 1 | 27.1 | - | - |
| total-returns-count | 1/1 | 1 | 1 | 56.0 | - | - |
| discount-formula | 1/1 | 1 | 1 | 50.6 | - | - |
| docs-only | 0/0 | 0 | 0 | 0.0 | - | - |
| **All** | **5/5 (100%)** | 5 | 5 | 27.1–56.0 | | |

The methodology table for the six diffs:

| Diff | Bug | Path | Expected findings |
|---|---|---|---|
| picker-index.diff | off-by-one (`index <= len(bins)`) | picker.py | 1 |
| double-subtract.diff | reserved quantity subtracted twice | stock.py | 1 |
| query-concat.diff | SQL built by string formatting | query.py | 1 |
| total-returns-count.diff | `len(items)` where a total was wanted | totals.py | 1 |
| discount-formula.diff | `price / percent` where a fraction was wanted | billing.py | 1 |
| docs-only.diff | documentation only (ignored) | — | 0 |

These samples took about half a minute to a minute each with the 7B GGUF on this machine.
