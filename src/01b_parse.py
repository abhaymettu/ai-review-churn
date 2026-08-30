"""Parse whatever GH Archive hours are on disk into a review-comment table."""
import csv, gzip, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT/"data"/"gharchive", ROOT/"data"/"review_comments.csv"
REVIEW_BOTS = {
 "coderabbitai[bot]","coderabbit[bot]","copilot-pull-request-reviewer[bot]",
 "github-copilot[bot]","gemini-code-assist[bot]","amazon-q-developer[bot]",
 "codiumai-pr-agent[bot]","pr-agent[bot]","sweep-ai[bot]","devin-ai-integration[bot]",
 "chatgpt-codex-connector[bot]","jules-google[bot]","sourcery-ai[bot]",
 "greptile-apps[bot]","cursor[bot]","ellipsis-dev[bot]","qodo-merge-pro[bot]"}
FIELDS=["hour","repo_name","pr_number","actor_login","is_review_bot","is_any_bot",
        "comment_id","path","created_at","pr_user","pr_user_is_bot"]
rows=[]; files=sorted(RAW.glob("*.json.gz"))
print(f"parsing {len(files)} hours", flush=True)
for p in files:
    hour=p.name.replace(".json.gz","")
    n=nb=0
    try:
        with gzip.open(p,"rt",errors="replace") as f:
            for line in f:
                if '"PullRequestReviewCommentEvent"' not in line: continue
                try: e=json.loads(line)
                except json.JSONDecodeError: continue
                if e.get("type")!="PullRequestReviewCommentEvent": continue
                pl=e.get("payload") or {}; c=pl.get("comment") or {}; pr=pl.get("pull_request") or {}
                if not pr.get("number"): continue
                login=(e.get("actor") or {}).get("login") or ""
                pru=((pr.get("user") or {}).get("login")) or ""
                rows.append({"hour":hour,"repo_name":(e.get("repo") or {}).get("name"),
                    "pr_number":pr["number"],"actor_login":login,
                    "is_review_bot":int(login in REVIEW_BOTS),
                    "is_any_bot":int(login.endswith("[bot]")),
                    "comment_id":c.get("id"),"path":c.get("path"),
                    "created_at":c.get("created_at") or e.get("created_at"),
                    "pr_user":pru,"pr_user_is_bot":int(pru.endswith("[bot]"))})
                n+=1; nb+= login in REVIEW_BOTS
    except (OSError,EOFError) as ex:
        print(f"  bad {p.name}: {ex}", flush=True); continue
    print(f"  {hour}: {n:,} review comments ({nb:,} review-bot)", flush=True)
with open(OUT,"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
prs={(r["repo_name"],r["pr_number"]) for r in rows}
botprs={(r["repo_name"],r["pr_number"]) for r in rows if r["is_review_bot"]}
print(f"\nrows {len(rows):,} | PRs {len(prs):,} | PRs with >=1 review-bot comment {len(botprs):,}")
