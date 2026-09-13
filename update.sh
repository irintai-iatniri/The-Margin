#!/usr/bin/env sh
# Take a new artifact build all the way to verified.
#
#   ./update.sh                       re-patch from the-margin-v2.html and test
#   ./update.sh ~/Downloads/new.html  adopt a new artifact build first
#
# The patching is the trivial part. The point of this script is that nothing
# reaches index.html without both suites passing, and that a failure leaves the
# previous working build in place.

set -e
cd "$(dirname "$0")"

SRC=the-margin-v2.html
NEW="$1"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---- 1. adopt a new artifact build, keeping the old one recoverable ----
if [ -n "$NEW" ]; then
  [ -f "$NEW" ] || { echo "no such file: $NEW"; exit 1; }
  grep -q 'window.claude' "$NEW" || {
    echo "$NEW has no window.claude block — that is not an artifact build."
    exit 1; }
  if [ -f "$SRC" ]; then
    cp "$SRC" ".$SRC.prev"
    echo "previous build kept as .$SRC.prev"
  fi
  cp "$NEW" "$SRC"
  echo "adopted $NEW as $SRC"
fi

# ---- 2. keep the last good output, so a failure is recoverable ----
[ -f index.html ] && cp index.html .index.html.prev

say "patching"
python3 patch.py || exit 1

say "stubbed suite (no API calls)"
if python3 test_ui.py; then
  UI=ok
else
  UI=failed
fi

say "live suite"
LIVE=skipped
if [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/the-margin/env" ] || [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  MARGIN_PORT=${MARGIN_TEST_PORT:-7882}
  export MARGIN_PORT
  ./run.sh >/tmp/margin-update.log 2>&1 &
  SRV=$!
  # wait for the port rather than guessing at a sleep; a server that never binds
  # should report as that, not as a mysteriously unreachable page
  UP=no
  i=0
  while [ $i -lt 40 ]; do
    if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$MARGIN_PORT/"; then UP=yes; break; fi
    i=$((i+1)); sleep 0.25
  done
  if [ "$UP" = no ]; then
    echo "  server never came up on $MARGIN_PORT — log follows"
    tail -5 /tmp/margin-update.log | sed "s/^/    /"
    LIVE=failed
  elif node test_run.js; then LIVE=ok; else LIVE=failed; fi
  kill $SRV 2>/dev/null || true
else
  echo "  no key configured — skipping (see README)"
fi

# ---- 3. verdict ----
say "result"
printf '  stubbed: %s\n  live:    %s\n\n' "$UI" "$LIVE"

if [ "$UI" = failed ] || [ "$LIVE" = failed ]; then
  if [ -f .index.html.prev ]; then
    mv .index.html.prev index.html
    rm -f .build-state.json
    echo "index.html rolled back to the previous working build."
    [ -n "$NEW" ] && [ -f ".$SRC.prev" ] && mv ".$SRC.prev" "$SRC" && echo "$SRC rolled back too."
  fi
  echo "NOT SHIPPED."
  exit 1
fi

rm -f .index.html.prev ".$SRC.prev"
echo "Verified. index.html is good."
