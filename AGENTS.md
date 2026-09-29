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

Follow the user's global delivery agreement for implementation work: review and
commit intended changes, push through the normal repository workflow, and deploy
and verify live when applicable. Honor explicit delivery restrictions.

Deployment is owner-specific and intentionally not described in tracked repo files.
Establish the owner's private deployment runbook before deploying; keep its details
out of tracked files.

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

Scope each lane's checks to the changes it owns. API, schema, or cross-stack
changes also need appropriate combined verification before shipping. For
documentation-only edits, review the diff and formatting; application test suites
are unnecessary.
