# youtube-skill

🎬 Search YouTube and manage your playlists (create, rename, delete, add and remove videos) via the [YouTube Data API v3](https://developers.google.com/youtube/v3). Search works with just an API key; managing playlists needs a one-time Google OAuth sign-in. Python 3 standard library only.

An agent skill for [OpenClaw](https://openclaw.ai) (published on ClawHub as `youtube-playlist-manager`), Claude Code, Codex and other agents that read `SKILL.md`.

## Install

Name the folder `youtube-playlist-manager`, the skill's `name`:

```bash
openclaw skills install @odrobnik/youtube-playlist-manager                               # OpenClaw
git clone https://github.com/odrobnik/youtube-skill ~/.claude/skills/youtube-playlist-manager  # Claude Code
git clone https://github.com/odrobnik/youtube-skill ~/.agents/skills/youtube-playlist-manager  # Codex
```

Then set up Google credentials as described in [SETUP.md](SETUP.md); [.env.example](.env.example) lists the environment variables.

## Quick Start

```bash
# Search (needs YOUTUBE_API_KEY, or config.json in ~/.openclaw/youtube/ or $YOUTUBE_SKILL_CONFIG_DIR)
python3 scripts/youtube.py search "lego technic review" --max 5

# Sign in once for playlist commands (needs an OAuth Desktop client, see SETUP.md)
python3 scripts/youtube.py auth

python3 scripts/youtube.py create "Weekend viewing"
python3 scripts/youtube.py add PLAYLIST_ID https://youtu.be/VIDEO_ID
python3 scripts/youtube.py videos PLAYLIST_ID
python3 scripts/youtube.py --json list | jq -r '.[].title'   # --json on any command: one JSON document on stdout
```

See [SKILL.md](SKILL.md) for all commands.

## Documentation

- [SKILL.md](SKILL.md) — agent-facing reference (commands, behavior, limitations)
- [SETUP.md](SETUP.md) — prerequisites, Google Cloud setup, and where credentials are stored
- [ClawHub](https://clawhub.ai/odrobnik/youtube-playlist-manager) — install via ClawHub registry
