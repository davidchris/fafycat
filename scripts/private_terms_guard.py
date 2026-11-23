"""Block commits, pushes and GitHub text that name private terms from the fafycat database.

Claude Code runs this as a PreToolUse hook (see ``.claude/settings.json``). The hook input
arrives on stdin. The script exits 2, which blocks the tool call, when the outgoing text
contains a private term. Outgoing text is:

* ``git commit``: the command (with its ``-m`` message), a ``-F``/``--file`` message file, the
  added lines of the staged and unstaged diffs, and the untracked files that a ``git add`` in
  the same command would stage.
* ``git push``: the message, file names and added lines of each commit that no remote-tracking
  branch has yet, so a first push and text added in one commit and removed in a later one count.
* ``gh ...``: the command and any ``--body-file`` / ``-F`` file it reads.
* the GitHub tools of T3 Code that write PRs, issues and comments: their whole input.

Git commands are checked in the repository they run in, after ``cd <dir>`` and ``git -C <dir>``.

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
PUBLISHING_COMMAND = re.compile(r"\bgit\b.*\b(commit|push)\b|(^|[\s;&|(])gh\s", re.DOTALL)
GH_FILE_FLAGS = ("--body-file", "-F", "--input")
MAX_FILE_BYTES = 1_000_000


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


def _published_log(log: str) -> str:
    """Keep what ``git log -p -U0`` would publish: messages, file names and added lines, not removed ones."""
    return "\n".join(line for line in log.splitlines() if not line.startswith(("-", "@@", "index ")))


def _read_file(cwd: str, name: str) -> str:
    path = Path(cwd, Path(name).expanduser())
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        return ""
    return path.read_text(errors="replace")


def _simple_commands(command: str, cwd: str) -> list[tuple[list[str], str]]:
    """Split a shell command into simple commands, each with the directory it runs in.

    Follows ``cd`` so that ``cd repo && git commit`` is checked in ``repo``. Quoted operators,
    such as a ``|`` inside a commit message, stay part of their word.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    commands, current = [], []
    for token in [*tokens, ";"]:
        if token and set(token) <= set(";&|()\n"):
            while current and re.match(r"^\w+=", current[0]):
                current = current[1:]
            if current[:1] == ["cd"]:
                cwd = str(Path(cwd, Path(current[1] if len(current) > 1 else "~").expanduser()))
            elif current:
                commands.append((current, cwd))
            current = []
        else:
            current.append(token)
    return commands


def _git_subcommand(tokens: list[str], cwd: str) -> tuple[str, list[str], str] | None:
    """Return (subcommand, its arguments, the directory git runs in) for a git command, else None."""
    if Path(tokens[0]).name != "git":
        return None
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] == "-C" and i + 1 < len(tokens):
            cwd = str(Path(cwd, Path(tokens[i + 1]).expanduser()))
        i += 2 if tokens[i] in ("-C", "-c") else 1
    return (tokens[i], tokens[i + 1 :], cwd) if i < len(tokens) else None


def _untracked_files_added_by(args: list[str], cwd: str) -> str:
    """Return the content of untracked files that ``git add <args>`` would stage.

    The hook runs before the command, so such files are in neither diff yet.
    """
    everything = any(arg in ("-A", "--all") for arg in args)
    pathspecs = [] if everything else [arg for arg in args if not arg.startswith("-")]
    if not everything and not pathspecs:
        return ""
    listed = _git(cwd, "ls-files", "--others", "--exclude-standard", "-z", "--", *pathspecs)
    return "\n".join(f"{name}\n{_read_file(cwd, name)}" for name in filter(None, listed.split("\0")))


def _commit_message_files(args: list[str], cwd: str) -> str:
    """Return the messages that ``git commit -F <file>`` / ``--file=<file>`` would read."""
    names = [value for flag, value in zip(args, args[1:], strict=False) if flag in ("-F", "--file")]
    names += [arg.removeprefix("--file=") for arg in args if arg.startswith("--file=")]
    return "\n".join(_read_file(cwd, name) for name in names if name != "-")


def _pushed_revisions(args: list[str], cwd: str) -> list[str]:
    """Return the local revisions ``git push <args>`` would publish (HEAD when none is named)."""
    if any(arg in ("--all", "--branches", "--mirror") for arg in args):
        return ["--branches"]
    positional = [arg for arg in args if not arg.startswith("-")]
    sources = [refspec.lstrip("+").split(":", 1)[0] for refspec in positional[1:]]
    revisions = [src for src in sources if src and _git(cwd, "rev-parse", "--verify", "--quiet", f"{src}^{{commit}}")]
    return revisions or ["HEAD"]


def _gh_body_files(args: list[str], cwd: str) -> str:
    """Return the files a ``gh`` command reads its text from (``--body-file``, ``-F body=@file``)."""
    names = [value for flag, value in zip(args, args[1:], strict=False) if flag in GH_FILE_FLAGS]
    names += [arg.split("=", 1)[1] for arg in args if arg.startswith("--body-file=")]
    return "\n".join(_read_file(cwd, name.split("=@", 1)[-1].removeprefix("@")) for name in names)


def outgoing_text(hook_input: dict) -> list[tuple[str, str]]:
    """Return (label, text) pairs that the tool call would publish."""
    tool, tool_input = hook_input.get("tool_name", ""), hook_input.get("tool_input", {})
    cwd = hook_input.get("cwd") or os.getcwd()
    if WRITING_MCP_TOOLS.match(tool):
        return [(tool, json.dumps(tool_input, ensure_ascii=False))]
    if tool != "Bash":
        return []
    command = tool_input.get("command", "")
    # The raw command holds -m messages and gh bodies even when it cannot be tokenised.
    texts = [("command", command)] if PUBLISHING_COMMAND.search(command) else []
    added, commits = [], []
    for tokens, directory in _simple_commands(command, cwd):
        if Path(tokens[0]).name == "gh":
            texts.append(("gh body file", _gh_body_files(tokens, directory)))
        if not (git := _git_subcommand(tokens, directory)):
            continue
        subcommand, args, directory = git
        if subcommand == "add":
            added.append(_untracked_files_added_by(args, directory))
        elif subcommand == "commit":
            commits.append(directory)
            texts.append(("commit message file", _commit_message_files(args, directory)))
        elif subcommand == "push":
            revisions = _pushed_revisions(args, directory)
            log = _git(
                directory,
                "log",
                "-p",
                "-U0",
                "--no-color",
                "--no-ext-diff",
                "--format=%B",
                *revisions,
                "--not",
                "--remotes",
            )
            texts.append(("pushed commits", _published_log(log)))
    for directory in dict.fromkeys(commits):
        texts.append(
            ("staged diff", _added_lines(_git(directory, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff")))
        )
        texts.append(("unstaged diff", _added_lines(_git(directory, "diff", "-U0", "--no-color", "--no-ext-diff"))))
    if commits:
        texts.append(("untracked files to be added", "\n".join(added)))
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
