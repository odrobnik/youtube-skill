#!/usr/bin/env python3
"""YouTube search and playlist management via the YouTube Data API v3.

Usage:
    python3 youtube.py search "query" [--max N] [--order relevance|date|...]
    python3 youtube.py auth [--manual] [--port N]  # One-time Google sign-in
    python3 youtube.py auth --code CODE_OR_URL     # Finish a manual sign-in
    python3 youtube.py list                        # List your playlists
    python3 youtube.py create "Name" [--privacy private|unlisted|public] [--description TEXT]
    python3 youtube.py edit <playlist_id> [--title T] [--description D] [--privacy P]
    python3 youtube.py add <playlist_id> <video_url_or_id> [...]
    python3 youtube.py videos <playlist_id>
    python3 youtube.py remove <playlist_item_id> [...] [--yes]  # Without --yes: preview only
    python3 youtube.py delete <playlist_id> [--yes]             # Without --yes: preview only
    python3 youtube.py logout                      # Revoke the sign-in, delete the tokens

Global option --json (before or after the subcommand): stdout carries exactly one
JSON document (errors too, as {"error": {...}}); human-readable text goes to stderr.

Credentials live in config.json in the config folder (env vars override it), OAuth
tokens in tokens.json next to it. The folder is $YOUTUBE_SKILL_CONFIG_DIR if set,
else $OPENCLAW_STATE_DIR/youtube, else ~/.openclaw/youtube. Standard library only.
"""

import argparse
import base64
import hashlib
import html
import http.server
import json
import os
import re
import secrets
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

# --- Paths ---

def _config_dir() -> Path:
    """Where config and tokens live; ~/.openclaw is kept by OpenClaw's backups and Docker setups."""
    custom = os.environ.get("YOUTUBE_SKILL_CONFIG_DIR")
    if custom:
        return Path(custom).expanduser()
    state = os.environ.get("OPENCLAW_STATE_DIR")
    return (Path(state).expanduser() if state else Path.home() / ".openclaw") / "youtube"


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = CONFIG_DIR / "tokens.json"
PENDING_AUTH_FILE = CONFIG_DIR / "pending-auth.json"

API_BASE = "https://www.googleapis.com/youtube/v3"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = "https://www.googleapis.com/auth/youtube"
AUTH_CALLBACK_PORT = 8923
AUTH_TIMEOUT = 300  # seconds to wait for the browser to come back
HTTP_TIMEOUT = 30
NEEDS_CONFIRMATION_EXIT = 3  # `delete`/`remove` without --yes: previewed, nothing changed

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# playlistItems.insert errors that concern one video; anything else stops `add`
VIDEO_ERRORS = {"videoNotFound", "invalidResourceId"}


# --- Errors ---

class ApiError(Exception):
    """An error response from a Google endpoint, reduced to one line."""

    def __init__(self, status: int, message: str, reason: str = ""):
        super().__init__(message)
        self.status = status
        self.reason = reason

    def __str__(self):
        reason = f" {self.reason}" if self.reason else ""
        return f"API error {self.status}{reason}: {self.args[0]}"


def _api_error(e: urllib.error.HTTPError) -> ApiError:
    try:
        body = json.loads(e.read().decode() or "{}")
    except (ValueError, OSError):
        body = {}
    finally:
        e.close()
    err = body.get("error", {}) if isinstance(body, dict) else {}
    if isinstance(err, str):  # OAuth endpoints: {"error": "invalid_grant", "error_description": ...}
        return ApiError(e.code, body.get("error_description") or err, err)
    reason = (err.get("errors") or [{}])[0].get("reason", "")
    return ApiError(e.code, err.get("message") or str(e.reason), reason)


# --- Output (text or --json) ---

JSON_MODE = False
_JSON_OUT = sys.stdout  # the real stdout; in JSON mode sys.stdout points at stderr
_RESULT = None


def emit(obj):
    """Record the command's JSON result (written once, at exit, in JSON mode)."""
    global _RESULT
    _RESULT = obj


def _write_json(obj):
    tty = _JSON_OUT.isatty()
    _JSON_OUT.write(json.dumps(obj, ensure_ascii=False, indent=2 if tty else None,
                               separators=None if tty else (",", ":")) + "\n")
    _JSON_OUT.flush()


def _flush_result():
    """Write the recorded result as the single JSON document (JSON mode only)."""
    global _RESULT
    if JSON_MODE and _RESULT is not None:
        _write_json(_RESULT)
        _RESULT = None


def _fail(message: str, code: str = "error", exit_code: int = 1):
    if JSON_MODE:
        _write_json({"error": {"message": message, "code": code}})
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(exit_code)


def _abort(partial: dict, e: "ApiError"):
    """Stop a run part-way: the JSON lists what already happened, plus the error."""
    code = e.reason or f"http_{e.status}"
    if JSON_MODE:
        _write_json(dict(partial, ok=False, error={"message": str(e), "code": code}))
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)


def _unescape(obj):
    """Decode HTML entities (&amp; &#39; ...) in every string of an API reply.

    Only search results arrive escaped; playlist endpoints return plain text, which
    must not be decoded (an edit would write the changed text back)."""
    if isinstance(obj, str):
        return html.unescape(obj)
    if isinstance(obj, list):
        return [_unescape(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _unescape(v) for k, v in obj.items()}
    return obj


def _playlist_json(p: dict) -> dict:
    s = p.get("snippet", {})
    return {
        "id": p["id"], "title": s.get("title", ""), "description": s.get("description", ""),
        "privacy": p.get("status", {}).get("privacyStatus"),
        "item_count": p.get("contentDetails", {}).get("itemCount"),
        "channel": s.get("channelTitle"), "channel_id": s.get("channelId"),
        "published_at": s.get("publishedAt"),
        "url": f"https://youtube.com/playlist?list={p['id']}",
    }


# --- Configuration (config.json + env var overrides) ---

def _load_config() -> dict:
    """Load config from config.json with env var overrides."""
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            if os.name == "posix" and CONFIG_FILE.stat().st_mode & 0o077:
                print(f"Warning: {CONFIG_FILE} is readable by other users; "
                      "restrict it to your account (file mode 600).", file=sys.stderr)
            cfg = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to read {CONFIG_FILE}: {e}", file=sys.stderr)

    # Env vars override config.json
    api_key = os.environ.get("YOUTUBE_API_KEY") or cfg.get("api_key", "")
    client_id = os.environ.get("YOUTUBE_CLIENT_ID") or cfg.get("client_id", "")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET") or cfg.get("client_secret", "")

    return {
        "api_key": api_key,
        "client_id": client_id,
        "client_secret": client_secret,
    }


def _require_oauth(cfg: dict) -> tuple:
    """Return (client_id, client_secret) or exit with error."""
    cid = cfg.get("client_id", "")
    csec = cfg.get("client_secret", "")
    if not cid or not csec:
        _fail("Missing client_id/client_secret for OAuth. Set YOUTUBE_CLIENT_ID + "
              f"YOUTUBE_CLIENT_SECRET env vars, or add them to {CONFIG_FILE}", "missing_oauth_client")
    return cid, csec


# --- Token Management ---

def _write_private(path: Path, data: dict):
    """Write JSON only the owner can read (0600), replacing the file atomically."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_tokens(tokens: dict):
    _write_private(TOKEN_FILE, tokens)


def load_tokens() -> dict:
    if not TOKEN_FILE.exists():
        _fail("Not signed in to YouTube. Run: youtube.py auth", "not_signed_in")
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (ValueError, OSError) as e:
        _fail(f"Cannot read {TOKEN_FILE} ({e}). Run: youtube.py auth")


def refresh_access_token(tokens: dict) -> dict:
    """Renew the expired sign-in; updates `tokens` in place and on disk."""
    if not tokens.get("refresh_token"):
        _fail("No refresh token stored. Run: youtube.py auth")
    client_id, client_secret = _require_oauth(_load_config())
    try:
        new = _post_form(TOKEN_URL, {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        })
    except ApiError as e:
        if e.reason != "invalid_grant":
            _fail(f"Token refresh failed: {e}")
        hint = ""
        if tokens.get("refresh_token_expires_in"):
            hint = ("\nGoogle gave this sign-in a limited lifetime, usually because the OAuth consent "
                    "screen is in Testing mode (7 days). Publish the app to stay signed in (see SETUP.md).")
        _fail("Google rejected the stored sign-in (expired or revoked). Run: youtube.py auth" + hint)
    tokens["access_token"] = new["access_token"]
    if new.get("refresh_token"):
        tokens["refresh_token"] = new["refresh_token"]
    save_tokens(tokens)
    return tokens


# --- API Helpers ---

def _open_json(req: urllib.request.Request) -> dict:
    """Send a request and decode the JSON reply; raises ApiError for HTTP errors."""
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise _api_error(e) from None
    return json.loads(raw) if raw else {}


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    return _open_json(urllib.request.Request(url, data=data))


def _api_url(endpoint: str, params: dict) -> str:
    return f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"


def api_request(method: str, url: str, tokens: dict, body=None, retry=True) -> dict:
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        return _open_json(req)
    except ApiError as e:
        if e.status == 401 and retry:
            refresh_access_token(tokens)
            return api_request(method, url, tokens, body, retry=False)
        raise


def _paged(endpoint: str, params: dict, tokens: dict):
    """Yield every item of a list endpoint, following nextPageToken."""
    params = dict(params, maxResults=50)
    while True:
        data = api_request("GET", _api_url(endpoint, params), tokens)
        yield from data.get("items", [])
        if not data.get("nextPageToken"):
            return
        params["pageToken"] = data["nextPageToken"]


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Return the 11-character video ID from a video URL or bare ID, or None."""
    s = url_or_id.strip()
    if VIDEO_ID_RE.match(s):
        return s
    parsed = urllib.parse.urlparse(s if "://" in s else f"https://{s}")
    host = (parsed.hostname or "").lower()
    path = [p for p in parsed.path.split("/") if p]
    candidate = ""
    if host == "youtu.be" and path:
        candidate = path[0]
    elif any(host == d or host.endswith("." + d) for d in ("youtube.com", "youtube-nocookie.com")):
        candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if not candidate and len(path) >= 2 and path[0] in ("shorts", "embed", "live", "v", "e"):
            candidate = path[1]
    return candidate if VIDEO_ID_RE.match(candidate) else None


# --- Commands ---

def _pkce_pair() -> tuple:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def cmd_auth(args):
    cfg = _load_config()
    client_id, client_secret = _require_oauth(cfg)

    if args.code:
        _finish_manual_auth(args.code, client_id, client_secret)
        return

    # One sign-in attempt = one state + PKCE verifier, kept on disk so `auth --code` can finish it
    redirect_uri = f"http://127.0.0.1:{args.port}"
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    _write_private(PENDING_AUTH_FILE, {
        "state": state, "code_verifier": verifier, "redirect_uri": redirect_uri,
    })
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    if args.manual:
        print("Open this URL in a browser and approve access:\n")
        print(f"{auth_url}\n")
        print(f"Google then sends the browser to {redirect_uri}/?state=...&code=...")
        print("That page may not load, which is expected. Copy the full address from the address bar")
        print('and run: youtube.py auth --code "<address>"')
        emit({"ok": True, "auth_url": auth_url, "redirect_uri": redirect_uri,
              "next": 'youtube.py auth --code "<address>"'})
        return

    # Ephemeral localhost server that captures the callback
    result = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        timeout = 10  # don't hang on browser preconnects that never send a request

        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = qs.get("code", [None])[0]
            error = qs.get("error", [None])[0]
            if code and qs.get("state", [None])[0] != state:
                self._reply(400, "This sign-in response belongs to a different attempt and was ignored.")
                return
            if not code and not error:
                self._reply(404, "Waiting for the Google sign-in response.")
                return
            result["code"], result["error"] = code, error
            if code:
                self._reply(200, "Authenticated! You can close this tab.")
            else:
                self._reply(200, f"Sign-in failed: {error}")

        def _reply(self, status, text):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>{text}</h2></body></html>".encode())

        def log_message(self, *_):
            pass  # Suppress server logs

    try:
        server = http.server.HTTPServer(("127.0.0.1", args.port), CallbackHandler)
    except OSError as e:
        _fail(f"Cannot listen on 127.0.0.1:{args.port} ({e.strerror}). Use --port N or --manual.")

    print("Opening browser for Google consent...\n")
    print(f"If the browser doesn't open, visit:\n{auth_url}\n")
    print(f"Waiting up to {AUTH_TIMEOUT // 60} minutes for the callback on {redirect_uri} ...", flush=True)
    webbrowser.open(auth_url)

    deadline = time.monotonic() + AUTH_TIMEOUT
    with server:
        while not result and time.monotonic() < deadline:
            server.timeout = max(1.0, deadline - time.monotonic())
            server.handle_request()

    if result.get("error"):
        _fail(f"Google sign-in failed: {result['error']}")
    if not result.get("code"):
        _fail('No callback received. Finish manually: youtube.py auth --code "<redirect address>"')
    _exchange_code(result["code"], client_id, client_secret, redirect_uri, verifier)


def _finish_manual_auth(code_or_url: str, client_id: str, client_secret: str):
    """Finish a sign-in with the code, or the whole redirect address, from the browser."""
    pending = {}
    if PENDING_AUTH_FILE.exists():
        try:
            pending = json.loads(PENDING_AUTH_FILE.read_text())
        except (ValueError, OSError):
            pass
    if not pending.get("redirect_uri"):
        _fail("No sign-in in progress. Run: youtube.py auth --manual, then pass the result to --code.")

    code = code_or_url.strip()
    if "code=" in code or "error=" in code:  # a pasted redirect address
        query = urllib.parse.urlparse(code).query or code.lstrip("?")
        qs = urllib.parse.parse_qs(query)
        if qs.get("error"):
            _fail(f"Google sign-in failed: {qs['error'][0]}")
        if qs.get("state", [None])[0] != pending.get("state"):
            _fail("That address belongs to a different sign-in attempt. Run: youtube.py auth --manual")
        code = qs.get("code", [""])[0]
    _exchange_code(code, client_id, client_secret, pending["redirect_uri"], pending.get("code_verifier"))


def _exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str,
                   verifier: Optional[str] = None):
    """Exchange authorization code for tokens."""
    fields = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if verifier:
        fields["code_verifier"] = verifier
    try:
        tokens = _post_form(TOKEN_URL, fields)
    except ApiError as e:
        _fail(f"Token exchange failed: {e}")
    tokens["obtained_at"] = int(time.time())
    save_tokens(tokens)
    PENDING_AUTH_FILE.unlink(missing_ok=True)
    print(f"✅ Authenticated! Tokens saved to {TOKEN_FILE}")
    if not tokens.get("refresh_token"):
        print("⚠️  Google sent no refresh token; you'll need to run auth again within the hour.")
    elif tokens.get("refresh_token_expires_in"):
        days = round(tokens["refresh_token_expires_in"] / 86400)
        print(f"⚠️  Google limited this sign-in to {days} days, usually because the OAuth consent "
              "screen is in Testing mode. Publish the app to stay signed in (see SETUP.md).")
    emit({"ok": True, "token_file": str(TOKEN_FILE),
          "has_refresh_token": bool(tokens.get("refresh_token")),
          "refresh_token_expires_in": tokens.get("refresh_token_expires_in")})


def cmd_create(args):
    tokens = load_tokens()
    body = {
        "snippet": {
            "title": args.name,
            "description": args.description,
        },
        "status": {"privacyStatus": args.privacy},
    }
    result = api_request("POST", _api_url("playlists", {"part": "snippet,status"}), tokens, body)
    pid = result["id"]
    title = result["snippet"]["title"]
    print(f"✅ Created playlist: {title} ({result['status']['privacyStatus']})")
    print(f"   ID: {pid}")
    print(f"   URL: https://youtube.com/playlist?list={pid}")
    emit({"ok": True, "playlist": _playlist_json(result)})


def cmd_list(_args):
    tokens = load_tokens()
    params = {"part": "snippet,contentDetails,status", "mine": "true"}
    count, out = 0, []
    for count, p in enumerate(_paged("playlists", params, tokens), 1):
        out.append(_playlist_json(p))
        items = p["contentDetails"]["itemCount"]
        privacy = p.get("status", {}).get("privacyStatus", "?")
        print(f"  📋 {p['snippet']['title']} ({items} videos, {privacy})")
        print(f"     ID: {p['id']}")
        print(f"     https://youtube.com/playlist?list={p['id']}")
        print()
    if not count:
        print("No playlists yet.")
    emit(out)


def cmd_add(args):
    tokens = load_tokens()
    failed, results = 0, []
    for vid in args.videos:
        video_id = extract_video_id(vid)
        if not video_id:
            print(f"  ❌ Not a YouTube video URL or ID: {vid}", file=sys.stderr)
            results.append({"input": vid, "ok": False, "video_id": None,
                            "error": {"message": "Not a YouTube video URL or ID", "code": "invalid_video"}})
            failed += 1
            continue
        body = {
            "snippet": {
                "playlistId": args.playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        try:
            result = api_request("POST", _api_url("playlistItems", {"part": "snippet"}), tokens, body)
        except ApiError as e:
            if e.reason not in VIDEO_ERRORS:
                _abort({"playlist_id": args.playlist_id, "results": results}, e)
            print(f"  ❌ {video_id}: {e}", file=sys.stderr)
            results.append({"input": vid, "ok": False, "video_id": video_id,
                            "error": {"message": e.args[0], "code": e.reason or str(e.status)}})
            failed += 1
            continue
        print(f"  ✅ Added: {result['snippet']['title']} ({video_id})")
        print(f"     Item ID: {result['id']}")
        results.append({"input": vid, "ok": True, "video_id": video_id, "item_id": result["id"],
                        "title": result["snippet"].get("title", ""),
                        "url": f"https://youtube.com/watch?v={video_id}"})
    emit({"ok": not failed, "playlist_id": args.playlist_id, "results": results})
    if failed:
        _flush_result()
        sys.exit(1)


def cmd_videos(args):
    tokens = load_tokens()
    params = {"part": "snippet", "playlistId": args.playlist_id}
    count, out = 0, []
    for count, item in enumerate(_paged("playlistItems", params, tokens), 1):
        s = item["snippet"]
        vid = s["resourceId"]["videoId"]
        channel = s.get("videoOwnerChannelTitle")
        out.append({"item_id": item["id"], "video_id": vid, "position": s.get("position"),
                    "title": s.get("title", ""), "description": s.get("description", ""),
                    "channel": channel, "channel_id": s.get("videoOwnerChannelId"),
                    "published_at": s.get("publishedAt"), "playlist_id": s.get("playlistId"),
                    "url": f"https://youtube.com/watch?v={vid}"})
        print(f"  {count}. {s['title']}" + (f"  ({channel})" if channel else ""))
        print(f"     https://youtube.com/watch?v={vid}")
        print(f"     Item ID: {item['id']} (for removal)")
        print()
    if not count:
        print("Playlist is empty.")
    emit(out)


def _needs_confirmation(what: str, preview=None):
    """Stop after a preview: destructive commands only run with --yes."""
    if JSON_MODE:
        _write_json(dict(preview or {}, ok=False, needs_confirmation=True, dry_run=True))
    print(f"\nNothing was {what}. Show this to the user and, after a clear yes, "
          "run the same command with --yes.", file=sys.stderr)
    sys.exit(NEEDS_CONFIRMATION_EXIT)


def _playlist_titles(playlist_ids: list, tokens: dict) -> dict:
    titles = {}
    for i in range(0, len(playlist_ids), 50):
        params = {"part": "snippet", "id": ",".join(playlist_ids[i:i + 50]), "maxResults": 50}
        for p in api_request("GET", _api_url("playlists", params), tokens).get("items", []):
            titles[p["id"]] = p["snippet"]["title"]
    return titles


def cmd_remove(args):
    tokens = load_tokens()

    # Show exactly what goes before anything is removed. Lookups by ID page too
    # (5 results by default), so ask for the whole batch of up to 50.
    found = {}
    for i in range(0, len(args.item_ids), 50):
        params = {"part": "snippet", "id": ",".join(args.item_ids[i:i + 50]), "maxResults": 50}
        for item in api_request("GET", _api_url("playlistItems", params), tokens).get("items", []):
            found[item["id"]] = item["snippet"]
    titles = _playlist_titles(sorted({s["playlistId"] for s in found.values()}), tokens)
    print(f"{'Removing' if args.yes else 'Would remove'} {len(args.item_ids)} playlist entr"
          f"{'y' if len(args.item_ids) == 1 else 'ies'}:")
    for item_id in args.item_ids:
        s = found.get(item_id)
        if s:
            playlist = titles.get(s["playlistId"], s["playlistId"])
            print(f"  - \"{s['title']}\" from \"{playlist}\"  [{item_id}]")
        else:
            print(f"  - unknown entry (not found, or not visible yet)  [{item_id}]")
    entries = []
    for item_id in args.item_ids:
        s = found.get(item_id)
        entries.append({"item_id": item_id, "found": bool(s),
                        "video_id": s["resourceId"]["videoId"] if s else None,
                        "title": s["title"] if s else None,
                        "playlist_id": s["playlistId"] if s else None,
                        "playlist_title": titles.get(s["playlistId"]) if s else None})
    if not args.yes:
        _needs_confirmation("removed", {"items": entries})

    for entry in entries:
        try:
            api_request("DELETE", _api_url("playlistItems", {"id": entry["item_id"]}), tokens)
        except ApiError as e:
            _abort({"items": entries}, e)
        entry["removed"] = True
        print(f"  ✅ Removed item {entry['item_id']}")
    emit({"ok": True, "items": entries})


def cmd_delete(args):
    tokens = load_tokens()

    # Show exactly what goes before anything is deleted
    params = {"part": "snippet,contentDetails,status", "id": args.playlist_id}
    items = api_request("GET", _api_url("playlists", params), tokens).get("items", [])
    pj = _playlist_json(items[0]) if items else {"id": args.playlist_id, "found": False}
    if items:
        p = items[0]
        label = (f"\"{p['snippet']['title']}\" ({p['contentDetails']['itemCount']} videos, "
                 f"{p['status']['privacyStatus']})")
    else:
        label = "unknown playlist (not found, or not visible yet)"
    print(f"{'Deleting' if args.yes else 'Would delete'} playlist {label}  [{args.playlist_id}]")
    if not args.yes:
        _needs_confirmation("deleted", {"playlist": pj})

    api_request("DELETE", _api_url("playlists", {"id": args.playlist_id}), tokens)
    print(f"  ✅ Deleted playlist {args.playlist_id}")
    emit({"ok": True, "deleted": True, "playlist": pj})


def cmd_logout(_args):
    """Revoke the sign-in at Google, then delete the local tokens."""
    if not TOKEN_FILE.exists():
        print("Not signed in; nothing to do.")
        emit({"ok": True, "revoked": False, "tokens_deleted": False, "was_signed_in": False})
        return
    tokens = load_tokens()
    token = tokens.get("refresh_token") or tokens.get("access_token")
    revoked = False
    if token:
        try:
            _post_form(REVOKE_URL, {"token": token})
            print("✅ Revoked the sign-in at Google.")
            revoked = True
        except ApiError as e:
            if e.reason != "invalid_token":
                _fail(f"Could not revoke the sign-in ({e}); {TOKEN_FILE} was kept. Try again, or "
                      "remove the app at https://myaccount.google.com/permissions")
            print("The stored sign-in was already invalid at Google.")
    TOKEN_FILE.unlink(missing_ok=True)
    PENDING_AUTH_FILE.unlink(missing_ok=True)
    print(f"✅ Deleted {TOKEN_FILE}")
    emit({"ok": True, "revoked": revoked, "tokens_deleted": True, "was_signed_in": True})


def cmd_edit(args):
    if args.title is None and args.description is None and args.privacy is None:
        _fail("Nothing to change. Pass --title, --description and/or --privacy.")
    tokens = load_tokens()

    # 1. Fetch current playlist details (title is required for updates).
    #    A playlist created moments ago takes a few seconds to become readable.
    url_get = _api_url("playlists", {"part": "snippet,status", "id": args.playlist_id})
    for attempt in range(4):
        if attempt:
            time.sleep(3)
        data = api_request("GET", url_get, tokens)
        if data.get("items"):
            break
    else:
        _fail(f"Playlist {args.playlist_id} not found.")

    playlist = data["items"][0]
    snippet = playlist["snippet"]
    status = playlist["status"]

    # 2. Update fields locally
    if args.title is not None:
        snippet["title"] = args.title
    if args.description is not None:
        snippet["description"] = args.description
    if args.privacy is not None:
        status["privacyStatus"] = args.privacy

    # 3. An update replaces the whole part, so send back every writable field
    #    (omitted ones are cleared); thumbnails/channelId etc. are read-only
    body = {
        "id": args.playlist_id,
        "snippet": {
            "title": snippet["title"],
            "description": snippet.get("description", ""),
        },
        "status": {"privacyStatus": status["privacyStatus"]},
    }
    for key in ("tags", "defaultLanguage"):
        if snippet.get(key):
            body["snippet"][key] = snippet[key]
    if status.get("podcastStatus"):
        body["status"]["podcastStatus"] = status["podcastStatus"]

    # 4. Send Update
    result = api_request("PUT", _api_url("playlists", {"part": "snippet,status"}), tokens, body)

    print(f"✅ Updated playlist: {result['snippet']['title']}")
    print(f"   Privacy: {result['status']['privacyStatus']}")
    emit({"ok": True, "playlist": _playlist_json(result)})


def cmd_search(args):
    params = {
        "part": "snippet",
        "q": args.query,
        "type": "video",
        "maxResults": args.max,
        "order": args.order,
    }

    if args.duration:
        params["videoDuration"] = args.duration

    if args.hd:
        params["videoDefinition"] = "high"

    if args.channel:
        params["channelId"] = args.channel

    if args.after:
        # Basic validation for RFC 3339 (YYYY-MM-DD or full timestamp)
        val = args.after.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            val += "T00:00:00Z"
        # If it doesn't match YYYY-MM-DD, assume user provided valid RFC 3339 or let API error out
        params["publishedAfter"] = val

    # API key if configured, otherwise the OAuth sign-in (same quota either way)
    cfg = _load_config()
    if cfg["api_key"]:
        url = _api_url("search", dict(params, key=cfg["api_key"]))
        data = _open_json(urllib.request.Request(url))
    elif TOKEN_FILE.exists():
        data = api_request("GET", _api_url("search", params), load_tokens())
    else:
        _fail(code="missing_credentials", message="Search needs an API key (YOUTUBE_API_KEY or api_key in "
              f"{CONFIG_FILE}) or a sign-in (youtube.py auth). See SETUP.md.")

    items = _unescape(data.get("items", []))  # search, unlike playlists, returns HTML-escaped text
    emit([{"id": item["id"].get("videoId"), "video_id": item["id"].get("videoId"),
           "title": item["snippet"].get("title", ""),
           "description": item["snippet"].get("description", ""),
           "channel": item["snippet"].get("channelTitle", ""),
           "channel_id": item["snippet"].get("channelId"),
           "published_at": item["snippet"].get("publishedAt"),
           "url": f"https://youtube.com/watch?v={item['id'].get('videoId')}"} for item in items])
    for item in items:
        s = item["snippet"]
        vid = item["id"].get("videoId", "?")
        print(f"  📺 {s['title']}")
        print(f"     Channel: {s['channelTitle']}  |  {s['publishedAt'][:10]}")
        print(f"     https://youtube.com/watch?v={vid}")
        print()
    if not items:
        print("No results.")


# --- CLI ---

def _int_between(low: int, high: int):
    def parse(value: str) -> int:
        n = int(value)
        if not low <= n <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return n
    return parse


def main():
    # Quiet broken pipe behavior when piping to `head` etc.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    # Keep stdout and stderr in order when both go to one pipe (as agents read them)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    json_opt = argparse.ArgumentParser(add_help=False)
    json_opt.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                          help="Print exactly one JSON document to stdout (text goes to stderr)")
    parser = argparse.ArgumentParser(description="YouTube search and playlist manager",
                                     parents=[json_opt])
    sub = parser.add_subparsers(dest="command")
    subparsers = []
    _add_parser = sub.add_parser

    def add_parser(*a, **kw):
        p = _add_parser(*a, parents=[json_opt], **kw)
        subparsers.append(p)
        return p
    sub.add_parser = add_parser

    p_auth = sub.add_parser("auth", help="Sign in with Google (opens browser)")
    p_auth.add_argument("--code", help="Finish a manual sign-in: the code or the full redirect address")
    p_auth.add_argument("--manual", action="store_true",
                        help="Print the consent URL and exit instead of waiting for the browser")
    p_auth.add_argument("--port", type=_int_between(1, 65535), default=AUTH_CALLBACK_PORT,
                        help=f"Local callback port (default: {AUTH_CALLBACK_PORT})")

    p_create = sub.add_parser("create", help="Create a playlist")
    p_create.add_argument("name", help="Playlist name")
    p_create.add_argument("--privacy", default="private",
                          choices=["public", "unlisted", "private"])
    p_create.add_argument("--description", default="", help="Playlist description")

    sub.add_parser("list", help="List your playlists")

    p_add = sub.add_parser("add", help="Add videos to a playlist")
    p_add.add_argument("playlist_id")
    p_add.add_argument("videos", nargs="+", help="Video URLs or IDs")

    p_vids = sub.add_parser("videos", help="List videos in a playlist")
    p_vids.add_argument("playlist_id")

    p_rm = sub.add_parser("remove", help="Remove videos from a playlist")
    p_rm.add_argument("item_ids", nargs="+", metavar="item_id",
                      help="Playlist item ID(s), as shown by `videos`")
    p_rm.add_argument("--yes", action="store_true",
                      help="Really remove them (without it, only shows what would be removed)")

    p_del = sub.add_parser("delete", help="Delete an entire playlist")
    p_del.add_argument("playlist_id", help="Playlist ID to delete")
    p_del.add_argument("--yes", action="store_true",
                       help="Really delete it (without it, only shows what would be deleted)")

    sub.add_parser("logout", help="Revoke the Google sign-in and delete the stored tokens")

    p_edit = sub.add_parser("edit", help="Edit a playlist (title, description, privacy)")
    p_edit.add_argument("playlist_id")
    p_edit.add_argument("--title")
    p_edit.add_argument("--description")
    p_edit.add_argument("--privacy", choices=["public", "unlisted", "private"])

    p_search = sub.add_parser("search", help="Search YouTube")
    p_search.add_argument("query")
    p_search.add_argument("--max", type=_int_between(1, 50), default=5,
                          help="Max results, 1-50 (default: 5)")
    p_search.add_argument("--order", default="relevance",
                          choices=["relevance", "date", "rating", "title", "videoCount", "viewCount"],
                          help="Sort order (default: relevance)")
    p_search.add_argument("--duration", choices=["any", "long", "medium", "short"],
                          help="Video duration (short <4m, medium 4-20m, long >20m)")
    p_search.add_argument("--hd", action="store_true", help="High definition (HD) only")
    p_search.add_argument("--after", help="Published after (YYYY-MM-DD)")
    p_search.add_argument("--channel", help="Filter by Channel ID")

    global JSON_MODE, _JSON_OUT
    _JSON_OUT = sys.stdout
    if "--json" in sys.argv[1:sys.argv.index("--") if "--" in sys.argv else None]:
        JSON_MODE = True  # set early so argparse usage errors are reported as JSON too
        sys.stdout = sys.stderr
        for p in (parser, *subparsers):  # a bad value for a subcommand option errors in its subparser
            p.error = lambda msg: _fail(msg, "usage", 2)
    args = parser.parse_args()
    JSON_MODE = getattr(args, "json", False) or JSON_MODE
    if JSON_MODE and sys.stdout is _JSON_OUT:
        sys.stdout = sys.stderr
    if not args.command:
        if JSON_MODE:
            _fail("No command given.", "usage", 2)
        parser.print_help()
        return

    cmds = {
        "auth": cmd_auth, "create": cmd_create, "list": cmd_list,
        "add": cmd_add, "videos": cmd_videos, "remove": cmd_remove,
        "delete": cmd_delete, "edit": cmd_edit, "search": cmd_search,
        "logout": cmd_logout,
    }
    try:
        cmds[args.command](args)
        _flush_result()
    except ApiError as e:
        _fail(str(e), e.reason or f"http_{e.status}")
    except (urllib.error.URLError, socket.timeout) as e:
        _fail(f"Network error: {getattr(e, 'reason', e)}", "network_error")
    except OSError as e:  # e.g. a config folder that can't be written; dropped connections have no filename
        if e.filename:
            _fail(f"Cannot use {e.filename}: {e.strerror or e}. Check the config folder "
                  "or set YOUTUBE_SKILL_CONFIG_DIR.", "filesystem_error")
        _fail(f"Network error: {e}", "network_error")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
