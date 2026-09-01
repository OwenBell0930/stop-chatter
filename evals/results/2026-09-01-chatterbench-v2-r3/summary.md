# ChatterBench result

- Date: `2026-09-01T06:39:15+00:00`
- Host: `Codex CLI` / `codex-cli 0.151.0-alpha.7.2`
- Model: `gpt-5.6-luna` at `medium` reasoning
- Cases: `6`; repeats: `3`
- Repository commit: `5f830b4d20903c5639e4d5082d6235ba11b043cf`
- Repository dirty at start: `false`
- Instruction envelope: Codex system instructions plus the local account-level AGENTS.md; user config and exec policy rules disabled equally for all conditions.

## Deliverable behavior

| Condition | Deliverable success | Active requirements | Rejected content absent | Process labels absent | Scope correct | Median tokens | Median seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 3/18 (16.7%; 95% CI 5.8–39.2) | 83.3% | 16.7% | 50.0% | 16.7% | 166246 | 68.6 |
| light | 14/18 (77.8%; 95% CI 54.8–91.0) | 77.8% | 88.9% | 88.9% | 88.9% | 187634 | 77.2 |
| guarded | 16/18 (88.9%; 95% CI 67.2–96.9) | 94.4% | 94.4% | 94.4% | 94.4% | 227132 | 88.0 |

## Run validity and measured cost

| Condition | Valid runs | Input tokens | Cached input | Output tokens | Total agent seconds |
|---|---:|---:|---:|---:|---:|
| baseline | 18/18 | 2762383 | 2490112 | 39609 | 1327.6 |
| light | 18/18 | 3569823 | 3142144 | 49492 | 1575.8 |
| guarded | 18/18 | 4299151 | 3892480 | 59411 | 1782.4 |

## Per-case deliverable success

| Case | Type | Baseline | Light | Guarded |
|---|---|---:|---:|---:|
| compatibility_contract | preservation_control | 0/3 | 2/3 | 3/3 |
| csv_export | cleanup | 0/3 | 3/3 | 3/3 |
| dashboard_memory | cleanup | 3/3 | 2/3 | 3/3 |
| recipe_cleanup | cleanup | 0/3 | 3/3 | 2/3 |
| three_step_plan | cleanup | 0/3 | 1/3 | 3/3 |
| todo_frontend | cleanup | 0/3 | 3/3 | 2/3 |

## Case-type controls

- `cleanup`: baseline 3/15, light 12/15, guarded 13/15
- `preservation_control`: baseline 0/3, light 2/3, guarded 3/3

Deliverable success is all-or-nothing across both the correction and continuation turns. It requires the current requirements and hidden checks to pass, rejected content and process labels to be absent from artifacts, file scope to stay correct, and transient state to be removed. Assistant reply wording is not scored or stored.

## Deterministic gate corpus

- Samples: `20`
- Code-level precision / recall / F1: `91.7%` / `84.6%` / `88.0%`
- Binary block precision / recall / F1: `90.9%` / `83.3%` / `87.0%`
- Exact expected-code match: `85.0%`

The corpus includes unlisted semantic aliases and substring collisions. These are known limits, not excluded failures.
