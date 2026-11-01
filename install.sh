#!/usr/bin/env bash
# agent-context-bridge installer (macOS / Linux)
#
#   curl -fsSL https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.sh | bash
#
# Options (env vars, since the script arrives on stdin):
#   AGENTLINK_HOME=/some/dir   where to keep the tool   (default ~/.local/share/agentlink)
#   AGENTLINK_AGENTS=dsh,codex,claude                    (default all three)
#   AGENTLINK_REF=main                                   branch or tag
#   AGENTLINK_NO_DEPS=1                                  skip installing zstandard
#   AGENTLINK_NO_PATH=1                                  do not touch PATH
#   AGENTLINK_FORCE=1                                    overwrite a non-agentlink directory

set -euo pipefail

REPO="gougougouz/agent-context-bridge"
REF="${AGENTLINK_REF:-main}"
DIR="${AGENTLINK_HOME:-$HOME/.local/share/agentlink}"
FORCE="${AGENTLINK_FORCE:-0}"
AGENTS="${AGENTLINK_AGENTS:-dsh,codex,claude}"

say() { printf '  %s\n' "$1"; }
head() { printf '\n\033[36m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m  x %s\033[0m\n' "$1" >&2; exit 1; }

printf '\n  \033[1magent-context-bridge\033[0m  |  sync project context across DSH / Codex / Claude\n'

# ------------------------------------------------------------------ python
head "1/4  python"
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  fi
done
[ -n "$PY" ] || fail "Python 3.9+ not found. Install it (brew install python / apt install python3) and re-run."
say "$PY  ($("$PY" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'))"

# ------------------------------------------------------------------ files
head "2/4  files"
mkdir -p "$DIR"
if [ -n "$(find "$DIR" -mindepth 1 -maxdepth 1 ! -name '.venv' -print -quit 2>/dev/null)" ] \
   && [ ! -f "$DIR/src/agentlink/__init__.py" ] && [ ! -f "$DIR/bin/agentlink.sh" ] \
   && [ "$FORCE" != "1" ]; then
  fail "target already has files: $DIR
    pick another place with AGENTLINK_HOME=/opt/agentlink, or re-run with AGENTLINK_FORCE=1"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL="https://codeload.github.com/$REPO/zip/refs/heads/$REF"
say "downloading $REF"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$TMP/repo.zip" || fail "download failed"
else
  wget -q "$URL" -O "$TMP/repo.zip" || fail "download failed"
fi
"$PY" - "$TMP/repo.zip" "$TMP" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
INNER="$(find "$TMP" -maxdepth 1 -type d -name 'agent-context-bridge-*' -print -quit)"
[ -n "$INNER" ] || fail "unexpected archive layout"
find "$DIR" -mindepth 1 -maxdepth 1 ! -name '.venv' -exec rm -rf {} +
cp -R "$INNER"/. "$DIR"/
say "$DIR"

# remember the interpreter this script actually picked: the PATH entry must use
# the same one, otherwise zstandard and the version check can disagree
PY_EXE="$("$PY" -c 'import sys; print(sys.executable)')"
printf '%s\n' "$PY_EXE" > "$DIR/.agentlink-python"

# ------------------------------------------------------------------ dependency
head "3/4  dependency"
if [ "${AGENTLINK_NO_DEPS:-0}" != "1" ]; then
  if "$PY" -c 'import zstandard' 2>/dev/null; then
    say "zstandard already available"
  else
    say "installing zstandard (reads compressed DSH sessions)"
    "$PY" -m pip install --quiet --disable-pip-version-check zstandard \
      || say "! pip failed - Codex/Claude still work; DSH needs: $PY -m pip install zstandard"
  fi
fi

# ------------------------------------------------------------------ skill
head "4/4  skill"
PYTHONPATH="$DIR/src" PYTHONUNBUFFERED=1 "$PY" -m agentlink install --agents "$AGENTS" \
  || fail "skill installation failed"
BIN="$DIR/bin"
chmod +x "$BIN/agentlink.sh" 2>/dev/null || true
VERSION="$("$BIN/agentlink.sh" --version 2>/dev/null || true)"
[ -n "$VERSION" ] || fail "the launcher did not run: check $PY_EXE or $DIR/src"
say "$VERSION"

if [ "${AGENTLINK_NO_PATH:-0}" != "1" ]; then
  LINK_DIR="$HOME/.local/bin"
  mkdir -p "$LINK_DIR"
  ln -sf "$BIN/agentlink.sh" "$LINK_DIR/agentlink"
  say "linked $LINK_DIR/agentlink"
  # verify the entry users will actually call, through the symlink
  LINKED="$("$LINK_DIR/agentlink" --version 2>/dev/null || true)"
  [ -n "$LINKED" ] || fail "the PATH entry at $LINK_DIR/agentlink does not run"
  case ":$PATH:" in
    *":$LINK_DIR:"*) ;;
    *) say "add this to your shell profile:  export PATH=\"$LINK_DIR:\$PATH\"" ;;
  esac
fi

head "done"
say "try it in any project:"
printf '\n    cd ~/code/your-project\n    agentlink brief\n\n'
say 'or, inside DSH / Codex / Claude, just say:  "read .agentlink/context.md and continue"'
say "restart DSH / Codex / Claude (or open a new session) so the skill shows up."