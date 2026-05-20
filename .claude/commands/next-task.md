Read TASKS.md from the project root, then do the following steps in order:

1. **Find the next task**: Look in TASKS.md for the first unchecked item (`- [ ]`). If all tasks are checked off, stop and tell the user there are no queued tasks.

2. **Get task context**: Read the TASKS.md heading, notes, and the selected task's sub-bullets for context on what we're building.

3. **Implement the task**: Do the work. Read relevant source files before writing code. Follow AGENTS.md and the repository's existing layout. When the task is complete, verify it works (run tests if they cover this area).

4. **Mark it done**: In TASKS.md, change `- [ ]` to `- [x]` on the task you just completed.

5. **Lint, test, and commit**:
   - Activate the venv: `source .venv/bin/activate`
   - Run linters and tests relevant to the files changed (backend: `ruff check . && ruff format --check . && pytest`; frontend: `npm run lint && npm test && npm run build`)
   - Fix any issues before committing
   - Stage only the files changed during this task
   - Commit with a concise message using the format `feat/fix/refactor/chore: description`
   - Push to origin
   - Skip committing only if tests/linting cannot be fixed, the user said not to commit, or no files were changed

6. **Deploy if this was the final task**: Check whether all tasks in TASKS.md are now checked off. If they are, run `/deploy`.

7. **Tell the user**: One sentence describing what you built, and how many tasks remain unchecked in TASKS.md.
