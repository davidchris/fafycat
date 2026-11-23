"""Block commits, pushes and GitHub text that name private terms from the fafycat database.

Claude Code runs this as a PreToolUse hook (see ``.claude/settings.json``). The hook input
arrives on stdin. The script exits 2, which blocks the tool call, when the outgoing text
contains a private term. Outgoing text is:

* ``git commit``: the command (with its message) and the added lines of the staged and
  unstaged diffs.
* ``git push``: the messages and added lines of the commits that the upstream does not have.
* ``gh ...``: the command and any ``--body-file`` / ``-F`` file it reads.
* the GitHub tools of T3 Code that write PRs, issues and comments: their whole input.

Private terms are the category names in the configured database, plus one term per line in
``private-terms.txt`` next to the fafycat config file (``~/.config/fafycat/`` by default).
Terms listed in ``private-terms-allow.txt`` in the same directory never block, for common words
such as a category that is also an English word. Both files stay outside the repository, so the
terms themselves are never published.
"""

import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

from fafycat.core.config import resolve_config, sqlite_path

WRITING_MCP_TOOLS = re.compile(
    r"mcp__t3-code__(pull_request_(create|update|respond|review|merge)|create_issue|comment_on_issue)$"
)
GIT_COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b")
GIT_PUSH = re.compile(r"\bgit\b[^|;&]*\bpush\b")
GH = re.compile(r"(^|[\s;&|(])gh\s")
FILE_FLAGS = ("--body-file", "-F", "--input")


def _terms_dir() -> Path:
    return Path(os.environ.get("FAFYCAT_CONFIG", "~/.config/fafycat/config.toml")).expanduser().parent


def _read_terms(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.lower() for line in lines if line and not line.startswith("#")}


def _category_names() -> set[str]:
    db = sqlite_path(resolve_config().database.url)
    if db is None or not db.is_file():
        return set()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return {name.lower() for (name,) in conn.execute("SELECT name FROM categories")}


def private_terms() -> set[str]:
    """Return the terms that must not leave the machine, in lower case."""
    terms_dir = _terms_dir()
    terms = _category_names() | _read_terms(terms_dir / "private-terms.txt")
    return terms - _read_terms(terms_dir / "private-terms-allow.txt")


def _git(cwd: str, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def _added_lines(diff: str) -> str:
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def _push_base(cwd: str) -> str:
    for ref in ("@{upstream}", "origin/HEAD"):
        base = _git(cwd, "merge-base", ref, "HEAD").strip()
        if base:
            return base
    return ""


def _files_read_by_gh(command: str, cwd: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    texts = []
    for flag, value in zip(tokens, tokens[1:], strict=False):
        if flag not in FILE_FLAGS:
            continue
        path = Path(cwd, value.split("=@", 1)[-1].removeprefix("@")).expanduser()
        if path.is_file():
            texts.append(path.read_text(errors="replace"))
    return texts


def outgoing_text(hook_input: dict) -> list[tuple[str, str]]:
    """Return (label, text) pairs that the tool call would publish."""
    tool, tool_input = hook_input.get("tool_name", ""), hook_input.get("tool_input", {})
    cwd = hook_input.get("cwd") or os.getcwd()
    if WRITING_MCP_TOOLS.match(tool):
        return [(tool, json.dumps(tool_input, ensure_ascii=False))]
    if tool != "Bash":
        return []
    command = tool_input.get("command", "")
    texts = []
    if GIT_COMMIT.search(command):
        texts.append(("commit command", command))
        texts.append(("staged diff", _added_lines(_git(cwd, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff"))))
        texts.append(("unstaged diff", _added_lines(_git(cwd, "diff", "-U0", "--no-color", "--no-ext-diff"))))
    if GIT_PUSH.search(command) and (base := _push_base(cwd)):
        texts.append(("pushed commit messages", _git(cwd, "log", "--format=%B", f"{base}..HEAD")))
        texts.append(
            ("pushed diff", _added_lines(_git(cwd, "diff", "-U0", "--no-color", "--no-ext-diff", base, "HEAD")))
        )
    if GH.search(command):
        texts.append(("gh command", command))
        texts.extend(("gh body file", text) for text in _files_read_by_gh(command, cwd))
    return texts


def find_private_terms(texts: list[tuple[str, str]], terms: set[str]) -> dict[str, set[str]]:
    """Return the private terms found, keyed by the label of the text they appear in."""
    if not terms:
        return {}
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE,
    )
    found: dict[str, set[str]] = {}
    for label, text in texts:
        hits = {m.lower() for m in pattern.findall(text)}
        if hits:
            found.setdefault(label, set()).update(hits)
    return found


def main() -> int:
    """Run the hook: exit 2 with a reason on stderr when outgoing text names a private term."""
    texts = outgoing_text(json.load(sys.stdin))
    if not texts:
        return 0
    found = find_private_terms(texts, private_terms())
    if not found:
        return 0
    where = "; ".join(f"{label}: {', '.join(sorted(hits))}" for label, hits in found.items())
    print(
        f"Blocked: this would publish private terms from the user's fafycat data ({where}). "
        "Describe results from real data in generic terms, or use fixture data, then retry. "
        f"If a term is a common word, the user can add it to {_terms_dir() / 'private-terms-allow.txt'}.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
