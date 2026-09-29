# Changelog

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
