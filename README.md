<p align="right">
  <strong>English</strong> | <a href="README.zh-CN.md">简体中文</a>
</p>

<div align="center">
  <a href="assets/hero-en.svg">
    <img src="assets/hero-en.svg" width="100%" alt="Stop Chatter — Make LLMs deliver only what you want now, without rejected scope or process residue" />
  </a>
</div>

# stop-chatter

<div align="center">

**Make LLMs deliver only what you want now—without rejected scope or process residue.**

[![CI](https://github.com/OwenBell0930/stop-chatter/actions/workflows/ci.yml/badge.svg)](https://github.com/OwenBell0930/stop-chatter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-0B1020.svg)](LICENSE)
[![Zero runtime dependencies](https://img.shields.io/badge/runtime_dependencies-0-19A974.svg)](#two-modes)
[![Cursor · Codex · Claude Code](https://img.shields.io/badge/Cursor_·_Codex_·_Claude_Code-ready-FF6B4A.svg)](#install-and-uninstall)
[![Local only](https://img.shields.io/badge/telemetry-none-19A974.svg)](#privacy)
[![Install + uninstall](https://img.shields.io/badge/install_+_uninstall-explicit-0B1020.svg)](#install-and-uninstall)

</div>

`stop-chatter` is a lightweight, portable Agent Skill with an optional zero-dependency deterministic gate. It does more than ask a model to “say less.” After a correction, it recompiles the current target and removes everything created only by the retired idea—including code, tests, comments, UI copy, PR text, and memory candidates.

Works with Cursor, OpenAI Codex, and Claude Code.

## The pain, in one story

> I asked for tomato-and-egg stir-fry. The agent added Dongpo pork. After I corrected it, the PR became “Tomato and egg (without Dongpo pork),” while comments and tests kept explaining why the pork was gone. Later in the same long task, a pork elbow appeared.

<div align="center">
  <a href="assets/user-story-en.svg">
    <img src="assets/user-story-en.svg" width="100%" alt="A typical agent leaks rejected ideas into artifacts; Stop Chatter keeps only the current target" />
  </a>
</div>

Another common version: you say “keep it concise and efficient,” but the artifact is titled “Plan 2.0 — concise, efficient, no-fluff edition.” The model may even save “the user dislikes Dongpo pork” as a durable preference.

This is not just verbosity. It is **dangling negation**: content already rejected in the conversation remains in the working specification and leaks into the final artifact.

| What you did | Typical failure | What `stop-chatter` aims for |
|---|---|---|
| Remove an unrequested feature | Titles, comments, and PR text keep announcing its absence | Artifacts describe only what exists now |
| Ask for concise execution | “Concise edition” labels and compliance essays appear | The constraint shapes execution, not product copy |
| Correct direction during a long task | A nearby synonym resurrects the rejected idea | Prune the dependency cone and relevant aliases |
| Correct one task | The example becomes a permanent user preference | Keep corrections task-local by default |

## Measured deliverable results

On 2026-09-01, ChatterBench ran **5 core Chinese correction cases × 3 conditions × 3 fresh repeats** on the same `gpt-5.6-luna` / Codex CLI setup: **45 core runs and 90 valid turns**. A separate 9-run preservation control checks that the tool does not delete an explicitly required compatibility contract. All **54 runs / 108 turns** completed successfully.

<div align="center">
  <a href="assets/benchmark-v2-en.svg">
    <img src="assets/benchmark-v2-en.svg" width="100%" alt="ChatterBench deliverable comparison: Baseline 20.0%, Light 80.0%, Guarded 86.7%, with token and time costs" />
  </a>
</div>

| Condition | Deliverable success | Current requirements kept | Rejected content absent | File scope correct | Median tokens | Median time |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 3/15, **20.0%** (95% CI 7.0–45.2) | 80.0% | 20.0% | 20.0% | 165.7k | 64.5s |
| Light | 12/15, **80.0%** (95% CI 54.8–93.0) | 80.0% | 86.7% | 86.7% | 178.9k (**+7.9%**) | 75.1s (**+16.4%**) |
| Guarded | 13/15, **86.7%** (95% CI 62.1–96.3) | 93.3% | 93.3% | 93.3% | 225.3k (**+35.9%**) | 88.0s (**+36.4%**) |

Token cost is the host-reported input plus output tokens for both turns; cached input is already a subset of input and is not added twice. Time is measured agent wall time.

**What the data supports:** Light increased deliverable success by **60.0 percentage points** with a **7.9% median-token increase**, making it the low-cost default. Guarded reached the highest observed success, but its extra checker workflow raised median tokens by **35.9%**; it is better reserved for long or high-residue tasks. Across all six cases including the preservation control, the result was Baseline **3/18**, Light **14/18**, and Guarded **16/18**. The control itself scored **0/3, 2/3, and 3/3**, respectively.

“Deliverable success” is deliberately plain: after both the correction turn and a neutral continuation, the required behavior must still work, active requirements must remain, rejected content and process labels must be absent from files, unrelated/protected files must stay untouched, and transient state must be removed. **Assistant reply wording does not affect the score**—the model should still tell the user what materially changed.

The formal run started from frozen clean commit `5f830b4`. The artifact-only public view was recomputed deterministically from those frozen checks and patches; no model run was repeated and no score was manually changed. Public records retain artifact evidence, timings, and token usage, but omit assistant replies and session identifiers.

This is still a small, synthetic, single-model and single-host benchmark—not a claim about Cursor, Claude Code, other models, English tasks, or production distributions. See the [method](evals/README.md), [artifact summary](evals/results/2026-09-01-chatterbench-v2-r3/summary.md), [machine-readable data](evals/results/2026-09-01-chatterbench-v2-r3/summary.json), [54 artifact-only run records](evals/results/2026-09-01-chatterbench-v2-r3/runs/), and [54 artifact patches](evals/results/2026-09-01-chatterbench-v2-r3/patches/).

The deterministic gate was evaluated separately on 20 labeled samples: code-level precision **91.7%**, recall **84.6%**, and F1 **88.0%**. Its two known misses were unlisted semantic aliases; its false positive was a substring collision. These numbers describe the checker only, not the whole Skill.

## How it works

1. **Recompile the current target:** express the latest request as a positive current-state goal; delete retracted items instead of preserving them as a ban list.
2. **Prune the dependency cone:** inspect plans, implementation, configuration, tests, comments, UI, PR text, and memory candidates created by the retired idea.
3. **Trace every change:** each changed artifact must map to an active requirement.
4. **Isolate process information:** correction history and execution constraints stay in working context, not in user-facing artifacts or durable memory.

The core path is deliberately small:

```text
Current positive target  →  necessary implementation  →  necessary validation  →  requested result
```

## Two modes

| Mode | Use when | Added machinery |
|---|---|---|
| Light | One correction, small output, easy to inspect | `SKILL.md` only |
| Guarded | Long task, multiple files, Git changes, repeated resurrection | transient target state + deterministic checker |

Light mode keeps the Skill lightweight. Guarded mode creates task-local transient state and checks observable residue before delivery. Neither mode modifies global configuration or durable memory automatically.

## Install and uninstall

```bash
git clone https://github.com/OwenBell0930/stop-chatter.git
cd stop-chatter
python3 scripts/install.py --host all --scope project --target /path/to/project
```

This creates:

- Cursor / Codex: `.agents/skills/stop-chatter`
- Claude Code: `.claude/skills/stop-chatter`

The installer never overwrites an existing destination. Invoke the Skill explicitly with:

| Host | Invocation |
|---|---|
| Cursor | `/stop-chatter` |
| OpenAI Codex | `$stop-chatter` |
| Claude Code | `/stop-chatter` |

Single-host and user-scope installation are also supported; see [host setup](references/host-setup.md).

Remove the same adapters with one explicit command:

```bash
python3 scripts/uninstall.py --host all --scope project --target /path/to/project
```

The uninstaller first verifies that each exact destination is a `stop-chatter` installation. It refuses unknown directories and leaves parent folders, sibling skills, host settings, and project files untouched. Both commands support `--dry-run`.

## Guarded mode in 30 seconds

After the first material correction, initialize task-local state:

```bash
STOP_CHATTER_SKILL_DIR=.agents/skills/stop-chatter
# For a Claude Code project install, use: .claude/skills/stop-chatter
# For a user-scope install, use the matching path from host setup
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" init --root .
```

Edit `.stop-chatter/state.json`: enter the current positive target, paths for active requirements, retired concepts, and useful semantic aliases, then set `ready` to `true`. The checker rejects an untouched template instead of returning a meaningless pass.

```bash
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" check --root .
```

By default, the checker inspects modified and untracked files in the Git worktree. Pass explicit paths for a non-Git workflow, `--mode staged` for the index, or `--mode all` for a bounded repository scan.

See the [target-state protocol](references/protocol.md) for the full schema and narrow exception rules.

## Gate findings

| Code | Meaning |
|---|---|
| `STC001` | A retired term or configured semantic alias remains in an artifact |
| `STC002` | A changed file maps to no active requirement |
| `STC003` | A meta-instruction or compliance label leaked into an artifact |
| `STC004` | A file could not be safely inspected |

The checker enforces deterministic facts only. The Skill supplies task-relevant aliases; the script does not pretend to understand arbitrary semantics.

## Privacy

- The Skill, installer, uninstaller, and deterministic checker run locally with the Python standard library: **zero third-party runtime dependencies, no network calls, no telemetry**.
- The installer does not add hooks, edit host settings, or write durable memory. Guarded state is task-local, Git-ignored, and removed after delivery.
- The public benchmark uses synthetic fixtures. Current run records contain artifact checks, patches, timings, and token counts—not assistant replies, session IDs, or user/project data.
- Stop Chatter does not change the privacy policy of Cursor, Codex, Claude Code, or the model provider. Any prompt or file context sent by the host is still governed by that host's settings and policy.

## Boundaries

- No hooks, host settings, durable memory, network calls, or telemetry are installed automatically.
- It does not add negative tests merely to prove that unrequested scope is absent. Keep one only when an active external contract or safety property requires it.
- Light mode depends on model compliance. Guarded mode hard-checks visible file facts; conversational completion replies remain outside the gate so the agent can report material changes and validation.
- A passing gate is artifact-hygiene evidence, not proof that the implementation is correct.

## Validate this repository

```bash
python3 -m unittest discover -s tests -v
```

The tests cover the two motivating regression families: rejected content leaking into artifacts, and meta-instructions such as “be concise” becoming artifact labels. CI runs the same suite on Python 3.11.

## License

[MIT](LICENSE)
