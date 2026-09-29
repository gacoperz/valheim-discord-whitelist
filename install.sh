#!/usr/bin/env bash
# Install (or re-configure) a Valheim dedicated server with the Discord whitelist bot on Debian/Ubuntu.
# Safe to run again: existing settings are offered as defaults and existing files are kept.
# See docs/INSTALL.md.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [options]

  --dry-run        show what would be done; change nothing
  --answers FILE   take answers from FILE (KEY=value lines, see docs/INSTALL.md) instead of asking
  --no-start       write the configuration but don't start any containers
  --reconfigure    ask again for settings that already have values (default: keep them)
  -h, --help       this help
EOF
}

BOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DRY_RUN=0 NO_START=0 RECONFIGURE=0 ANSWERS_FILE=
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=1 ;;
        --answers) ANSWERS_FILE=${2:?--answers needs a file}; shift ;;
        --no-start) NO_START=1 ;;
        --reconfigure) RECONFIGURE=1 ;;
        -h | --help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------- output and dry-run helpers
if [[ -t 1 ]]; then BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RESET=$'\e[0m'
else BOLD='' DIM='' RED='' GREEN='' YELLOW='' RESET=''; fi
step() { echo; echo "${BOLD}== $*${RESET}"; }
info() { echo "   $*"; }
ok() { echo "   ${GREEN}✓${RESET} $*"; }
warn() { echo "   ${YELLOW}!${RESET} $*"; }
die() { echo "${RED}error:${RESET} $*" >&2; exit 1; }

# Run a command, or only show it in --dry-run.
run() {
    if ((DRY_RUN)); then echo "   ${DIM}would run: $*${RESET}"; else "$@"; fi
}

# write_file PATH MODE OWNER: write stdin to PATH (only if it doesn't exist, unless FORCE=1).
write_file() {
    local path=$1 mode=$2 owner=$3 content
    content=$(cat)
    if [[ -e $path && ${FORCE:-0} != 1 ]]; then
        info "keeping existing $path"
        return
    fi
    if ((DRY_RUN)); then
        echo "   ${DIM}would write $path (mode $mode, owner $owner)${RESET}"
        return
    fi
    install -D -m "$mode" -o "${owner%%:*}" -g "${owner##*:}" /dev/null "$path"
    printf '%s\n' "$content" >"$path"
    ok "wrote $path"
}

# ---------------------------------------------------------------- answers
declare -A ANSWER=()
if [[ -n $ANSWERS_FILE ]]; then
    [[ -r $ANSWERS_FILE ]] || die "cannot read $ANSWERS_FILE"
    while IFS= read -r line || [[ -n $line ]]; do
        [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
        [[ $line =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]] || die "bad line in $ANSWERS_FILE: $line"
        value=${BASH_REMATCH[2]}
        value=${value#[\'\"]} value=${value%[\'\"]}
        ANSWER[${BASH_REMATCH[1]}]=$value
    done <"$ANSWERS_FILE"
fi
INTERACTIVE=0
[[ -z $ANSWERS_FILE && -t 0 ]] && INTERACTIVE=1

# read_env FILE: print KEY=value lines from an existing env file, quotes removed (never sourced).
declare -A EXISTING=()
read_env() {
    local file=$1 line key value
    [[ -r $file ]] || return 0
    while IFS= read -r line || [[ -n $line ]]; do
        [[ $line =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]] || continue
        key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
        value=${value%%[[:space:]]#*}
        value=${value#\'} value=${value%\'} value=${value#\"} value=${value%\"}
        EXISTING[$key]=$value
    done <"$file"
}

# ask KEY "question" DEFAULT [secret|optional]: set the variable KEY. Order: answers file, existing
# setting (unless --reconfigure), prompt (interactive), default.
ask() {
    local key=$1 question=$2 default=${3:-} kind=${4:-} reply=
    if [[ -v ANSWER[$key] ]]; then
        reply=${ANSWER[$key]}
    elif [[ -v EXISTING[$key] ]] && ((!RECONFIGURE)); then
        reply=${EXISTING[$key]}
    elif ((INTERACTIVE)); then
        [[ -v EXISTING[$key] ]] && default=${EXISTING[$key]}
        if [[ $kind == secret ]]; then
            read -r -s -p "   $question${default:+ [keep current]}: " reply
            echo
        else
            read -r -p "   $question${default:+ [$default]}: " reply
        fi
        reply=${reply:-$default}
    else
        reply=$default
    fi
    if [[ -z $reply && $kind != optional ]]; then
        die "$key is required ($question)"
    fi
    [[ $reply == *"'"* ]] && die "$key must not contain a single quote"
    printf -v "$key" '%s' "$reply"
}

# ask_yes KEY "question" DEFAULT(yes|no): true if the answer is yes.
ask_yes() {
    local key=$1
    ask "$key" "$2 (yes/no)" "$3"
    [[ ${!key,,} == y || ${!key,,} == yes ]]
}

is_ip() { [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }
is_steamid64() { [[ $1 =~ ^7656119[0-9]{10}$ ]]; }

# ---------------------------------------------------------------- 1. preflight
step "Checking this machine"
((EUID == 0)) || ((DRY_RUN)) || die "run as root (sudo ./install.sh)"
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu || $ID == debian ]] || die "only Ubuntu and Debian are supported (this is $PRETTY_NAME)"
[[ $(uname -m) == x86_64 ]] || die "the Valheim server needs an x86_64 machine (this is $(uname -m))"
ok "$PRETTY_NAME, x86_64"
MEM_MB=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
SWAP_MB=$(awk '/SwapTotal/ {print int($2 / 1024)}' /proc/meminfo)
if ((MEM_MB >= 3500)); then ok "${MEM_MB} MB RAM"; else warn "${MEM_MB} MB RAM: Valheim wants about 4 GB; swap helps"; fi
((DRY_RUN)) && warn "dry run: nothing will be changed"

read_env "$BOT_DIR/.env"
ask VALHEIM_DIR "Folder for the game server" /opt/valheim
# ask() sets its variables with printf -v, which shellcheck cannot see
# shellcheck disable=SC2153
read_env "$VALHEIM_DIR/.env"
read_env "$BOT_DIR/.env"  # bot settings win where both define a key
read_env "$BOT_DIR/secrets.env"

# ---------------------------------------------------------------- 2. Docker
step "Docker"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    ok "$(docker --version | cut -d, -f1), $(docker compose version --short 2>/dev/null || true)"
elif ask_yes INSTALL_DOCKER "Docker is missing. Install Docker Engine from Docker's official repository?" yes; then
    run apt-get update -qq
    run apt-get install -y -qq ca-certificates curl
    run install -m 0755 -d /etc/apt/keyrings
    run curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    run chmod a+r /etc/apt/keyrings/docker.asc
    FORCE=1 write_file /etc/apt/sources.list.d/docker.sources 644 root:root <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $VERSION_CODENAME
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    run apt-get update -qq
    run apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    run systemctl enable --now docker
else
    die "Docker Engine with the compose plugin is required"
fi

# ---------------------------------------------------------------- 3. settings
step "Settings (press Enter to accept the value in brackets)"
DETECTED_IP=$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
DETECTED_TZ=$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)

ask SERVER_NAME "Server name (shown in Valheim and Discord)" "My Valheim Server"
ask WORLD_NAME "World name (letters and digits)" MyWorld
[[ $WORLD_NAME =~ ^[A-Za-z0-9_-]+$ ]] || die "WORLD_NAME may only contain letters, digits, - and _"
ask SERVER_PASS "Game password (empty = whitelist only)" "" optional
if [[ -n $SERVER_PASS ]]; then
    ((${#SERVER_PASS} >= 5)) || die "SERVER_PASS must be at least 5 characters"
    [[ $SERVER_NAME != *"$SERVER_PASS"* ]] || die "SERVER_PASS must not be part of SERVER_NAME (Valheim refuses it)"
fi
ask SERVER_ARGS "Extra server arguments, e.g. -preset normal -modifier raids none" "-preset normal" optional
ask TZ "Time zone" "$DETECTED_TZ"
ask MAX_PLAYERS "Maximum players" 10
ask SITE_ADDRESS "Domain name for the bot's HTTPS page, or this server's public IP" "$DETECTED_IP"
if is_ip "$SITE_ADDRESS"; then CADDYFILE=./caddy/Caddyfile.ip; else CADDYFILE=./caddy/Caddyfile.domain; fi
PUBLIC_URL=https://$SITE_ADDRESS
ask JOIN_ADDRESS "Address players type in Valheim (Join Game -> Add server)" "$SITE_ADDRESS:2456"

info "Discord (docs/INSTALL.md shows where to find each value):"
ask DISCORD_TOKEN "Bot token" "" secret
ask DISCORD_CLIENT_SECRET "OAuth2 client secret" "" secret
ask ALLOWED_GUILDS "Discord server ID(s) the bot serves, space-separated"
for guild in $ALLOWED_GUILDS; do [[ $guild =~ ^[0-9]{17,20}$ ]] || die "not a Discord server ID: $guild"; done
ask PROTECTED_STEAMIDS "Your SteamID64 (always whitelisted, so you can't lock yourself out)" "" optional
for steamid in $PROTECTED_STEAMIDS; do is_steamid64 "$steamid" || die "not a SteamID64: $steamid"; done
ask NOTIFY_USER_ID "Your Discord user ID (for admin alert DMs; empty = none)" "" optional
[[ -z $NOTIFY_USER_ID || $NOTIFY_USER_ID =~ ^[0-9]{17,20}$ ]] || die "not a Discord user ID: $NOTIFY_USER_ID"

# ---------------------------------------------------------------- 4. game server
step "Game server in $VALHEIM_DIR"
if getent passwd valheim >/dev/null; then
    ok "user valheim exists"
else
    run useradd --system --no-create-home --shell /usr/sbin/nologin valheim
fi
VALHEIM_UID=$(id -u valheim 2>/dev/null || echo 999)
VALHEIM_GID=$(id -g valheim 2>/dev/null || echo 982)

EXISTING_COMPOSE=
for name in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do
    [[ -f $VALHEIM_DIR/$name ]] && EXISTING_COMPOSE=$VALHEIM_DIR/$name && break
done
if [[ -n $EXISTING_COMPOSE && $(cat "$EXISTING_COMPOSE") != $(cat "$BOT_DIR/valheim/compose.yaml") ]]; then
    warn "using your existing $EXISTING_COMPOSE (not changed). The bot needs these in it:"
    missing=0
    for needle in 'CONFIG_FILE_PERMISSIONS: "664"' 'VALHEIM_LOG_FILTER_REGEXP_DiscordBot' \
        'is blacklisted or not in whitelist' '/config/bot/events.log'; do
        if grep -qF "$needle" "$EXISTING_COMPOSE"; then ok "$needle"; else warn "missing: $needle"; missing=1; fi
    done
    ((missing)) && warn "copy the lines marked 'bot:' from $BOT_DIR/valheim/compose.yaml, then recreate the server"
else
    run install -d -m 755 "$VALHEIM_DIR"
    run cp "$BOT_DIR/valheim/compose.yaml" "$VALHEIM_DIR/compose.yaml"
    write_file "$VALHEIM_DIR/.env" 600 root:root <<EOF
# Game server settings (written by install.sh; see $BOT_DIR/valheim/.env.example)
SERVER_NAME='$SERVER_NAME'
WORLD_NAME='$WORLD_NAME'
SERVER_PASS='$SERVER_PASS'
SERVER_PUBLIC='false'
SERVER_ARGS='$SERVER_ARGS'
VALHEIM_UID='$VALHEIM_UID'
VALHEIM_GID='$VALHEIM_GID'
TZ='$TZ'
EOF
fi
run install -d -m 755 -o valheim -g valheim "$VALHEIM_DIR/config" "$VALHEIM_DIR/config/bot" "$VALHEIM_DIR/data"
[[ -e $VALHEIM_DIR/config/bot/events.log ]] || run install -m 644 -o valheim -g valheim /dev/null "$VALHEIM_DIR/config/bot/events.log"
# The whitelist file must exist before the bot mounts it (Docker would create a directory), and must never
# be empty: an empty permitted list lets everyone in. "0" is a placeholder the bot replaces on start.
write_file "$VALHEIM_DIR/config/permittedlist.txt" 664 valheim:valheim <<'EOF'
// List permitted players ID ONE per line
0
EOF

# ---------------------------------------------------------------- 5. bot
step "Bot in $BOT_DIR"
FORCE_BOT=0
if [[ -e $BOT_DIR/.env ]] && ((RECONFIGURE)); then FORCE_BOT=1; fi
FORCE=$FORCE_BOT write_file "$BOT_DIR/.env" 644 root:root <<EOF
# Bot and Caddy settings (written by install.sh; see .env.example and docs/CONFIGURATION.md)
COMPOSE_PROFILES='https'
BOT_CONTAINER='valheim-bot'
CADDY_CONTAINER='valheim-bot-caddy'
WEB_NETWORK='valheim-bot-web'
VALHEIM_DIR='$VALHEIM_DIR'
WORLD_NAME='$WORLD_NAME'
VALHEIM_HOST='valheim'
VALHEIM_NETWORK='$(basename "$VALHEIM_DIR")_default'
VALHEIM_GID='$VALHEIM_GID'
SERVER_NAME='$SERVER_NAME'
JOIN_ADDRESS='$JOIN_ADDRESS'
MAX_PLAYERS='$MAX_PLAYERS'
TZ='$TZ'
SITE_ADDRESS='$SITE_ADDRESS'
CADDYFILE='$CADDYFILE'
PUBLIC_URL='$PUBLIC_URL'
ALLOWED_GUILDS='$ALLOWED_GUILDS'
PROTECTED_STEAMIDS='$PROTECTED_STEAMIDS'
NOTIFY_USER_ID='$NOTIFY_USER_ID'
EOF
FORCE=$FORCE_BOT write_file "$BOT_DIR/secrets.env" 600 root:root <<EOF
DISCORD_TOKEN='$DISCORD_TOKEN'
DISCORD_CLIENT_SECRET='$DISCORD_CLIENT_SECRET'
EOF
[[ -e $BOT_DIR/motd/motd.md ]] || run cp "$BOT_DIR/motd/motd.example.md" "$BOT_DIR/motd/motd.md"
run install -d -m 700 -o 10001 -g 10001 "$BOT_DIR/data"  # the bot runs as uid 10001
run install -d -m 700 "$BOT_DIR/caddy/data" "$BOT_DIR/caddy/config"

# ---------------------------------------------------------------- 6. optional host setup
step "Optional host setup"
if ((SWAP_MB == 0 && MEM_MB < 6000)) && ask_yes SETUP_SWAP "Add a 4 GB swapfile (recommended below 6 GB RAM)?" yes; then
    if [[ -e /swapfile ]]; then warn "/swapfile already exists; skipped"; else
        run fallocate -l 4G /swapfile
        run chmod 600 /swapfile
        run mkswap /swapfile
        run swapon /swapfile
        grep -q '^/swapfile' /etc/fstab || run sh -c "echo '/swapfile none swap sw 0 0' >> /etc/fstab"
    fi
fi

if ask_yes SETUP_FIREWALL "Firewall (ufw): allow only SSH, 2456-2457/udp and 443/tcp, and stop Docker bypassing it?" yes; then
    SSH_PORTS=$(sshd -T 2>/dev/null | awk '/^port / {print $2}' | sort -u)
    SSH_PORTS=${SSH_PORTS:-22}
    command -v ufw >/dev/null || run apt-get install -y -qq ufw
    for port in $SSH_PORTS; do run ufw allow "$port/tcp" comment SSH; done  # before enabling: keep this session
    run ufw allow 2456:2457/udp comment Valheim
    run ufw allow 443/tcp comment 'Discord login return page'
    run ufw default deny incoming
    run ufw default allow outgoing
    EXT_IF=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}')
    if grep -q 'BEGIN DOCKER-USER guard' /etc/ufw/after.rules 2>/dev/null; then
        ok "Docker guard already in /etc/ufw/after.rules"
    elif [[ -n $EXT_IF ]]; then
        run cp -n /etc/ufw/after.rules /etc/ufw/after.rules.bak
        if ((DRY_RUN)); then info "${DIM}would append host/docker-user-guard.rules (interface $EXT_IF)${RESET}"
        else sed "s/@EXT_IF@/$EXT_IF/g" "$BOT_DIR/host/docker-user-guard.rules" >>/etc/ufw/after.rules; fi
    else
        warn "couldn't find the external interface; add host/docker-user-guard.rules by hand"
    fi
    run ufw --force enable
fi

if ask_yes SETUP_FAIL2BAN "fail2ban for SSH (bans addresses that keep failing to log in)?" yes; then
    run apt-get install -y -qq fail2ban
    MY_IP=${SSH_CLIENT:-}
    MY_IP=${MY_IP%% *}
    ask FAIL2BAN_IGNOREIP "Addresses never to ban (your own)" "$MY_IP" optional
    sed "s/@IGNOREIP@/$FAIL2BAN_IGNOREIP/" "$BOT_DIR/host/fail2ban/jail.local" | write_file /etc/fail2ban/jail.local 644 root:root
    run systemctl enable --now fail2ban
    run systemctl restart fail2ban
fi

if ask_yes SETUP_TIMERS "Timers: daily bot database snapshot and monthly image refresh?" yes; then
    write_file /etc/default/valheim-discord-whitelist 644 root:root <<EOF
VALHEIM_DIR=$VALHEIM_DIR
BOT_DIR=$BOT_DIR
BOT_CONTAINER=valheim-bot
BACKUP_DIR=/root/backups/bot-db
KEEP_DAYS=14
EOF
    for script in valheim-monthly-update valheim-botdb-snapshot; do
        run install -m 755 "$BOT_DIR/host/bin/$script" "/usr/local/sbin/$script"
        run install -m 644 "$BOT_DIR/host/systemd/$script.service" "$BOT_DIR/host/systemd/$script.timer" /etc/systemd/system/
    done
    run systemctl daemon-reload
    run systemctl enable --now valheim-monthly-update.timer valheim-botdb-snapshot.timer
fi

# ---------------------------------------------------------------- 7. start
if ((NO_START || DRY_RUN)); then
    step "Not starting anything (--no-start or --dry-run)"
    info "start later with: docker compose --project-directory $VALHEIM_DIR up -d && docker compose --project-directory $BOT_DIR up -d --build"
    exit 0
fi

step "Starting"
docker compose --project-directory "$VALHEIM_DIR" up -d
info "the first start downloads the game (about 2 GB) and can take 10+ minutes; the bot shows it as offline until then"
docker compose --project-directory "$BOT_DIR" up -d --build
info "waiting for the bot to become healthy..."
# shellcheck disable=SC2016  # expanded by the inner sh, on purpose
if timeout 300 sh -c 'until [ "$(docker inspect -f "{{.State.Health.Status}}" valheim-bot)" = healthy ]; do sleep 5; done'; then
    ok "bot is healthy"
else
    warn "the bot isn't healthy yet: check 'docker compose --project-directory $BOT_DIR logs bot'"
fi
INVITE=$(docker logs valheim-bot 2>&1 | grep -o 'https://discord.com/oauth2/authorize?[^ ]*' | tail -1 || true)

step "Almost done: finish in the Discord Developer Portal (docs/INSTALL.md, step 5)"
info "1. OAuth2 -> Redirects: add ${BOLD}$PUBLIC_URL/discord/callback${RESET}"
info "2. Bot -> Privileged Gateway Intents: turn on ${BOLD}Server Members Intent${RESET}"
info "3. Invite the bot: ${INVITE:-see the 'invite link' line in the bot log}"
info "4. In your Discord, run ${BOLD}/setup-dashboard${RESET} in the channel for it, and pin the message"
is_ip "$SITE_ADDRESS" || info "5. Make sure the DNS name $SITE_ADDRESS points at this server (Caddy needs it for HTTPS)"
