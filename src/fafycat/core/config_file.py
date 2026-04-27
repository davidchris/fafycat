"""Config-file loader for FafyCat.

Reads ~/.config/fafycat/config.toml (or the path given by FAFYCAT_CONFIG) and
returns a flat dict of the [paths] section. Pure function: no DB or network access.
"""

import functools
import os
import sys
import tomllib
from pathlib import Path

_DEFAULT_CONFIG_PATH = Path("~/.config/fafycat/config.toml").expanduser()
_KNOWN_PATHS_KEYS = frozenset({"data_dir", "db_url", "model_dir", "export_dir"})


class ConfigFileError(Exception):
    """Raised when the FafyCat config file exists but cannot be parsed."""


@functools.cache
def _load_at_path(path: Path) -> dict[str, str]:
    """Parse *path* once; results are cached by resolved path for the process lifetime."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigFileError(f"Malformed TOML in {path}: {exc}") from exc

    result: dict[str, str] = {}

    for section in data:
        if section != "paths":
            print(f"Warning: unknown section [{section}] in {path}", file=sys.stderr)  # noqa: T201

    paths_section: dict[str, object] = data.get("paths", {})
    for key, value in paths_section.items():
        if key not in _KNOWN_PATHS_KEYS:
            print(f"Warning: unknown key {key!r} in [{path}] [paths]", file=sys.stderr)  # noqa: T201
            continue
        result[key] = str(value)

    return result


def load_config_file(path: Path | None) -> dict[str, str]:
    """Load the FafyCat config file and return a flat dict of [paths] settings.

    Args:
        path: Explicit path to read. ``None`` checks ``FAFYCAT_CONFIG`` env var
            first, then falls back to ``~/.config/fafycat/config.toml``.

    Returns:
        Flat dict whose keys are the recognised [paths] fields that appear in the
        file (``data_dir``, ``db_url``, ``model_dir``, ``export_dir``). Returns
        an empty dict when the file does not exist.

    Raises:
        ConfigFileError: When the file exists but contains malformed TOML.
    """
    if path is None:
        env_path = os.getenv("FAFYCAT_CONFIG")
        path = Path(env_path) if env_path else _DEFAULT_CONFIG_PATH
    return _load_at_path(path)
