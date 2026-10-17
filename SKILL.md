---
name: youtube-playlist-manager
description: "Search YouTube and manage the user's own YouTube playlists via the YouTube Data API v3. Search works with just an API key, without signing in. Managing playlists needs a one-time Google OAuth sign-in in the browser: list playlists and the videos in them, create, edit (title, description, privacy) and delete playlists, add and remove videos. The sign-in is stored locally (by default in ~/.openclaw/youtube/), refreshed automatically, and revoked by logout. Every command can also print JSON (--json) for scripts. Use when the user explicitly asks to search YouTube or to view or change their YouTube playlists."
summary: "YouTube search (API key) and playlist management (Google OAuth sign-in) via the Data API v3."
version: 1.2.0
homepage: https://github.com/odrobnik/youtube-skill
compatibility: "Python 3.8+ (standard library only) and network access to Google APIs. Works in OpenClaw, Claude Code, Codex and other agents that read SKILL.md."
permissions:
  - "network: Google only (www.googleapis.com, accounts.google.com, oauth2.googleapis.com), plus the local sign-in callback on 127.0.0.1 (port 8923 by default, or the one passed to auth --port)"
  - "file_read: config.json, tokens.json and pending-auth.json in the skill's config folder (~/.openclaw/youtube/ by default, or YOUTUBE_SKILL_CONFIG_DIR, or OPENCLAW_STATE_DIR/youtube)"
  - "file_write: tokens.json and pending-auth.json in that config folder (owner-only)"
  - "env: YOUTUBE_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_SKILL_CONFIG_DIR, OPENCLAW_STATE_DIR"
metadata:
  openclaw:
    emoji: "🎬"
    homepage: https://github.com/odrobnik/youtube-skill
    requires:
      bins: ["python3"]
    primaryEnv: YOUTUBE_API_KEY
    envVars:
      - name: YOUTUBE_API_KEY
        required: false
        description: "YouTube Data API v3 key for search (or api_key in config.json)."
      - name: YOUTUBE_CLIENT_ID
        required: false
        description: "OAuth client ID (Desktop app) for playlist commands (or client_id in config.json)."
      - name: YOUTUBE_CLIENT_SECRET
        required: false
        description: "OAuth client secret for playlist commands (or client_secret in config.json)."
      - name: YOUTUBE_SKILL_CONFIG_DIR
        required: false
        description: "Folder for config.json and the stored sign-in (default ~/.openclaw/youtube/)."
      - name: OPENCLAW_STATE_DIR
        required: false
        description: "OpenClaw's state folder; when set, the default config folder is OPENCLAW_STATE_DIR/youtube."
---

# YouTube Playlist Manager

Search YouTube and manage your own playlists through the YouTube Data API v3.

**Entry point:** `scripts/youtube.py` in this skill's folder (Python 3 standard library only)

Paths in this file are relative to the skill's folder, the one that contains this SKILL.md. Run the script by its full path, for example `python3 /path/to/youtube-playlist-manager/scripts/youtube.py list`, or from inside that folder. OpenClaw's docs call this folder `{baseDir}`; Claude Code also provides it as `${CLAUDE_SKILL_DIR}`.

## When to use

- The user explicitly asks to search YouTube, or to see or change their own YouTube playlists.
- Not for general questions about videos, other video sites, downloading videos, or transcripts.
- `search`, `list` and `videos` only read. `create`, `edit`, `add`, `remove` and `delete` change the user's YouTube account: run them only for a change the user asked for.

## Setup

See [SETUP.md](SETUP.md). Search works with just an API key, without signing in. Everything that touches the user's playlists (`list`, `videos`, `create`, `edit`, `delete`, `add`, `remove`) needs a one-time Google OAuth sign-in with `auth`.

Credentials are read from `config.json` in the config folder: `~/.openclaw/youtube/` by default, `$OPENCLAW_STATE_DIR/youtube` when OpenClaw's state folder is moved, or any folder named by `YOUTUBE_SKILL_CONFIG_DIR`. The env vars `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` override it. The sign-in is stored in `tokens.json` in the same folder, readable by the owner only. Never print or share these files.

## Commands

```bash
# Search (uses the API key, or the sign-in if no key is set)
python3 scripts/youtube.py search "query" [--max 1-50] [--order relevance|date|viewCount|rating|title|videoCount]
python3 scripts/youtube.py search "query" [--duration short|medium|long] [--hd] [--after YYYY-MM-DD] [--channel CHANNEL_ID]

# Sign in (one-time) and out
python3 scripts/youtube.py auth                      # opens a browser, waits for the localhost callback
python3 scripts/youtube.py auth --manual             # prints the consent URL and exits
python3 scripts/youtube.py auth --code "<redirect address or code>"
python3 scripts/youtube.py logout                    # revokes the sign-in at Google, deletes tokens.json

# Playlists
python3 scripts/youtube.py list
python3 scripts/youtube.py create "Name" [--privacy private|unlisted|public] [--description "..."]
python3 scripts/youtube.py edit <playlist_id> [--title "..."] [--description "..."] [--privacy private|unlisted|public]
python3 scripts/youtube.py delete <playlist_id> [--yes]

# Videos in a playlist
python3 scripts/youtube.py videos <playlist_id>      # shows each entry's Item ID
python3 scripts/youtube.py add <playlist_id> <video_url_or_id> [more ...]
python3 scripts/youtube.py remove <playlist_item_id> [more ...] [--yes]
```

## JSON output (`--json`)

Add `--json` before or after the subcommand (`youtube.py --json list` = `youtube.py list --json`) to get machine-readable output:

- **stdout carries exactly one JSON document**, also for errors. Human-readable text, emoji and warnings go to stderr (discard with `2>/dev/null`).
- Pretty-printed (indent 2) when stdout is a terminal, compact one-line JSON when piped. UTF-8, not ASCII-escaped. Search results arrive HTML-escaped from YouTube; their entities (`&amp;`, `&#39;`) are decoded, in text and JSON mode. Playlist data is passed through unchanged.
- **Errors:** `{"error": {"message": "...", "code": "..."}}` on stdout, non-zero exit (1 = failure, 2 = usage, including bad option values). `code` is the API reason (e.g. `playlistNotFound`, `invalid`), or `not_signed_in`, `missing_credentials`, `missing_oauth_client`, `network_error`, `usage`.
- If `add` or `remove` stops part-way on a playlist-level error, the JSON still lists what was already done, with `"ok": false` and an `error` object.

| Command | JSON shape |
|---|---|
| `search` | `[{id, video_id, title, description, channel, channel_id, published_at, url}]` |
| `list` | `[{id, title, description, privacy, item_count, channel, channel_id, published_at, url}]` |
| `videos` | `[{item_id, video_id, position, title, description, channel, channel_id, published_at, playlist_id, url}]` |
| `create`, `edit` | `{ok, playlist: {...same as list...}}` |
| `add` | `{ok, playlist_id, results: [{input, ok, video_id, item_id?, title?, url?, error?}]}` (exit 1 if any failed) |
| `remove` | `{ok, items: [{item_id, found, video_id, title, playlist_id, playlist_title, removed?}]}` |
| `delete` | `{ok, deleted, playlist: {...}}` |
| `remove`/`delete` without `--yes` | the preview plus `"ok": false, "needs_confirmation": true, "dry_run": true`, exit 3 |
| `auth --manual` | `{ok, auth_url, redirect_uri, next}`; `auth --code` / `auth`: `{ok, token_file, has_refresh_token, refresh_token_expires_in}` |
| `logout` | `{ok, revoked, tokens_deleted, was_signed_in}` |

```bash
python3 scripts/youtube.py --json search "lego technic" --max 3 | jq -r '.[] | "\(.title)\t\(.url)"'
python3 scripts/youtube.py list --json | jq -r '.[] | select(.privacy == "private") | .id'
python3 scripts/youtube.py videos <playlist_id> --json | jq -r '.[].item_id'
```

## How to use it

- **`delete` and `remove` are permanent and need `--yes`.** Run them without `--yes` first: they list exactly what would go, change nothing, and exit with status 3. Show that list to the user, and only after a clear yes run the same command with `--yes`.
- New playlists are **private** unless the user asks for something else.
- `remove` takes the **Item ID** shown by `videos`, not the video ID.
- `add` accepts watch, `youtu.be`, Shorts, embed and live URLs as well as bare 11-character video IDs.
- Search returns the most relevant matches. Use `--order date` only when the user wants the newest uploads.
- YouTube shows changes after a few seconds. `list` right after a change can still show the old state, and two quick `edit`s of the same playlist can undo each other, so leave about 10 seconds between them.
- **Signing in needs the user.** In cloud, container or other headless sessions always use `auth --manual`: send the user the URL and ask for the address their browser shows afterwards. It starts with `http://127.0.0.1:8923/` (or the port passed with `--port`), and that page not loading is expected. Then run `auth --code "<that address>"`. On the user's own computer, plain `auth` opens the browser and finishes by itself.
- If a command reports that the sign-in expired or was revoked, sign in again. If that happens every 7 days, point the user to the "Publish app" step in SETUP.md.

## Security and permissions

- **Network:** only Google. `www.googleapis.com` for the YouTube Data API; `accounts.google.com` and `oauth2.googleapis.com` for signing in and out.
- **Files:** reads `config.json` from the config folder (default `~/.openclaw/youtube/`); reads and writes `tokens.json` and, during sign-in, `pending-auth.json` there, all owner-only. Nothing else on disk.
- **Local:** `auth` opens the browser and listens on `127.0.0.1` for up to 5 minutes, on port 8923 unless `--port` picks another. Apart from that, the script starts no other programs and downloads no code.
- **Sign-in lifetime:** the stored sign-in keeps working until it is revoked. `logout` revokes it at Google and deletes `tokens.json`.
- **Declared scope:** the `permissions` list in the frontmatter states this same scope for reviewers and scanners. Hosts don't enforce it; it describes what the script does.

## Quota

Each Google Cloud project gets 10,000 units a day by default, reset at midnight Pacific time.

| Command | Cost |
|---|---|
| `search` | 100 units (about 100 searches a day) |
| `create`, `edit`, `delete` | 50 units per playlist |
| `add`, `remove` | 50 units per video |
| `list`, `videos`, previews | 1 unit per 50 entries |

## Limits

- **Watch Later** and watch history aren't available through the API (a Google restriction since 2016).
- The sign-in uses Google's `youtube` scope, which allows managing the whole YouTube account. The script itself only reads search results and reads and changes playlists.
- To play a playlist inside a web page or an app, see [references/iframe-player.md](references/iframe-player.md).
