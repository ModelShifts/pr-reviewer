"""Compare review comments with the synthetic ground truth in ``samples/diffs``.

    python scripts/evaluate.py
    python scripts/evaluate.py --out eval.json

A finding counts as found when a comment is on the same file and side, the line
is within the finding's window, and the comment body contains one of the
keywords. This is a check against small fictional diffs, not a quality claim
about real pull requests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pr_reviewer.config import Settings
from pr_reviewer.review import review_diff
from pr_reviewer.rules import load_rules

ROOT = Path(__file__).resolve().parent.parent


def matches(comment, finding: dict) -> bool:
    if comment.path != finding["path"]:
        return False
    if comment.side != finding.get("side", "RIGHT"):
        return False
    window = int(finding.get("window", 0))
    if abs(comment.line - int(finding["line"])) > window:
        return False
    body = comment.body.casefold()
    # Phrases that mean the comment agrees with the bug instead of reporting it.
    avoid = [str(word).casefold() for word in finding.get("avoid") or []]
    if any(word in body for word in avoid):
        return False
    keywords = [str(word).casefold() for word in finding.get("keywords") or []]
    if keywords and not any(word in body for word in keywords):
        return False
    return True


def score(comments, expected: list[dict]) -> tuple[int, int, list[str], list[str]]:
    """Return found count, true-positive comments, missed notes, extra notes."""
    unused = list(comments)
    missed = []
    found = 0
    for finding in expected:
        hit = next((comment for comment in unused if matches(comment, finding)), None)
        if hit is None:
            missed.append(f"{finding['path']}:{finding['line']} {finding.get('needle', '')}")
            continue
        unused.remove(hit)
        found += 1
    extras = [f"{comment.path}:{comment.line} {comment.body}" for comment in unused]
    return found, len(comments) - len(unused), missed, extras


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate pr-reviewer on the synthetic diffs.")
    parser.add_argument("--samples", default=str(ROOT / "samples" / "diffs"))
    parser.add_argument("--config", default=str(ROOT / ".github" / "pr-reviewer.yml"))
    parser.add_argument("--out")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    rules = load_rules(args.config)
    rows = []
    raw = []
    tot_found = tot_expected = tot_tp = tot_comments = 0
    for truth_path in sorted(Path(args.samples).glob("*.truth.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        diff_path = truth_path.with_name(truth["diff"])
        diff = diff_path.read_text(encoding="utf-8")
        started = time.time()
        try:
            review = review_diff(diff, settings, rules, pr_title=str(truth.get("pr_title") or ""))
        except Exception as exc:
            rows.append((truth["name"], 0, len(truth["expected"]), 0, 0, 0.0, f"error: {exc}", ""))
            tot_expected += len(truth["expected"])
            print(f"{truth['name']}: error: {exc}", file=sys.stderr)
            continue
        elapsed = time.time() - started
        found, tp, missed, extras = score(review.comments, truth["expected"])
        rows.append((
            truth["name"], found, len(truth["expected"]), tp, len(review.comments), elapsed,
            "; ".join(missed), "; ".join(extras),
        ))
        tot_found += found
        tot_expected += len(truth["expected"])
        tot_tp += tp
        tot_comments += len(review.comments)
        raw.append(review.to_dict() | {"sample": truth["name"], "seconds": round(elapsed, 2)})
        print(
            f"{truth['name']}: {found}/{len(truth['expected'])} found, "
            f"{len(review.comments)} comments, {elapsed:.1f}s",
            file=sys.stderr,
        )

    print(f"\nBackend: {settings.backend}, model: {settings.model_name}\n")
    print("| Sample | Found | Comments | True positives | Time (s) | Missed | Extra |")
    print("|---|---|---|---|---|---|---|")
    for name, found, expected, tp, comments, elapsed, missed, extras in rows:
        print(
            f"| {name} | {found}/{expected} | {comments} | {tp} | {elapsed:.1f} | "
            f"{missed or '-'} | {extras or '-'} |"
        )
    recall = 100 * tot_found / max(tot_expected, 1)
    print(
        f"| **All** | **{tot_found}/{tot_expected} ({recall:.0f}%)** | {tot_comments} | {tot_tp} | | | |"
    )
    if args.out:
        Path(args.out).write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
