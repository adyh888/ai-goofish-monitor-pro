#!/usr/bin/env bash
################################################################################
# 闲鱼监控系统 - 重建容器使配置生效 (在云服务器上运行)
#
# 用法:
#   bash deploy/restart.sh        # 改了 .env(如端口/密码/Key)后执行, 几秒生效
#
# 说明:
#   · 自动识别部署模式(自构建/官方镜像), 用与部署时一致的配置重建容器
#   · 改端口示例: vim .env 改 SERVER_PORT → bash deploy/restart.sh
#   · 会做健康检查并打印最新访问地址
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$APP_DIR"

# 无 docker 权限时自动用 sudo 重跑自己
if ! docker compose ps >/dev/null 2>&1; then
  exec sudo bash "$SCRIPT_DIR/restart.sh" "$@"
fi

[[ -f docker-compose.yaml ]] || { echo "未找到 docker-compose.yaml, 请在项目目录结构下运行" >&2; exit 1; }

# 与部署时保持一致的 compose 文件组合
COMPOSE_FILES=()
BUILD_MODE=0
if [[ -f docker-compose.build.yaml ]]; then
  COMPOSE_FILES=(-f docker-compose.yaml -f docker-compose.build.yaml)
  BUILD_MODE=1
  log "检测到自构建模式部署, 使用 docker-compose.yaml + docker-compose.build.yaml"
fi

PORT=$(grep -E '^SERVER_PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d ' "' || true)
PORT=${PORT:-8000}

log "重建容器中(应用最新 .env 配置, 端口 $PORT)..."
# 兼容 bash 4.2 以下: set -u 时展开空数组会报错
if [[ $BUILD_MODE -eq 1 ]]; then
  docker compose ${COMPOSE_FILES[@]+"${COMPOSE_FILES[@]}"} up -d --build
else
  docker compose up -d --remove-orphans
fi

# 健康检查
ok=0
for _ in $(seq 1 15); do
  if curl -m 3 -s -o /dev/null "http://127.0.0.1:$PORT/"; then ok=1; break; fi
  sleep 2
done
if [[ $ok -eq 1 ]]; then
  log "服务正常 ✔"
else
  warn "端口 $PORT 暂未响应, 查看日志: bash deploy/logs.sh"
fi

SERVER_IP=$(curl -m 3 -s ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "<服务器IP>")
echo ""
log "访问地址: http://$SERVER_IP:$PORT"
if [[ $PORT != "8000" ]]; then
  warn "记得确认防火墙/云安全组已放行 TCP $PORT"
fi
