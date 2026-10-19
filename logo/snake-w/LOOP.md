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

## Objective and priorities (fixed by the owner; read before every invocation)

**The task is to fit each numbered lobe to its reference anatomy.**
- **Governing principle:**
  - The numbered-lobe evaluator determines what is wrong.
  - The geometry optimiser corrects it.
  - The visual critic determines whether the sculpture improved.
  - Appearance diagnostics may inform the work, but must not replace it.
- **The authoritative ledger** for geometry is the per-feature anatomical discrepancy of L01–L16, H1/H2 and the negative spaces:
  - per-feature IoU and contour alignment (both ways, worst arc, p95);
  - extrema, orientation and visible boundaries;
  - the independent visual severity.
- **Never use these as a geometry objective, gate or stopping criterion:**
  - global silhouette IoU;
  - whole-frame colour difference (`tools/seen.py`, CIEDE2000);
  - a shading decomposition, or any new aggregate metric.

  They may be reported as context. Do not dismiss a local correction because it barely changes a global score: a genuine improvement to one lobe matters.
- **Lighting and look work is not part of the loop.** If it seems warranted, propose it to the owner separately, with the reason, and wait for approval. Never suspend the geometry loop for it.
- **Do not add stopping criteria, global gates or optimisation objectives** that supersede the numbered-feature evaluation without the owner's explicit approval. Do not redefine the goal.
- **Keep surface quality separate.** Assess clay and zebra surface quality apart from colour and lighting; visible shape and sculptural continuity are first-class targets.
- **When local improvements plateau:**
  - diagnose which lobes are stuck and why the current controls cannot fit them;
  - add the specific missing freedom, or coordinated shape changes across neighbouring lobes;
  - then resume the same per-lobe loop.

  A plateau is not evidence that the remaining error is lighting.
- **Report progress** each round as:
  - the change in the worst lobe's discrepancy;
  - the number of anatomically faithful features (provisionally IoU ≥ 0.95 where the reference self-split is reliable, p95 contour error ≤ 3 px, no major crossing error, no new crease; a reporting lens to calibrate, not a gate);
  - the significant shape improvements accepted, with visual comparison sheets;
  - the remaining errors.

  Rounds completed and global appearance statistics are not progress.

## The round: look, describe, act, verify, reassess

The visual diagnosis comes before the optimisation. The optimiser does not generate candidates for the judge to reject afterwards.

1. **LOOK.** `diag_pages.py RENDERS TAG auto/rN/diag` builds pages of the incumbent beside the reference: reference | colour | clay | zebra | overlay. The overlay draws the reference outline in red and the current one in green. The pages cover the whole frame, every feature, every junction between neighbouring features, and the negative spaces. A fresh Sonnet (xhigh) critic inspects them with the diagnosis prompt (the round-22 prompt is in `auto/r22/diagnosis.md`'s header). It ranks the discrepancies that matter. For each it gives:
   - the feature or junction;
   - what the reference shows and what the current shows;
   - the specific error and where on the lobe;
   - its magnitude, severity and confidence;
   - the geometric correction, and the neighbours it affects;
   - coupled problems.
2. **DESCRIBE.** Check the critic's claims against the evaluator: extents, arcs, tilt, widths. Write `auto/rN/diagnosis.md`. Choose the round's corrections from the ranked discrepancies, not from lobe IDs. Rank by visible impact, measured magnitude, and whether the controls can make the change. A lobe can carry several distinct errors. Junctions and negative spaces count. Take up to three that do not share a crop.
3. **ACT.** For each chosen correction, write a `plan.json` entry: observed mismatch → desired change → responsible surface → controls → expected neighbour effects. The entry holds `target`, `joint` (a coupled neighbour fitted together), `controls` (only those the correction calls for) and `edge` ("x,y,r": the diagnosed location, weighted in the fit). Run `autoround.py propose rN --plan auto/rN/plan.json`.
   - If the change cannot be expressed by the handles, name the missing freedom and add it. Do not search the same space with another seed.
   - A failure that has repeated is evidence. Change the correction: fit it jointly with a neighbour, change the controls, or defer it.
4. **VERIFY.** Real colour, clay and zebra renders, then all features measured. The blind pair judge sees the targets and the targeted junction enlarged. It says which is closer, and what still differs in the closer one: outline, mass distribution or junction curvature. Accept only if the target improves without a new junction artefact or other defect.
5. **REASSESS.**
   - **Ledger:** fill in the round's rows of `auto/DISCREPANCIES.md` (feature | observed error | reference target | planned correction | attempted change | visual result | verdict | remaining error).
   - **Causes:** record every rejection's defect in `auto/causes.json` as a structured cause (`junction_pinch`, `crease`, `thinning`, `stray_blob`, `crossing_notch`, `mass_distribution`, `flat_top`) at its feature or junction. Every later fit whose crop holds that feature or junction tightens the guard for exactly that cause (`lobefit --causes`).
   - **Next round:** rebuild the diagnosis pages from the new incumbent, and diagnose again.

## Where the state lives (read this first)

**Workspace (WS):** a working copy of `logo/snake-w/`, with the snakes venv beside it. The repository's `logo/snake-w/` holds the same tools, and the `auto/` records are synced into `logo/snake-w/auto/`.
- Run every command from WS, with that venv's python.
- The session that started the loop uses the scratch copy named in `.claude/loop.md`.

**`WS/auto/state.json`** holds:
- the incumbent: `{tag, spec, renders, metrics, params, heads, look}` (the scene params file and its head bake, and the look file, its renders use);
- `tried`: rejected attempts per feature;
- `rounds`: every finished round.

**`WS/auto/owner.json`** holds what the owner said about features of the incumbent: `{fid: {sev, said, date, addressed}}`.
- The ranking takes the larger of the judges' and the owner's severity, so a fault the owner names comes back as a target even where the judges rate it low.
- Each accepted correction of that feature takes one step off the owner's severity (`merge`); at 1 the entry is `addressed` and the ranking stops counting it. Only the owner's words set an entry: add one when the owner says a feature is still wrong.

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
  - a target whose crop holds a head with a variant (`HEAD_VARIANTS` in `autoround.py`) gets a second candidate, key `TARGET+NAME`, fitted and rendered with that head; judge it like any other. H1's `neck1` was on for rounds 12–13 and is off from round 14: its head has a dark zebra blob under the jaw, which the judges count against every neck1 candidate;
  - build the sheets and the pair pages.
- **`autoround.py merge rN KEY,KEY [--rejected KEY,KEY]`** composes the accepted handles, renders and gates the result, and updates the incumbent. The keys are the summary's: `L01`, `L01+neck1`.
  - Accept at most one candidate per target: of a target's two candidates, the one its judge prefers, or the plain one when both are equal.
  - An accepted head variant's params and head bake become the incumbent's.
- **`autoledger.py`** rewrites `WS/auto/LEDGER.md`.
- **`lobemap.py spec out.json out.png`** draws the lobe-to-surface map.
- **`discrepancy.py colour.png out.json`** produces the ranking.

**The judge:** one Sonnet (xhigh) agent per candidate, seeing only `pair-<tag>/`. Its prompt is `WS/auto/JUDGE_PROMPT.md` (also in `logo/snake-w/auto/JUDGE_PROMPT.md`), with `{PAGES}` replaced by the absolute path of `pair-<tag>/`. X/Y comes from `mapping.json`. Write the verdict to `judge-<tag>.md`.
- **ACCEPT** when the candidate is closer to the reference at its target (by 1 or more) and introduces no defect of its own.
- **ACCEPT (neutral)** when the judge finds no difference and no defect anywhere, the gates pass, and the real renders measure a clear gain at the target: IoU up 0.03 or more, or its worst contour arc 5 px smaller. A change too small to see but measurably closer is kept, and later attempts build on it.
- **REJECT** otherwise.
- **Repair seed:** when the judge finds a rejected candidate closer at its target by 2 or more and rejects it only for a small defect it names (a seam, a crease), pass `--seed TARGET` to `merge`. The next round re-fits that target first, from the rejected handle (`lobefit --init`, sigma 0.4, the guards' crease tolerance 1.15 instead of 1.4), and the rejection does not count against the target's rank.
- Read X and Y from `mapping.json` before writing each verdict; the judge's "X" is not always the candidate.
- Paired verdicts count only beyond about one step: an untouched feature judged one step different is noise.
- The pair pages carry `page4-focus.png`: the target, and the neighbours whose IoU changed, enlarged. Small corrections (10–15 px) are invisible at the standard tile size. Round 1's first L01 judge said "same" everywhere while the collar had moved 13 px down.
- After the judges, write `WS/auto/sev.json`: `{feature: severity}`.
  - For each feature, take the severity the judge gave the version that becomes the incumbent: the candidate's column when it is accepted, the incumbent's column otherwise.
  - Where several judges cover a feature, use the judge of the candidate that changed it.
  - `discrepancy.py` adds 3 × this visual severity (1.5 before round 10) to the score, so lobes that look wrong but measure well (thin, rope-like, creased) keep coming back as targets.

## On every invocation

1. **Resume existing work first.** Inspect `state.json`, the latest `auto/rN/`, any background jobs (`ps aux | grep -E "autoround|lobefit|ffd_worker|audit_render"`) and active subagents. Do not restart work already in progress or duplicate expensive jobs.
2. **Complete pending evaluations.** For a finished `propose`:
   - judge every gate-passing candidate blind;
   - write the `judge-*.md` files;
   - run `merge` with the accepted tags and `--rejected` with the judge-rejected ones;
   - run `autoledger.py`.
3. **Select the next targets autonomously.** Run `autoround.py propose r(N+1)` from the new incumbent. The ranking chooses; the user does not. Rejected features are down-weighted automatically.
4. **Fit geometry directly.** Use the lobe handles: translate, depth, rotate, stretch, radius, width, side bulges, end rounding and, from round 16, end moves, on the strand's own station run. At a lobe whose run ends at its strand's tail (L01, L16), the end-b move carries the whole tail, and from round 19 the tail can also taper (`eb_r`) and turn on screen about the run's end (`eb_rot`). Use broader composition controls (`tools/twist.py`, regionfit) when an error comes from the arrangement and the same lobe fails twice.
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
