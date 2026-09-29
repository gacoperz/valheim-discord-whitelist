# Security

## Reporting a problem
Please report security problems privately through GitHub: **Security → Report a vulnerability** on this
repository. Don't open a public issue for them. Include what you found, how to reproduce it, and what an
attacker could do with it.

What the bot stores about people, and how to delete it: [PRIVACY.md](PRIVACY.md).

## Design
The bot controls who may join a game server that may have **no password**, so it is built to fail closed.

**Whitelist**
- The game's `permittedlist.txt` is never left empty; Valheim treats an empty list as "everyone may join". The
  bot writes a placeholder when nobody is on it, and protected owner IDs are always written.
- It is the only game file the bot can write, through the file's group. Everything else is mounted read-only.

**Discord**
- Everything is refused outside the Discord servers in `ALLOWED_GUILDS`, including commands, buttons and whitelist
  links, so *Manage Server* in some other server never grants whitelist admin. An empty list refuses everything.
- Admin commands require *Manage Server* and check it at run time, not only through Discord's visibility
  settings, which a server's *Integrations* page can override.
- The bot never pings (`AllowedMentions.none()`), because some replies repeat what users typed.
- Commands are installable in servers only (no user installs or DMs).

**Linking (Discord OAuth2)**
- Scopes `identify` and `connections` only. The access token is revoked right after use and never stored.
- A one-time link token, valid 10 minutes, ties the login to the Discord user and server that clicked
  *Join whitelist*. A different account completing the login is refused.
- Only a **verified** Steam connection is accepted, and one Steam account can belong to one Discord user.
- Everything shown on the return page is HTML-escaped. Caddy's log redacts the OAuth `code` and `state`.

**Containers and host**
- The bot runs as uid 10001 on a read-only filesystem, with all capabilities dropped, `no-new-privileges`, a
  memory limit, and no Docker socket. Caddy has only `NET_BIND_SERVICE`.
- Secrets live only in `secrets.env` (mode 600), which is passed to the bot container alone and excluded from
  git and from Docker build contexts.
- The optional host setup allows only SSH, `2456-2457/udp` and `443/tcp`, and adds a `DOCKER-USER` guard so Docker's
  published ports can't bypass the firewall. Port 80 stays closed; certificates are validated on 443.
- The installer never changes SSH. Use key-only SSH login on any internet-facing server.
