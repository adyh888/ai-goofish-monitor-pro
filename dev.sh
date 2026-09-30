#!/bin/bash
# 闲鱼监控系统 - 本地运行脚本
#
# 用法:
#   ./dev.sh            一键启动：后端(后台) + 前端 dev(前台)，Ctrl+C 全部停止
#   ./dev.sh backend    只启动后端（前台，Ctrl+C 停止）
#   ./dev.sh frontend   只启动前端 dev（前台，需另开终端先跑 ./dev.sh backend）
#   ./dev.sh build      构建前端 + 后台启动后端（生产模式，单端口访问，无需 Node 常驻）
#   ./dev.sh stop       停止脚本启动的后台服务
#   ./dev.sh status     查看运行状态

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 从 .env 读取后端端口（默认 8000）
SERVER_PORT=$(grep -E '^SERVER_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]')
SERVER_PORT=${SERVER_PORT:-8000}
WEB_DEV_PORT=${WEB_DEV_PORT:-5173}

PYTHON="$SCRIPT_DIR/.venv/bin/python"
BACKEND_LOG="$SCRIPT_DIR/logs/backend-dev.log"
BACKEND_PID_FILE="$SCRIPT_DIR/.backend.pid"

ensure_venv() {
    if [ ! -x "$PYTHON" ]; then
        echo -e "${RED}✗ 未找到虚拟环境 .venv${NC}"
        echo "  请先执行:"
        echo "    uv venv --python 3.11 .venv"
        echo "    uv pip install --python .venv/bin/python -r requirements.txt"
        exit 1
    fi
}

backend_running() {
    [ -f "$BACKEND_PID_FILE" ] && kill -0 "$(cat "$BACKEND_PID_FILE")" 2>/dev/null
}

start_backend_bg() {
    ensure_venv
    if backend_running; then
        echo -e "${GREEN}✅ 后端已在运行${NC} (PID $(cat "$BACKEND_PID_FILE"), http://127.0.0.1:$SERVER_PORT)"
        return
    fi
    mkdir -p logs
    echo "🚀 启动后端..."
    nohup "$PYTHON" -m src.app > "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
    for _ in $(seq 1 30); do
        if curl -s -o /dev/null "http://127.0.0.1:$SERVER_PORT/"; then
            echo -e "${GREEN}✅ 后端已就绪${NC} (PID $(cat "$BACKEND_PID_FILE"))"
            echo "   Web UI : http://127.0.0.1:$SERVER_PORT"
            echo "   API 文档: http://127.0.0.1:$SERVER_PORT/docs"
            echo "   日志   : $BACKEND_LOG"
            return
        fi
        sleep 0.5
    done
    echo -e "${RED}⚠️  后端 15 秒内未就绪，请查看日志: $BACKEND_LOG${NC}"
}

stop_backend() {
    if backend_running; then
        local pid
        pid=$(cat "$BACKEND_PID_FILE")
        kill "$pid" 2>/dev/null && echo -e "${GREEN}🛑 已停止后端${NC} (PID $pid)"
    fi
    rm -f "$BACKEND_PID_FILE"
}

case "${1:-all}" in
    all)
        start_backend_bg
        trap stop_backend EXIT
        echo ""
        echo -e "${YELLOW}🌐 启动前端 dev 服务: http://127.0.0.1:$WEB_DEV_PORT${NC}"
        echo -e "${YELLOW}   (按 Ctrl+C 同时停止前端和后端)${NC}"
        echo ""
        cd web-ui
        if [ ! -d node_modules ]; then
            echo "📦 首次运行，安装前端依赖..."
            npm install --no-audit --no-fund
        fi
        npm run dev -- --port "$WEB_DEV_PORT" --strictPort
        ;;
    backend)
        ensure_venv
        echo -e "${GREEN}🚀 启动后端（前台）: http://127.0.0.1:$SERVER_PORT${NC}"
        echo -e "${YELLOW}   (Ctrl+C 停止；前端如需 dev 模式请另开终端执行 ./dev.sh frontend)${NC}"
        exec "$PYTHON" -m src.app
        ;;
    frontend)
        echo -e "${YELLOW}🌐 启动前端 dev（前台）: http://127.0.0.1:$WEB_DEV_PORT${NC}"
        echo -e "${YELLOW}   注意: 需要后端已在运行（另开终端执行 ./dev.sh backend），否则页面无数据${NC}"
        cd web-ui
        if [ ! -d node_modules ]; then
            echo "📦 首次运行，安装前端依赖..."
            npm install --no-audit --no-fund
        fi
        npm run dev -- --port "$WEB_DEV_PORT" --strictPort
        ;;
    build)
        ensure_venv
        echo "🔨 构建前端..."
        cd web-ui
        if [ ! -d node_modules ]; then
            echo "📦 首次运行，安装前端依赖..."
            npm install --no-audit --no-fund
        fi
        npm run build
        cd "$SCRIPT_DIR"
        echo -e "${GREEN}✅ 前端构建完成，产物已输出到 dist/${NC}"
        start_backend_bg
        echo -e "${GREEN}🎉 生产模式已启动，访问: http://127.0.0.1:$SERVER_PORT${NC}"
        echo -e "${YELLOW}   停止请执行: ./dev.sh stop${NC}"
        ;;
    stop)
        stop_backend
        ;;
    status)
        if backend_running; then
            echo -e "${GREEN}后端: 运行中${NC} (PID $(cat "$BACKEND_PID_FILE"), http://127.0.0.1:$SERVER_PORT)"
        elif curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$SERVER_PORT/"; then
            echo -e "${YELLOW}后端: 端口 $SERVER_PORT 有服务（非本脚本启动）${NC}"
        else
            echo -e "${RED}后端: 未运行${NC}"
        fi
        if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$WEB_DEV_PORT/"; then
            echo -e "${GREEN}前端 dev: 运行中${NC} (http://127.0.0.1:$WEB_DEV_PORT)"
        else
            echo -e "${RED}前端 dev: 未运行${NC}（生产模式无需前端 dev，后端直接托管 dist）"
        fi
        ;;
    *)
        echo "用法: ./dev.sh [all|backend|frontend|build|stop|status]"
        exit 1
        ;;
esac
