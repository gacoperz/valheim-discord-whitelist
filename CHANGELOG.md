# Changelog

## v1.1.1
**Upgrading:** check out the tag and run `docker compose up -d --build`. No database changes and nothing to do by
hand. The image is rebuilt with pinned dependency versions.

- **Background work survives errors.** The hourly Discord member check keeps running after an error, and one
  unreadable line in the events log is logged and skipped instead of stopping all stats and session tracking.
  The events log is read in pieces of at most 8 MiB per poll.
- **Login page.** A ban that lands while someone is linking now shows the "Blocked" page instead of an error;
  calls to Discord time out after 10 s; requests are limited to 30 per minute per address.
- **Admin commands.** `/whitelist-admin remove` and `unban` check the SteamID like `add` and `ban` do;
  `/setup-dashboard` answers cleanly when it can't post in the channel.
- The database waits up to 5 s for a lock (backups, read-only checks) instead of failing at once.
- CI also lints the snapshot script.

## v1.1.0
**Upgrading:** check out the tag and run `docker compose up -d --build`. The database is migrated automatically on
start (new columns and a `blocklist` table). Commands are re-registered on start; press Ctrl+R in Discord if the
new ones don't show.

- **Bans that stick.** `/whitelist-admin ban member:` or `steamid:` removes someone and blocks them from joining
  again; banning a member also blocks their Discord account. `/whitelist-admin unban` lifts it. Banned people get a
  clear message from *Join whitelist*, *Whitelist status* and the login page. Bans show in `/whitelist-admin list`.
- **Stats per player.** Two players who use the same character name are now counted separately (also when both are
  online at once), and *My stats* shows only your own characters. The leaderboard and `/stats` add the end of the
  Steam ID when a name is shared.
- Docs: the game image's GitHub repo moved to `community-valheim-tools/valheim-server-docker`.

## v1.0.0
First public release.
