# youtube-skill

🎬 Search YouTube and manage your playlists (create, rename, delete, add and remove videos) via the [YouTube Data API v3](https://developers.google.com/youtube/v3). Python 3 standard library only.

An [OpenClaw](https://openclaw.ai) skill, published on ClawHub as `youtube-playlist-manager`.

## Quick Start

```bash
# Search (needs YOUTUBE_API_KEY or ~/.openclaw/youtube/config.json)
python3 scripts/youtube.py search "lego technic review" --max 5

# Sign in once for playlist commands (needs an OAuth Desktop client, see SETUP.md)
python3 scripts/youtube.py auth

python3 scripts/youtube.py create "Weekend viewing"
python3 scripts/youtube.py add <playlist_id> https://youtu.be/<video_id>
python3 scripts/youtube.py videos <playlist_id>
```

See [SKILL.md](SKILL.md) for all commands.

## Documentation

- [SKILL.md](SKILL.md) — agent-facing reference (commands, behavior, limitations)
- [SETUP.md](SETUP.md) — prerequisites, Google Cloud setup, and where credentials are stored
- [ClawHub](https://clawhub.ai/odrobnik/youtube-playlist-manager) — install via ClawHub registry
