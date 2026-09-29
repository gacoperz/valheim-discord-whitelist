# valheim-discord-whitelist

A Discord bot for a **Valheim dedicated server** that shows live server status and lets your Discord members
**whitelist themselves** with their verified Steam account. No game password to share, and no admin copying
Steam IDs around.

- **Live dashboard** in a Discord channel: online/offline, who's playing and for how long, in-game day, last
  save, version, a message of the day, and how to join.
- **Self-service whitelist:** members click *Join whitelist*, log in with Discord, and the bot reads their
  **verified Steam connection**. Leaving the Discord removes them again.
- **Stats:** playtime, sessions and deaths per character, a leaderboard, and "My stats".
- **Help for people who can't join:** the bot reads the game's refusal messages and tells the player why
  (wrong game version, not whitelisted yet, probably playing on another Steam account).
- **Admin tools:** list, add by SteamID64, remove, change history, failed joins; private DM alerts when the
  server is down or something breaks.
- **Hardened by default:** unprivileged read-only container, the game's whitelist file is the only thing it
  writes, and admin commands are checked at run time.

It works with [lloesche/valheim-server](https://github.com/lloesche/valheim-server-docker) and runs on one
Debian or Ubuntu machine with Docker. `install.sh` sets up the game server, the bot and HTTPS, and can harden
the host (firewall, fail2ban, backups).

## Quick start
```bash
git clone https://github.com/gacoperz/valheim-discord-whitelist.git /opt/valheim-bot
cd /opt/valheim-bot
sudo ./install.sh
```
Before you run it, create a Discord application and have a domain name or a public IP ready.
**[docs/INSTALL.md](docs/INSTALL.md)** walks through everything, including the Discord Developer Portal.

| Document | What's in it |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Requirements, creating the Discord application, running the installer, first setup in Discord |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting, HTTPS with a domain or a bare IP, adapting an existing game server |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Updates, backups and restore, admin alerts, troubleshooting, how it works |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Code map, tests, a development instance next to production, branches and releases |
| [SECURITY.md](SECURITY.md) | Security design and how to report a problem |
| [PRIVACY.md](PRIVACY.md) | What data the bot stores, for how long, and how to delete someone's data |

---

## For players

### Getting on the whitelist
1. Connect your Steam account to Discord: *User Settings → Connections → Steam*.
2. On the dashboard message, click **✅ Join whitelist**.
3. Click **🔗 Link Steam**, then **Authorize** on the Discord page that opens.
4. The page says you're on the whitelist. In Valheim: **Join Game → Add server**, then the address shown on
   the dashboard.

The bot only reads your Steam connection, to get your Steam ID. It doesn't keep your Discord login.
The link is personal and expires after 10 minutes.

### Buttons and commands
Answers to buttons are only visible to you.

| Button / command | What it does |
|---|---|
| **✅ Join whitelist** | Link your Steam account (see above). Linking again replaces your old one. |
| **👋 Leave whitelist** | Removes you. The button asks for confirmation first. |
| **ℹ️ Whitelist status** | Whether you're whitelisted, with which Steam account, and why your last join failed. |
| **🏆 Leaderboard** | Playtime, sessions and deaths. |
| **📊 My stats** | Your own characters (needs your Steam linked, so the bot knows which characters are yours). |
| `/status` | Server online/offline, players, in-game day, version. |
| `/stats [player]` | The leaderboard, or one character's stats. |

**Rules:** one Steam account per Discord user, and each Steam account can be linked to only one Discord user.
Leaving (or being removed from) the Discord also removes you from the whitelist.

---

## For admins
`/setup-dashboard` and `/whitelist-admin` need the **Manage Server** permission. Discord hides them from other
members, and the bot checks the permission itself every time one runs, so an *Integrations* override can't
hand them to anyone else.

| Command | What it does |
|---|---|
| `/setup-dashboard` | Posts the dashboard in this channel (pin it). Running it again moves it; there is one dashboard. |
| `/whitelist-admin list` | Everyone on the whitelist, with Discord user or note, date added, and when they last played. |
| `/whitelist-admin add steamid:<SteamID64> note:<who>` | Whitelist someone without Discord. Manual entries are never removed automatically. |
| `/whitelist-admin remove member:@someone` / `steamid:<id>` | Remove an entry. |
| `/whitelist-admin history` | The last 20 changes: when, what, which Steam ID, and who did it. |
| `/whitelist-admin attempts` | The last 20 failed joins: not whitelisted, wrong game version, kicked, or dropped. |

- **SteamID64:** 17 digits starting with `7656119`. From a profile link `steamcommunity.com/profiles/7656119…`
  it's the number at the end. A custom URL (`steamcommunity.com/id/name`) needs a lookup site such as steamid.io.
- **Someone can't join?** Ask them to click **ℹ️ Whitelist status** first; it reads the server log and explains.
- **Message of the day:** edit `motd/motd.md` (Discord markdown, up to 1,024 characters). The dashboard shows
  the change within 30 seconds, and it also appears on the page players see after linking.
- **Protected IDs:** Steam IDs in `PROTECTED_STEAMIDS` are always on the whitelist, so the owner can't lock
  themselves out by testing *Leave whitelist*.

> ⚠️ **Never empty the game's `permittedlist.txt` by hand.** Valheim treats an empty whitelist as "everyone may
> join". The bot always keeps it non-empty (a placeholder `0` when nobody is on it) and rewrites it on every
> change, so manage the list through the bot.

## Credits
This bot stands on these projects:
- [lloesche/valheim-server-docker](https://github.com/lloesche/valheim-server-docker): the Valheim server image,
  including the log hooks the bot reads its events from (Apache-2.0)
- [discord.py](https://github.com/Rapptz/discord.py) (MIT) and [aiohttp](https://github.com/aio-libs/aiohttp)
  (Apache-2.0)
- [Caddy](https://caddyserver.com) for HTTPS (Apache-2.0)

## License
Copyright (C) 2026 gacoperz

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any
later version. It is distributed WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

Valheim, Discord and Steam are trademarks of their respective owners. This project is not affiliated with or
endorsed by Iron Gate, Coffee Stain, Valve or Discord.
