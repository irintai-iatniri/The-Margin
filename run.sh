#!/usr/bin/env sh
# The Margin — start the local server.
#
#   ./run.sh          python server, no build
#   ./run.sh rust     cargo run --release
#
# The key is read from ~/.config/the-margin/env so it never lives in this
# directory, in shell history, or in anything committed.

set -e
cd "$(dirname "$0")"

CONF="${XDG_CONFIG_HOME:-$HOME/.config}/the-margin/env"
if [ -f "$CONF" ]; then
  # set -a exports everything the file assigns, not just the key. Without it a
  # bare MARGIN_PORT=7878 in the env file becomes a shell variable that never
  # reaches the server process, and the override silently does nothing.
  set -a
  # shellcheck disable=SC1090
  . "$CONF"
  set +a
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  cat <<EOF
No ANTHROPIC_API_KEY found.

Put it in $CONF :

    ANTHROPIC_API_KEY=sk-ant-...

then  chmod 600 "$CONF"  and run this again.
A key is created at https://console.anthropic.com under API Keys, and is
shown once — copy it when it appears.

For one session only, without a file:

    export ANTHROPIC_API_KEY=sk-ant-...
    ./run.sh

EOF
  exit 1
fi

export ANTHROPIC_API_KEY

case "${1:-python}" in
  rust|cargo)
    PATH="$HOME/.cargo/bin:$PATH"
    export PATH
    exec cargo run --release
    ;;
  *)
    exec python3 serve.py
    ;;
esac
