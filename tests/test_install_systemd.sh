#!/usr/bin/env bash
# Execute only the installer's configuration preflight, never installation.
set -euo pipefail

test_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
installer="${test_dir}/../deploy/install_systemd.sh"
preflight=""
found_boundary=false
while IFS= read -r line; do
  line="${line%$'\r'}"
  if [[ "$line" == 'REPO_ROOT='* ]]; then
    found_boundary=true
    break
  fi
  preflight+="$line"$'\n'
done < "$installer"
[[ "$found_boundary" == true ]] || { echo "Missing preflight boundary" >&2; exit 1; }

settings=(APP_USER APP_ROOT APP_DIR VENV_DIR STATE_DIR BACKUP_DIR CONFIG_DIR)
defaults=(swejobs /opt/swe-jobs /opt/swe-jobs/current /opt/swe-jobs/venv /var/lib/swe-jobs /var/backups/swe-jobs /etc/swe-jobs)
unset "${settings[@]}"

check_defaults() {
  local output
  output="$(bash -c "$preflight"$'\n''printf "%s\n" "$APP_USER" "$APP_ROOT" "$APP_DIR" "$VENV_DIR" "$STATE_DIR" "$BACKUP_DIR" "$CONFIG_DIR"')"
  [[ "$output" == "$(printf '%s\n' "${defaults[@]}")" ]]
}

check_defaults
echo 'PASS: unset settings resolve to the installed-unit defaults'
for i in "${!settings[@]}"; do
  export "${settings[$i]}=${defaults[$i]}"
done
check_defaults
echo 'PASS: explicit documented defaults are accepted'
unset "${settings[@]}"

for name in "${settings[@]}"; do
  for value in alternate '/custom path/jobs' '$(false);*' $'custom\npath'; do
    export "$name=$value"
    if output="$(bash -c "$preflight" 2>&1)"; then
      echo "FAIL: accepted unsupported $name" >&2
      exit 1
    fi
    [[ "$output" == *"Unsupported ${name}:"* ]] || { echo "FAIL: unclear rejection for $name" >&2; exit 1; }
  done
  unset "$name"
  echo "PASS: $name rejects unsupported values"
done

# Preserve the installer's existing empty-as-unset default behavior.
for name in "${settings[@]}"; do
  export "$name="
done
check_defaults
echo 'PASS: empty settings use documented defaults'
