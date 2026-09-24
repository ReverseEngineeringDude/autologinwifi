#!/usr/bin/env bash
# install.sh - install the Wi-Fi portal auto-login and start it at every desktop login (Linux).
#
#   ./install.sh                  install (uses wifi.py or portal_login.py from this folder)
#   ./install.sh path/to/app.py   install a specific script
#   ./install.sh uninstall        stop it and remove everything
#
# Fill in USERNAME and PASSWORD at the top of the python file first, or leave
# them empty and this installer will ask for them.
set -euo pipefail

NAME="wifi-autologin"
DEST="$HOME/.local/share/$NAME"
SCRIPT="$DEST/autologin.py"
LAUNCHER="$DEST/run.sh"
LOG="$DEST/watch.log"
AUTOSTART="$HOME/.config/autostart/$NAME.desktop"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_watcher() { pkill -f "$SCRIPT watch" 2>/dev/null || true; }

if [[ "${1:-}" == "uninstall" ]]; then
  stop_watcher
  rm -f "$AUTOSTART"
  rm -rf "$DEST"
  echo "Uninstalled."
  exit 0
fi

command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }

# 1. Find the python script to install
SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  for f in "$HERE/wifi.py" "$HERE/portal_login.py"; do
    if [[ -f "$f" ]]; then SRC="$f"; break; fi
  done
fi
[[ -f "$SRC" ]] || { echo "Put wifi.py next to install.sh (or pass its path)." >&2; exit 1; }

# 2. Work on a private temporary copy, so a failed install never breaks a working setup
mkdir -p "$DEST" "$(dirname "$AUTOSTART")"
TMP="$SCRIPT.new"
trap 'rm -f "$TMP"' EXIT
cp "$SRC" "$TMP"
chmod 600 "$TMP"                                # it may hold your password in plain text

# 3. Make sure credentials are set; ask for them if the script has none
if python3 - "$TMP" <<'PY'
import re, sys
s = open(sys.argv[1]).read()
def filled(name):
    return re.search(r'^' + name + r' = (["\'])(.+?)\1', s, re.M) is not None
sys.exit(0 if filled("USERNAME") and filled("PASSWORD") else 1)
PY
then
  echo "Using the credentials already set in $(basename "$SRC")."
else
  if [[ ! -t 0 ]]; then
    echo "No USERNAME/PASSWORD set in $(basename "$SRC"). Fill them in, or run this from a terminal." >&2
    exit 1
  fi
  read -rp "Wi-Fi portal username: " user
  read -rsp "Wi-Fi portal password: " pass; echo
  [[ -n "$user" && -n "$pass" ]] || { echo "Username and password are required." >&2; exit 1; }
  U="$user" P="$pass" python3 - "$TMP" <<'PY'
import os, re, sys
path = sys.argv[1]
s = open(path).read()
for name, var in (("USERNAME", "U"), ("PASSWORD", "P")):
    s, n = re.subn(r'^' + name + r' = .*$',
                   lambda m: f"{name} = {os.environ[var]!r}", s, flags=re.M)
    if n == 0:
        sys.exit(f"Could not find the {name} line in the script.")
open(path, "w").write(s)
PY
fi

# 4. Everything worked, so swap the new script in
stop_watcher
mv -f "$TMP" "$SCRIPT"

# 5. Launcher that runs the watcher in the background with a log file
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Started at every desktop login by $AUTOSTART
[[ -f "$LOG" ]] && (( \$(stat -c %s "$LOG") > 1048576 )) && mv -f "$LOG" "$LOG.old"
exec python3 -u "$SCRIPT" watch >>"$LOG" 2>&1 </dev/null
EOF
chmod +x "$LAUNCHER"

# 6. Add it to Startup Applications
cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Wi-Fi Auto Login
Comment=Logs in to the Wi-Fi captive portal automatically
Exec="$LAUNCHER"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

# 7. Start it now
setsid "$LAUNCHER" </dev/null >/dev/null 2>&1 &
sleep 2

echo "Installed. It runs now and at every desktop login."
echo "Log file: $LOG"
