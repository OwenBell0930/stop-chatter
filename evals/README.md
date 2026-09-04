# ChatterBench

ChatterBench measures one narrow behavior: after a user retracts an unrequested
idea, does the agent leave the deliverables in the correct current state—without
rejected content, correction-history labels, unrelated file changes, broken
active requirements, or a later resurrection?

New publishable runs follow [evaluation-plan.md](evaluation-plan.md) (SCE-1.2).
The official campaign host is local Grok Build (`grok-4.6`), not Codex and not
the Cursor chat or a Task subagent. That document is the unique spec: orthogonal
fixtures, per-turn trees and patches, a hashed source freeze, checker command
logs tied to each turn, and absolute duration / token / estimated-USD cost.
Do not publish token or wall-clock increase percentages. ChatterBench v2
numbers remain a historical AND of their then-defined checks. Historical result
directories must not be rewritten.

It is intentionally separate from the repository unit tests. Unit tests show
that the installer and deterministic gate behave as implemented. ChatterBench
compares end-to-end agent behavior against an independent, frozen gold spec.

## Protocol

- Six correction cases are copied into fresh Git repositories with a two-commit
  history so leftover extra files are visibly from an earlier over-scoped draft.
  Five require pruning; one requires preserving an explicit compatibility
  rejection and its negative contract test. Gold specs stay outside the agent
  workspace.
- Baseline does not install Stop Chatter. Light and Guarded install it through
  the normal installer. Guarded state is not pre-filled; the model initializes
  from the visible task and Skill, and that cost is measured.
- The same model, reasoning effort, fixture, and user task are run in three
  conditions: `baseline`, `light`, and `guarded`. Conditions rotate so the same
  mode is not always first.
- Each task gets a new session. Only that task's continuation turn resumes it.
  Cross-session memory is disabled. The continuation prompt is an ordinary
  follow-up: it does not re-force Guarded or name checker commands.
- Deterministic graders check both turns' real files: active requirements,
  retired-concept residue, process-label leakage, retired-surface files gone,
  and unauthorized add/modify/delete/restore. Reply wording is not scored.
  Checker call counts and leftover transient state are diagnostics only.
- A run is a **deliverable success** only when both turns complete and every
  required artifact check passes.
- Results identify the host, actual model slug, reasoning effort, date, and
  freeze file hashes. Public records contain timings and token usage but do
  not contain assistant reply text, hidden chain-of-thought, or session
  identifiers.

The included gate corpus is also independent of the implementation. It contains
clean samples, direct matches, configured aliases, unlisted semantic aliases,
substring collisions, exceptions, allowlists, binary data, and unreadable text.
Its precision/recall/F1 describe only the deterministic checker, not the Skill.

## Run

Gate corpus only (no model calls):

```bash
python3 evals/benchmark.py gate
```

Protocol smoke with the real host (not part of calibration):

```bash
python3 evals/benchmark.py agent \
  --grok-bin "/Applications/Grok Build.app/Contents/Resources/resources/bin/grok" \
  --conditions baseline light guarded \
  --cases recipe_cleanup \
  --repeats 1 \
  --model grok-4.6 \
  --reasoning medium \
  --timeout 600 \
  --output /tmp/stop-chatter-smoke
```

Official campaign: six cases, three conditions, five repeats, 90 two-turn tasks:

```bash
python3 evals/benchmark.py agent \
  --grok-bin "/Applications/Grok Build.app/Contents/Resources/resources/bin/grok" \
  --conditions baseline light guarded \
  --repeats 5 \
  --model grok-4.6 \
  --reasoning medium \
  --timeout 600 \
  --output "/Users/zhaosi./Documents/Cursor Projects/stop-chatter/evals/results/sce-1.2-grok46"
```

The runner writes a freeze snapshot, a manifest, one artifact-only JSON record
and per-turn trees/patches per run, `summary.json`, and `summary.md`. The same
output directory can resume by skipping complete records on the same freeze;
incomplete records are not retried automatically. Rescoring must import the
frozen scorer; drift stops the job instead of falling back to live sources.

## Interpretation

This benchmark is deliberately adversarial and small. A host/model result is
not evidence for another host/model. CLI USD figures are estimates, not
invoices. Missing cost fields stay unknown. The deterministic gate cannot infer
an alias that neither the user nor the task state supplies; the corpus measures
that limitation.

## Published evidence

Public README numbers pool the two SCE-1.2 campaigns on the same six scenarios: Grok Build / `grok-4.6` and WorkBuddy / GLM-5.3, 90 tasks each, **180** in total. Headline deliverable success is Baseline **18/60**, Light **48/60**, Guarded **53/60**. The chart snapshot is [evals/public/sce-1.2.json](public/sce-1.2.json).

The earlier Codex ChatterBench v2 artifact view remains at [results/2026-09-01-chatterbench-v2-r3/](results/2026-09-01-chatterbench-v2-r3/). That directory is historical and must not be rewritten.

Earlier Git commits used a reply-inclusive benchmark schema and may contain
synthetic model replies. The current public dataset contains only synthetic
fixtures, artifact evidence, and measured cost—never real user or project data.
