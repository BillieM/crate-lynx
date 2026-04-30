Read EPICS.md and TASKS.md from the project root, then do the following steps in order:

1. **Confirm tasks are done**: Check that every task in TASKS.md is checked off (all lines starting with `- [x]`). If any unchecked tasks remain, stop and tell the user which ones are incomplete.

2. **Find the current epic**: Look in EPICS.md for the epic marked `` `in progress` ``. That is the epic we just finished.

3. **Mark it done**: In EPICS.md, replace `` `in progress` `` on that epic's heading with `` `done` ``.

4. **Find the next epic**: The epic immediately after the one we just marked done (in document order). If there is no next epic, stop and tell the user that all epics are complete.

5. **Mark it in progress**: In EPICS.md, append `` `in progress` `` to the next epic's heading (it currently has no status badge).

6. **Rewrite TASKS.md**: Clear TASKS.md entirely and replace it with a task breakdown for the new epic. Use this format:

```
# <Epic ID> — <Epic Title>

- [ ] <task>
- [ ] <task>
...
```

Break the epic description into concrete, actionable implementation tasks — one per line. Each task should be specific enough to be completable in a single focused session. Derive the tasks from the epic's description in EPICS.md and the subdir layout at the top of that file. Don't include tasks already handled by earlier epics. Do not analyze the codebase for reuse opportunities — that is Codex's job at implementation time.

7. Tell the user: which epic we just completed, which epic is now active, and how many tasks are queued.
