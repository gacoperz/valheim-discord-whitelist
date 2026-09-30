# Operations

```bash
cd /opt/valheim-bot
docker compose ps                  # bot (should say "healthy") and caddy
docker compose logs -f bot         # logins, whitelist changes ("whitelist "), errors
docker compose logs -f caddy       # HTTPS and certificates
docker compose up -d               # apply a changed .env or secrets.env
```
The game server lives in its own folder: `docker compose --project-directory /opt/valheim logs -f`.

## Updating
- **The game** updates itself when nobody is online (the image's `UPDATE_IF_IDLE`), and restarts daily at
  05:10 (server time) when empty.
- **Images** (game server, Caddy, the bot's Python base and packages) are refreshed monthly by
  `valheim-monthly-update.timer`, if you enabled the timers. The game container is only recreated when its
  image changed **and** nobody is online. Log: `journalctl -u valheim-monthly-update`.
- **The bot** follows releases. To update:
  ```bash
  cd /opt/valheim-bot
  git fetch --tags && git checkout v1.2.0        # the release you want; see the release notes
  docker compose up -d --build
  ```
  Your `.env`, `secrets.env`, `motd/motd.md` and `data/` are not tracked, so updates don't touch them. Roll back
  by checking out the previous tag and running the same command.

## Backups
- **Bot database** (`data/bot.db`: whitelist, stats, history): `valheim-botdb-snapshot.timer` saves a checked
  snapshot daily at 03:30 UTC to `/root/backups/bot-db` and keeps 14 days (`/etc/default/valheim-discord-whitelist`).
  `permittedlist.txt` is rebuilt from it. To restore:
  ```bash
  docker compose stop bot
  cp /root/backups/bot-db/bot-<time>.db data/bot.db && chown 10001:10001 data/bot.db && chmod 600 data/bot.db
  docker compose start bot
  ```
- **The world:** the game image backs it up hourly to `VALHEIM_DIR/config/backups` and keeps 3 days.
- **Your configuration:** `.env`, `secrets.env`, `motd/motd.md`, `caddy/extra/`. Keep a copy somewhere safe;
  `secrets.env` only where secrets belong.

Everything above stays on the server. Copy backups off it if you want them to survive losing the machine.

## Admin alerts
The bot DMs `NOTIFY_USER_ID` once when one of these problems starts, and once when it clears. Nothing is posted
in a channel.

| Alert | When | Usual cause |
|---|---|---|
| 🔴 Server offline | The game server hasn't answered for 10 minutes (restarts and updates take under a minute). | A crash, or the container is stopped. |
| ⚠️ Can't write `permittedlist.txt` | A whitelist change couldn't be written. The bot retries every 30 s. | File permissions (see below). |
| ⚠️ Events log stale | The server is up, but no "server started" line reached `events.log` for 50 h, although it restarts daily when empty. | The log filter in the game compose is broken, so sessions and stats aren't recorded. |

## Health
`docker ps` shows the bot as *healthy* while its 30-second poll works. *Unhealthy* means no successful poll for
150 s, so the dashboard and session tracking are stuck: look for `poll failed` in the log, then
`docker compose restart bot`.

## Troubleshooting
| Symptom | Check |
|---|---|
| Discord says **"Invalid redirect_uri"** | The portal redirect must be exactly `PUBLIC_URL/discord/callback`. |
| Page says **"No Steam account linked"** | The player must add Steam under Discord *Connections*, and it must be verified. |
| A linked player is still refused | `/whitelist-admin attempts` and their **ℹ️ Whitelist status**. Then `cat VALHEIM_DIR/config/permittedlist.txt`. Valheim should reload the file on change; if not, restart the game server while it's empty. |
| Bot log: **`cannot write /whitelist/permittedlist.txt`** | `ls -l VALHEIM_DIR/config/permittedlist.txt` should be `-rw-rw-r-- valheim valheim`, and the game compose must keep `CONFIG_FILE_PERMISSIONS: "664"`. |
| Status shows **offline** while the game runs | The bot must be on the game's network (`VALHEIM_NETWORK`), and `VALHEIM_HOST` must be the game container's name. |
| Slash commands missing | Press Ctrl+R in Discord. Global command changes can take a few minutes to reach every client. |
| HTTPS or certificate errors | `docker compose logs caddy`. Port 443/tcp must be reachable; with a domain, its DNS must point at the server. |
| Nobody appears as online after a restart | Normal until the next join: sessions come from the game log, which only records new events. |

## How it works
```
Game server (VALHEIM_DIR)                                   Bot (this folder)
  log hook ──► config/bot/events.log ────(read-only)──────►  players, sessions, deaths, failed joins, version
  config/worlds_local/<world>/*.db2 ─────(read-only)──────►  in-game day
  UDP 2457 ◄──────────── liveness probe ──────────────────  online / offline
  config/permittedlist.txt ◄───(its only writable file)───  whitelist
                                                               ▲
Internet ──443/tcp──► Caddy ───────────────────────────────────┘  /discord/callback (Discord login)
```
- **Events:** the game compose's log filter copies join/leave/death, start and version lines, and the game's
  refusal messages, to `events.log`. The bot reads only what's new since its last read (at most 8 MiB per poll, and a line it can't
  process is logged and skipped). The file only grows, about a few KB a day; the bot never rotates it (it is
  mounted read-only), and if you truncate or replace it the bot starts again from the top.
- **Online/offline:** an unlisted server doesn't answer Steam (A2S) queries, so the bot sends a UDP probe to
  port 2457: no reply means listening (online); "port unreachable" means down.
- **In-game day:** the world time in the latest save, plus the time players were online since.
- **Whitelist linking:** Discord OAuth2 with the scopes `identify` and `connections`. The bot checks that the same
  Discord user started the link (a one-time, 10-minute token), that they're a member of an allowed server, and
  that their Steam connection is **verified**. It revokes the access token right away.
- **Storage:** SQLite in `data/bot.db`.
