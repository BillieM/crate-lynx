from __future__ import annotations

import json
import sys

from app.main import app


def main() -> None:
    json.dump(app.openapi(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
