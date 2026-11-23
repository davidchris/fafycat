"""scripts/private_terms_guard.py blocks tool calls that would publish private terms."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "private_terms_guard.py"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo, a database with one category, and a config dir with one extra private term."""
    db = tmp_path / "prod.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE categories (name TEXT)")
        conn.execute("INSERT INTO categories VALUES ('Childbenefit')")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "private-terms.txt").write_text("# merchants\nAcme Telecom\n")
    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_dir / "config.toml"))
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    return work


def _run(repo: Path, tool_name: str, tool_input: dict) -> subprocess.CompletedProcess[str]:
    hook_input = {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(repo)}
    return subprocess.run(
        [sys.executable, str(_SCRIPT)], input=json.dumps(hook_input), capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "staged", "blocked"),
    [
        ("Bash", {"command": 'git commit -m "Fix childbenefit predictions"'}, "", True),
        ("Bash", {"command": 'git commit -m "Fix recurring income predictions"'}, "", False),
        ("Bash", {"command": 'git add -A && git commit -m "docs"'}, "Paid by ACME telecom\n", True),
        ("mcp__t3-code__pull_request_create", {"body": "Acme Telecom is now predicted."}, "", True),
        ("mcp__t3-code__pull_request_read", {"query": "Acme Telecom"}, "", False),
        ("Bash", {"command": "rg -i childbenefit"}, "", False),
    ],
)
def test_guard_blocks_only_outgoing_private_text(repo, tool_name, tool_input, staged, blocked):
    if staged:
        (repo / "notes.md").write_text(staged)
        subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True)

    result = _run(repo, tool_name, tool_input)

    assert result.returncode == (2 if blocked else 0), result.stderr


def test_allow_list_lets_a_common_word_through(repo, tmp_path):
    (tmp_path / "config" / "private-terms-allow.txt").write_text("childbenefit\n")

    result = _run(repo, "Bash", {"command": 'git commit -m "Fix childbenefit predictions"'})

    assert result.returncode == 0, result.stderr
