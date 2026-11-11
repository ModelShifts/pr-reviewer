"""Write the synthetic diffs in ``samples/diffs``.

Every name and figure is fictional. The script is deterministic: running it
again leaves the committed files unchanged.

    python scripts/make_samples.py
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "diffs"

PICKER = """\
def pick(bins, index):
    \"\"\"Return the bin at the given index.\"\"\"
    if index <= len(bins):
        return bins[index]
    return None
"""

DISCOUNT_OLD = """\
def apply_discount(price, percent):
    \"\"\"Apply a discount. percent is a number from 0 to 100.\"\"\"
    if percent < 0:
        raise ValueError("percent must be >= 0")
    return price * (100 - percent) / 100
"""

DISCOUNT_NEW = """\
def apply_discount(price, percent):
    \"\"\"Apply a discount. percent is a number from 0 to 100.\"\"\"
    if percent < 0:
        raise ValueError("percent must be >= 0")
    return price - price / percent
"""

STOCK = """\
def units_available(stock, reserved):
    \"\"\"Return how many units can still be picked.\"\"\"
    return stock - reserved - reserved
"""

QUERY = """\
def find_item(db, name):
    \"\"\"Look up an item by name.\"\"\"
    query = "SELECT id FROM items WHERE name = '%s'" % name
    return db.execute(query)
"""

TOTAL_OLD = """\
def order_total(items):
    \"\"\"Sum the price of every item.\"\"\"
    total = 0
    for item in items:
        total += item["price"]
    return total
"""

TOTAL_NEW = """\
def order_total(items):
    \"\"\"Sum the price of every item.\"\"\"
    total = 0
    for item in items:
        total += item["price"]
    return len(items)
"""

DOCS_OLD = """\
# Guide

The picker returns a bin.
"""

DOCS_NEW = """\
# Guide

The picker returns the first bin.
"""


def line_number(source: str, needle: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if needle in line:
            return number
    raise SystemExit(f"needle not in source: {needle}")


def render_diff(path: str, old: str | None, new: str | None) -> str:
    old_lines = [] if old is None else old.splitlines()
    new_lines = [] if new is None else new.splitlines()
    fromfile = "/dev/null" if old is None else f"a/{path}"
    tofile = "/dev/null" if new is None else f"b/{path}"
    # lineterm="" keeps control lines free of a newline; content lines copied from
    # splitlines() have none either. Add one newline per record so the file is a real diff.
    chunks = difflib.unified_diff(
        old_lines, new_lines, fromfile=fromfile, tofile=tofile, n=3, lineterm=""
    )
    body = "".join(chunk if chunk.endswith("\n") else chunk + "\n" for chunk in chunks)
    header = [f"diff --git a/{path} b/{path}\n"]
    if old is None:
        header.append("new file mode 100644\nindex 0000000..1111111\n")
    elif new is None:
        header.append("deleted file mode 100644\nindex 1111111..0000000\n")
    else:
        header.append("index 2222222..3333333 100644\n")
    text = "".join(header) + body
    if not text.endswith("\n"):
        text += "\n"
    return text


def _finding(path: str, source: str, needle: str, category: str, keywords: list[str], avoid: list[str] | None = None) -> dict:
    finding = {
        "path": path,
        "line": line_number(source, needle),
        "side": "RIGHT",
        "category": category,
        "window": 2,
        "keywords": keywords,
        "needle": needle,
    }
    if avoid:
        finding["avoid"] = avoid
    return finding


SAMPLES = [
    {
        "name": "picker-index",
        "path": "picker.py",
        "old": None,
        "new": PICKER,
        "expected": [_finding(
            "picker.py", PICKER, "if index <= len(bins):", "correctness",
            ["len", "bound", "off-by", "out of"],
        )],
    },
    {
        "name": "discount-formula",
        "path": "billing.py",
        "old": DISCOUNT_OLD,
        "new": DISCOUNT_NEW,
        "expected": [_finding(
            "billing.py", DISCOUNT_NEW, "return price - price / percent", "correctness",
            ["divis", "zero", "percent", "100", "discount"],
        )],
    },
    {
        "name": "double-subtract",
        "path": "stock.py",
        "old": None,
        "new": STOCK,
        "pr_title": "KAN-4 Return units still available",
        "expected": [_finding(
            "stock.py", STOCK, "return stock - reserved - reserved", "correctness",
            ["twice", "double", "subtract"],
            avoid=["should subtract"],
        )],
    },
    {
        "name": "query-concat",
        "path": "query.py",
        "old": None,
        "new": QUERY,
        "expected": [_finding(
            "query.py", QUERY, "SELECT id FROM items", "security",
            ["select", "sql", "inject", "quote", "param", "concat"],
        )],
    },
    {
        "name": "total-returns-count",
        "path": "totals.py",
        "old": TOTAL_OLD,
        "new": TOTAL_NEW,
        "expected": [_finding(
            "totals.py", TOTAL_NEW, "return len(items)", "correctness",
            ["len", "count", "total"],
            avoid=["should return the number", "should return the count", "not their total"],
        )],
    },
    {
        "name": "docs-only",
        "path": "docs/guide.md",
        "old": DOCS_OLD,
        "new": DOCS_NEW,
        "ignored": True,
        "expected": [],
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in SAMPLES:
        diff = render_diff(spec["path"], spec["old"], spec["new"])
        (OUT / f"{spec['name']}.diff").write_text(diff, encoding="utf-8")
        truth = {
            "name": spec["name"],
            "diff": f"{spec['name']}.diff",
            "ignored": bool(spec.get("ignored", False)),
            "expected": spec["expected"],
        }
        if spec.get("pr_title"):
            truth["pr_title"] = spec["pr_title"]
        (OUT / f"{spec['name']}.truth.json").write_text(
            json.dumps(truth, indent=2) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(SAMPLES)} diffs in {OUT}")


if __name__ == "__main__":
    main()
