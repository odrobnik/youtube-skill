# YouTube Playlist Manager Setup

## Prerequisites

- Python 3.8 or later (standard library only, no pip dependencies)
- A Google Cloud project with the **YouTube Data API v3** enabled

## Where Credentials Live

Nothing is stored inside the skill folder.

| What | Where |
|---|---|
| API key, OAuth client ID and secret | `~/.openclaw/youtube/config.json`, or env vars (env vars win) |
| Sign-in tokens, written by `auth` | `~/.openclaw/youtube/tokens.json` (mode 600) |
| Sign-in in progress, removed when done | `~/.openclaw/youtube/pending-auth.json` (mode 600) |

Create `~/.openclaw/youtube/config.json`:

```json
{
  "api_key": "YOUR_YOUTUBE_API_KEY",
  "client_id": "YOUR_OAUTH_CLIENT_ID",
  "client_secret": "YOUR_OAUTH_CLIENT_SECRET"
}
```

Keep the file private to your account (file mode 600); the script warns when other users can read it.

### Environment Variables

Env vars override config.json values:

| Variable | Needed for | Description |
|---|---|---|
| `YOUTUBE_API_KEY` | Search | YouTube Data API v3 key. Without it, search uses your sign-in. |
| `YOUTUBE_CLIENT_ID` | Playlists | OAuth 2.0 client ID (Desktop app) |
| `YOUTUBE_CLIENT_SECRET` | Playlists | OAuth 2.0 client secret |

In OpenClaw you can also set the API key as `skills.entries.youtube-playlist-manager.apiKey` in `openclaw.json`.

## 1. Enable the API

1. Open <https://console.cloud.google.com/> and create or pick a project.
2. **APIs & Services → Library → YouTube Data API v3 → Enable**.

## 2. API Key (Search)

1. **APIs & Services → Credentials → + Create credentials → API key**.
2. Edit the key and restrict it to **YouTube Data API v3**.
3. Add it to config.json as `api_key`, or export `YOUTUBE_API_KEY`.

## 3. OAuth Client (Playlist Management)

1. Open **Google Auth Platform** (formerly *OAuth consent screen*) and set it up with user type **External**.
2. Under **Audience**, add your Google account as a **test user**. While the app is in *Testing*, only test users can sign in.
3. Still under **Audience**, click **Publish app** to move it to *In production*. Google limits sign-ins to apps in Testing to **7 days**, after which every playlist command fails until you sign in again. An unverified app in production is fine for personal use; you click through the "Google hasn't verified this app" warning once.
4. Under **Clients**, create a client of type **Desktop app** and copy its client ID and secret into config.json (or the env vars).

## 4. Sign In

```bash
python3 scripts/youtube.py auth
```

This opens a browser for Google consent; a short-lived server on `http://127.0.0.1:8923` catches the redirect (pick another port with `--port`). Tokens are saved to `~/.openclaw/youtube/tokens.json` and refresh automatically.

### Headless Machines

```bash
python3 scripts/youtube.py auth --manual
```

Open the printed URL on any device and approve access. The browser then tries to load `http://127.0.0.1:8923/?state=…&code=…`, which fails on another device; that's expected. Copy the whole address and finish with:

```bash
python3 scripts/youtube.py auth --code "http://127.0.0.1:8923/?state=...&code=..."
```

Or forward the port (`ssh -L 8923:127.0.0.1:8923 <host>`) and run plain `auth` on the remote machine.

## Signing Out

```bash
python3 scripts/youtube.py logout
```

This revokes the sign-in at Google and deletes `~/.openclaw/youtube/tokens.json`. You can also remove the app's access at <https://myaccount.google.com/permissions>.
