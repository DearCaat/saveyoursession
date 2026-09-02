#!/usr/bin/env bash
# Install (but do not enable) a 12-hour systemd user timer for saveyoursession.
set -euo pipefail

SERVICE_NAME="saveyoursession-sync"
SYNC_TIME="03:00"
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON_BIN="python3"

usage() {
  cat <<'EOF'
Usage: scripts/install_linux_schedule.sh [--time HH:MM] [--plugin-root PATH] [--python PATH]

Writes a systemd user service and a timer that runs every 12 hours. --time
selects the first daily anchor (default: 03:00, then 15:00). It does not enable
or start the timer.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --time) SYNC_TIME="${2:?--time requires HH:MM}"; shift 2 ;;
    --plugin-root) PLUGIN_ROOT="${2:?--plugin-root requires PATH}"; shift 2 ;;
    --python) PYTHON_BIN="${2:?--python requires PATH}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "$SYNC_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "--time must be a 24-hour HH:MM value" >&2
  exit 2
fi
SYNC_HOUR="${SYNC_TIME%%:*}"
SYNC_MINUTE="${SYNC_TIME##*:}"
SECOND_HOUR=$(printf '%02d' "$(( (10#$SYNC_HOUR + 12) % 24 ))")
ON_CALENDAR="*-*-* ${SYNC_HOUR},${SECOND_HOUR}:${SYNC_MINUTE}:00"
if [[ ! -f "$PLUGIN_ROOT/scripts/manager.py" ]]; then
  echo "manager.py not found under --plugin-root: $PLUGIN_ROOT" >&2
  exit 2
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
  cat >&2 <<'EOF'
The systemd user manager is unavailable. On WSL, enable systemd in /etc/wsl.conf,
then run `wsl --shutdown` from Windows and reopen this Ubuntu distribution.
EOF
  exit 1
fi

CONFIG_DIR="$HOME/.config/saveyoursession"
STATE_DIR="$HOME/.local/state/saveyoursession"
UNIT_DIR="$HOME/.config/systemd/user"
ENV_FILE="$CONFIG_DIR/sync.env"
SERVICE_FILE="$UNIT_DIR/$SERVICE_NAME.service"
TIMER_FILE="$UNIT_DIR/$SERVICE_NAME.timer"

mkdir -p "$CONFIG_DIR" "$STATE_DIR" "$UNIT_DIR"
chmod 700 "$CONFIG_DIR"

if [[ ! -e "$ENV_FILE" ]]; then
  umask 077
  cat >"$ENV_FILE" <<EOF
# Scheduler configuration only. Keep HF_TOKEN in config/local.env or HF_TOKEN_FILE,
# never in this file or the systemd unit.
SAVEYOURSESSION_PLUGIN_ROOT=$PLUGIN_ROOT
SAVEYOURSESSION_PYTHON=$PYTHON_BIN
EOF
  echo "Created $ENV_FILE"
else
  echo "Keeping existing $ENV_FILE"
fi

cat >"$SERVICE_FILE" <<'EOF'
[Unit]
Description=Archive and upload saveyoursession changes
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-%h/.config/saveyoursession/sync.env
Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/bin/sh -c 'exec "${SAVEYOURSESSION_PYTHON:-python3}" "${SAVEYOURSESSION_PLUGIN_ROOT:?SAVEYOURSESSION_PLUGIN_ROOT is required}/scripts/manager.py" sync'
StandardOutput=append:%h/.local/state/saveyoursession/sync.log
StandardError=append:%h/.local/state/saveyoursession/sync.log
EOF

cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Run saveyoursession every 12 hours

[Timer]
OnCalendar=$ON_CALENDAR
Persistent=true
RandomizedDelaySec=10m
Unit=$SERVICE_NAME.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
cat <<EOF
Installed (not enabled):
  $SERVICE_FILE
  $TIMER_FILE
  $ENV_FILE

Review the environment file, then enable the 12-hour timer explicitly:
  systemctl --user enable --now $SERVICE_NAME.timer

Inspect its next run and logs with:
  systemctl --user list-timers $SERVICE_NAME.timer
  journalctl --user -u $SERVICE_NAME.service
  tail -f "$STATE_DIR/sync.log"
EOF
