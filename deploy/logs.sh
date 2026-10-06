#!/usr/bin/env bash
################################################################################
# 闲鱼监控系统 - 查看应用日志 (在云服务器上运行)
#
# 用法:
#   bash deploy/logs.sh                 # 实时跟踪日志(等同 docker compose logs -f app), Ctrl+C 退出
#   bash deploy/logs.sh --tail 200      # 只看最近 200 行, 不跟踪
#   bash deploy/logs.sh --since 30m     # 看最近 30 分钟内的日志
#
# 说明: 在项目目录内外均可运行; 无 docker 权限时自动尝试 sudo。
################################################################################
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$APP_DIR"

# 非 root 且 docker 权限不足时, 自动用 sudo 重跑自己
if ! docker compose ps >/dev/null 2>&1; then
  exec sudo bash "$SCRIPT_DIR/logs.sh" "$@"
fi

if [[ $# -eq 0 ]]; then
  exec docker compose logs -f app
else
  exec docker compose logs "$@" app
fi
