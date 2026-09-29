# What data the bot stores

This describes what an instance of this bot collects and keeps. Whoever runs an instance is responsible for
it: Discord's Developer Policy expects apps that handle user data to tell their users what they collect, and
in the EU the GDPR may apply. Feel free to link your members to this page, or copy it.

Everything stays **on the server that runs the bot**. The bot talks only to Discord (to run the bot and the
login) and shares this data with no one else.

## Collected
| What | Where it comes from | Why |
|---|---|---|
| Discord user ID and username, and the Discord server ID | Clicking *Join whitelist* and logging in | To link a Discord member to one Steam account, and remove them when they leave the Discord |
| SteamID64 and Steam display name | The member's **verified Steam connection** on Discord (OAuth scope `connections`) | To put the Steam account on the game's whitelist |
| Character names, and when each play session started and ended | The game server's log | Online list, playtime, sessions, "My stats", in-game day |
| Time of each death, per character and Steam account | The game server's log | Death counts |
| Failed joins: SteamID64, character name, time, reason (e.g. game versions) | The game server's log | Explaining to a player why they couldn't join |
| Whitelist changes: time, action, SteamID64, the member's name, who made the change | Every change | The admin history (`/whitelist-admin history`) |
| A notes field for manually added Steam IDs | Admins | Knowing who a manual entry belongs to |
| Bans: SteamID64 and/or Discord user ID, name, reason, time, who banned | `/whitelist-admin ban` | Keeping banned people from joining again |

**Not collected:** email addresses, passwords, message contents (the bot doesn't have the message-content intent),
or the Discord login itself. The OAuth access token is used once to read the Steam connection and is **revoked
straight away**; it is never stored. The one-time link token (valid 10 minutes) is deleted when it's used or
expires.

The bot also receives, from Discord, the member list of the servers it's in (the *Server Members* intent). It
uses that only to notice people who leave, and doesn't store it.

## Where it's kept, and for how long
| Place | Contains | Kept |
|---|---|---|
| `data/bot.db` (SQLite) | Everything in the table above | Whitelist entries until the member leaves the whitelist or the Discord, or an admin removes them; bans until an admin lifts them. **Stats, failed joins and the change history have no automatic deletion.** |
| The game's `config/permittedlist.txt` | SteamID64s on the whitelist | Rewritten on every change |
| The game's `config/bot/events.log` | Raw game log lines: SteamID64s, character names, times | Not trimmed automatically |
| Container logs (bot, Caddy, game) | Whitelist changes with names and SteamID64s; Caddy's access log with visitors' IP addresses (the OAuth `code` and `state` are redacted) | Rotated by size (a few MB each) |
| Database snapshots (if the timers are enabled) | Copies of `data/bot.db` | 14 days |
| The game's world backups | The world, including characters' positions and builds | 3 days |

Only the server's administrators (root) can read these files.

## Removing someone's data
**Leave whitelist** (or leaving the Discord) removes the whitelist entry. To delete everything the bot holds about a
Steam account, an operator can run this on the server, with the bot stopped:
```bash
cd /opt/valheim-bot && docker compose stop bot
STEAMID=7656119XXXXXXXXXX python3 - <<'EOF'
import os, sqlite3
db, sid = sqlite3.connect("data/bot.db"), os.environ["STEAMID"]
with db:
    for table in ("sessions", "deaths", "join_attempts", "whitelist", "whitelist_audit", "blocklist"):
        db.execute(f"DELETE FROM {table} WHERE steamid = ?", (sid,))
EOF
docker compose start bot
```
Then delete older database snapshots, or let them expire. The game's own log and world backups still mention the
character; they age out on their own.
Don't shorten `events.log` by hand while the bot keeps its reading position in the database: a shorter file makes
the bot read it again from the start, duplicating stats.
