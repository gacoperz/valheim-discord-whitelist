# Changelog

## Unreleased (branch `ponytail-refactor`)
No database changes and nothing to do by hand.

- **Liveness probe only.** `bot/a2s.py` no longer parses A2S replies: any reply or no reply means online, "port
  unreachable" means offline. Before, a reply the parser didn't expect made every poll fail. Player count and
  version now always come from the events log, also on a public server.
- **Alert DMs** show 24 h or more as days and hours ("2d 2h" instead of "50h 5m").
- Code with one caller is folded into it (`bot/world.py`, `bot/web.py`, `bot/orphans.py`); new tests cover the
  probe, the in-game day and the status embed.

## v1.1.2
**Upgrading:** check out the tag and run `docker compose up -d --build`. The bot's behaviour is unchanged; this
release is documentation, metadata and CI. No database changes and nothing to do by hand.

- **Docs check in CI.** `check_docs.py` (also part of `./check.sh`) fails on doc lines over 120 characters, filler
  words, links to missing files or headings, and setting names that appear nowhere outside the docs.
- **Docs wording.** Long lines are wrapped, the game image's repo URL is stated once (README credits), and the
  v1.1.1 changelog entry and a README bullet say what they do instead of using a vague label.
- The copyright line and `pyproject.toml` name the author.

## v1.1.1
**Upgrading:** check out the tag and run `docker compose up -d --build`. No database changes and nothing to do by
hand. The image is rebuilt with pinned dependency versions.

- **Errors no longer stop background work.** The hourly Discord member check logs an error and tries again an
  hour later. An events-log line that fails to process is logged and skipped, so later lines still count for stats
  and sessions. Each poll reads at most 8 MiB of the log.
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
