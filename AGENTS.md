# Agent Instructions

When the user confirms a subtask is complete:

1. Run any available linters and tests for changed code
2. Fix any issues surfaced before committing
3. Stage only files changed during the subtask
4. Commit with a concise message (`feat/fix/refactor/chore: description`)
5. Push to origin

## Linting & tests

**Backend (`app/`)**
```
ruff check .
ruff format --check .
pytest
```

**Frontend (`app-ui/`)**
```
npm run lint
npm test
npm run build
```

Only run the commands relevant to the files changed in the subtask.
