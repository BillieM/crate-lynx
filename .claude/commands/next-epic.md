This repository uses TASKS.md as the active planning source.

1. **Confirm tasks are done**: Check that every task in TASKS.md is checked off. If any unchecked tasks remain, stop and tell the user which ones are incomplete.

2. **Summarize completion**: Read TASKS.md and summarize the completed work at the tracker-heading level.

3. **Ask for the next plan source**: Stop and ask the user for the next goal or planning document to turn into TASKS.md.

4. **Rewrite only after user approval**: If the user provides the next goal and approves rewriting TASKS.md, clear TASKS.md and replace it with a task breakdown using this format:

```
# TASKS

## <Plan Title>

- [ ] <task>
- [ ] <task>
...
```

Break the goal into concrete, actionable implementation tasks. Each task should be specific enough to be completable in a single focused session without being unnecessarily small.

5. Tell the user what was completed, what plan is now active, and how many tasks are queued.
