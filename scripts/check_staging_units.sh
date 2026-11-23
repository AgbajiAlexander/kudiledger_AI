#!/usr/bin/env bash
# Parse the real units without running services or touching installed units.
set -euo pipefail
root="$(mktemp -d)"
cleanup() {
    python3 -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$root"
}
trap cleanup EXIT
install -d "$root/etc/systemd/system" "$root/usr/lib/systemd/system" "$root/opt/kudiledger/venv/bin"
install -m 0755 /bin/true "$root/opt/kudiledger/venv/bin/python"
cp /usr/lib/systemd/system/*.target "$root/usr/lib/systemd/system/"
install -m 0644 deploy/staging/*.service deploy/staging/*.timer "$root/etc/systemd/system/"
systemd-analyze verify --man=no --recursive-errors=no --root="$root" \
    "$root/etc/systemd/system/"*.service "$root/etc/systemd/system/"*.timer
systemd-analyze calendar "$(sed -n 's/^OnCalendar=//p' deploy/staging/kudiledger-backup.timer)"
