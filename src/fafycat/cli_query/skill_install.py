"""Skill install helper: reads bundled SKILL.md and writes it to a target directory."""

import importlib.resources
from pathlib import Path


def install_skill(target_dir: Path, force: bool = False) -> Path:
    """Write the bundled SKILL.md to target_dir/SKILL.md.

    Args:
        target_dir: Directory to write the skill file into.
        force: Overwrite an existing file when True.

    Returns:
        Path to the written file.

    Raises:
        FileExistsError: If the target file exists and force is False.
    """
    target_file = target_dir / "SKILL.md"
    if target_file.exists() and not force:
        raise FileExistsError(f"{target_file} already exists. Use --force to overwrite.")

    template = importlib.resources.files("fafycat.data.skill").joinpath("SKILL.md").read_text(encoding="utf-8")

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file.write_text(template, encoding="utf-8")
    return target_file
