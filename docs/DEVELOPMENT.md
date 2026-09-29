# Development

## Code map
| Path | Purpose |
|---|---|
| `bot/main.py` | Entry point: the Discord client, the 30 s poll, the hourly member check, admin DMs. |
| `bot/config.py` | All settings (`Config.from_env()`) and tuning constants. |
| `bot/commands.py` | Slash commands; `ManageServerGroup` checks *Manage Server* at run time for every admin subcommand. |
| `bot/views.py` | Dashboard buttons, leave confirmation, the allowed-server check, error replies, `BotInteraction`. |
| `bot/embeds.py` | Everything the bot says: fixed texts, status/leaderboard/player embeds, admin lists. |
| `bot/store.py` | Events log parser, sessions, deaths, failed joins, bot state (SQLite). |
| `bot/whitelist.py` | Whitelist entries, audit history, writing `permittedlist.txt`. |
| `bot/web.py` | The OAuth return page and its one-time link tokens. |
| `bot/server.py`, `bot/a2s.py` | What the bot knows about the game server; the UDP/A2S probe. |
| `bot/world.py` | In-game day from the world save header. |
| `bot/alerts.py`, `bot/orphans.py` | Admin alert conditions; whitelist entries from servers the bot can't serve. |
| `bot/motd.py` | The message of the day. |
| `tests/` | pytest suite (no network: Discord is faked). |
| `install.sh`, `host/`, `valheim/`, `caddy/` | Installer, host scripts and units, game server and HTTPS templates. |

## Checks
Nothing needs installing on the host; everything runs in a throwaway container:
```bash
./check.sh                  # ruff + pytest
```
One test, with the same container:
```bash
docker run --rm -v "$PWD":/src:ro -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.13-slim sh -c \
  'pip install -q --root-user-action=ignore -r requirements.txt pytest >/dev/null && python -m pytest -q -p no:cacheprovider tests/test_web.py'
```
CI (GitHub Actions, `.github/workflows/ci.yml`) runs ruff, pytest, shellcheck and a check that the compose files
resolve, on every push and pull request. To run shellcheck locally:
`docker run --rm -v "$PWD":/mnt:ro -w /mnt koalaman/shellcheck:stable -x install.sh check.sh host/bin/valheim-monthly-update`

Type checking works too; `bot/` has no `__init__.py`, so tell mypy the layout:
`mypy --explicit-package-bases bot`.

## Rules that must not break
- **Never leave `permittedlist.txt` empty.** Empty means "everyone may join". `Whitelist.write_file()` writes the
  placeholder `0`, and protected IDs are always written.
- **Never rename** the dashboard buttons' `custom_id`s (`wl:join`, `wl:leave`, `wl:me`, `st:top`, `st:me`) or the
  values of `StateKey`, `JoinProblem`, `AuditAction` and `Alert`: posted messages and database rows depend on them.
  Tests guard the button IDs.
- **Admin subcommands go in `ManageServerGroup`** (`/whitelist-admin`), which checks *Manage Server* when they run.
- **The client never pings** (`AllowedMentions.none()`), because replies can echo user input.
- **Parse the game log by its exact wording**, taken from the game's own code, not by guessing.
- Wrap the body of every `discord.ext.tasks` loop in `try/except`: an unhandled exception stops the loop for good.

## A development instance next to production
A second bot, with its own Discord application, database and container, running the `dev` branch on the same
machine. It reads the game's log and world save like production, but **never writes the real whitelist file**.

1. **Discord:** create a second application (see [INSTALL.md](INSTALL.md#2-create-the-discord-application)),
   invite it only to a test Discord server, and add the redirect `https://<SITE_ADDRESS>/dev/discord/callback`.
2. **Checkout:**
   ```bash
   git clone -b dev https://github.com/gacoperz/valheim-discord-whitelist.git /opt/valheim-bot-dev
   cd /opt/valheim-bot-dev
   cp .env.example .env && cp secrets.env.example secrets.env && chmod 600 secrets.env
   cp motd/motd.example.md motd/motd.md
   install -m 664 -g <VALHEIM_GID> /dev/null dev-permittedlist.txt
   install -d -m 700 -o 10001 -g 10001 data
   ```
3. **`.env`**: copy production's values, then change these:
   ```
   COMPOSE_FILE=compose.yaml:compose.dev.yaml
   COMPOSE_PROFILES=
   BOT_CONTAINER=valheim-bot-dev
   WHITELIST_HOST_FILE=/opt/valheim-bot-dev/dev-permittedlist.txt
   PUBLIC_URL=https://<SITE_ADDRESS>/dev
   ALLOWED_GUILDS=<your test Discord server>
   NOTIFY_USER_ID=
   ```
   `compose.dev.yaml` refuses to start without `WHITELIST_HOST_FILE`. `NOTIFY_USER_ID` stays empty so you don't
   get every alert twice. Put the dev application's token and secret in `secrets.env`.
4. **Route it:** in production, `cp caddy/extra/dev.caddy.example caddy/extra/dev.caddy` and
   `docker compose restart caddy`.
5. `docker compose up -d --build` in the dev folder.

## Branches and releases
- **`dev`**: day-to-day work, deployed to the development instance.
- **`main`**: released code only. Changes arrive by pull request from `dev` (or a feature branch), and CI must pass.
- **Releases** are tags on `main`: `vMAJOR.MINOR.PATCH`, with notes on anything an admin has to do.
  Production checks out a tag (see [OPERATIONS.md](OPERATIONS.md#updating)).

For changes that touch stored data, compare the old and new code on a **copy** of a real `data/bot.db` before
releasing: unit tests don't prove the behaviour on real data is unchanged.
