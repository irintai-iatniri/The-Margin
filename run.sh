#!/usr/bin/env sh
# The Margin — start the local server.
#
#   ./run.sh          python server, no build
#   ./run.sh rust     cargo run --release
#   ./run.sh lan      python server, reachable from your own network
#
# The key is read from ~/.config/the-margin/env so it never lives in this
# directory, in shell history, or in anything committed.

set -e
cd "$(dirname "$0")"

CONF="${XDG_CONFIG_HOME:-$HOME/.config}/the-margin/env"
if [ -f "$CONF" ]; then
  # Anything already set in the environment is explicit and must win over the
  # config file -- otherwise `MARGIN_PORT=7882 ./run.sh` silently binds whatever
  # the file says, which is how update.sh first started the server on one port
  # and tested another. Remember what was set, source, then put it back.
  _p="${MARGIN_PORT:-}"; _q="${MARGIN_QUICK:-}"; _d="${MARGIN_DEFAULT:-}"
  _c="${MARGIN_COMPLEX:-}"; _m="${MARGIN_MAX_TOKENS:-}"; _k="${ANTHROPIC_API_KEY:-}"

  # set -a exports everything the file assigns, not just the key. Without it a
  # bare MARGIN_PORT=7878 in the env file becomes a shell variable that never
  # reaches the server process, and the override silently does nothing.
  set -a
  # shellcheck disable=SC1090
  . "$CONF"
  set +a

  [ -n "$_p" ] && MARGIN_PORT="$_p"
  [ -n "$_q" ] && MARGIN_QUICK="$_q"
  [ -n "$_d" ] && MARGIN_DEFAULT="$_d"
  [ -n "$_c" ] && MARGIN_COMPLEX="$_c"
  [ -n "$_m" ] && MARGIN_MAX_TOKENS="$_m"
  [ -n "$_k" ] && ANTHROPIC_API_KEY="$_k"
  export MARGIN_PORT MARGIN_QUICK MARGIN_DEFAULT MARGIN_COMPLEX MARGIN_MAX_TOKENS
  unset _p _q _d _c _m _k
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
  lan)
    MARGIN_HOST=0.0.0.0
    export MARGIN_HOST
    IP=$(ip route get 1.1.1.1 2>/dev/null | awk "/src/ {print \$7; exit}")
    [ -n "$IP" ] && printf "\n  Someone else on this network opens:  http://%s:%s\n\n" "$IP" "${MARGIN_PORT:-7878}"
    exec python3 serve.py
    ;;
  rust|cargo)
    PATH="$HOME/.cargo/bin:$PATH"
    export PATH
    exec cargo run --release
    ;;
  *)
    exec python3 serve.py
    ;;
esac
