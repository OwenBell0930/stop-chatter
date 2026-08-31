# Target-state protocol

Read this reference only for guarded mode, checker configuration, or exception review.

## Invariants

1. **Current target is authoritative.** Conversation history is evidence for recompilation, not the continuing specification.
2. **Retraction deletes.** A retired item and anything supported only by it leave the plan and deliverables.
3. **Artifacts are positive projections.** They describe the desired state, not the correction path.
4. **Every changed path has a reason.** At least one active requirement must map to it.
5. **Memory is a separate decision.** Task corrections do not become durable preferences without explicit evidence.

## Correction reducer

For each new user message, reduce it against the prior active target:

| Input signal | State operation |
|---|---|
| New requested outcome | add or replace an active requirement |
| “Remove”, “not needed”, or narrower scope | retire the affected requirement and its dependency cone |
| Corrected value | replace the old value; do not keep both values plus a warning |
| “Be concise/efficient” | record a meta-constraint, not product content |
| Explicit durable preference | create a separately scoped memory candidate |

Write active requirements in positive current-state language. A negative statement belongs in the active target only when absence is itself externally observable, safety-critical, or explicitly accepted.

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
    "exceptions": []
  }
}
```

The retired ledger may contain exact rejected labels because it is task-local, gitignored, and excluded from artifacts. Do not copy it into a PR, issue, memory file, or final response. The generated template starts with `ready: false`; change it to `true` only after replacing every placeholder with the current task state. Remove the state file when the task or handoff ends.

## Dependency-cone review

For each retired entry, review:

1. direct implementation;
2. configuration and data schema;
3. tests, fixtures, and snapshots;
4. comments and documentation;
5. UI copy and metadata;
6. task names, PR text, release notes, and versions;
7. memories, reusable rules, and future-task prompts.

Keep an item only if a different active requirement independently supports it.

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

The referenced requirement must be active, the reason must be non-empty, and the exception must name a narrow path. Do not create an exception merely to preserve correction history.

`allow_process_trace_paths` is for artifacts whose purpose is explicitly historical, such as a requested migration record. Prefer a narrow file path over a broad glob.

## Checker boundary

The checker can prove only configured, deterministic properties:

- paths map to active requirements;
- configured retired labels and aliases are absent;
- configured meta markers and narrow built-in compliance labels are absent;
- inspected files are readable text within the size limit.

It cannot prove semantic equivalence, discover every paraphrase, judge product correctness, or intercept output unless the host actually runs it. Treat a passing result as artifact-hygiene evidence, not proof that the task is correct.
