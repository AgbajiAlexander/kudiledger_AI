#!/usr/bin/env bash
# Release CI only. Keep Chrome sandboxed and apply any profile only during tests.
set -euo pipefail
browser="${KUDILEDGER_BROWSER:?Verified Chrome path required}"
work="$(mktemp -d)"
profile="$work/chrome-ci.apparmor"
profile_loaded=0
cleanup() {
    status=$?
    trap - EXIT
    if [ "$profile_loaded" = 1 ]; then
        sudo apparmor_parser -R "$profile" || status=1
    fi
    python -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$work" || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -u /opt/google/chrome/chrome-sandbox ]; then
    export CHROME_DEVEL_SANDBOX=/opt/google/chrome/chrome-sandbox
fi
probe() {
    timeout --kill-after=5s 30s "$browser" --headless --disable-gpu --dump-dom about:blank --user-data-dir="$1"
}
if ! probe "$work/probe" >"$work/probe.log" 2>&1; then
    if ! grep -q "No usable sandbox" "$work/probe.log"; then
        cat "$work/probe.log"
        exit 1
    fi
    [[ "${GITHUB_ACTIONS:-}" = true && "${RUNNER_OS:-}" = Linux ]]
    [ "$(readlink -f "$browser")" = /opt/google/chrome/google-chrome ]
    chrome=/opt/google/chrome/chrome
    [[ -x "$chrome" && "$(readlink -f "$chrome")" = "$chrome" ]]
    [ "$(stat -c '%u' "$chrome")" = 0 ]
    [ "$(( 8#$(stat -c '%a' "$chrome") & 8#022 ))" = 0 ]
    cat >"$profile" <<'EOF'
abi <abi/4.0>,
include <tunables/global>
profile kudiledger-ci-chrome /opt/google/chrome/chrome flags=(unconfined) {
  userns,
}
EOF
    sudo apparmor_parser -r "$profile"
    profile_loaded=1
    printf '%s\n' 'Loaded the CI-only profile for root-owned Chrome.'
    probe "$work/retry" >/dev/null
fi
python -m unittest discover -v
