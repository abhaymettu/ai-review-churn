"""Sample AI-bot-reviewed PRs, one random 30-minute window per month.

The substitution question is "among PRs an AI review bot reviewed, how often did
no human review inline?" So the frame only has to select bot-reviewed PRs, which
is precisely what `commenter:<bot>` returns. Whether a human also reviewed is
answered from the complete thread set via GraphQL, not from the frame.

Stratified by month so the time trend is estimable; windows are the clusters.
"""
import csv, json, random, subprocess, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "frame_prs.csv"
PACE = 11.0
BOTS = ["coderabbitai[bot]", "copilot-pull-request-reviewer[bot]",
        "gemini-code-assist[bot]"]
MONTHS = [(y, m) for y in (2025, 2026) for m in range(1, 13) if (y, m) <= (2026, 8)]
FIELDS = ["repo_name", "pr_number", "frame_bot", "window_start", "window_total",
          "pr_created_at", "pr_user"]


def search(bot, t0, t1, page):
    q = (f"commenter:{bot} type:pr "
         f"created:{t0:%Y-%m-%dT%H:%M:%S}..{t1:%Y-%m-%dT%H:%M:%S}")
    for attempt in range(3):
        p = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f", f"q={q}",
                            "-f", "per_page=100", "-f", f"page={page}",
                            "-f", "sort=created", "-f", "order=asc"],
                           capture_output=True, text=True)
        out = p.stdout.strip()
        if out:
            try:
                d = json.loads(out)
            except json.JSONDecodeError:
                d = None
            if isinstance(d, dict) and "items" in d:
                return d
            if isinstance(d, dict) and "secondary rate limit" in (d.get("message") or "").lower():
                print("    secondary limit, 120s", flush=True); time.sleep(120); continue
        time.sleep(30)
    return None


def main():
    rng = random.Random(20260830)
    seen, rows = set(), []
    if OUT.exists():
        OUT.unlink()
    fh = open(OUT, "w", newline="")
    w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader()
    for (y, m) in MONTHS:
        start = datetime(y, m, 1)
        days = (datetime(y + (m == 12), m % 12 + 1, 1) - start).days
        for bot in BOTS:
            t0 = start + timedelta(hours=rng.randrange(days * 24))
            t1 = t0 + timedelta(minutes=30)
            d = search(bot, t0, t1, 1); time.sleep(PACE)
            if not d:
                print(f"  {y}-{m:02d} {bot}: no response", flush=True); continue
            total = d.get("total_count", 0)
            items = list(d.get("items") or [])
            for pg in (2, 3):
                if len(items) >= min(total, 1000):
                    break
                d2 = search(bot, t0, t1, pg); time.sleep(PACE)
                if not (d2 and d2.get("items")):
                    break
                items += d2["items"]
            n = 0
            for it in items:
                repo = "/".join(it.get("repository_url", "").split("/")[-2:])
                num = it.get("number")
                if not repo or not num or (repo, num) in seen:
                    continue
                seen.add((repo, num))
                w.writerow({"repo_name": repo, "pr_number": num, "frame_bot": bot,
                            "window_start": t0.isoformat(), "window_total": total,
                            "pr_created_at": it.get("created_at"),
                            "pr_user": (it.get("user") or {}).get("login")})
                n += 1
            fh.flush()
            print(f"  {y}-{m:02d} {bot.split('[')[0]:34s} total={total:<5} +{n:<4} cum={len(seen):,}",
                  flush=True)
    fh.close()
    print(f"\nframe: {len(seen):,} bot-reviewed PRs -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
