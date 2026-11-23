#!/bin/sh
# PreToolUse hook: start the Python guard only for tool calls that can publish text.
# Other Bash commands exit here, so they do not pay for starting uv.
input=$(cat)
if [ "$(printf '%s' "$input" | jq -r .tool_name)" = Bash ] &&
    ! printf '%s' "$input" | jq -r .tool_input.command | grep -Eq 'git.*(commit|push)|gh '; then
    exit 0
fi
dir=$(cd "$(dirname "$0")/.." && pwd)
printf '%s' "$input" | exec uv run --quiet --project "$dir" python "$dir/scripts/private_terms_guard.py"
