# /next-task

Read `TASKS.md` and find the first unchecked item (`- [ ]`).

## Steps

1. **Identify** the next unchecked task in `TASKS.md`
2. **Implement** it — write code, config, or files as required
3. **Lint and test** any changed files using the commands in `AGENTS.md`
4. **Fix** any issues before proceeding

## Before checking off

- If the task description contains words like "smoke test", "verify", "check", or "test:" — **stop and ask the user to confirm** it passes before marking complete
- Otherwise, mark the task as done by changing `- [ ]` to `- [x]` in `TASKS.md`

## Commit

Follow the commit instructions in `AGENTS.md`.

Then **tell the user what was completed** and ask if they want to run `/next-task` again.
