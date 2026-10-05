"""
登录状态管理路由
"""
import os
import json
import aiofiles
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import get_current_user
from src.infrastructure.persistence.user_repository import User
from src.utils import get_user_state_dir, get_user_state_file


router = APIRouter(prefix="/api/login-state", tags=["login-state"])


class LoginStateUpdate(BaseModel):
    """登录状态更新模型"""
    content: str


@router.post("", response_model=dict)
async def update_login_state(
    data: LoginStateUpdate,
    current_user: User = Depends(get_current_user),
):
    """接收前端发送的登录状态JSON字符串，保存到当前用户的登录态文件。"""
    os.makedirs(get_user_state_dir(current_user.id), exist_ok=True)
    state_file = get_user_state_file(current_user.id)

    try:
        # 验证是否是有效的JSON
        json.loads(data.content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="提供的内容不是有效的JSON格式。")

    try:
        async with aiofiles.open(state_file, 'w', encoding='utf-8') as f:
            await f.write(data.content)
        return {"message": f"登录状态文件 '{state_file}' 已成功更新。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入登录状态文件时出错: {e}")


@router.delete("", response_model=dict)
async def delete_login_state(current_user: User = Depends(get_current_user)):
    """删除当前用户的登录态文件"""
    state_file = get_user_state_file(current_user.id)

    if os.path.exists(state_file):
        try:
            os.remove(state_file)
            return {"message": "登录状态文件已成功删除。"}
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"删除登录状态文件时出错: {e}")

    return {"message": "登录状态文件不存在，无需删除。"}
