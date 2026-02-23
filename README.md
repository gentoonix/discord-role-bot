# rally-bot-mvc

A Discord bot for coordinating rallies within Voice Channels. It automatically manages member nicknames with alliance tags, syncs channel permissions across categories, and provides a fully interactive settings UI — all configurable per-server without touching a config file.

---

## Features

- **Alliance Tag Nicknames** — Automatically prefixes member nicknames with their alliance tag role (e.g. `[TAG] Username`). Tags are applied/removed in real time as roles change, and on member join.
- **Bulk Nickname Refresh** — Retroactively apply tags to all existing members in one action.
- **Category Permission Sync** — Automatically syncs channel permissions to their parent category whenever a category is updated. Supports manual full-server syncs too.
- **Sync Exclusions** — Exclude specific channels or entire categories from permission syncing.
- **Log Channel** — Route all bot activity (nickname changes, syncs, config changes) to a designated log channel with color-coded embeds.
- **Interactive Settings UI** — All configuration is done through a button/dropdown menu inside Discord via `/role_settings`. No need to edit files or run commands manually.
- **Persistent Storage** — All settings are stored in a local SQLite database and survive restarts.
- **Multi-server** — Fully isolated per-guild configuration.

---

## Prerequisites

- A [Discord Developer Portal](https://discord.com/developers/applications) account with a bot application created
- A Discord Bot Token
- **Privileged Gateway Intents:** `Server Members Intent` must be enabled in the Developer Portal
- Docker (recommended) **or** Python 3.12+

---

## Bot Permissions

When inviting the bot to your server, grant it the following permissions:

- **Manage Nicknames** — required to set alliance tag prefixes
- **Manage Channels** — required for category permission syncing
- **Send Messages** / **Embed Links** — required for the log channel
- **View Channels** — required to see channels for exclusion management

You can generate an invite URL from the [Discord Developer Portal](https://discord.com/developers/applications) under **OAuth2 → URL Generator**. Select `bot` + `applications.commands` scopes, then check the permissions above.

> **Important:** The bot's role must be positioned **above** any roles it needs to manage nicknames for in your server's role list.

---

## Configuration

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

That's the only required configuration. Everything else (staff role, tag roles, log channel, exclusions) is configured interactively inside Discord after the bot starts.

> **Never commit your `.env` file to version control.**

---

## Installation

### Option 1 — Docker (Recommended)

The Dockerfile uses Python 3.12-slim and stores the SQLite database at `/app/data/bot.db`. Mount a volume there to persist data across container restarts.

#### 1. Clone the repository

```bash
git clone https://github.com/gentoonix/rally-bot-mvc.git
cd rally-bot-mvc
```

#### 2. Create your `.env` file

```bash
echo "DISCORD_TOKEN=your_discord_bot_token_here" > .env
```

#### 3. Build the image

```bash
docker build -t rally-bot-mvc .
```

#### 4. Run the container

```bash
docker run -d \
  --name rally-bot \
  --env-file .env \
  -v rally-bot-data:/app/data \
  --restart unless-stopped \
  rally-bot-mvc
```

The `-v rally-bot-data:/app/data` flag mounts a named volume so your SQLite database persists across restarts and rebuilds.

#### Useful Docker commands

```bash
# View live logs
docker logs -f rally-bot

# Stop the bot
docker stop rally-bot

# Restart the bot
docker restart rally-bot

# Remove the container (data volume is preserved)
docker rm -f rally-bot
```

---

### Option 2 — Docker Compose

Create a `docker-compose.yml` in the project root:

```yaml
version: "3.8"

services:
  rally-bot:
    build: .
    container_name: rally-bot
    env_file:
      - .env
    volumes:
      - rally-bot-data:/app/data
    restart: unless-stopped

volumes:
  rally-bot-data:
```

Then start it with:

```bash
docker compose up -d --build
```

---

### Option 3 — Manual (Python 3.12+)

#### 1. Clone the repository

```bash
git clone https://github.com/gentoonix/rally-bot-mvc.git
cd rally-bot-mvc
```

#### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate.bat       # Windows
```

#### 3. Install dependencies

```bash
pip install -r requirements.txt
```

#### 4. Create the data directory and run

```bash
mkdir -p /app/data
python main.py
```

> If you'd prefer the database stored elsewhere, update the `DB_PATH` variable at the top of `main.py`.

---

## First-Time Setup in Discord

Once the bot is running and has joined your server:

1. Run `/role_settings` in any channel (server administrator required for first-time setup).
2. You'll be prompted to set a **Staff Role** — this role gates access to the settings menu going forward.
3. From the settings menu, configure:
   - **Tag Roles** — add the roles that should be used as nickname tag prefixes (e.g. your alliance roles)
   - **Log Channel** — select a text channel for the bot to post activity logs
   - **Excluded Channels / Categories** — opt specific channels or whole categories out of permission syncing
4. Use **Refresh All** to apply tags retroactively to all current members.
5. Use **Sync Categories** to do a full manual permission sync across the server.

---

## Settings Menu Reference

| Button | Description |
|---|---|
| **Staff Role** | Set which role can access `/role_settings` |
| **Tag Roles** | Add or remove roles used as nickname tag prefixes |
| **Log Channel** | Set or clear the channel for bot activity logs |
| **Excluded Channels** | Exclude individual channels or categories from permission sync |
| **Refresh All** | Bulk-update nicknames for all current members |
| **Sync Categories** | Manually sync all category channel permissions server-wide |

---

## Project Structure

```
rally-bot-mvc/
├── main.py             # Bot entry point — all logic, views, and commands
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker build instructions
├── .env                # Your local secrets (not committed)
└── LICENSE
```

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `discord.py` | ≥2.4.0 | Discord API client and slash commands |
| `aiosqlite` | ≥0.20.0 | Async SQLite for per-guild configuration |
| `python-dotenv` | ≥1.0.0 | Load `DISCORD_TOKEN` from `.env` |

---

## Contributing

Pull requests are welcome. For major changes please open an issue first to discuss what you'd like to change.

---

## License

See [LICENSE](LICENSE) for details.
