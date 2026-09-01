# ChatterBench result

- Date: `2026-09-01T05:02:11+00:00`
- Host: `Codex CLI` / `codex-cli 0.151.0-alpha.7.2`
- Model: `gpt-5.6-luna` at `medium` reasoning
- Cases: `5`; repeats: `1`
- Repository commit: `39a936c6d594fe02afab6a2365f6c0984cf89aa1`
- Instruction envelope: Codex system instructions plus the local account-level AGENTS.md; user config and exec policy rules disabled equally for all conditions.

## Agent behavior

| Condition | Clean delivery | Active requirements | Artifact residue-free | Response residue-free | Scope clean | Median tokens | Median seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0/5 (0.0%; 95% CI 0.0–43.4) | 80.0% | 20.0% | 100.0% | 20.0% | 173108 | 65.4 |
| guarded | 2/5 (40.0%; 95% CI 11.8–76.9) | 60.0% | 100.0% | 100.0% | 100.0% | 243044 | 99.4 |
| light | 2/5 (40.0%; 95% CI 11.8–76.9) | 80.0% | 60.0% | 100.0% | 60.0% | 190806 | 69.5 |

Clean delivery is all-or-nothing across both the correction and continuation turns.

## Deterministic gate corpus

- Samples: `20`
- Code-level precision / recall / F1: `91.7%` / `84.6%` / `88.0%`
- Binary block precision / recall / F1: `90.9%` / `83.3%` / `87.0%`
- Exact expected-code match: `85.0%`

The corpus includes unlisted semantic aliases and substring collisions. These are known limits, not excluded failures.
