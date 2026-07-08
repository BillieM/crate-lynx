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

Deployment is owner-specific and intentionally not described in tracked repo files.
Do not deploy, push, or commit unless the current user request explicitly asks for it.

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
