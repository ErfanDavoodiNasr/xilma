#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# Simple, safe deploy script for the Xilma bot
# - SSH into VPS
# - Clone/pull repo
# - Upload .env
# - Build & run with Docker Compose

# Colors (TTY only)
if [ -t 1 ]; then
  C_RESET="\033[0m"
  C_RED="\033[31m"
  C_GREEN="\033[32m"
  C_YELLOW="\033[33m"
  C_BLUE="\033[34m"
else
  C_RESET=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_BLUE=""
fi

log() { echo -e "${C_GREEN}[+]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[!]${C_RESET} $*"; }
info() { echo -e "${C_BLUE}[-]${C_RESET} $*"; }
die() { echo -e "${C_RED}[x]${C_RESET} $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

trim() {
  # shellcheck disable=SC2001
  echo "$1" | sed 's/^ *//;s/ *$//'
}

prompt_var() {
  # Usage: prompt_var VAR "Prompt" "default" "secret" "required"
  local var="$1"
  local prompt="$2"
  local default="${3-}"
  local secret="${4-}"
  local required="${5-1}"

  # If already set via env, keep it
  local val="${!var:-}"
  if [ -n "$val" ]; then
    return 0
  fi

  local suffix=""
  if [ -n "$default" ]; then
    suffix=" [$default]"
  fi

  if [ "$secret" = "secret" ]; then
    read -r -s -p "$prompt$suffix: " val
    echo
  else
    read -r -p "$prompt$suffix: " val
  fi

  val="$(trim "$val")"
  if [ -z "$val" ]; then
    val="$default"
  fi

  if [ -z "$val" ] && [ "$required" = "1" ]; then
    die "$var is required"
  fi

  printf -v "$var" '%s' "$val"
}

mask_secret() {
  local v="$1"
  local n=${#v}
  if [ "$n" -le 4 ]; then
    printf '****'
  else
    printf '****%s' "${v:$((n-4))}"
  fi
}

confirm() {
  local prompt="$1"
  local ans
  read -r -p "$prompt [y/N]: " ans
  ans="$(trim "$ans")"
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

shell_quote() {
  # Shell-escape a value for safe embedding in a script
  printf '%q' "$1"
}

cleanup() {
  if [ -n "${ENV_FILE:-}" ] && [ -f "$ENV_FILE" ]; then
    rm -f "$ENV_FILE"
  fi
  if [ -n "${REMOTE_SCRIPT:-}" ] && [ -f "$REMOTE_SCRIPT" ]; then
    rm -f "$REMOTE_SCRIPT"
  fi
}
trap cleanup EXIT

need_cmd ssh
need_cmd scp
need_cmd mktemp

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'USAGE'
Usage: ./deploy.sh

Optional env vars to skip prompts:
  DEPLOY_HOST, DEPLOY_USER, DEPLOY_PORT, DEPLOY_AUTH, DEPLOY_SSH_KEY, DEPLOY_PASSWORD
  REPO_URL, REPO_BRANCH, APP_DIR
  BOT_TOKEN, ADMIN_USER_ID
  POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, DATABASE_URL
  INSTALL_DOCKER
USAGE
  exit 0
fi

info "Xilma deploy - interactive setup"

# Connection details
prompt_var DEPLOY_HOST "VPS IP/Host"
prompt_var DEPLOY_USER "SSH user" "root"
prompt_var DEPLOY_PORT "SSH port" "22"

# Auth method
prompt_var DEPLOY_AUTH "Auth method (key/password)" "key"
DEPLOY_AUTH="$(echo "$DEPLOY_AUTH" | tr '[:upper:]' '[:lower:]')"
if [ "$DEPLOY_AUTH" = "password" ]; then
  prompt_var DEPLOY_PASSWORD "SSH password" "" "secret"
  if ! command -v sshpass >/dev/null 2>&1; then
    die "sshpass is required for password auth. Install it or use key auth."
  fi
elif [ "$DEPLOY_AUTH" = "key" ]; then
  prompt_var DEPLOY_SSH_KEY "Path to SSH private key (leave blank for ssh-agent)" "" "" 0
  if [ -n "${DEPLOY_SSH_KEY:-}" ] && [ ! -f "$DEPLOY_SSH_KEY" ]; then
    die "SSH key not found at: $DEPLOY_SSH_KEY"
  fi
else
  die "Invalid auth method: $DEPLOY_AUTH (use key or password)"
fi

# Repo details
prompt_var REPO_URL "Git repo URL (HTTPS or SSH)" "https://github.com/ErfanDavoodiNasr/xilma"
prompt_var REPO_BRANCH "Git branch" "main"
prompt_var APP_DIR "Remote app directory" "/opt/xilma"

# App env
prompt_var BOT_TOKEN "BOT_TOKEN" "" "secret"
prompt_var ADMIN_USER_ID "ADMIN_USER_ID"
prompt_var POSTGRES_DB "POSTGRES_DB" "xilma"
prompt_var POSTGRES_USER "POSTGRES_USER" "xilma"
prompt_var POSTGRES_PASSWORD "POSTGRES_PASSWORD" "" "secret"

# Optional override
prompt_var DATABASE_URL "DATABASE_URL (leave blank to auto-generate)" "" "" 0
if [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
fi

if ! [[ "$ADMIN_USER_ID" =~ ^[0-9]+$ ]]; then
  warn "ADMIN_USER_ID does not look numeric. Telegram IDs are usually numbers."
fi

# Docker install option
prompt_var INSTALL_DOCKER "Install Docker if missing? (yes/no)" "no" "" 0
INSTALL_DOCKER="$(echo "$INSTALL_DOCKER" | tr '[:upper:]' '[:lower:]')"
if [ "$INSTALL_DOCKER" != "yes" ] && [ "$INSTALL_DOCKER" != "no" ] && [ -n "$INSTALL_DOCKER" ]; then
  die "INSTALL_DOCKER must be 'yes' or 'no'"
fi

# Prepare .env
ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"

escape_env() {
  # Escape for .env (double-quoted string)
  local v="$1"
  v="${v//\\/\\\\}"
  v="${v//\"/\\\"}"
  printf '"%s"' "$v"
}

{
  echo "POSTGRES_DB=$(escape_env "$POSTGRES_DB")"
  echo "POSTGRES_USER=$(escape_env "$POSTGRES_USER")"
  echo "POSTGRES_PASSWORD=$(escape_env "$POSTGRES_PASSWORD")"
  echo "DATABASE_URL=$(escape_env "$DATABASE_URL")"
  echo "BOT_TOKEN=$(escape_env "$BOT_TOKEN")"
  echo "ADMIN_USER_ID=$(escape_env "$ADMIN_USER_ID")"
} > "$ENV_FILE"

# Summary
info "\nReview configuration:"
echo "Host:            $DEPLOY_HOST"
echo "User:            $DEPLOY_USER"
echo "Port:            $DEPLOY_PORT"
echo "Auth:            $DEPLOY_AUTH"
echo "Repo:            $REPO_URL"
echo "Branch:          $REPO_BRANCH"
echo "App dir:         $APP_DIR"
echo "BOT_TOKEN:       $(mask_secret "$BOT_TOKEN")"
echo "ADMIN_USER_ID:   $ADMIN_USER_ID"
echo "POSTGRES_DB:     $POSTGRES_DB"
echo "POSTGRES_USER:   $POSTGRES_USER"
echo "POSTGRES_PASSWORD: $(mask_secret "$POSTGRES_PASSWORD")"
echo "DATABASE_URL:    $DATABASE_URL"

if ! confirm "Proceed with deployment?"; then
  die "Aborted by user"
fi

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

SSH_OPTS=( -p "$DEPLOY_PORT" -o ServerAliveInterval=30 -o ServerAliveCountMax=5 )
SCP_OPTS=( -P "$DEPLOY_PORT" )

if [ "$DEPLOY_AUTH" = "password" ]; then
  SSH_CMD=( sshpass -p "$DEPLOY_PASSWORD" ssh )
  SCP_CMD=( sshpass -p "$DEPLOY_PASSWORD" scp )
elif [ "$DEPLOY_AUTH" = "key" ]; then
  SSH_CMD=( ssh )
  SCP_CMD=( scp )
  if [ -n "${DEPLOY_SSH_KEY:-}" ]; then
    SSH_OPTS+=( -i "$DEPLOY_SSH_KEY" )
    SCP_OPTS+=( -i "$DEPLOY_SSH_KEY" )
  fi
fi

# Upload .env to remote temp
REMOTE_ENV="/tmp/xilma.env.$RANDOM.$RANDOM"
info "Uploading .env to remote..."
"${SCP_CMD[@]}" "${SCP_OPTS[@]}" "$ENV_FILE" "$SSH_TARGET:$REMOTE_ENV"

# Build remote bootstrap script
REMOTE_SCRIPT="$(mktemp)"
{
  cat <<'REMOTE_HEADER'
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
REMOTE_HEADER

  echo "APP_DIR=$(shell_quote "$APP_DIR")"
  echo "REPO_URL=$(shell_quote "$REPO_URL")"
  echo "BRANCH=$(shell_quote "$REPO_BRANCH")"
  echo "ENV_SRC=$(shell_quote "$REMOTE_ENV")"
  echo "INSTALL_DOCKER=$(shell_quote "$INSTALL_DOCKER")"

  cat <<'REMOTE_EOF'

log() { echo "[+] $*"; }
warn() { echo "[!] $*"; }
err() { echo "[x] $*" >&2; }

die() { err "$*"; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

cleanup() {
  if [ -n "${ENV_SRC:-}" ] && [ -f "$ENV_SRC" ]; then
    rm -f "$ENV_SRC"
  fi
}
trap cleanup EXIT

# Sudo setup
if [ "$(id -u)" -eq 0 ]; then
  SUDO=()
else
  if need_cmd sudo; then
    SUDO=(sudo)
  else
    die "This user is not root and sudo is not available"
  fi
fi

# Package manager detection
PM=""
if need_cmd apt-get; then
  PM="apt"
elif need_cmd dnf; then
  PM="dnf"
elif need_cmd yum; then
  PM="yum"
elif need_cmd apk; then
  PM="apk"
elif need_cmd pacman; then
  PM="pacman"
fi

pkg_update_done="no"

pkg_install() {
  case "$PM" in
    apt)
      if [ "$pkg_update_done" != "yes" ]; then
        "${SUDO[@]}" apt-get update -y
        pkg_update_done="yes"
      fi
      "${SUDO[@]}" apt-get install -y "$@"
      ;;
    dnf)
      "${SUDO[@]}" dnf install -y "$@"
      ;;
    yum)
      "${SUDO[@]}" yum install -y "$@"
      ;;
    apk)
      "${SUDO[@]}" apk add --no-cache "$@"
      ;;
    pacman)
      "${SUDO[@]}" pacman -Sy --noconfirm "$@"
      ;;
    *)
      die "Unsupported package manager. Install required packages manually."
      ;;
  esac
}

# Ensure git
if ! need_cmd git; then
  log "Installing git..."
  pkg_install git
fi

# Ensure curl for docker install if needed
if [ "$INSTALL_DOCKER" = "yes" ] && ! need_cmd curl; then
  log "Installing curl..."
  pkg_install curl
fi

# Docker install if missing
if ! need_cmd docker; then
  if [ "$INSTALL_DOCKER" = "yes" ]; then
    log "Installing Docker (official convenience script)..."
    pkg_install ca-certificates
    curl -fsSL https://get.docker.com | "${SUDO[@]}" sh
    # enable/start if systemd exists
    if need_cmd systemctl; then
      "${SUDO[@]}" systemctl enable --now docker
    fi
  else
    die "Docker is not installed. Re-run and choose to install Docker, or install it manually."
  fi
fi

# Determine docker command (use sudo when needed)
if [ "$(id -u)" -eq 0 ]; then
  DOCKER=(docker)
else
  if id -nG "$USER" | grep -qw docker; then
    DOCKER=(docker)
  else
    DOCKER=(sudo docker)
  fi
fi

# Determine compose command
if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
  COMPOSE=("${DOCKER[@]}" compose)
elif need_cmd docker-compose; then
  if [ "$(id -u)" -eq 0 ]; then
    COMPOSE=(docker-compose)
  else
    COMPOSE=(sudo docker-compose)
  fi
else
  die "Docker Compose not found. Install docker compose plugin or docker-compose."
fi

# Prepare app directory
if [ -d "$APP_DIR/.git" ]; then
  log "Updating existing repo in $APP_DIR"
  cd "$APP_DIR"
  git fetch --all --prune
  git checkout "$BRANCH"
  git pull --ff-only
elif [ -e "$APP_DIR" ]; then
  die "$APP_DIR exists but is not a git repo. Remove it or choose another directory."
else
  log "Cloning repo to $APP_DIR"
  "${SUDO[@]}" mkdir -p "$APP_DIR"
  "${SUDO[@]}" chown -R "$USER":"$USER" "$APP_DIR"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

# Install .env
if [ ! -f "$ENV_SRC" ]; then
  die "Remote env file not found: $ENV_SRC"
fi

log "Installing .env"
install -m 600 "$ENV_SRC" "$APP_DIR/.env"
rm -f "$ENV_SRC"

# Build and run
log "Building and starting containers"
export DOCKER_BUILDKIT=1
"${COMPOSE[@]}" build --pull
"${COMPOSE[@]}" up -d --remove-orphans

log "Deployment complete"
"${COMPOSE[@]}" ps
REMOTE_EOF
} > "$REMOTE_SCRIPT"

chmod +x "$REMOTE_SCRIPT"

info "Running remote deployment..."
"${SSH_CMD[@]}" "${SSH_OPTS[@]}" "$SSH_TARGET" "bash -s" < "$REMOTE_SCRIPT"

log "Done."
