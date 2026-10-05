"""
闲鱼账号管理路由
"""
import json
import os
import re
import aiofiles
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from src.api.dependencies import get_current_user
from src.infrastructure.persistence.user_repository import User
from src.utils import get_user_state_dir


router = APIRouter(prefix="/api/accounts", tags=["accounts"])

ACCOUNT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


class AccountCreate(BaseModel):
    name: str
    content: str


class AccountUpdate(BaseModel):
    content: str


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return value[1:-1]
    return value


def _state_dir(current_user: User) -> str:
    """当前用户的登录态目录：state/u{user_id}/（多用户隔离）。"""
    return get_user_state_dir(current_user.id)


def _ensure_state_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed or not ACCOUNT_NAME_RE.match(trimmed):
        raise HTTPException(status_code=400, detail="账号名称只能包含字母、数字、下划线或短横线。")
    return trimmed


def _account_path(name: str, current_user: User) -> str:
    filename = f"{name}.json"
    return os.path.join(_state_dir(current_user), filename)


def _validate_json(content: str) -> None:
    try:
        json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="提供的内容不是有效的JSON格式。")


@router.get("", response_model=List[dict])
async def list_accounts(current_user: User = Depends(get_current_user)):
    state_dir = _state_dir(current_user)
    if not os.path.isdir(state_dir):
        return []
    files = [f for f in os.listdir(state_dir) if f.endswith(".json")]
    accounts = []
    for filename in sorted(files):
        name = filename[:-5]
        accounts.append({
            "name": name,
            "path": os.path.join(state_dir, filename),
        })
    return accounts


@router.get("/{name}", response_model=dict)
async def get_account(name: str, current_user: User = Depends(get_current_user)):
    account_name = _validate_name(name)
    path = _account_path(account_name, current_user)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return {"name": account_name, "path": path, "content": content}


@router.post("", response_model=dict)
async def create_account(
    data: AccountCreate,
    current_user: User = Depends(get_current_user),
):
    account_name = _validate_name(data.name)
    _validate_json(data.content)
    state_dir = _state_dir(current_user)
    _ensure_state_dir(state_dir)
    path = _account_path(account_name, current_user)
    if os.path.exists(path):
        raise HTTPException(status_code=409, detail="账号已存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(data.content)
    return {"message": "账号已添加", "name": account_name, "path": path}


@router.put("/{name}", response_model=dict)
async def update_account(
    name: str,
    data: AccountUpdate,
    current_user: User = Depends(get_current_user),
):
    account_name = _validate_name(name)
    _validate_json(data.content)
    state_dir = _state_dir(current_user)
    _ensure_state_dir(state_dir)
    path = _account_path(account_name, current_user)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(data.content)
    return {"message": "账号已更新", "name": account_name, "path": path}


@router.delete("/{name}", response_model=dict)
async def delete_account(name: str, current_user: User = Depends(get_current_user)):
    account_name = _validate_name(name)
    path = _account_path(account_name, current_user)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    os.remove(path)
    return {"message": "账号已删除"}
