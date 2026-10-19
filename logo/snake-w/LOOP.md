# Autonomous Snake-W Reconstruction Loop

The tracked copy of the loop's instructions. A local `.claude/loop.md` points here and names its session's workspace.

**Mission:** continue improving the procedural snake-W reconstruction in `logo/snake-w/` toward the reference image (`snakes/ref/reference.png`). Pursue the highest achievable visual fidelity without waiting for human art direction.

The starting point is what already exists:
- the current accepted-best candidate;
- the anatomy registry;
- the discrepancy ranking and ledger;
- the lobe-to-surface map and lobe handles;
- the Three.js renderer;
- the blind visual judge process.

## Where the state lives (read this first)

**Workspace (WS):** a working copy of `logo/snake-w/`, with the snakes venv beside it. The repository's `logo/snake-w/` holds the same tools, and the `auto/` records are synced into `logo/snake-w/auto/`.
- Run every command from WS, with that venv's python.
- The session that started the loop uses the scratch copy named in `.claude/loop.md`.

**`WS/auto/state.json`** holds:
- the incumbent: `{tag, spec, renders, metrics}`;
- `tried`: rejected attempts per feature;
- `rounds`: every finished round.

**`WS/auto/rN/`** holds round N:
- `rank.md` / `rank.json`: the discrepancy ranking of the incumbent;
- `summary.json`: per target, the attribution, handle, before/after numbers and gates;
- `mapping.json`: the X/Y order for the judge;
- `pair-<tag>/`: the judge pages;
- `delta-<tag>.png`: the delta sheet;
- `judge-<tag>.md`: the verdict file, whose first line is `verdict: ACCEPT|REJECT`;
- `renders/`: the real renders.

**The tools** (in `WS/tools/`):
- **`autoround.py propose rN [--n 3] [--gens 18]`** runs one round end to end, except the judge:
  - rank the incumbent's lobes;
  - choose non-neighbouring targets;
  - for each target: `lobefit.py` (attribution + CMA-ES on the lobe handle), a real render, `evaluate.py` and the gates;
  - build the sheets and the pair pages.
- **`autoround.py merge rN TAG,TAG [--rejected T,T]`** composes the accepted handles, renders and gates the result, and updates the incumbent.
- **`autoledger.py`** rewrites `WS/auto/LEDGER.md`.
- **`lobemap.py spec out.json out.png`** draws the lobe-to-surface map.
- **`discrepancy.py colour.png out.json`** produces the ranking.

**The judge:** one Sonnet (xhigh) agent per candidate, seeing only `pair-<tag>/`. Its prompt is `WS/auto/JUDGE_PROMPT.md` (also in `logo/snake-w/auto/JUDGE_PROMPT.md`), with `{PAGES}` replaced by the absolute path of `pair-<tag>/`. X/Y comes from `mapping.json`. Write the verdict to `judge-<tag>.md`.
- **ACCEPT** when the candidate is closer to the reference at its target (by 1 or more) and introduces no defect of its own.
- **ACCEPT (neutral)** when the judge finds no difference and no defect anywhere, the gates pass, and the real renders measure a clear gain at the target: IoU up 0.03 or more, or its worst contour arc 5 px smaller. A change too small to see but measurably closer is kept, and later attempts build on it.
- **REJECT** otherwise.
- Paired verdicts count only beyond about one step: an untouched feature judged one step different is noise.
- The pair pages carry `page4-focus.png`: the target, and the neighbours whose IoU changed, enlarged. Small corrections (10–15 px) are invisible at the standard tile size. Round 1's first L01 judge said "same" everywhere while the collar had moved 13 px down.
- After the judges, write `WS/auto/sev.json`: `{feature: severity}`.
  - For each feature, take the severity the judge gave the version that becomes the incumbent: the candidate's column when it is accepted, the incumbent's column otherwise.
  - Where several judges cover a feature, use the judge of the candidate that changed it.
  - `discrepancy.py` adds 1.5 × this visual severity to the score, so lobes that look wrong but measure well (thin, rope-like, creased) keep coming back as targets.

## On every invocation

1. **Resume existing work first.** Inspect `state.json`, the latest `auto/rN/`, any background jobs (`ps aux | grep -E "autoround|lobefit|ffd_worker|audit_render"`) and active subagents. Do not restart work already in progress or duplicate expensive jobs.
2. **Complete pending evaluations.** For a finished `propose`:
   - judge every gate-passing candidate blind;
   - write the `judge-*.md` files;
   - run `merge` with the accepted tags and `--rejected` with the judge-rejected ones;
   - run `autoledger.py`.
3. **Select the next targets autonomously.** Run `autoround.py propose r(N+1)` from the new incumbent. The ranking chooses; the user does not. Rejected features are down-weighted automatically.
4. **Fit geometry directly.** Use the lobe handles: translate, depth, rotate, stretch, radius, width, side bulges and end rounding, on the strand's own station run. Use broader composition controls (`tools/twist.py`, regionfit) when an error comes from the arrangement and the same lobe fails twice.
5. **Judge actual renders.** Every challenger is compared with the incumbent in matched colour, clay and zebra views, at full frame and per feature, with the metrics and an independent visual judge.
6. **Accept or reject.** Preserve the accepted best. Reject regressions even when the surrogate cost improves. Record what changed and whether it looks closer to the reference.
7. **Continue.** Start the next highest-impact correction. Do not stop because a single lobe improved or a local fit failed.

## Execution policy

- **Roles and concurrency:**
  - Opus is the lead integrator; delegate bounded independent tasks (judging, critiques) to Sonnet subagents.
  - Run independent work concurrently, but do not duplicate running jobs or launch conflicting edits. The machine has 4 cores, and one `propose` uses about 3.
- **Scope:**
  - Do not turn every failure into new infrastructure, unit tests or documentation.
  - The reference image and actual sculptural quality (clay, zebra: no seams, creases, lumps) are the ultimate criteria.
  - If a modelling representation repeatedly stalls, compare a bounded alternative rather than endlessly tuning penalty weights.
- **Publishing:**
  - Push meaningful iterations, visual comparisons and ledgers to PR #86, on branch `claude/logo-snake-w`, under `logo/snake-w/`.
  - Sync the tools, the accepted spec and the `auto/` records.
  - Leave out large renders and buffers, and `.raw` files.
  - Maintain the development journal (`docs/JOURNAL.md` format) at milestones.
- **Git rules:**
  - Use the user's git identity. No AI attribution or co-author trailers.
  - Never merge, never push to master, never force-push, never release.
  - The user squash-merges with ghprsm.
- **Reporting to the user:** show each round's delta sheet and the ranked discrepancy ledger in chat. Do not ask the user to choose the next lobe.

## Progress and continuation

- **At the end of each invocation:** persist enough state that the next invocation can resume without guessing. `state.json` and `auto/rN/` do this; add a line to `WS/auto/NEXT.md` with the next action if it is not obvious.
- **While optimisation is running:** check whether results are ready, and do useful independent work meanwhile.
- **If all experiments fail:** diagnose the most important remaining visual mismatch and try a meaningfully different bounded correction.
- **Do not treat a completed iteration as completion of the project.**
  - The target is sustained, autonomous, measurable improvement of the entire sculpture, not a perfect optimisation score or a collection of individually fixed dimples.
  - Continue until the reference is convincingly reproduced, the available approaches have demonstrably plateaued, or an operational limit prevents further progress.
  - If blocked, report the specific obstacle and preserve resumable state rather than declaring artistic success.

## After a container restart

Background jobs die; the workspace (scratchpad) survives. `autoround.py propose rN` resumes an interrupted round: it keeps finished fits (`rN/<target>/fit.json`) and renders (`rN/metrics-<tag>.json`). Remove a stale `auto/LOCK` whose pid is not an `autoround.py` process, then rerun the same `propose rN`.
