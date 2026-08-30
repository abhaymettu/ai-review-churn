# Nobody is reading the robot

**On 91% of pull requests that an AI reviewer touches, no human leaves a single inline
review comment. And when the bot reviews alone, its comments get resolved 45% of the time
instead of 76%.**

AI code review is being used as a replacement for human review, not a supplement. That is
precisely the condition under which it works worst.

## The numbers

Sample: 1,818 public GitHub pull requests that received at least one inline review comment
from CodeRabbit, GitHub Copilot's code reviewer, or Gemini Code Assist, drawn from 1,686
distinct repositories across 20 monthly strata (Jan 2025 to Aug 2026). Confidence intervals
are bootstrap, resampling repositories rather than pull requests, because one repository's
review habits apply to all of its PRs.

| | |
|---|---|
| AI-reviewed PRs with **no human inline review at all** | **90.9%** [89.6, 92.3] |
| Bot review threads resolved, **bot reviewing alone** | **44.8%** [41.3, 48.5] |
| Bot review threads resolved, **human also reviewing** | **75.6%** [65.6, 83.3] |
| Human replies to a bot thread | 14.3% |
| Human replies to a human thread | 48.0% |
| Code changed under a bot thread (`isOutdated`) | 36.0% |
| Code changed under a human thread | 62.4% |
| Bot threads the bot resolved itself | 0.0% |

The share with no human inline review is rising:

| Quarter | AI-reviewed PRs | No human inline review |
|---|---|---|
| 2025 Q1 | 43 | 76.7% |
| 2025 Q2 | 119 | 86.6% |
| 2025 Q3 | 143 | 86.7% |
| 2025 Q4 | 226 | 91.2% |
| 2026 Q1 | 416 | 91.4% |
| 2026 Q2 | 580 | 92.4% |
| 2026 Q3 | 291 | 93.1% |

Merge rates are unmoved: 84.8% for bot-only PRs, 84.9% when a human reviewed too. Whatever
the bot is doing, it is not gating anything.

## Why this is not the study everyone already did

Two 2026 papers measured whether AI review comments get acted on, and both are good:

- [Human-AI Synergy in Agentic Code Review](https://arxiv.org/abs/2603.15911) — 278,790
  inline conversations, human suggestion adoption 56.5% vs AI 16.6%.
- ["Go Home Copilot, You're Drunk"](https://arxiv.org/abs/2607.21997) — 54,713 agent
  comments, resolution rates 72.9% (Copilot), 67.2% (Cursor), 54.8% (Codex).

Both sample from projects where human review is happening: 300 projects with 100+ stars in
the first, 341 Python repositories with PRs through December 2023 in the second. In this
sample that population is the **9.1% "both" cell** — and inside it, bot threads resolve at
75.6%, close to the published figures. So this is not a contradiction. It is the same
measurement extended to the 91% of AI-reviewed PRs those samples exclude, where the number
collapses to 44.8%.

The published resolution rates are conditional on a human being in the room.

## Method

1. **Frame.** GitHub search API, `commenter:<bot> type:pr`, one random 30-minute window per
   bot per month, Jan 2025 to Aug 2026. Windows are clusters; whole windows are taken so
   there is no top-1000 ranking bias. 7,380 PRs.
2. **Outcomes.** GitHub GraphQL, complete `reviewThreads` per PR: `isResolved`,
   `isOutdated`, `resolvedBy`, and every thread's first-comment author with `__typename`.
   Costs one rate-limit point per PR.
3. **Classification.** A PR is `bot_only` if every inline review thread was opened by a
   known AI review bot, `both` if humans opened some too. Non-review bots (security
   scanners, CI, linters) are bucketed separately and counted in neither arm.

Classification uses the complete thread set from the API, never the sampling window, since
a window only shows comments posted inside it and a human may comment an hour later.

```bash
pip install -r requirements.txt
python src/01c_frame_search.py          # build the frame (needs gh auth)
python src/02_fetch_outcomes.py data/frame_prs_shuffled.csv
python src/03_analyze.py
python src/03_analyze.py --selfcheck    # planted-effect test on synthetic data
```

## What this does not show

- **`isResolved` is not correctness.** It means somebody closed the thread. A dismissed
  comment and a fixed one look identical. `isOutdated` is reported alongside it as a
  second, independent signal, and it moves the same direction (36.0% vs 62.4%).
- **Repos that never use the resolve feature** depress the bot-only number. This is the
  main open threat: bot-only PRs skew toward smaller repositories, which may use GitHub's
  resolve affordance less regardless of who is reviewing. Separating "nobody read it" from
  "this repo does not click resolve" needs a repo-level control that is not in here yet.
- **Not causal.** Repos where humans review are different from repos where they do not, in
  ways beyond the presence of a bot.
- The frame selects PRs an AI bot commented on, so every rate is conditional on that. This
  says nothing about the share of *all* GitHub PRs that get AI review.

## Layout

```
src/01c_frame_search.py   sampling frame from the GitHub search API
src/01_build_frame.py     GH Archive alternative (abandoned, see NOTES.md)
src/02_fetch_outcomes.py  GraphQL outcome fetcher, resumable
src/03_analyze.py         classification, clustered bootstrap, self-check
NOTES.md                  design log, including what was tried and dropped
out/results.json          every number in this README
```

MIT.
