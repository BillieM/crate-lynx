from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from app.sonic.semantic import (
    CLAP_ONNX_MODEL_FILENAME,
    CLAP_ONNX_MODEL_ID,
    CLAP_ONNX_MODEL_REVISION,
    verify_model_asset,
)

DEFAULT_MODEL_PATH = Path("/data/models/clap-htsat-unfused-audio.onnx")
DOWNLOAD_URL = (
    "https://huggingface.co/"
    f"{CLAP_ONNX_MODEL_ID}/resolve/{CLAP_ONNX_MODEL_REVISION}/onnx/"
    f"{CLAP_ONNX_MODEL_FILENAME}"
)


def install_model_asset(destination: Path, *, url: str = DOWNLOAD_URL) -> Path:
    """Explicitly download, verify, and atomically install the pinned model."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with (
            os.fdopen(file_descriptor, "wb") as target,
            urlopen(url, timeout=120) as response,
        ):
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        verify_model_asset(temporary_path)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def _default_model_path() -> Path:
    configured = os.environ.get("SONIC_SEMANTIC_MODEL_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_MODEL_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the pinned Crate Lynx CLAP ONNX audio model asset."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=_default_model_path(),
    )
    arguments = parser.parse_args()
    installed_path = install_model_asset(arguments.destination)
    print(installed_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
