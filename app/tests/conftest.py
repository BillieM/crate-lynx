import sys
from pathlib import Path


BACKEND_SRC = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_SRC.parent

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
