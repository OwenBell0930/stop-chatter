# ChatterBench

ChatterBench measures one narrow behavior: after a user retracts an unrequested
idea, does the agent deliver the current result without leaving the rejected
idea, correction history, compliance labels, redundant artifacts, or a later
resurrection behind?

It is intentionally separate from the repository unit tests. Unit tests show
that the installer and deterministic gate behave as implemented. ChatterBench
compares end-to-end agent behavior against an independent, frozen gold spec.

## Protocol

- Six correction cases are copied into fresh Git repositories. Five require
  pruning; one requires preserving an explicit compatibility rejection and its
  negative contract test, so indiscriminate deletion cannot score well. Gold
  specs stay outside the agent workspace.
- The same model, reasoning effort, fixture, and user task are run in three
  conditions: `baseline`, `light`, and `guarded`.
- Each run has a correction turn and a neutral continuation turn that does not
  repeat the retired concept.
- Deterministic graders check active requirements, retired-concept residue,
  process-trace leakage, unexpected files, protected content, hidden behavior,
  final-response residue, and continuation resurrection.
- A run counts as a **clean delivery** only when every required check passes.
- Token use, response length, and latency are reported as costs, not quality.
- Results always identify the host, model, reasoning effort, date, sample count,
  repeat count, repository commit, and instruction envelope.

The included gate corpus is also independent of the implementation. It contains
clean samples, direct matches, configured aliases, unlisted semantic aliases,
substring collisions, exceptions, allowlists, binary data, and unreadable text.
Its precision/recall/F1 describe only the deterministic checker, not the Skill.

## Run

Gate corpus only (no model calls):

```bash
python3 evals/benchmark.py gate
```

One smoke run:

```bash
python3 evals/benchmark.py agent \
  --codex-bin /Applications/ChatGPT.app/Contents/Resources/codex \
  --conditions baseline light guarded \
  --cases recipe_cleanup \
  --repeats 1 \
  --model gpt-5.6-luna \
  --reasoning medium \
  --output /tmp/stop-chatter-smoke
```

A publishable run should use at least three repeats, ideally five:

```bash
python3 evals/benchmark.py agent \
  --codex-bin /Applications/ChatGPT.app/Contents/Resources/codex \
  --conditions baseline light guarded \
  --repeats 5 \
  --model gpt-5.6-luna \
  --reasoning medium
```

The runner writes a manifest, one JSON record and artifact patch per run, the
two final agent replies used by the residue grader, `summary.json`, and
`summary.md`. It does not publish hidden chain-of-thought or Codex session
identifiers.

On macOS, the desktop-bundled Codex binary may be newer than a separately
installed `/usr/local/bin/codex`. Pass `--codex-bin` explicitly so the manifest
records the executable that produced the data.

## Interpretation

This benchmark is deliberately adversarial and small. A host/model result is
not evidence for another host/model, and a single repeat is a pilot rather than
a stable estimate. The deterministic gate cannot infer an alias that neither
the user nor the task state supplies; the corpus measures that limitation.

## Published evidence

- [ChatterBench v2: 54 runs / 108 valid turns](results/2026-09-01-chatterbench-v2-r3/)
  uses six cases and three fresh repeats from frozen clean commit `5f830b4`.
- The earlier [15-run pilot](results/2026-09-01-codex-luna-pilot/) is retained
  as historical evidence and is not pooled with v2.
