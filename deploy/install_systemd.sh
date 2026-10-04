#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-swejobs}"
APP_ROOT="${APP_ROOT:-/opt/swe-jobs}"
APP_DIR="${APP_DIR:-$APP_ROOT/current}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/venv}"
STATE_DIR="${STATE_DIR:-/var/lib/swe-jobs}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/swe-jobs}"
CONFIG_DIR="${CONFIG_DIR:-/etc/swe-jobs}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root (sudo)." >&2
  exit 1
fi

if [[ "${REPO_ROOT}" != "${APP_DIR}" ]]; then
  echo "This installer expects the repository at ${APP_DIR}." >&2
  echo "Current repository: ${REPO_ROOT}" >&2
  exit 1
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home "${STATE_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${STATE_DIR}" "${BACKUP_DIR}"
install -d -o root -g "${APP_USER}" -m 0750 "${CONFIG_DIR}"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${CONFIG_DIR}/swe-jobs.env" ]]; then
  install -o root -g "${APP_USER}" -m 0640 \
    "${APP_DIR}/deploy/swe-jobs.env.example" "${CONFIG_DIR}/swe-jobs.env"
  echo "Created ${CONFIG_DIR}/swe-jobs.env. Fill Telegram secrets before enabling the timer."
fi

# Import the latest GitHub data-branch snapshot once when this is a fresh VPS.
if [[ ! -f "${STATE_DIR}/jobs.db" ]] && git -C "${APP_DIR}" remote get-url origin >/dev/null 2>&1; then
  if git -C "${APP_DIR}" fetch --depth=1 origin data; then
    tmp_db="${STATE_DIR}/jobs.db.import"
    if git -C "${APP_DIR}" show origin/data:jobs.db > "${tmp_db}"; then
      chown "${APP_USER}:${APP_USER}" "${tmp_db}"
      chmod 0640 "${tmp_db}"
      mv "${tmp_db}" "${STATE_DIR}/jobs.db"
      echo "Imported jobs.db from origin/data."
    else
      rm -f "${tmp_db}"
    fi
  fi
fi

install -o root -g root -m 0644 "${APP_DIR}/deploy/systemd/swe-jobs.service" /etc/systemd/system/swe-jobs.service
install -o root -g root -m 0644 "${APP_DIR}/deploy/systemd/swe-jobs.timer" /etc/systemd/system/swe-jobs.timer
install -o root -g root -m 0644 "${APP_DIR}/deploy/systemd/swe-jobs-backup.service" /etc/systemd/system/swe-jobs-backup.service
install -o root -g root -m 0644 "${APP_DIR}/deploy/systemd/swe-jobs-backup.timer" /etc/systemd/system/swe-jobs-backup.timer

systemctl daemon-reload

echo
echo "Bootstrap complete."
echo "1) Edit ${CONFIG_DIR}/swe-jobs.env"
echo "2) Test: systemctl start swe-jobs.service"
echo "3) Logs: journalctl -u swe-jobs.service -n 100 --no-pager"
echo "4) Enable: systemctl enable --now swe-jobs.timer swe-jobs-backup.timer"
