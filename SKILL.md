---
name: youtube-playlist-manager
description: "Search YouTube and manage your own playlists via the YouTube Data API v3: find videos, create, rename and delete playlists, add and remove videos. Use when asked to find YouTube videos, build or tidy a YouTube playlist, or collect videos to watch."
summary: "YouTube search and playlist management via the Data API v3."
version: 1.0.0
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

## Setup

See [SETUP.md](SETUP.md). Search needs an API key or a sign-in; playlist commands need a one-time Google sign-in.

Credentials are read from `~/.openclaw/youtube/config.json`; the env vars `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` override it. The sign-in is stored in `~/.openclaw/youtube/tokens.json`, readable by the owner only. Never print or share these files.

## Commands

```bash
# Search (uses the API key, or the sign-in if no key is set)
python3 {baseDir}/scripts/youtube.py search "query" [--max 1-50] [--order relevance|date|viewCount|rating|title|videoCount]
python3 {baseDir}/scripts/youtube.py search "query" [--duration short|medium|long] [--hd] [--after YYYY-MM-DD] [--channel CHANNEL_ID]

# Sign in (one-time)
python3 {baseDir}/scripts/youtube.py auth                      # opens a browser, waits for the localhost callback
python3 {baseDir}/scripts/youtube.py auth --manual             # prints the consent URL and exits
python3 {baseDir}/scripts/youtube.py auth --code "<redirect address or code>"

# Playlists
python3 {baseDir}/scripts/youtube.py list
python3 {baseDir}/scripts/youtube.py create "Name" [--privacy private|unlisted|public] [--description "..."]
python3 {baseDir}/scripts/youtube.py edit <playlist_id> [--title "..."] [--description "..."] [--privacy private|unlisted|public]
python3 {baseDir}/scripts/youtube.py delete <playlist_id>

# Videos in a playlist
python3 {baseDir}/scripts/youtube.py videos <playlist_id>      # shows each entry's Item ID
python3 {baseDir}/scripts/youtube.py add <playlist_id> <video_url_or_id> [more ...]
python3 {baseDir}/scripts/youtube.py remove <playlist_item_id> [more ...]
```

## How to use it

- **Ask before `delete` and `remove`.** Both are permanent. Name the playlist or the videos and wait for a clear yes.
- New playlists are **private** unless the user asks for something else.
- `remove` takes the **Item ID** shown by `videos`, not the video ID.
- `add` accepts watch, `youtu.be`, Shorts, embed and live URLs as well as bare 11-character video IDs.
- Search returns the most relevant matches. Use `--order date` only when the user wants the newest uploads.
- YouTube shows changes after a few seconds. `list` right after a change can still show the old state, and two quick `edit`s of the same playlist can undo each other, so leave about 10 seconds between them.
- **Signing in needs the user.** Run `auth --manual`, send the user the URL, and ask for the address their browser shows afterwards. It starts with `http://127.0.0.1:8923/`, and that page not loading is expected. Then run `auth --code "<that address>"`. On the user's own computer, plain `auth` opens the browser and finishes by itself.
- If a command reports that the sign-in expired or was revoked, sign in again. If that happens every 7 days, point the user to the "Publish app" step in SETUP.md.

## Quota

Each Google Cloud project gets 10,000 units a day by default, reset at midnight Pacific time.

| Command | Cost |
|---|---|
| `search` | 100 units (about 100 searches a day) |
| `create`, `edit`, `delete` | 50 units per playlist |
| `add`, `remove` | 50 units per video |
| `list`, `videos` | 1 unit per 50 entries |

## Limits

- **Watch Later** and watch history aren't available through the API (a Google restriction since 2016).
- The sign-in uses Google's `youtube` scope, which allows managing the whole YouTube account. The script itself only reads search results and reads and changes playlists.
- To play a playlist inside a web page or an app, see [references/iframe-player.md](references/iframe-player.md).
