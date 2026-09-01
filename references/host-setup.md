# Host setup

Read this reference only when installing Stop Chatter or diagnosing skill discovery.

## Project scope

| Host | Discovery path | Explicit invocation |
|---|---|---|
| Cursor | `.agents/skills/stop-chatter/SKILL.md` | `/stop-chatter` |
| OpenAI Codex | `.agents/skills/stop-chatter/SKILL.md` | `$stop-chatter` |
| Claude Code | `.claude/skills/stop-chatter/SKILL.md` | `/stop-chatter` |

Cursor and Codex share the `.agents/skills` copy. Claude Code receives a separate copy so a checkout works without relying on symlink support.

Install all project adapters:

```bash
python3 scripts/install.py --host all --scope project --target /path/to/project
```

Preview without writing:

```bash
python3 scripts/install.py --host all --scope project --target /path/to/project --dry-run
```

Remove the same project adapters:

```bash
python3 scripts/uninstall.py --host all --scope project --target /path/to/project
```

The uninstaller verifies the `stop-chatter` skill marker before removing an
exact destination. It does not remove parent folders, sibling skills, host
settings, or project files. Add `--dry-run` to preview the exact paths.

## User scope

User-level installation is opt-in:

| Host | Path |
|---|---|
| Cursor | `~/.cursor/skills/stop-chatter` |
| OpenAI Codex | `~/.codex/skills/stop-chatter` |
| Claude Code | `~/.claude/skills/stop-chatter` |

```bash
python3 scripts/install.py --host all --scope user
```

```bash
python3 scripts/uninstall.py --host all --scope user
```

The installer refuses existing destinations and never modifies host settings,
hooks, memory, or unrelated rules. Installation and removal are explicit; there
is no automatic overwrite or background update path.

## Official format references

- Cursor: <https://prod.cursor.com/docs/skills>
- OpenAI Codex: <https://developers.openai.com/codex/skills>
- Claude Code: <https://code.claude.com/docs/en/skills>
