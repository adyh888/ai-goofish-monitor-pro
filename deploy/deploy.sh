#!/usr/bin/env bash
################################################################################
# 闲鱼智能监控系统 - 云服务器一键部署 / 更新脚本
#
# 用法:
#   sudo bash deploy.sh                  # 拉取官方镜像部署(推荐, 最快)
#   sudo bash deploy.sh --build          # 用当前目录代码在服务器上构建镜像(含你自己的改动)
#   sudo bash deploy.sh --port 8001      # 指定宿主机访问端口(默认读 .env 的 SERVER_PORT)
#
# 可重复执行: 已有 .env / 已修改的 compose 端口映射不会被覆盖; 重跑即为更新。
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

REPO_URL="https://github.com/Usagi-org/ai-goofish-monitor"
GHCR_OFFICIAL="ghcr.io/usagi-org/ai-goofish:latest"
GHCR_MIRROR="ghcr.nju.edu.cn/usagi-org/ai-goofish:latest"
GH_PROXIES=("https://ghfast.top/" "https://gh-proxy.com/" "https://ghproxy.net/")

MODE="image"; ARG_PORT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) MODE="build"; shift ;;
    --port)  ARG_PORT="${2:?--port 需要一个端口号}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
    *) err "未知参数: $1"; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { err "请使用 root 权限运行: sudo bash $0"; exit 1; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# ---------- 基础工具 ----------
if ! command -v curl >/dev/null 2>&1; then
  log "安装 curl ..."
  if command -v apt-get >/dev/null 2>&1; then apt-get update -y && apt-get install -y curl
  else yum install -y curl || dnf install -y curl; fi
fi

# ---------- Docker 检查(缺失则自动调用同目录 install-docker.sh) ----------
if ! command -v docker >/dev/null 2>&1; then
  if [[ -f "$SCRIPT_DIR/install-docker.sh" ]]; then
    log "未检测到 Docker, 自动执行安装脚本..."
    bash "$SCRIPT_DIR/install-docker.sh"
  else
    err "未安装 Docker, 且同目录找不到 install-docker.sh, 请先安装 Docker"; exit 1
  fi
fi
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  err "未检测到 Docker Compose, 请重新运行 install-docker.sh"; exit 1
fi

# ---------- 网络环境 ----------
detect_cn() { curl -m 5 -sfI https://download.docker.com/linux/ >/dev/null 2>&1 && return 1; return 0; }
detect_cn && IS_CN=1 || IS_CN=0

# ---------- 定位项目目录(向上查找; 找不到则克隆官方仓库) ----------
PROJECT_DIR=""
d=$SCRIPT_DIR
while [[ $d != "/" ]]; do
  [[ -f "$d/docker-compose.yaml" ]] && { PROJECT_DIR=$d; break; }
  d=$(dirname "$d")
done
if [[ -z $PROJECT_DIR && -f "$PWD/docker-compose.yaml" ]]; then PROJECT_DIR=$PWD; fi
if [[ -z $PROJECT_DIR ]]; then
  log "未找到项目代码, 克隆官方仓库..."
  command -v git >/dev/null 2>&1 || {
    command -v apt-get >/dev/null 2>&1 && apt-get update -y && apt-get install -y git \
      || yum install -y git || dnf install -y git; }
  git clone "$REPO_URL" "$PWD/ai-goofish-monitor" 2>/dev/null || {
    ok=0
    for p in "${GH_PROXIES[@]}"; do
      log "直连失败, 尝试加速通道: $p"
      git clone "${p}${REPO_URL}" "$PWD/ai-goofish-monitor" && { ok=1; break; }
    done
    [[ $ok -eq 1 ]] || { err "仓库克隆失败, 请手动上传代码后重试"; exit 1; }
  }
  PROJECT_DIR="$PWD/ai-goofish-monitor"
fi
cd "$PROJECT_DIR"
log "项目目录: $PROJECT_DIR"

# ---------- .env / config.json 初始化与检查 ----------
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    log "已根据 .env.example 生成 .env"
  else
    err "目录里缺少 .env 和 .env.example (上传时注意保留隐藏文件), 无法继续"; exit 1
  fi
fi
# config.json 缺失时必须补齐, 否则 docker 挂载会创建同名目录导致启动失败
if [[ ! -f config.json ]]; then
  if [[ -f config.json.example ]]; then
    cp config.json.example config.json
    log "未找到 config.json, 已由 config.json.example 生成"
  else
    echo '[]' > config.json
    log "未找到 config.json, 已生成空任务配置"
  fi
fi
if grep -qE '^OPENAI_API_KEY=sk-\.\.\.' .env || grep -qE '^OPENAI_API_KEY=\s*$' .env; then
  warn ".env 中 OPENAI_API_KEY 还是占位符, AI 分析将不可用!"
  warn "请编辑: vim $PROJECT_DIR/.env 填写 API Key 后重新运行本脚本"
fi
if grep -qE '^WEB_PASSWORD=admin123' .env; then
  warn "Web 管理界面密码为默认值 admin123, 服务暴露公网前请务必修改 .env 中的 WEB_PASSWORD!"
fi

# ---------- 端口处理: 将 compose 端口映射参数化, 以 .env 的 SERVER_PORT 为准 ----------
PORT=${ARG_PORT:-$(grep -E '^SERVER_PORT=' .env | cut -d= -f2- | tr -d ' "' || true)}
PORT=${PORT:-8000}
if grep -q '"8000:8000"' docker-compose.yaml; then
  sed -i.bak 's/- "8000:8000"/- "${SERVER_PORT:-8000}:${SERVER_PORT:-8000}"/' docker-compose.yaml \
    && rm -f docker-compose.yaml.bak
  log "已将 docker-compose.yaml 端口映射参数化为 \${SERVER_PORT:-8000}"
fi
log "宿主机访问端口: $PORT"

update_env() {  # update_env KEY VALUE
  { grep -v "^$1=" .env || true; echo "$1=$2"; } > .env.tmp && mv .env.tmp .env
}

# ---------- 镜像准备 ----------
if [[ $MODE == "image" ]]; then
  if [[ $IS_CN -eq 1 ]]; then
    log "国内环境: 优先从南大镜像 (ghcr.nju.edu.cn) 拉取官方镜像..."
    if docker pull "$GHCR_MIRROR"; then
      update_env APP_IMAGE "$GHCR_MIRROR"
      log "已将 .env 中 APP_IMAGE 固定为南大镜像地址, 后续 docker compose pull 均走镜像源"
    elif docker pull "$GHCR_OFFICIAL"; then
      update_env APP_IMAGE "$GHCR_OFFICIAL"
    else
      err "官方镜像拉取失败。可选择: 1) 重试  2) 使用 --build 用代码自行构建镜像"
      exit 1
    fi
  else
    docker pull "$GHCR_OFFICIAL" || { err "官方镜像拉取失败, 请检查网络后重试"; exit 1; }
  fi
fi

# ---------- 构建模式 ----------
BUILD_FILES=()
if [[ $MODE == "build" ]]; then
  log "构建模式: 使用当前目录代码构建镜像 (首次构建需 5-15 分钟)..."
  local_mem=$(free -m 2>/dev/null | awk '/^Mem/{print $2}')
  local_mem=${local_mem:-0}
  if [[ $local_mem -gt 0 && $local_mem -lt 1800 ]]; then
    warn "服务器内存仅 ${local_mem}MB, 构建 Vue 前端可能内存不足, 建议先添加 2G swap:"
    warn "  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
  fi
  cat > docker-compose.build.yaml <<'YAML'
services:
  app:
    image: ai-goofish-monitor:local
    build:
      context: .
      dockerfile: Dockerfile
    pull_policy: build
YAML
  BUILD_FILES=(-f docker-compose.yaml -f docker-compose.build.yaml)
fi

# ---------- 启动 ----------
log "启动服务..."
# 兼容 bash 4.2 以下: set -u 时展开空数组会报错
"${COMPOSE[@]}" ${BUILD_FILES[@]+"${BUILD_FILES[@]}"} up -d --remove-orphans

# ---------- 防火墙放行(尽力而为; 云控制台安全组需手动放行!) ----------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qw active; then
  ufw allow "$PORT/tcp" >/dev/null 2>&1 || true
  log "已通过 ufw 放行端口 $PORT"
fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  log "已通过 firewalld 放行端口 $PORT"
fi

# ---------- 健康检查 ----------
log "等待服务启动..."
ok=0
for _ in $(seq 1 30); do
  if curl -m 3 -s -o /dev/null "http://127.0.0.1:$PORT/"; then ok=1; break; fi
  sleep 2
done
if [[ $ok -eq 1 ]]; then
  log "服务已启动 ✔"
else
  warn "端口 $PORT 暂未响应, 可稍后手动检查: docker compose logs -f app"
fi

# ---------- 完成信息 ----------
SERVER_IP=$(curl -m 3 -s ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "<服务器IP>")
WEB_USER=$(grep -E '^WEB_USERNAME=' .env | cut -d= -f2- | tr -d ' "' || echo admin)
echo ""
echo -e "${C_GREEN}========================================================${C_RESET}"
echo -e "${C_GREEN}  🎉 部署完成!${C_RESET}"
echo -e "${C_GREEN}========================================================${C_RESET}"
echo -e "  访问地址:  ${C_GREEN}http://$SERVER_IP:$PORT${C_RESET}"
echo -e "  登录账号:  $WEB_USER  (密码见 .env 的 WEB_PASSWORD)"
echo ""
echo -e "  ${C_YELLOW}⚠ 别忘了在云控制台【安全组】放行 TCP $PORT 端口, 否则无法从外网访问!${C_RESET}"
echo ""
echo "  常用命令:"
echo "    查看日志:   docker compose logs -f app"
echo "    重启服务:   docker compose restart"
echo "    停止服务:   docker compose down"
echo "    修改配置:   vim .env 后执行 docker compose up -d"
echo "    更新程序:   重新运行本脚本 (自构建模式: 上传新代码后 bash deploy.sh --build)"
