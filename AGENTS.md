# Agent Instructions

## Python environment

Use Python 3.12.13 for this repository.

Always use the project venv for Python commands:

```
source .venv/bin/activate
```

If `.venv` doesn't exist, create it and install dependencies:

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt -r requirements-dev.txt
```

At the end of every completed task, deploy to production using the `gluesoup-0-docker` Docker context. Follow `.codex/commands/deploy.md`.

After a completed task is verified and deployed, commit the relevant changes unless the user explicitly asks not to commit.

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
