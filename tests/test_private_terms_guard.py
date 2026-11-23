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


def _run(cwd: Path, tool_name: str, tool_input: dict) -> subprocess.CompletedProcess[str]:
    hook_input = {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd)}
    return subprocess.run(
        [sys.executable, str(_SCRIPT)], input=json.dumps(hook_input), capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "new_file", "blocked"),
    [
        ("Bash", {"command": 'git commit -m "Fix childbenefit predictions"'}, None, True),
        ("Bash", {"command": 'git commit -m "Fix recurring income predictions"'}, None, False),
        ("Bash", {"command": 'git commit -m "docs"'}, "staged", True),
        ("Bash", {"command": 'git add -A && git commit -m "docs"'}, "untracked", True),
        ("Bash", {"command": 'git add src && git commit -m "docs"'}, "untracked", False),
        ("Bash", {"command": 'git commit -m "docs"'}, "untracked", False),
        ("Bash", {"command": "git commit -F notes.md"}, "untracked", True),
        ("Bash", {"command": "git commit --file=notes.md"}, "untracked", True),
        ("mcp__t3-code__pull_request_create", {"body": "Acme Telecom is now predicted."}, None, True),
        ("mcp__t3-code__pull_request_read", {"query": "Acme Telecom"}, None, False),
        ("Bash", {"command": "rg -i childbenefit"}, None, False),
    ],
)
def test_guard_blocks_only_outgoing_private_text(repo, tool_name, tool_input, new_file, blocked):
    """A new file with a private term blocks a commit only when the commit will include it."""
    if new_file:
        (repo / "notes.md").write_text("Paid by ACME telecom\n")
    if new_file == "staged":
        subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True)

    result = _run(repo, tool_name, tool_input)

    assert result.returncode == (2 if blocked else 0), result.stderr


@pytest.fixture
def git(repo, tmp_path, monkeypatch):
    """Run git in the repo with a throwaway identity; ``origin`` is an empty bare repository."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test\n\temail = test@example.com\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "origin.git")], check=True)

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run("remote", "add", "origin", str(tmp_path / "origin.git"))
    run("commit", "-q", "--allow-empty", "-m", "base")
    return run


def test_push_checks_every_outgoing_commit_not_only_the_final_tree(repo, git):
    git("push", "-q", "-u", "origin", "HEAD")
    (repo / "notes.md").write_text("Paid by Acme Telecom\n")
    git("add", "notes.md")
    git("commit", "-q", "-m", "add notes")
    (repo / "notes.md").write_text("Paid by a telecom provider\n")
    git("commit", "-q", "-am", "reword notes")

    result = _run(repo, "Bash", {"command": "git push"})

    assert result.returncode == 2, result.stderr


def test_first_push_without_an_upstream_is_checked(repo, git):
    git("commit", "-q", "--allow-empty", "-m", "Fix Acme Telecom predictions")

    result = _run(repo, "Bash", {"command": "git push -u origin HEAD"})

    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("command", ['git -C {repo} commit -m "docs"', 'cd {repo} && git commit -m "docs"'])
def test_commit_in_another_directory_checks_that_repository(repo, tmp_path, command):
    (repo / "notes.md").write_text("Paid by Acme Telecom\n")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True)

    result = _run(tmp_path, "Bash", {"command": command.format(repo=repo)})

    assert result.returncode == 2, result.stderr


def test_allow_list_lets_a_common_word_through(repo, tmp_path):
    (tmp_path / "config" / "private-terms-allow.txt").write_text("childbenefit\n")

    result = _run(repo, "Bash", {"command": 'git commit -m "Fix childbenefit predictions"'})

    assert result.returncode == 0, result.stderr
