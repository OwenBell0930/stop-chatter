# Pilot adjudication

The raw deterministic result is preserved unchanged: Baseline 0/5, Light 2/5,
and Guarded 2/5 clean deliveries. Manual review found two rubric mismatches.

## Overrides

1. `three_step_plan__guarded__r1` — reclassified from fail to pass. The prompt
   required each step to contain `负责人：待定`; the artifact did so using a
   Chinese semicolon, while the frozen assertion unnecessarily required an em
   dash. Correction and continuation were otherwise clean.
2. `todo_frontend__guarded__r1` — active-requirement check reclassified from
   fail to pass, but the run remains an overall fail. The artifact creates a
   functional button dynamically with `document.createElement("button")`; the
   assertion accepted only a literal HTML `<button>`. The correction response
   still repeated the retired concept, so adjudication does not change the
   clean-delivery outcome.

No other run outcome was changed. The adjudicated clean-delivery totals are:

| Condition | Raw automated | Adjudicated |
|---|---:|---:|
| Baseline | 0/5 | 0/5 |
| Light | 2/5 | 2/5 |
| Guarded | 2/5 | 3/5 |

The original run JSON and artifact patches remain untouched under `runs/` and
`patches/`.

