# Target-state protocol

Read this reference only for guarded mode, checker configuration, or exception review. Ordinary corrections stay in Light mode.

## Invariants

1. **Current target is authoritative.** Conversation history is evidence for recompilation, not the continuing specification.
2. **Retraction deletes that item.** A retired item and anything supported only by it leave the plan and deliverables. It does not authorize a project-wide cleanup.
3. **Artifacts are positive projections.** They describe the desired state, not the correction path.
4. **This round's file operations have a reason.** Added or modified paths must map to an active requirement. Whole-file deletion needs its own evidence.
5. **Memory is a separate decision.** Task corrections do not become durable preferences without explicit evidence.

## Correction reducer

For each new user message, reduce it against the prior active target:

| Input signal | State operation |
|---|---|
| New requested outcome | add or replace an active requirement |
| “Remove”, “not needed”, or narrower scope | retire the affected requirement and any derivative that exists only to serve it |
| Corrected value | replace the old value; do not keep both values plus a warning |
| “Be concise/efficient” | record a meta-constraint, not product content |
| Explicit durable preference | create a separately scoped memory candidate |

Write active requirements in positive current-state language. A negative statement belongs in the active target only when absence is itself externally observable, safety-critical, or explicitly accepted.

Not mentioned this round ≠ retracted. Unclear origin → keep. Ask only when the ambiguity blocks delivery.

## Transient state

`.stop-chatter/state.json` uses this shape:

```json
{
  "schema_version": 1,
  "ready": true,
  "active_target": {
    "goal": "Describe the current desired outcome.",
    "requirements": [
      {
        "id": "R1",
        "text": "A positive active requirement.",
        "paths": ["src/**", "tests/test_active_behavior.py"]
      }
    ],
    "meta_constraints": [
      {
        "id": "M1",
        "text": "Keep the delivery concise.",
        "leak_markers": ["concise edition"]
      }
    ]
  },
  "retired": [
    {
      "id": "X1",
      "label": "superseded concept",
      "aliases": ["nearby renamed concept"],
      "scope": "task"
    }
  ],
  "delivery": {
    "ignore_paths": [".git/**", ".stop-chatter/**"],
    "allow_process_trace_paths": [],
    "must_remove": [],
    "exceptions": []
  }
}
```

`init` writes a start baseline into the same file. Do not edit it. The baseline records the starting commit when Git is available, plus type and content digests for files that were already dirty or untracked. It does not copy the repository and is not a backup, permission, or restore system.

The generated template starts with `ready: false`; change it to `true` only after replacing every placeholder with the current task state. An unfilled template must not pass.

`active_target.requirements[].paths` is the narrowest set of paths this round may add or modify. It does not authorize deleting those files.

`delivery.must_remove` is an exact-path list. A path belongs there only when visible task evidence supports deleting that derivative. The list is both the required-removal set and the only deletion allow-list. Do not enlarge it just to pass the check. Exact paths must stay inside the project root; globs, `..`, and repo-wide wildcards are rejected.

The retired ledger may contain exact rejected labels because it is task-local, gitignored, and excluded from artifacts. Do not dump it into a PR, issue, memory file, or completion reply; summarize a materially relevant removal in the reply when the user needs that information.

## Lifecycle

Normal path: initialize once before changing deliverables, finish the edits, check once, and remove the task state.

If valid state already exists for this root, reuse it. Do not overwrite the file or reset the start baseline. Repeated `init` is not an error merely because the file exists. If the state is invalid JSON, has the wrong schema, or belongs to a different root, stop; do not reuse or replace it.

A successful check with `--cleanup-state-on-pass` removes only that state file in the same command. A failed check leaves it for one targeted repair and rerun. Do not run a second check after success, and do not inspect the filesystem just to confirm cleanup. Omit the option only when an active handoff still needs the state, then remove the file when that handoff ends.

After this correction, ordinary continuation returns to Light. Do not recreate Guarded state for a routine follow-up. Do not delete interpreter caches, test caches, or other user files in the name of cleanup.

## File operations

The checker reports; it does not delete or restore deliverables, and it does not assign product ownership.

- Added or modified files this round must map to an active requirement (`STC002`).
- Deleting a file that is not listed in `must_remove` is unauthorized (`STC005`), even if the file mapped to a requirement or contains no retired term.
- Every `must_remove` path is existence-checked, whether or not it appears in Git, has a keyword, or was passed as an explicit check path (`STC006`).
- Original dirty files that still match the start baseline are not this-round overreach. Further edits or deletions of those files are.
- Renames are an add of the new path plus a delete of the old path.
- When Git, explicit paths, or older state cannot supply a complete start baseline, the checker may still run content checks. It must label that coverage `limited` and must not claim it verified that original user changes were left untouched. Do not scan the whole repository just to invent complete coverage.

## Narrow exceptions

An exception is appropriate when a retired term must remain in an externally required compatibility or safety test:

```json
{
  "path": "tests/contracts/**",
  "codes": ["STC001"],
  "terms": ["legacy-wire-token"],
  "requirement_id": "R7",
  "reason": "R7 requires rejecting this externally supplied legacy token."
}
```

The referenced requirement must be active, the reason must be non-empty, and the exception must name a narrow path. Residue outside that path still fails. Do not create an exception merely to preserve correction history.

`allow_process_trace_paths` is for artifacts whose purpose is explicitly historical, such as a requested migration record. Prefer a narrow file path over a broad glob.

## Checker boundary

The checker can prove only configured, deterministic properties:

- this-round added or modified paths map to active requirements;
- unauthorized whole-file deletions are reported;
- configured `must_remove` paths are absent;
- configured retired labels and aliases are absent from inspected files;
- configured meta markers and narrow built-in compliance labels are absent;
- inspected files are readable text within the size limit.

It cannot prove semantic equivalence, discover every paraphrase, judge product correctness, or intercept output unless the host actually runs it. Treat a passing result as evidence that the configured checks passed, not as proof that the implementation is correct or that nothing remains.
