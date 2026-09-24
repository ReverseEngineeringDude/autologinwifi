#!/usr/bin/env python3
"""Auto login/logout for the captive portal at 172.16.100.1:8090.

Usage:
  python portal_login.py login
  python portal_login.py logout
  python portal_login.py status
  python portal_login.py watch [--interval 30]

Credentials: PORTAL_USER / PORTAL_PASS env vars, else the OS keyring
(pip install keyring), else an interactive prompt. Never hardcode them
and never commit them to git.

Standard library only, so it runs unchanged on Windows, macOS and Linux.
"""
import argparse
import getpass
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PORTAL = "http://172.16.100.1:8090"
PROBE_URL = "http://connectivitycheck.gstatic.com/generate_204"
KEYRING_SERVICE = "captive-portal-autologin"

# Hardcode your credentials here (stored in plain text, so keep this file
# private and out of git). Leave empty to use env vars / keyring / prompt.
USERNAME = "cs_pvn"
PASSWORD = "Pvn@2535"

NET_ERRORS = (urllib.error.URLError, OSError, ET.ParseError)

# Send the same headers Firefox sends, since the portal is happy with those.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": PORTAL,
    "Referer": PORTAL + "/",
}
# The portal is on the local network: never route it through a system proxy
# (urllib would otherwise obey http_proxy / HTTP_PROXY environment variables).
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_online():
    """204 from the probe URL means no portal is intercepting traffic."""
    try:
        with urllib.request.urlopen(PROBE_URL, timeout=5) as r:
            return r.status == 204
    except NET_ERRORS:
        return False


def _post(path, fields):
    fields = {**fields, "a": str(int(time.time() * 1000)), "producttype": "0"}
    req = urllib.request.Request(
        PORTAL + path,
        data=urllib.parse.urlencode(fields).encode(),  # encodes '@' etc. for us
        headers=BROWSER_HEADERS,
        method="POST",
    )
    with _direct.open(req, timeout=10) as r:
        root = ET.fromstring(r.read())
    return root.findtext("status", "").strip(), root.findtext("message", "").strip()


def login(user, password):
    status, msg = _post(
        "/login.xml", {"mode": "191", "username": user, "password": password}
    )
    return status == "LIVE", msg.replace("{username}", user)


def logout(user):
    status, msg = _post("/logout.xml", {"mode": "193", "username": user})
    return status == "LOGIN", msg


def get_credentials():
    interactive = sys.stdin.isatty()
    user = USERNAME or os.environ.get("PORTAL_USER")
    if not user:
        if not interactive:
            sys.exit("PORTAL_USER is not set (running without a terminal).")
        user = input("Username: ").strip()
    password = PASSWORD or os.environ.get("PORTAL_PASS")
    keyring = None
    try:
        import keyring
    except ImportError:
        pass
    if not password and keyring:
        try:
            password = keyring.get_password(KEYRING_SERVICE, user)
        except Exception:  # keyring backend locked/unavailable at startup
            password = None
    if not password:
        if not interactive:
            sys.exit("No password found in PORTAL_PASS or the keyring.")
        password = getpass.getpass("Password: ")
        if keyring and input("Save to OS keyring? [y/N] ").lower() == "y":
            keyring.set_password(KEYRING_SERVICE, user, password)
    return user, password


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def watch(interval):
    """Simple polling loop. Later, replace with OS network-change hooks."""
    user, password = get_credentials()
    rejected = 0
    last = None
    while True:
        if is_online():
            last = None
        else:
            try:
                ok, msg = login(user, password)
                rejected = 0 if ok else rejected + 1
            except NET_ERRORS as e:
                ok, msg = False, f"portal unreachable ({e})"
            if (ok, msg) != last:  # log changes only, not every poll
                log("login", "ok" if ok else "FAILED", "-", msg)
                last = (ok, msg)
            if rejected >= 3:  # avoid locking the account with a wrong password
                print("Portal rejected the credentials 3 times; stopping.", file=sys.stderr)
                sys.exit(2)  # code 2 = don't auto-restart (see systemd note)
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="Captive portal login manager")
    p.add_argument("command", choices=["login", "logout", "status", "watch"])
    p.add_argument("--interval", type=int, default=30, help="watch poll seconds")
    args = p.parse_args()

    if args.command == "status":
        print("online" if is_online() else "offline or behind the portal")
    elif args.command == "login":
        ok, msg = login(*get_credentials())
        print("OK" if ok else "FAILED", "-", msg)
        sys.exit(0 if ok else 1)
    elif args.command == "logout":
        user = USERNAME or os.environ.get("PORTAL_USER") or input("Username: ").strip()
        ok, msg = logout(user)
        print("OK" if ok else "FAILED", "-", msg)
        sys.exit(0 if ok else 1)
    else:
        watch(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except NET_ERRORS as e:
        sys.exit(f"Could not reach the portal: {e}")