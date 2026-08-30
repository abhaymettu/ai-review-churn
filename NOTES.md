# Design log

Written as the study was built, so the methods section reflects what actually
happened rather than a tidied-up version of it.

## The question

AI review bots post inline comments on pull requests. Benchmarks show they flag
problems on code that needs no changes: SWR-Bench (arXiv 2509.01494) built 500
"Clean-PRs" alongside 500 that genuinely needed changes and measured precision of
2.79% to 15.39% across tools. That is a benchmark result. It says nothing about
what happens to those comments in the field.

So: when an AI review bot opens a review thread on a real pull request, does
anyone act on it?

## Why not the obvious dataset

Started on CodAGE (HF `taher-ghaleb/CodAGE`), the dataset behind "AI-to-AI Code
Reviews of GitHub Pull Requests" (arXiv 2608.21311, ESEM 2026). Abandoned it:

1. Its own card says it is recall-oriented and "contains false positives by
   design". `agent_type` is a candidate label, not a verified one.
2. Coverage stops 2026-04-15.
3. Anonymous Hugging Face downloads are IP-throttled; the 4.2GB review-comment
   file 429'd on both remote range reads and direct download.

Reading GitHub directly turned out to be strictly better: no inherited false
positives, current data, and the outcome fields only exist in the API anyway.

## Frame

GitHub search API, `commenter:<bot> type:pr` restricted to random 20-minute
windows between 2025-01-01 and 2026-08-20. A 20-minute window holds roughly
80-150 PRs per bot, comfortably under the search API's 1000-result ceiling, so
every PR inside a sampled window is enumerable. Taking whole windows avoids the
ranking bias of reading the top 1000 of a wide slice. This is a cluster sample;
windows are the clusters.

Bots: coderabbitai, copilot-pull-request-reviewer, gemini-code-assist,
amazon-q-developer, codiumai-pr-agent. All are `[bot]`-anchored logins, which is
the high-precision identification signal.

## Outcome

GitHub GraphQL, `PullRequestReviewThread`:
- `isResolved` - someone marked the thread resolved
- `isOutdated` - the code under the comment changed afterward
- `resolvedBy` - who resolved it, so bot self-resolution can be separated out
- comment authors and `__typename`, so threads are classified bot vs human by
  who opened them

Cost is 1 rate-limit point per PR, so ~5000 PRs/hour.

## Known threats, and what is done about them

- **`isResolved` is not "the comment was correct".** It means someone closed the
  thread. Dismissal and fixing look identical. Mitigated by reading `isOutdated`
  alongside it (did the code actually change) and by reporting both.
- **Bots resolving their own threads.** Captured via `resolvedBy` and excluded in
  the robustness pass.
- **Repos that never use the resolve feature.** A repo where no thread is ever
  resolved contributes only noise. Robustness pass drops repos with zero resolved
  threads.
- **Selection into the paired comparison.** The within-PR comparison only exists
  on PRs carrying both bot and human review threads. Pilot data suggests that is
  a minority of PRs, so the paired result is reported as conditional on that
  subset, not as the population estimate.

## Pilot finding that changed the design

A 20-PR pilot from one window: 13 PRs had bot inline review threads and **zero**
human inline review threads; 7 had no threads at all. Not one PR had both. These
were small repositories.

Consequence: the within-PR paired comparison cannot be the only design, because
its subset may be small and unrepresentative. The share of bot-reviewed PRs that
receive no human inline review is itself a primary result, and it is measurable
on the full unbiased sample.

---

## What the study became (final)

The original question ("do AI review comments get acted on, compared to human ones?") was
already answered while this was being built. Two papers found in the novelty check:

- arXiv 2603.15911, *Human-AI Synergy in Agentic Code Review*: 278,790 inline conversations,
  300 projects, within-PR comparison, human suggestion adoption 56.5% vs AI 16.6%.
- arXiv 2607.21997, *"Go Home Copilot, You're Drunk"*: 54,713 agent comments, 341 Python
  repos, uses `isResolved` — the same primary measure planned here. Copilot 72.9%,
  Cursor 67.2%, Codex 54.8%.

Running a smaller version of that was not worth doing. The study pivoted to the population
both papers exclude by construction: 2603.15911 requires 100+ stars and consistent activity,
2607.21997 requires Python and PRs created through Dec 2023. Both therefore condition on
projects where human review happens.

New question: **among PRs that an AI bot reviews, how often does no human review inline at
all, and does the bot's own effectiveness depend on whether a human is there?**

## Why the frame moved twice

1. **CodAGE** — dropped. Recall-oriented with false positives by design, ends 2026-04-15,
   and anonymous Hugging Face downloads are IP-throttled.
2. **GH Archive hourly dumps** — attempted, then abandoned on time cost, not on principle.
   It is the better instrument (every review comment in an hour, bot and human, from one
   draw) but the link ran at 287 KB/s against ~37 MB per hour-file, and repeated partial
   downloads left truncated gzips. Not affordable in one night. Worth redoing properly.
3. **GitHub search API** — used. For this question the frame only has to select
   *AI-reviewed* PRs, which `commenter:<bot>` does exactly. Whether a human also reviewed
   is answered from the complete thread set via GraphQL, not from the frame, so the frame's
   selection is the population of interest rather than a bias.

## Bug worth recording

GraphQL returns bot logins **bare** (`coderabbitai`); GH Archive and the REST API return
them **suffixed** (`coderabbitai[bot]`). The bot-matching set used the suffixed form, so
every AI review thread was silently bucketed as "other bot" and excluded from both arms.
The first analysis run reported zero bot threads on a sample that contained 355 CodeRabbit
threads. Caught by checking the author distribution rather than trusting the summary.
The self-check now asserts both login forms match.

## Threat that is now measured rather than assumed

Bot self-resolution (a bot closing its own thread, which would inflate resolution rates)
was the main worry about `isResolved`. Measured: **0.0%** of bot threads in the sample.
Not a problem here.

The threat that remains open is repo-level use of the resolve affordance. Bot-only PRs
skew small, and small repos may simply not click resolve. That needs a repo-level control.
