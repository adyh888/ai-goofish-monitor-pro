#!/usr/bin/env bash
################################################################################
# 闲鱼监控系统 - 一键推送自己的代码并部署/更新到云服务器 (在自己电脑上运行)
#
# 首次使用:  bash deploy/push.sh
#            (首次会询问服务器信息并记住; 引导配置一次免密登录; 自动装 Docker)
# 以后更新:  改完代码 → 再跑一遍 bash deploy/push.sh 即可, 没有别的步骤
#
# 可选参数:
#   --sync-config   强制用本地的 config.json 和 prompts/ 覆盖服务器上的
#                   (默认: 仅服务器缺失时才上传, 避免覆盖你在网页端改的任务)
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

SYNC_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --sync-config) SYNC_CONFIG=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
    *) err "未知参数: $arg"; exit 1 ;;
  esac
done

command -v rsync >/dev/null 2>&1 || { err "本机缺少 rsync, 请先安装: brew install rsync"; exit 1; }

# ---------- 定位项目根目录(向上查找 docker-compose.yaml) ----------
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=""
d=$SCRIPT_DIR
while [[ $d != "/" ]]; do
  [[ -f "$d/docker-compose.yaml" ]] && { PROJECT_ROOT=$d; break; }
  d=$(dirname "$d")
done
[[ -n $PROJECT_ROOT ]] || { err "请在项目目录内运行本脚本"; exit 1; }

# ---------- 读取 / 初始化服务器配置 ----------
CONF="$SCRIPT_DIR/server.conf"
if [[ -f $CONF ]] && grep -q '^SERVER_IP=.' "$CONF"; then
  # shellcheck disable=SC1090
  source "$CONF"
  log "目标服务器: $SERVER_USER@$SERVER_IP (SSH:$SSH_PORT, 目录:$APP_DIR)"
  log "配置来自 $CONF, 换服务器请编辑该文件"
else
  echo "首次使用, 请回答以下问题 (直接回车 = 用默认值, 之后不再询问):"
  read -r -p "  服务器公网 IP: " SERVER_IP
  [[ -n ${SERVER_IP:-} ]] || { err "必须填写服务器 IP"; exit 1; }
  read -r -p "  SSH 端口 [22]: " SSH_PORT; SSH_PORT=${SSH_PORT:-22}
  read -r -p "  登录用户 [root]: " SERVER_USER; SERVER_USER=${SERVER_USER:-root}
  read -r -p "  应用安装目录 [/opt/ai-goofish-monitor]: " APP_DIR
  APP_DIR=${APP_DIR:-/opt/ai-goofish-monitor}
  cat > "$CONF" <<EOF
SERVER_IP=$SERVER_IP
SSH_PORT=$SSH_PORT
SERVER_USER=$SERVER_USER
APP_DIR=$APP_DIR
EOF
  chmod 600 "$CONF"
  log "配置已保存到 $CONF, 以后一条命令直达"
fi

SSH_OPTS=(-o "Port=$SSH_PORT" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
REMOTE="$SERVER_USER@$SERVER_IP"
[[ $SERVER_USER == "root" ]] && SUDO="" || SUDO="sudo "

# ---------- 免密登录检查与引导 ----------
if ! ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$REMOTE" true 2>/dev/null; then
  warn "尚未配置免密登录, 现在配置一次 (输入服务器密码即可, 之后永久免密)"
  ssh-copy-id -o "Port=$SSH_PORT" -o "StrictHostKeyChecking=accept-new" "$REMOTE"
  ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$REMOTE" true 2>/dev/null \
    || { err "免密登录配置失败, 请手动执行: ssh-copy-id -o Port=$SSH_PORT $REMOTE 后重试"; exit 1; }
  log "免密登录配置成功 ✔"
fi

# ---------- 服务器端环境准备 ----------
log "准备服务器环境..."
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$APP_DIR'"
ssh "${SSH_OPTS[@]}" "$REMOTE" "command -v rsync >/dev/null 2>&1 || { $SUDO apt-get update -y >/dev/null 2>&1 && $SUDO apt-get install -y rsync || $SUDO yum install -y rsync || $SUDO dnf install -y rsync; }"

# ---------- 增量同步代码 ----------
# 数据类目录/文件(.env、config.json、prompts、state、data 等)默认不上传,
# 避免 local 覆盖服务器上网页端产生的配置与数据; 配合 --delete, 远端受保护路径不受影响。
log "同步代码到服务器 (增量上传, 只传有改动的文件)..."
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'node_modules/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.DS_Store' \
  --exclude '.idea/' --exclude '.serena/' --exclude '.aider*' \
  --exclude 'dist/' --exclude '.backend.pid' --exclude 'xianyu_state.json' \
  --exclude 'data/' --exclude 'logs/' --exclude 'images/' --exclude 'jsonl/' \
  --exclude 'state/' --exclude 'price_history/' \
  --exclude '.env' --exclude 'config.json' --exclude 'prompts/' \
  "$PROJECT_ROOT/" "$REMOTE:$APP_DIR/"

# ---------- config.json / prompts: 首次上传, 或 --sync-config 强制覆盖 ----------
if [[ $SYNC_CONFIG -eq 1 ]]; then
  rsync -az "$PROJECT_ROOT/config.json" "$REMOTE:$APP_DIR/config.json"
  if [[ -d $PROJECT_ROOT/prompts ]]; then rsync -az --delete "$PROJECT_ROOT/prompts/" "$REMOTE:$APP_DIR/prompts/"; fi
  log "已强制覆盖服务器的 config.json 与 prompts/"
else
  if ! ssh "${SSH_OPTS[@]}" "$REMOTE" "test -f '$APP_DIR/config.json'"; then
    rsync -az "$PROJECT_ROOT/config.json" "$REMOTE:$APP_DIR/config.json"
    log "已上传初始 config.json (任务配置)"
  fi
  if [[ -d $PROJECT_ROOT/prompts ]] && ! ssh "${SSH_OPTS[@]}" "$REMOTE" "test -d '$APP_DIR/prompts'"; then
    rsync -az "$PROJECT_ROOT/prompts/" "$REMOTE:$APP_DIR/prompts/"
    log "已上传初始 prompts/ (AI 标准)"
  fi
fi

# ---------- 远端构建并启动 (deploy.sh 会自动装 Docker → 构建 → 启动 → 健康检查) ----------
log "在服务器上构建并启动 (首次构建 5-15 分钟, 之后增量构建只需几分钟)..."
ssh -t "${SSH_OPTS[@]}" "$REMOTE" "cd '$APP_DIR' && $SUDO bash deploy/deploy.sh --build"

# ---------- 完成信息 ----------
PORT=$(ssh "${SSH_OPTS[@]}" "$REMOTE" "grep -E '^SERVER_PORT=' '$APP_DIR/.env' 2>/dev/null | cut -d= -f2- | tr -d ' \"'" || true)
PORT=${PORT:-8000}
echo ""
echo -e "${C_GREEN}========================================================${C_RESET}"
echo -e "${C_GREEN}  🎉 全部完成!${C_RESET}"
echo -e "${C_GREEN}========================================================${C_RESET}"
echo -e "  访问地址:  ${C_GREEN}http://$SERVER_IP:$PORT${C_RESET}  (账号/密码见服务器 $APP_DIR/.env)"
echo -e "  ${C_YELLOW}⚠ 若外网打不开: 去云控制台【安全组】放行 TCP $PORT${C_RESET}"
echo ""
echo "  以后更新代码, 只需要两步:"
echo "    1. 在本机改代码"
echo "    2. 再运行一次:  bash deploy/push.sh"
echo ""
echo "  提示: 如果你在网页端改过任务/AI标准, 又在本地也改了, 想以本地为准推送:"
echo "        bash deploy/push.sh --sync-config"
