# Configuration

Three files, all written by `install.sh`, none of them tracked by git:

| File | Contains | Mode |
|---|---|---|
| `.env` (bot folder) | Bot and Caddy **settings**. Docker Compose reads it automatically. Not secret. | 644 |
| `secrets.env` (bot folder) | `DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`. Only the bot container gets these. | 600 |
| `.env` (game server folder) | Game server settings, including the optional game password. | 600 |

After changing a file, apply it with `docker compose up -d` in that folder. Templates with every key are in
`.env.example`, `secrets.env.example` and `valheim/.env.example`.

## Bot settings (`.env`)
| Setting | Meaning |
|---|---|
| `SERVER_NAME` | Shown on the dashboard and pages. Usually the same as the game server's name. |
| `JOIN_ADDRESS` | What players type in Valheim (*Join Game → Add server*), e.g. `203.0.113.7:2456`. |
| `MAX_PLAYERS` | Shown as "Players n/MAX". Valheim's limit is 10. |
| `TZ` | Time zone for log timestamps, e.g. `Europe/Berlin`. |
| `SITE_ADDRESS` | Domain name or public IP that serves the HTTPS return page. |
| `CADDYFILE` | `./caddy/Caddyfile.domain` for a domain, `./caddy/Caddyfile.ip` for a bare IP. |
| `PUBLIC_URL` | `https://<SITE_ADDRESS>`. Discord's redirect URI is `PUBLIC_URL/discord/callback`. |
| `ALLOWED_GUILDS` | Discord server IDs the bot serves, space-separated. Commands, buttons and whitelist links from any other server are refused, so *Manage Server* somewhere else never grants whitelist admin. **Empty = refused everywhere.** |
| `PROTECTED_STEAMIDS` | SteamID64s that are always on the whitelist (the owner), space-separated. |
| `NOTIFY_USER_ID` | Discord user ID that gets admin alert DMs. Empty = no DMs. |
| `VALHEIM_DIR` | The game server's folder (with its compose file and `config/`). |
| `WORLD_NAME` | The game server's world name; the bot reads that world's save for the in-game day. |
| `VALHEIM_HOST` | The game server's container name (`valheim`), probed on UDP 2457. |
| `VALHEIM_NETWORK` | The game server's compose network, `<folder name>_default`, e.g. `valheim_default`. |
| `VALHEIM_GID` | Group that owns the game's files; the bot joins it to write `permittedlist.txt`. |
| `WHITELIST_HOST_FILE` | Optional. Defaults to `VALHEIM_DIR/config/permittedlist.txt`. A development instance must set a dummy file. |
| `COMPOSE_PROFILES` | `https` starts Caddy too. Empty for a development instance. |
| `BOT_CONTAINER`, `CADDY_CONTAINER`, `WEB_NETWORK` | Container and network names; change only for a second instance. |

Tuning constants that rarely need changing (poll interval, alert thresholds, link lifetime) are at the top of
`bot/config.py`.

## Game server settings (`VALHEIM_DIR/.env`)
| Setting | Meaning |
|---|---|
| `SERVER_NAME`, `WORLD_NAME` | As in Valheim. |
| `SERVER_PASS` | Optional. With the whitelist it can stay empty. If set: 5+ characters and not part of the server name. |
| `SERVER_PUBLIC` | `false` = not listed in the in-game browser; players join by address. |
| `SERVER_ARGS` | Extra arguments, e.g. `-preset normal -modifier raids none` (world presets and modifiers). |
| `VALHEIM_UID`, `VALHEIM_GID` | The unprivileged host user the game runs as. |
| `VALHEIM_MEM_LIMIT` | Memory cap for the game container (default `3200m`). |

The game image has many more options (backups, update schedule, mods): see its
[documentation](https://github.com/community-valheim-tools/valheim-server-docker#environment-variables).

### World seed
Valheim's dedicated server has no seed option: a new world gets a random seed. To play on a chosen seed, create
the world in the game (*Start Game → New world*, with your seed), start it once, then copy its files from your PC
(`%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\worlds_local\`) to `VALHEIM_DIR/config/worlds_local/` on the
server, while the server is stopped. Set `WORLD_NAME` to that world's name. The game image's documentation covers
this too.

## HTTPS: domain or bare IP
Discord sends players back to `PUBLIC_URL/discord/callback` after they log in, so that page needs HTTPS.
Caddy handles the certificate. Only port 443 is used (TLS-ALPN validation); port 80 can stay closed.
- **Domain (recommended):** point an A record at the server, set `SITE_ADDRESS` to the name and `CADDYFILE` to
  `./caddy/Caddyfile.domain`.
- **Bare IP:** set `SITE_ADDRESS` to the public IP and `CADDYFILE` to `./caddy/Caddyfile.ip`. Let's Encrypt
  issues IP certificates only as 6-day certificates, which Caddy renews on its own.

Only `/discord/*` is forwarded to the bot; everything else answers 404. Extra routes can go in
`caddy/extra/*.caddy` (see `dev.caddy.example`).

## Using an existing game server
If `VALHEIM_DIR` already contains a compose file, `install.sh` leaves it alone and checks that it has what the
bot needs. Copy the lines marked `bot:` from `valheim/compose.yaml`:

1. **`CONFIG_FILE_PERMISSIONS: "664"`**: the bot writes `config/permittedlist.txt` through the file's group, and
   the image resets permissions on `/config/*.txt` at every start.
2. **The log filter** `VALHEIM_LOG_FILTER_REGEXP_DiscordBot` with its `ON_…` hook: it copies join/leave/death,
   start and version lines, and the game's refusal messages, to `config/bot/events.log` with a timestamp.
3. **`PUID`/`PGID`** of an unprivileged user, whose group is `VALHEIM_GID`.

Then create `config/bot/` owned by that user, recreate the game server **while nobody is online**, and check
that `permittedlist.txt` is group-writable and not empty.
