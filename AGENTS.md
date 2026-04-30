# Agent Instructions

## Python environment

Always use the project venv for Python commands:

```
source .venv/bin/activate
```

If `.venv` doesn't exist, create it and install dependencies:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt -r requirements-dev.txt
```

When a subtask is complete, unless the scope, desired commit contents, or validation result is ambiguous:

1. Run any available linters and tests for changed code
2. Fix any issues surfaced before committing
3. Stage only files changed during the subtask
4. Commit with a concise message (`feat/fix/refactor/chore: description`)
5. Push to origin

If the task depends on manual verification, external confirmation, or there is ambiguity about what should be committed, stop and ask the user before committing or pushing.

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
