# Installing

This sets up three things on one machine: the Valheim dedicated server
(the `lloesche/valheim-server` image, see [Credits](../README.md#credits)), the bot, and
[Caddy](https://caddyserver.com) for the HTTPS page Discord's login returns to.

## 1. Requirements
- **A Debian or Ubuntu server, x86_64**, with root access. Valheim wants **about 4 GB RAM** (the installer
  offers swap on smaller machines) and 2+ CPU cores; the bot and Caddy add about 60 MB.
- **Ports reachable from the internet:** `2456-2457/udp` (the game) and `443/tcp` (HTTPS). Port 80 isn't
  needed: certificates are validated on 443.
- **A domain name pointing at the server, or its public IP address.** With a domain, Caddy gets a normal
  Let's Encrypt certificate. With only an IP, it gets a Let's Encrypt IP certificate (6-day certificates,
  renewed automatically).
- **A Discord server** where you have *Manage Server*.
- Docker is installed by the installer if it's missing (from Docker's official repository).

## 2. Create the Discord application
In the [Discord Developer Portal](https://discord.com/developers/applications):

1. **New Application**, and give it a name (this becomes the bot's name).
2. **Bot** page:
   - **Reset Token** and copy it: this is `DISCORD_TOKEN`. Keep it secret.
   - Turn on **Server Members Intent** (under *Privileged Gateway Intents*). Without it, people who leave your
     Discord are removed from the whitelist only by an hourly check.
   - Turn off **Public Bot**, so only you can invite it.
3. **OAuth2** page:
   - Copy the **Client Secret** (reset it if needed): this is `DISCORD_CLIENT_SECRET`.
   - Under **Redirects**, add `https://<your domain or IP>/discord/callback`. It must match exactly.
4. **Installation** page: turn off **User Install** (the bot only works inside servers).

### IDs you'll need
Turn on *Developer Mode* in Discord (*User Settings → Advanced*). Then:
- **Server ID** (`ALLOWED_GUILDS`): right-click your server icon → *Copy Server ID*.
- **Your user ID** (`NOTIFY_USER_ID`, for admin alert DMs): right-click your name → *Copy User ID*.
- **Your SteamID64** (`PROTECTED_STEAMIDS`, so you can never lock yourself out): on your Steam profile page,
  the number in `steamcommunity.com/profiles/7656119…`, or look up a custom URL on a site such as steamid.io.

## 3. Run the installer
```bash
git clone https://github.com/gacoperz/valheim-discord-whitelist.git /opt/valheim-bot
cd /opt/valheim-bot
sudo ./install.sh --dry-run   # optional: see what it would do
sudo ./install.sh
```
It asks for each setting, with a sensible default in brackets. What it does, in order:

1. Checks the OS, CPU architecture and memory.
2. Installs Docker if it's missing (asks first).
3. Asks for the settings: server name, world name, optional game password, time zone, the HTTPS address, the
   join address, and the Discord values from step 2. Secrets are typed without echo.
4. Game server: creates the unprivileged `valheim` user and `/opt/valheim` with the prepared compose file,
   the events log and a non-empty whitelist file. **If `/opt/valheim` already has a compose file, it is left
   untouched**; the installer only checks that it has what the bot needs (see
   [CONFIGURATION.md](CONFIGURATION.md#using-an-existing-game-server)).
5. Bot: writes `.env` (settings), `secrets.env` (mode 600) and `motd/motd.md`.
6. Optional host setup, each asked separately:
   - a 4 GB swapfile (on machines under 6 GB RAM without swap);
   - **firewall:** ufw allowing only your SSH port, `2456-2457/udp` and `443/tcp`, plus a guard that stops
     Docker's published ports from bypassing ufw. SSH is allowed *before* ufw is enabled, so you keep your
     session;
   - **fail2ban** for SSH, never banning the address you're connected from;
   - **timers:** a daily database snapshot and a monthly image refresh.

   The installer never changes your SSH configuration.
7. Starts the game server and the bot, waits for the bot to report healthy, and prints the remaining steps.

The first start downloads the game (about 2 GB) and generates the world, which takes 10 minutes or more.
Until then the dashboard shows the server as offline.

### Running it again
Re-running is safe: settings you already have are kept (and offered as defaults with `--reconfigure`), and
existing files aren't overwritten. Use `--no-start` to write the configuration without starting anything.

### Unattended install
`--answers FILE` takes the answers from a file of `KEY=value` lines instead of asking. The keys are the setting
names in [CONFIGURATION.md](CONFIGURATION.md), plus `DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`, `VALHEIM_DIR`,
`SERVER_PASS`, `SERVER_ARGS`, and `yes`/`no` for `INSTALL_DOCKER`, `SETUP_SWAP`, `SETUP_FIREWALL`,
`SETUP_FAIL2BAN`, `SETUP_TIMERS` and `FAIL2BAN_IGNOREIP`. The file contains your secrets: delete it afterwards.

## 4. Finish in Discord
1. Check the redirect URI from step 2 matches what the installer printed: `https://<address>/discord/callback`.
2. Invite the bot with the link the installer printed (scopes `bot` and `applications.commands`; permissions
   View Channel, Send Messages, Embed Links, Read Message History).
3. In the channel your players should use, run **`/setup-dashboard`** and pin the message.
4. Try it: click **✅ Join whitelist** yourself. If slash commands don't show up, press Ctrl+R in Discord.

## 5. Check it works
```bash
docker ps                                                  # valheim, valheim-bot (healthy), valheim-bot-caddy
docker compose --project-directory /opt/valheim-bot logs bot   # "logged in as ..."
cat /opt/valheim/config/permittedlist.txt                  # never empty
```
Then join the game with the address on the dashboard. Next: [OPERATIONS.md](OPERATIONS.md).
