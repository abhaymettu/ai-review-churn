"""Build the sampling frame from GH Archive hourly dumps.

Cluster sample: draw random hours between 2025-01-01 and 2026-08-20, take every
PullRequestReviewCommentEvent in each sampled hour. Hours are the clusters.

Why not the GitHub search API: `commenter:` search works but its undocumented
secondary rate limiter throttles hard, and it only finds PRs a bot touched, so
the human comparison arm would come from a different selection process. GH
Archive gives every review comment in the hour, bot and human alike, from one
draw. Why not CodAGE: recall-oriented with false positives by design, stops
2026-04-15, and anonymous Hugging Face downloads are IP-throttled.
"""
import csv, gzip, json, random, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "gharchive"
OUT = ROOT / "data" / "review_comments.csv"
SEED = 20260829
N_HOURS = 60
START = datetime(2025, 1, 1)
END = datetime(2026, 8, 20)

# Login-anchored review bots. Bare-login or free-text matching (the source of
# CodAGE's false positives) is deliberately not used.
REVIEW_BOTS = {
    "coderabbitai[bot]", "coderabbit[bot]", "copilot-pull-request-reviewer[bot]",
    "github-copilot[bot]", "gemini-code-assist[bot]", "amazon-q-developer[bot]",
    "codiumai-pr-agent[bot]", "pr-agent[bot]", "sweep-ai[bot]",
    "devin-ai-integration[bot]", "chatgpt-codex-connector[bot]", "jules-google[bot]",
    "sourcery-ai[bot]", "greptile-apps[bot]", "cursor[bot]", "ellipsis-dev[bot]",
}
FIELDS = ["hour", "repo_name", "pr_number", "actor_login", "is_review_bot",
          "comment_id", "path", "created_at"]


def fetch(hour):
    dest = RAW / f"{hour:%Y-%m-%d-%-H}.json.gz"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    url = f"https://data.gharchive.org/{hour:%Y-%m-%d-%-H}.json.gz"
    r = subprocess.run(["curl", "-s", "--max-time", "300", "--retry", "3",
                        "-o", str(dest), url], capture_output=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    dest.unlink(missing_ok=True)
    return None


def parse(path, hour):
    rows = []
    try:
        with gzip.open(path, "rt", errors="replace") as f:
            for line in f:
                if '"PullRequestReviewCommentEvent"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "PullRequestReviewCommentEvent":
                    continue
                p = e.get("payload") or {}
                c = p.get("comment") or {}
                pr = p.get("pull_request") or {}
                login = (e.get("actor") or {}).get("login")
                if not pr.get("number"):
                    continue
                rows.append({
                    "hour": f"{hour:%Y-%m-%d-%H}",
                    "repo_name": (e.get("repo") or {}).get("name"),
                    "pr_number": pr["number"],
                    "actor_login": login,
                    "is_review_bot": int(login in REVIEW_BOTS),
                    "comment_id": c.get("id"),
                    "path": c.get("path"),
                    "created_at": c.get("created_at") or e.get("created_at"),
                })
    except (OSError, EOFError) as exc:
        print(f"  bad gz {path.name}: {exc}", flush=True)
    return rows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    span = int((END - START).total_seconds() // 3600)
    hours = sorted({START + timedelta(hours=rng.randrange(span))
                    for _ in range(N_HOURS * 2)})[:N_HOURS]

    print(f"downloading {len(hours)} random hours...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        paths = list(ex.map(fetch, hours))

    all_rows, ok = [], 0
    for h, p in zip(hours, paths):
        if p is None:
            print(f"  MISSING {h:%Y-%m-%d-%H}", flush=True)
            continue
        r = parse(p, h)
        all_rows += r
        ok += 1
        nb = sum(x["is_review_bot"] for x in r)
        print(f"  {h:%Y-%m-%d-%Hh}: {len(r):,} review comments, {nb:,} from bots",
              flush=True)

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    prs = {(r["repo_name"], r["pr_number"]) for r in all_rows}
    botprs = {(r["repo_name"], r["pr_number"]) for r in all_rows if r["is_review_bot"]}
    print(f"\nhours ok: {ok}/{len(hours)}")
    print(f"review comments: {len(all_rows):,}  "
          f"({sum(r['is_review_bot'] for r in all_rows):,} from review bots)")
    print(f"PRs: {len(prs):,} total, {len(botprs):,} with >=1 bot review comment")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
