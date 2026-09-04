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

On 2026-09-03, ChatterBench (SCE-1.2) ran **6 correction scenarios × 3 modes × 5 repeats** on local Grok Build with `grok-4.6`: **90 tasks**, 30 per mode. A task counts as success only after both the correction and one ordinary follow-up leave the files in the current requested state.

<div align="center">
  <a href="assets/benchmark-v2-en.svg">
    <img src="assets/benchmark-v2-en.svg" width="100%" alt="ChatterBench deliverable comparison: Baseline 33.3%, Light 86.7%, Guarded 96.7%" />
  </a>
</div>

| Mode | Deliverable success | Current requirements kept | Rejected content absent | Retired files removed |
|---|---:|---:|---:|---:|
| Baseline | 10/30, **33.3%** | 96.7% | 90.0% | 36.7% |
| Light | 26/30, **86.7%** | 96.7% | 100% | 90.0% |
| Guarded | 29/30, **96.7%** | 100% | 100% | 96.7% |

With the Skill installed, deliverable success moves from about one in three to nearly nine in ten. Adding the optional checker brings it to 29 out of 30. Light and Guarded keep process labels out of the files.

“Deliverable success” means the current behavior is still there, retracted ideas and process wording are gone from remaining files, and files that existed only for the retracted idea have been removed. **Reply wording is not scored.**

This is a synthetic, single-model measurement of correction hygiene—not a claim about every host or production task. See the [method](evals/README.md). The checker script was scored separately on 20 labeled samples: precision **91.7%**, recall **84.6%**, F1 **88.0%**.

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
| Light | Default for ordinary corrections and later supplements | `SKILL.md` only |
| Guarded | Explicit request, or a repeated regression whose check scope can be bounded | transient target state + deterministic checker |

Light is the default. Do not enter Guarded merely because the task is long, touches Git, or spans multiple files. Guarded mode creates task-local transient state and checks configured residue before delivery. Neither mode modifies global configuration or durable memory automatically.

## Install and uninstall

```bash
git clone https://github.com/OwenBell0930/stop-chatter.git
cd stop-chatter
python3 scripts/install.py --host all --scope project --target /path/to/project
```

This creates:

- Cursor / Codex: `.agents/skills/stop-chatter`
- Claude Code: `.claude/skills/stop-chatter`

The installer never overwrites an existing destination. After install, type `/stop-chatter` (Codex: `$stop-chatter`) when you correct a requirement. You do not need to attach it on every message; Cursor may also apply it when the request looks like a correction.

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

Initialize before changing deliverables. If valid state for this root already exists, `init` reuses it and does not reset the start baseline:

```bash
STOP_CHATTER_SKILL_DIR=.agents/skills/stop-chatter
# For a Claude Code project install, use: .claude/skills/stop-chatter
# For a user-scope install, use the matching path from host setup
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" init --root .
```

Edit `.stop-chatter/state.json`: enter the current positive target, the narrowest add/modify paths, exact `must_remove` paths that visible evidence supports deleting, retired concepts, and useful semantic aliases. Leave the captured baseline unchanged. Set `ready` to `true` only after those values are current. The checker rejects an untouched template instead of returning a meaningless pass.

```bash
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" check --root . --cleanup-state-on-pass
```

By default, this-round file operations are compared with the task-start Git baseline when one exists; `must_remove` paths are existence-checked even if they were not modified. A passing final check removes only the transient state in the same command; a failed check keeps it for one targeted repair and rerun. Without a complete baseline, the result is labeled limited coverage and does not claim that original user changes were verified. Pass explicit paths for a non-Git workflow, `--mode staged` for the index, or `--mode all` for a bounded repository scan.

See the [target-state protocol](references/protocol.md) for the full schema and narrow exception rules.

## Gate findings

| Code | Meaning |
|---|---|
| `STC001` | A retired term or configured semantic alias remains in an artifact |
| `STC002` | A this-round added or modified file maps to no active requirement |
| `STC003` | A meta-instruction or compliance label leaked into an artifact |
| `STC004` | A file could not be safely inspected |
| `STC005` | A file was deleted without being listed in `delivery.must_remove` |
| `STC006` | A path listed in `delivery.must_remove` still exists |

The checker enforces deterministic facts only. The Skill supplies task-relevant aliases; the script does not pretend to understand arbitrary semantics.

## Privacy

- The Skill, installer, uninstaller, and deterministic checker run locally with the Python standard library: **zero third-party runtime dependencies, no network calls, no telemetry**.
- The installer does not add hooks, edit host settings, or write durable memory. Guarded state is task-local, Git-ignored, and removed after delivery.
- The public benchmark uses synthetic fixtures. Current run records contain artifact checks, patches, and execution metadata—not assistant replies, session IDs, or user/project data.
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
