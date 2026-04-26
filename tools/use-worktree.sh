#!/usr/bin/env bash
# Repoint Live's Remote Script symlink at one of the project's worktrees.
# Restart (or toggle) AbletonMCP in Live afterward to reload the module.
#
#   tools/use-worktree.sh                 # show current target
#   tools/use-worktree.sh main            # main worktree (~/Develop/ableton-mcp)
#   tools/use-worktree.sh <slug>          # ~/Develop/ableton-mcp-<slug>

set -euo pipefail

LIVE_LINK="$HOME/Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py"
MAIN_TREE="$HOME/Develop/ableton-mcp"

if [[ ! -L "$LIVE_LINK" ]]; then
    echo "error: $LIVE_LINK is not a symlink" >&2
    exit 1
fi

if [[ $# -eq 0 ]]; then
    target=$(readlink "$LIVE_LINK")
    echo "current: $target"
    exit 0
fi

slug="$1"
if [[ "$slug" == "main" ]]; then
    new_target="$MAIN_TREE/AbletonMCP_Remote_Script/__init__.py"
else
    new_target="$HOME/Develop/ableton-mcp-$slug/AbletonMCP_Remote_Script/__init__.py"
fi

if [[ ! -f "$new_target" ]]; then
    echo "error: $new_target does not exist" >&2
    exit 1
fi

ln -sfn "$new_target" "$LIVE_LINK"
echo "switched: $(readlink "$LIVE_LINK")"
echo "restart Live (or toggle AbletonMCP in Preferences > Link/Tempo/MIDI) to reload"
