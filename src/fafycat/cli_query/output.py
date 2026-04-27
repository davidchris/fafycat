"""JSON output helpers shared by all query CLI handlers."""

import json
import sys
from typing import Any


def emit_success(data: Any) -> None:
    """Write data as indented JSON to stdout and exit 0."""
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")


def emit_error(message: str) -> None:
    """Write error payload as JSON to stdout and exit 1."""
    sys.stdout.write(json.dumps({"error": message}) + "\n")
    sys.exit(1)
