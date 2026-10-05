"""
WebSocket 路由
提供实时通信功能（连接需携带 JWT，广播按用户隔离）
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Optional, Set


router = APIRouter()

# 全局 WebSocket 连接管理：connection -> (用户 id, 是否管理员)
active_connections: dict[WebSocket, tuple[int, bool]] = {}


def _resolve_user_from_token(token: str | None) -> Optional[tuple[int, bool]]:
    if not token:
        return None
    try:
        from src.services.security import decode_access_token

        payload = decode_access_token(token)
        if not payload or not payload.get("sub"):
            return None
        from src.infrastructure.persistence.user_repository import (
            get_user_by_id_sync,
        )

        user = get_user_by_id_sync(int(payload["sub"]))
        if user is None or user.status != "active":
            return None
        return user.id, user.is_admin
    except Exception:
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    """WebSocket 端点（?token=<JWT> 握手认证）"""
    token = websocket.query_params.get("token")
    resolved = _resolve_user_from_token(token)
    if resolved is None:
        await websocket.close(code=4401)
        return

    # 接受连接
    await websocket.accept()
    active_connections[websocket] = resolved

    try:
        # 保持连接并接收消息
        while True:
            # 接收客户端消息（如果有的话）
            data = await websocket.receive_text()
            # 这里可以处理客户端发送的消息
            # 目前我们主要用于服务端推送，所以暂时不处理
    except WebSocketDisconnect:
        active_connections.pop(websocket, None)
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        active_connections.pop(websocket, None)


async def broadcast_message(message_type: str, data: dict, user_id: int | None = None):
    """广播消息。

    user_id=None：全员广播（系统级事件）；
    指定 user_id：仅推送给该用户与管理员。
    """
    message = {
        "type": message_type,
        "data": data
    }

    # 移除已断开的连接
    disconnected = []

    for connection, (owner_id, owner_is_admin) in list(active_connections.items()):
        if user_id is not None and owner_id != user_id and not owner_is_admin:
            continue
        try:
            await connection.send_json(message)
        except Exception:
            disconnected.append(connection)

    # 清理断开的连接
    for connection in disconnected:
        active_connections.pop(connection, None)
