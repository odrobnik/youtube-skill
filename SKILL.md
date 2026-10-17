---
name: youtube-playlist-manager
description: "Search YouTube and manage the user's own YouTube playlists via the YouTube Data API v3: list, create, rename and delete playlists, add and remove videos. Use when the user explicitly asks to search YouTube or to view or change their YouTube playlists."
summary: "YouTube search and playlist management via the Data API v3."
version: 1.1.0
homepage: https://github.com/odrobnik/youtube-skill
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
        description: "YouTube Data API v3 key for search (or api_key in ~/.openclaw/youtube/config.json)."
      - name: YOUTUBE_CLIENT_ID
        required: false
        description: "OAuth client ID (Desktop app) for playlist commands (or client_id in config.json)."
      - name: YOUTUBE_CLIENT_SECRET
        required: false
        description: "OAuth client secret for playlist commands (or client_secret in config.json)."
---

# YouTube Playlist Manager

Search YouTube and manage your own playlists through the YouTube Data API v3.

**Entry point:** `{baseDir}/scripts/youtube.py` (Python 3 standard library only)

## When to use

- The user explicitly asks to search YouTube, or to see or change their own YouTube playlists.
- Not for general questions about videos, other video sites, downloading videos, or transcripts.
- `search`, `list` and `videos` only read. `create`, `edit`, `add`, `remove` and `delete` change the user's YouTube account: run them only for a change the user asked for.

## Setup

See [SETUP.md](SETUP.md). Search needs an API key or a sign-in; playlist commands need a one-time Google sign-in.

Credentials are read from `~/.openclaw/youtube/config.json`; the env vars `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` override it. The sign-in is stored in `~/.openclaw/youtube/tokens.json`, readable by the owner only. Never print or share these files.

## Commands

```bash
# Search (uses the API key, or the sign-in if no key is set)
python3 {baseDir}/scripts/youtube.py search "query" [--max 1-50] [--order relevance|date|viewCount|rating|title|videoCount]
python3 {baseDir}/scripts/youtube.py search "query" [--duration short|medium|long] [--hd] [--after YYYY-MM-DD] [--channel CHANNEL_ID]

# Sign in (one-time) and out
python3 {baseDir}/scripts/youtube.py auth                      # opens a browser, waits for the localhost callback
python3 {baseDir}/scripts/youtube.py auth --manual             # prints the consent URL and exits
python3 {baseDir}/scripts/youtube.py auth --code "<redirect address or code>"
python3 {baseDir}/scripts/youtube.py logout                    # revokes the sign-in at Google, deletes tokens.json

# Playlists
python3 {baseDir}/scripts/youtube.py list
python3 {baseDir}/scripts/youtube.py create "Name" [--privacy private|unlisted|public] [--description "..."]
python3 {baseDir}/scripts/youtube.py edit <playlist_id> [--title "..."] [--description "..."] [--privacy private|unlisted|public]
python3 {baseDir}/scripts/youtube.py delete <playlist_id> [--yes]

# Videos in a playlist
python3 {baseDir}/scripts/youtube.py videos <playlist_id>      # shows each entry's Item ID
python3 {baseDir}/scripts/youtube.py add <playlist_id> <video_url_or_id> [more ...]
python3 {baseDir}/scripts/youtube.py remove <playlist_item_id> [more ...] [--yes]
```

## How to use it

- **`delete` and `remove` are permanent and need `--yes`.** Run them without `--yes` first: they list exactly what would go, change nothing, and exit with status 3. Show that list to the user, and only after a clear yes run the same command with `--yes`.
- New playlists are **private** unless the user asks for something else.
- `remove` takes the **Item ID** shown by `videos`, not the video ID.
- `add` accepts watch, `youtu.be`, Shorts, embed and live URLs as well as bare 11-character video IDs.
- Search returns the most relevant matches. Use `--order date` only when the user wants the newest uploads.
- YouTube shows changes after a few seconds. `list` right after a change can still show the old state, and two quick `edit`s of the same playlist can undo each other, so leave about 10 seconds between them.
- **Signing in needs the user.** Run `auth --manual`, send the user the URL, and ask for the address their browser shows afterwards. It starts with `http://127.0.0.1:8923/`, and that page not loading is expected. Then run `auth --code "<that address>"`. On the user's own computer, plain `auth` opens the browser and finishes by itself.
- If a command reports that the sign-in expired or was revoked, sign in again. If that happens every 7 days, point the user to the "Publish app" step in SETUP.md.

## Security and permissions

- **Network:** only Google. `www.googleapis.com` for the YouTube Data API; `accounts.google.com` and `oauth2.googleapis.com` for signing in and out.
- **Files:** reads `~/.openclaw/youtube/config.json`; reads and writes `tokens.json` and, during sign-in, `pending-auth.json` in the same folder, all owner-only. Nothing else on disk.
- **Local:** `auth` opens the browser and listens on `127.0.0.1:8923` for up to 5 minutes. Apart from that, the script starts no other programs and downloads no code.
- **Sign-in lifetime:** the stored sign-in keeps working until it is revoked. `logout` revokes it at Google and deletes `tokens.json`.

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
