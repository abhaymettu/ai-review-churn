"""Fetch PR outcomes + review-thread resolution state from the GitHub GraphQL API.

Resumable: appends one JSON object per PR to out/pr_outcomes.jsonl and skips
anything already present. Batches PRs per request via GraphQL aliases.
"""
import json, os, subprocess, sys, time, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "pr_outcomes.jsonl"
BATCH = 20          # PRs per GraphQL request (costs 1 rate-limit point per PR)
PACE = 2.0          # seconds between batches; bursts trip a secondary limiter
THREADS = 100       # review threads fetched per PR
TCOMMENTS = 10      # comments fetched per thread

FRAG = """
  fragment prF on PullRequest {
    number state merged mergedAt createdAt closedAt isDraft
    author { login __typename }
    authorAssociation
    additions deletions changedFiles
    comments { totalCount }
    reviews(first:1) { totalCount }
    reviewThreads(first:%d) {
      totalCount
      nodes {
        isResolved isOutdated isCollapsed path line startLine diffSide
        resolvedBy { login __typename }
        comments(first:%d) {
          totalCount
          nodes { databaseId createdAt authorAssociation
                  author { login __typename } bodyText }
        }
      }
    }
  }
""" % (THREADS, TCOMMENTS)


def run_query(pairs):
    """pairs: list of (owner, name, number). Returns dict alias -> pr json."""
    parts = []
    for i, (o, n, num) in enumerate(pairs):
        parts.append(
            f'a{i}: repository(owner:"{o}", name:"{n}") '
            f'{{ pullRequest(number:{num}) {{ ...prF }} }}'
        )
    q = "query {\n" + "\n".join(parts) + "\n  rateLimit { cost remaining resetAt }\n}\n" + FRAG
    for attempt in range(6):
        p = subprocess.run(["gh", "api", "graphql", "-f", f"query={q}"],
                           capture_output=True, text=True)
        out = p.stdout.strip()
        if not out:
            time.sleep(10 * (attempt + 1))
            continue
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            time.sleep(10 * (attempt + 1))
            continue
        msg = (d.get("message") or "") if isinstance(d, dict) else ""
        if "secondary rate limit" in msg.lower():
            print("    secondary limit, sleeping 120s", flush=True)
            time.sleep(120)
            continue
        if d.get("data"):
            return d, None
        # transient GraphQL errors (timeouts on huge PRs) - retry once, then skip
        time.sleep(8 * (attempt + 1))
    return None, "exhausted retries"


def main(frame_csv, limit=None):
    import csv
    pairs = []
    with open(frame_csv) as f:
        for row in csv.DictReader(f):
            pairs.append((row["repo_name"], int(row["pr_number"])))
    if limit:
        pairs = pairs[:int(limit)]

    done = set()
    if OUT.exists():
        with open(OUT) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r["repo_name"], r["pr_number"]))
                except Exception:
                    pass
    todo = [p for p in pairs if p not in done]
    print(f"{len(pairs):,} PRs in sample, {len(done):,} already fetched, {len(todo):,} to go",
          flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fh = open(OUT, "a")
    ok = err = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        trip = []
        for repo, num in chunk:
            if "/" not in repo:
                continue
            o, n = repo.split("/", 1)
            trip.append((o, n, num))
        d, e = run_query(trip)
        if d is None:
            print(f"  batch {i//BATCH} failed: {e}", flush=True)
            err += len(chunk); time.sleep(5); continue
        time.sleep(PACE)
        data = d.get("data") or {}
        rl = data.get("rateLimit") or {}
        for j, (o, n, num) in enumerate(trip):
            node = (data.get(f"a{j}") or {}).get("pullRequest") if data.get(f"a{j}") else None
            rec = {"repo_name": f"{o}/{n}", "pr_number": num}
            if node is None:
                rec["missing"] = True
                err += 1
            else:
                rec.update(node); ok += 1
            fh.write(json.dumps(rec) + "\n")
        fh.flush()
        if (i // BATCH) % 10 == 0:
            print(f"  {i+len(chunk):,}/{len(todo):,}  ok={ok:,} err={err:,} "
                  f"rate_remaining={rl.get('remaining')}", flush=True)
        rem = rl.get("remaining")
        if rem is not None and rem < 200:
            reset = rl.get("resetAt")
            print(f"  rate limit low ({rem}), sleeping until {reset}", flush=True)
            time.sleep(300)
    fh.close()
    print(f"done. ok={ok:,} err={err:,}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
