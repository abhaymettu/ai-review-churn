"""Who reviews the long tail? Share of reviewed PRs whose only inline reviewer is an AI bot.

Sampling: random hours of GH Archive select PRs that received at least one inline
review comment. Classification does NOT use the hour's events, because an hour
only shows comments posted inside it and a human may have commented later.
Every sampled PR is re-fetched in full from the GitHub API and classified on its
complete set of review threads.
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
JL = ROOT / "out" / "pr_outcomes.jsonl"

REVIEW_BOTS = {
 "coderabbitai[bot]","coderabbit[bot]","copilot-pull-request-reviewer[bot]",
 "github-copilot[bot]","gemini-code-assist[bot]","amazon-q-developer[bot]",
 "codiumai-pr-agent[bot]","pr-agent[bot]","sweep-ai[bot]","devin-ai-integration[bot]",
 "chatgpt-codex-connector[bot]","jules-google[bot]","sourcery-ai[bot]",
 "greptile-apps[bot]","cursor[bot]","ellipsis-dev[bot]","qodo-merge-pro[bot]"}


def _norm(login):
    """GraphQL returns bot logins bare ("coderabbitai"); GH Archive and REST
    return them suffixed ("coderabbitai[bot]"). Compare on the bare form."""
    return (login or "").removesuffix("[bot]").lower()


REVIEW_BOTS_N = {_norm(b) for b in REVIEW_BOTS}


def load(path=JL):
    """One row per PR, classified on its complete review-thread set."""
    prs, threads = [], []
    with open(path) as f:
        for line in f:
            pr = json.loads(line)
            if pr.get("missing") or not pr.get("reviewThreads"):
                continue
            rt = pr["reviewThreads"]
            pid = f"{pr['repo_name']}#{pr['pr_number']}"
            nbot = nhum = 0
            for th in rt["nodes"]:
                cs = (th.get("comments") or {}).get("nodes") or []
                if not cs:
                    continue
                a = cs[0].get("author") or {}
                login = a.get("login")
                is_bot = a.get("__typename") == "Bot" or (login or "").endswith("[bot]")
                # A bot that is not a known AI review bot (security scanners, CI,
                # linters) is counted separately so it inflates neither arm.
                if is_bot and _norm(login) in REVIEW_BOTS_N:
                    kind = "reviewbot"; nbot += 1
                elif is_bot:
                    kind = "otherbot"
                else:
                    kind = "human"; nhum += 1
                rb = (th.get("resolvedBy") or {})
                threads.append(dict(
                    pr_id=pid, repo=pr["repo_name"], kind=kind, author=login,
                    resolved=bool(th.get("isResolved")),
                    outdated=bool(th.get("isOutdated")),
                    n_comments=(th.get("comments") or {}).get("totalCount", 0),
                    human_replied=any((c.get("author") or {}).get("__typename") == "User"
                                      for c in cs[1:]),
                    self_resolved=bool(rb.get("login")) and rb.get("login") == login))
            if nbot + nhum == 0:
                continue
            au = pr.get("author") or {}
            prs.append(dict(
                pr_id=pid, repo=pr["repo_name"], pr_number=pr["pr_number"],
                created_at=pr.get("createdAt"), merged=bool(pr.get("merged")),
                state=pr.get("state"),
                author=au.get("login"), author_is_bot=au.get("__typename") == "Bot",
                assoc=pr.get("authorAssociation"),
                changed_files=pr.get("changedFiles"),
                additions=pr.get("additions"), deletions=pr.get("deletions"),
                n_bot_threads=nbot, n_human_threads=nhum,
                truncated=rt["totalCount"] > len(rt["nodes"]),
                arm=("bot_only" if nbot and not nhum else
                     "human_only" if nhum and not nbot else "both")))
    return pd.DataFrame(prs), pd.DataFrame(threads)


def report(prs, threads):
    out = {}
    out["n_prs"] = int(len(prs))
    out["n_repos"] = int(prs["repo"].nunique())
    out["n_threads"] = int(len(threads))
    out["truncated_prs"] = int(prs["truncated"].sum())

    # Headline: among PRs that got any inline review, who did the reviewing
    mix = prs["arm"].value_counts(normalize=True).to_dict()
    out["review_mix"] = {k: float(v) for k, v in mix.items()}
    out["review_mix_n"] = {k: int(v) for k, v in prs["arm"].value_counts().items()}

    # Restricted to PRs an AI review bot touched at all
    touched = prs[prs.n_bot_threads > 0]
    out["among_bot_reviewed"] = {
        "n": int(len(touched)),
        "share_no_human_inline_review": float((touched.arm == "bot_only").mean()),
    }

    # Repo-clustered bootstrap: repos are the resampling unit, since one repo
    # can contribute many PRs and its review norms are shared across them.
    def cluster_ci(frame, mask_fn, reps=2000, seed=0):
        if not len(frame):
            return (None, None, None)
        rng = np.random.default_rng(seed)
        repos = frame["repo"].unique()
        by = {r: g for r, g in frame.groupby("repo")}
        point = float(mask_fn(frame))
        est = []
        for _ in range(reps):
            pick = rng.choice(repos, size=len(repos), replace=True)
            samp = pd.concat([by[r] for r in pick])
            est.append(mask_fn(samp))
        return point, float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))

    pt, lo, hi = cluster_ci(touched, lambda d: (d.arm == "bot_only").mean())
    out["among_bot_reviewed"]["ci95_repo_clustered"] = [lo, hi]

    # Trend by quarter
    p = prs.copy()
    p["q"] = pd.to_datetime(p["created_at"], format="mixed", utc=True).dt.to_period("Q").astype(str)
    tr = p.groupby("q").agg(n=("pr_id", "size"),
                            bot_only=("arm", lambda s: float((s == "bot_only").mean())),
                            any_bot=("n_bot_threads", lambda s: float((s > 0).mean())))
    out["by_quarter"] = tr.reset_index().to_dict("records")
    # The frame selects AI-reviewed PRs, so the meaningful trend is conditional
    # on the PR having had an AI review at all.
    t = p[p.n_bot_threads > 0].copy()
    tq = t.groupby("q").agg(n=("pr_id", "size"),
                            no_human_inline=("arm", lambda s: float((s == "bot_only").mean())))
    out["by_quarter_among_bot_reviewed"] = tq.reset_index().to_dict("records")

    # Does the bot get read when it is alone? resolution split by whether a
    # human also reviewed the same PR.
    rbt = threads[threads.kind == "reviewbot"].merge(
        prs[["pr_id", "arm"]], on="pr_id", how="left")
    for arm in ["bot_only", "both"]:
        sub = rbt[rbt.arm == arm]
        pt2, lo2, hi2 = cluster_ci(sub, lambda d: d.resolved.mean())
        out[f"bot_thread_resolution_{arm}"] = {
            "n_threads": int(len(sub)), "rate": pt2, "ci95": [lo2, hi2]}

    # Does anything happen to bot-only review? resolution + merge
    for arm in ["bot_only", "both", "human_only"]:
        sub = prs[prs.arm == arm]
        th = threads[threads.pr_id.isin(sub.pr_id)]
        out[f"outcomes_{arm}"] = {
            "n_prs": int(len(sub)),
            "merge_rate": float(sub.merged.mean()) if len(sub) else None,
            "bot_thread_resolved": float(th[th.kind == "reviewbot"].resolved.mean())
                                   if (th.kind == "reviewbot").any() else None,
            "human_thread_resolved": float(th[th.kind == "human"].resolved.mean())
                                     if (th.kind == "human").any() else None,
        }
    # Self-resolution check: bots closing their own threads inflates resolution
    rb = threads[threads.kind == "reviewbot"]
    out["bot_self_resolved_share"] = float(rb.self_resolved.mean()) if len(rb) else None
    out["bot_thread_human_reply_rate"] = float(rb.human_replied.mean()) if len(rb) else None
    hm = threads[threads.kind == "human"]
    out["human_thread_human_reply_rate"] = float(hm.human_replied.mean()) if len(hm) else None
    return out


def _selfcheck():
    """Hour-local events must not decide the arm; only the full thread set does."""
    recs = [
        # bot-only PR
        {"repo_name": "a/b", "pr_number": 1, "merged": True, "createdAt": "2026-01-01T00:00:00Z",
         "author": {"login": "u", "__typename": "User"}, "reviewThreads": {"totalCount": 2, "nodes": [
             {"isResolved": True, "resolvedBy": {"login": "u"}, "comments": {"totalCount": 1, "nodes": [
                 {"author": {"login": "coderabbitai", "__typename": "Bot"}}]}},
             {"isResolved": False, "resolvedBy": None, "comments": {"totalCount": 1, "nodes": [
                 {"author": {"login": "coderabbitai[bot]", "__typename": "Bot"}}]}}]}},
        # mixed PR
        {"repo_name": "a/b", "pr_number": 2, "merged": False, "createdAt": "2026-04-01T00:00:00Z",
         "author": {"login": "u", "__typename": "User"}, "reviewThreads": {"totalCount": 2, "nodes": [
             {"isResolved": True, "resolvedBy": {"login": "coderabbitai"}, "comments": {"totalCount": 1, "nodes": [
                 {"author": {"login": "coderabbitai", "__typename": "Bot"}}]}},
             {"isResolved": True, "resolvedBy": {"login": "v"}, "comments": {"totalCount": 2, "nodes": [
                 {"author": {"login": "v", "__typename": "User"}},
                 {"author": {"login": "u", "__typename": "User"}}]}}]}},
        # CI bot must not count as a reviewer in either arm
        {"repo_name": "a/c", "pr_number": 3, "merged": True, "createdAt": "2026-04-01T00:00:00Z",
         "author": {"login": "u", "__typename": "User"}, "reviewThreads": {"totalCount": 1, "nodes": [
             {"isResolved": False, "resolvedBy": None, "comments": {"totalCount": 1, "nodes": [
                 {"author": {"login": "codecov", "__typename": "Bot"}}]}}]}},
    ]
    tmp = ROOT / "out" / "_selfcheck.jsonl"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(json.dumps(r) for r in recs))
    prs, th = load(tmp)
    assert len(prs) == 2, prs                      # PR 3 has no real reviewer, dropped
    assert prs.set_index("pr_number").loc[1, "arm"] == "bot_only"
    assert prs.set_index("pr_number").loc[2, "arm"] == "both"
    r = report(prs, th)
    assert r["among_bot_reviewed"]["share_no_human_inline_review"] == 0.5, r
    assert abs(r["bot_self_resolved_share"] - 1/3) < 1e-9, r
    tmp.unlink()
    print("selfcheck OK: bare and suffixed bot logins both match; CI bots excluded from both arms")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck(); sys.exit(0)
    prs, th = load()
    prs.to_parquet(ROOT/"out"/"prs.parquet"); th.to_parquet(ROOT/"out"/"threads.parquet")
    res = report(prs, th)
    (ROOT/"out"/"results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
