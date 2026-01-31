#!/usr/bin/env bash
set -euo pipefail
set -E
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

on_error() {
  local code=$?
  local line=${BASH_LINENO[0]}
  local cmd=${BASH_COMMAND}
  die "Command failed (exit $code) at line $line: $cmd"
}
trap on_error ERR

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

mask_database_url() {
  local url="$1"
  if [ -z "$url" ]; then
    printf ''
    return 0
  fi
  printf '%s' "$url" | sed -E 's#(://[^:/]+):[^@]+@#\1:****@#'
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${ENV_PATH:-$SCRIPT_DIR/.env}"

load_env_file() {
  local path="$1"
  if [ -f "$path" ]; then
    info "Loading env from $path"
    set -a
    # shellcheck disable=SC1090
    source "$path"
    set +a
  else
    warn "Env file not found at $path (continuing with prompts/env vars)"
  fi
}

load_env_file "$ENV_PATH"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'USAGE'
Usage: ./deploy.sh [deploy|update]

Optional env vars to skip prompts:
  DEPLOY_HOST, DEPLOY_USER, DEPLOY_PORT, DEPLOY_AUTH, DEPLOY_SSH_KEY, DEPLOY_PASSWORD
  REPO_URL, REPO_BRANCH, APP_DIR
  TELEGRAM_BOT_TOKEN, BOT_TOKEN, ADMIN_USER_ID
  POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, DATABASE_URL
  API_KEY, BASE_URL, DEFAULT_MODEL, LOG_FORMAT
  INSTALL_DOCKER
  SYNC_ENV (update only: auto/yes/no, default auto)
  ENV_PATH (path to .env, default: ./.env)

Modes:
  deploy (default)  Full setup: clone repo + upload .env + build & run
  update            Fast update: git pull + build & run (no .env prompts)
USAGE
  exit 0
fi

MODE="deploy"
if [ $# -gt 0 ]; then
  case "$1" in
    deploy|--deploy) MODE="deploy" ;;
    update|--update) MODE="update" ;;
    *) die "Unknown mode: $1 (use deploy or update)" ;;
  esac
fi

info "Xilma deploy - interactive setup"

# Connection details
info "Collecting connection settings..."
prompt_var DEPLOY_HOST "VPS IP/Host"
prompt_var DEPLOY_USER "SSH user" "root"
prompt_var DEPLOY_PORT "SSH port" "22"

# Auth method
info "Collecting auth settings..."
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
info "Collecting repo settings..."
DEFAULT_REF="main"
if command -v git >/dev/null 2>&1; then
  CURRENT_REF="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ -n "$CURRENT_REF" ]; then
    DEFAULT_REF="$CURRENT_REF"
  fi
fi
if [ "$MODE" = "deploy" ]; then
  prompt_var REPO_URL "Git repo URL (HTTPS or SSH)" "https://github.com/ErfanDavoodiNasr/xilma"
  prompt_var REPO_BRANCH "Git ref (branch/tag/commit)" "$DEFAULT_REF"
  prompt_var APP_DIR "Remote app directory" "/opt/xilma"

  # App env
  info "Collecting app settings..."
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${BOT_TOKEN:-}" ]; then
    TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
  fi
  prompt_var TELEGRAM_BOT_TOKEN "TELEGRAM_BOT_TOKEN" "" "secret"
  prompt_var ADMIN_USER_ID "ADMIN_USER_ID"
  prompt_var POSTGRES_DB "POSTGRES_DB" "xilma"
  prompt_var POSTGRES_USER "POSTGRES_USER" "xilma"
  prompt_var POSTGRES_PASSWORD "POSTGRES_PASSWORD" "" "secret"
  prompt_var API_KEY "API_KEY (optional)" "" "secret" 0
  prompt_var BASE_URL "BASE_URL (optional)" "" "" 0
  prompt_var DEFAULT_MODEL "DEFAULT_MODEL (optional)" "" "" 0
  prompt_var LOG_FORMAT "LOG_FORMAT (optional: text/json/both)" "" "" 0

  # Optional override
  prompt_var DATABASE_URL "DATABASE_URL (leave blank to auto-generate)" "" "" 0
  if [ -z "${DATABASE_URL:-}" ]; then
    DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
  fi

  if ! [[ "$ADMIN_USER_ID" =~ ^[0-9]+$ ]]; then
    warn "ADMIN_USER_ID does not look numeric. Telegram IDs are usually numbers."
  fi
else
  prompt_var APP_DIR "Remote app directory" "/opt/xilma"
  prompt_var REPO_BRANCH "Git ref (leave blank to keep current)" "" "" 0
fi

# Docker install option
info "Collecting Docker install preference..."
if [ "$MODE" = "deploy" ]; then
  prompt_var INSTALL_DOCKER "Install Docker if missing? (yes/no)" "no" "" 0
else
  INSTALL_DOCKER="${INSTALL_DOCKER:-no}"
fi
INSTALL_DOCKER="$(echo "$INSTALL_DOCKER" | tr '[:upper:]' '[:lower:]')"
if [ "$INSTALL_DOCKER" != "yes" ] && [ "$INSTALL_DOCKER" != "no" ] && [ -n "$INSTALL_DOCKER" ]; then
  die "INSTALL_DOCKER must be 'yes' or 'no'"
fi

# Prepare .env for upload
SYNC_ENV="${SYNC_ENV:-auto}"
SYNC_ENV="$(echo "$SYNC_ENV" | tr '[:upper:]' '[:lower:]')"
if [ "$SYNC_ENV" != "auto" ] && [ "$SYNC_ENV" != "yes" ] && [ "$SYNC_ENV" != "no" ]; then
  die "SYNC_ENV must be auto, yes, or no"
fi

if [ "$MODE" = "deploy" ]; then
  info "Preparing temporary .env for upload..."
  ENV_FILE="$(mktemp)"
  chmod 600 "$ENV_FILE"

  escape_env() {
    # Escape for .env (double-quoted string)
    local v="$1"
    v="${v//\\/\\\\}"
    v="${v//\"/\\\"}"
    printf '"%s"' "$v"
  }
  emit_env_optional() {
    local key="$1"
    local val="$2"
    if [ -n "$val" ]; then
      echo "${key}=$(escape_env "$val")"
    fi
  }

  {
    echo "POSTGRES_DB=$(escape_env "$POSTGRES_DB")"
    echo "POSTGRES_USER=$(escape_env "$POSTGRES_USER")"
    echo "POSTGRES_PASSWORD=$(escape_env "$POSTGRES_PASSWORD")"
    echo "DATABASE_URL=$(escape_env "$DATABASE_URL")"
    echo "TELEGRAM_BOT_TOKEN=$(escape_env "$TELEGRAM_BOT_TOKEN")"
    echo "ADMIN_USER_ID=$(escape_env "$ADMIN_USER_ID")"
    emit_env_optional "API_KEY" "$API_KEY"
    emit_env_optional "BASE_URL" "$BASE_URL"
    emit_env_optional "DEFAULT_MODEL" "$DEFAULT_MODEL"
    emit_env_optional "LOG_FORMAT" "$LOG_FORMAT"
  } > "$ENV_FILE"
else
  if [ "$SYNC_ENV" = "auto" ]; then
    if [ -f "$ENV_PATH" ]; then
      SYNC_ENV="yes"
    else
      SYNC_ENV="no"
    fi
  fi
  if [ "$SYNC_ENV" = "yes" ]; then
    info "Preparing temporary .env from $ENV_PATH"
    if [ ! -f "$ENV_PATH" ]; then
      die "Env file not found at $ENV_PATH"
    fi
    ENV_FILE="$(mktemp)"
    chmod 600 "$ENV_FILE"
    cp "$ENV_PATH" "$ENV_FILE"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && ! grep -q '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE"; then
      escape_env_update() {
        local v="$1"
        v="${v//\\/\\\\}"
        v="${v//\"/\\\"}"
        printf '"%s"' "$v"
      }
      echo "TELEGRAM_BOT_TOKEN=$(escape_env_update "$TELEGRAM_BOT_TOKEN")" >> "$ENV_FILE"
    fi
  fi
fi

# Summary
info "\nReview configuration:"
echo "Mode:            $MODE"
echo "Host:            $DEPLOY_HOST"
echo "User:            $DEPLOY_USER"
echo "Port:            $DEPLOY_PORT"
echo "Auth:            $DEPLOY_AUTH"
echo "App dir:         $APP_DIR"
if [ "$MODE" = "deploy" ]; then
  echo "Repo:            $REPO_URL"
  echo "Ref:             $REPO_BRANCH"
  echo "TELEGRAM_BOT_TOKEN: $(mask_secret "$TELEGRAM_BOT_TOKEN")"
  echo "ADMIN_USER_ID:   $ADMIN_USER_ID"
  echo "POSTGRES_DB:     $POSTGRES_DB"
  echo "POSTGRES_USER:   $POSTGRES_USER"
  echo "POSTGRES_PASSWORD: $(mask_secret "$POSTGRES_PASSWORD")"
  echo "DATABASE_URL:    $(mask_database_url "$DATABASE_URL")"
else
  echo "Ref:             ${REPO_BRANCH:-<keep current>}"
  echo "Env sync:        ${SYNC_ENV}"
fi

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

# Upload .env to remote temp (if prepared)
REMOTE_ENV=""
if [ -n "${ENV_FILE:-}" ]; then
  REMOTE_ENV="/tmp/xilma.env.$RANDOM.$RANDOM"
  info "Uploading .env to remote..."
  "${SCP_CMD[@]}" "${SCP_OPTS[@]}" "$ENV_FILE" "$SSH_TARGET:$REMOTE_ENV"
fi

# Build remote bootstrap script
info "Building remote bootstrap script..."
REMOTE_SCRIPT="$(mktemp)"
{
  cat <<'REMOTE_HEADER'
#!/usr/bin/env bash
set -euo pipefail
set -E
IFS=$'\n\t'
REMOTE_HEADER

  echo "MODE=$(shell_quote "$MODE")"
  echo "APP_DIR=$(shell_quote "$APP_DIR")"
  echo "REPO_URL=$(shell_quote "${REPO_URL:-}")"
  echo "BRANCH=$(shell_quote "${REPO_BRANCH:-}")"
  echo "ENV_SRC=$(shell_quote "$REMOTE_ENV")"
  echo "INSTALL_DOCKER=$(shell_quote "$INSTALL_DOCKER")"

  cat <<'REMOTE_EOF'

log() { echo "[+] $*"; }
warn() { echo "[!] $*"; }
err() { echo "[x] $*" >&2; }

die() { err "$*"; exit 1; }
on_error() {
  local code=$?
  local line=${BASH_LINENO[0]}
  local cmd=${BASH_COMMAND}
  err "Command failed (exit $code) at line $line: $cmd"
  exit "$code"
}
trap on_error ERR

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

# Prepare app directory / update flow
if [ "$MODE" = "update" ]; then
  if [ ! -d "$APP_DIR/.git" ]; then
    die "Update mode requires an existing git repo at $APP_DIR"
  fi
  log "Updating repo in $APP_DIR"
  cd "$APP_DIR"
  git fetch --all --prune
  if [ -n "$BRANCH" ]; then
    git checkout "$BRANCH"
  fi
  if git symbolic-ref -q HEAD >/dev/null 2>&1; then
    git pull --ff-only
  fi
else
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

  # Install .env if provided
  if [ -n "${ENV_SRC:-}" ]; then
    if [ ! -f "$ENV_SRC" ]; then
      die "Remote env file not found: $ENV_SRC"
    fi
    log "Installing .env"
    install -m 600 "$ENV_SRC" "$APP_DIR/.env"
    rm -f "$ENV_SRC"
  fi
fi

# Install .env on update if provided
if [ "$MODE" = "update" ] && [ -n "${ENV_SRC:-}" ]; then
  if [ ! -f "$ENV_SRC" ]; then
    warn "Remote env file not found: $ENV_SRC"
  else
    log "Installing .env"
    install -m 600 "$ENV_SRC" "$APP_DIR/.env"
    rm -f "$ENV_SRC"
  fi
fi

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
