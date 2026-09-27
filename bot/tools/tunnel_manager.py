"""
Self-healing Cloudflare quick-tunnel manager for the WAGMI site's live API.

Keeps a `cloudflared` quick tunnel pointed at the local api_server (localhost:8000)
alive, and whenever the public trycloudflare URL changes (first run, or after a PC
reboot / tunnel restart), it:
  1. updates the Vercel env var NEXT_PUBLIC_API_URL (production + preview) via REST, and
  2. pushes an empty commit to `main` to trigger a Vercel rebuild that bakes the new URL
     into the client bundle (NEXT_PUBLIC_* is build-time inlined).

This is the "live API" half of the site's hybrid data model. The snapshot fallback in
web/src/api.ts means the site keeps working (last-known data) whenever the tunnel is down
or between URL-change rebuilds — so this is best-effort real-time, never a hard dependency.

Run supervised via the WAGMI-Tunnel scheduled task:
  python tools/tunnel_manager.py

Stdlib only. Cloudflared quick tunnels need no account/login.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

CLOUDFLARED = r"C:\Users\vince\ngrok_bin\cloudflared.exe"
AUTH_JSON = r"C:/Users/vince/AppData/Roaming/xdg.data/com.vercel.cli/auth.json"
TEAM = "team_AP0cJlWt8BMxpURpS2GJg2QA"
PROJECT = "prj_FaTrVr29CMJyOvH6d4vwpB4irMAI"
REPO_DIR = r"C:\Users\vince\WAGMI_web_deploy"   # sparse worktree tracking main
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_FILE = os.path.join(BOT_DIR, "data", "tunnel_url.txt")
LOG = os.path.join(BOT_DIR, "logs", "tunnel_manager.log")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


_token_warned = False


def _token() -> str:
    """Vercel auth token, or "" when it is missing/expired.

    Was `json.load(open(AUTH_JSON))["token"]`. When the CLI's auth file lost that
    key the bare KeyError escaped _api's HTTPError handler and killed the manager
    mid-loop, so the supervisor relaunched it every 10-20s forever (see
    tunnel_manager.log 2026-09-09). A dead token must degrade to "no Vercel
    update", never to a crash-loop: cloudflared itself works fine without it.
    """
    global _token_warned
    try:
        tok = json.load(open(AUTH_JSON)).get("token") or ""
    except (OSError, ValueError):
        tok = ""
    if not tok and not _token_warned:
        _token_warned = True
        log("vercel token missing/unreadable - skipping env updates "
            "(tunnel still serves; re-auth with `vercel login` to restore)")
    return tok


def _api(method: str, path: str, body=None):
    tok = _token()
    if not tok:
        return {"_err": "no_token"}
    u = "https://api.vercel.com" + path + ("&" if "?" in path else "?") + "teamId=" + TEAM
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        u, data=data, method=method,
        headers={"Authorization": "Bearer " + _token(), "Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "body": e.read().decode()[:300]}


def update_vercel_env(url: str) -> None:
    envs = _api("GET", f"/v9/projects/{PROJECT}/env")
    for e in envs.get("envs", []):
        if e.get("key") == "NEXT_PUBLIC_API_URL":
            _api("DELETE", f"/v9/projects/{PROJECT}/env/{e['id']}")
    res = _api("POST", f"/v10/projects/{PROJECT}/env",
               {"key": "NEXT_PUBLIC_API_URL", "value": url, "type": "plain",
                "target": ["production", "preview"]})
    log(f"vercel env NEXT_PUBLIC_API_URL -> {url} ({'ok' if '_err' not in res else res})")


def trigger_rebuild(url: str) -> None:
    """Empty commit to main => Vercel auto-build bakes the new URL. CLI upload is
    unreliable on this host (ECONNRESET), so we use git push."""
    def git(*args):
        return subprocess.run(["git", "-C", REPO_DIR, *args], capture_output=True, text=True)
    git("fetch", "origin", "main")
    git("reset", "--hard", "origin/main")
    git("commit", "--allow-empty", "-m", f"chore(web): rebuild for live API url {url}")
    p = git("push", "origin", "HEAD:main")
    log(f"rebuild push: {'ok' if p.returncode == 0 else p.stderr.strip()[:200]}")


def read_last_url() -> str:
    try:
        return open(URL_FILE, encoding="utf-8").read().strip()
    except Exception:
        return ""


def write_url(url: str) -> None:
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    with open(URL_FILE, "w", encoding="utf-8") as f:
        f.write(url + "\n")


def run_once() -> None:
    """Start cloudflared, capture the URL, re-point Vercel if it changed, then block
    until cloudflared exits (so the supervisor loop restarts it)."""
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://localhost:8000", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    url = None
    deadline = time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = URL_RE.search(line)
        if m:
            url = m.group(0)
            break
    if not url:
        log("no tunnel URL captured within 60s; killing and retrying")
        proc.kill()
        return
    log(f"tunnel up: {url}")
    if url != read_last_url():
        write_url(url)
        update_vercel_env(url)
        trigger_rebuild(url)
    else:
        log("URL unchanged — no Vercel update needed")
    # Drain remaining output so the process doesn't block; wait until it dies.
    for _ in proc.stdout:
        if proc.poll() is not None:
            break
    proc.wait()
    log("cloudflared exited")


def main() -> int:
    log("=== tunnel_manager started ===")
    backoff = 5
    while True:
        try:
            run_once()
            backoff = 5
        except Exception as e:
            log(f"error: {type(e).__name__}: {e}")
            backoff = min(300, backoff * 2)
        log(f"restarting tunnel in {backoff}s")
        time.sleep(backoff)


if __name__ == "__main__":
    sys.exit(main())
