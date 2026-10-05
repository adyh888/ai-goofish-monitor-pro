"""
Prompt 管理路由
"""
import os
import aiofiles
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import get_current_user
from src.infrastructure.persistence.user_repository import User
from src.utils import get_user_prompt_dir


router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_SYSTEM_PROMPTS_DIR = Path("prompts").resolve()


def _user_prompts_dir(current_user: User) -> Path:
    return Path(get_user_prompt_dir(current_user.id)).resolve()


def _safe_prompt_path(filename: str, base_dir: Path) -> Path:
    """返回经过 containment 检查的绝对路径，防止任意 OS 上的路径穿越。"""
    try:
        resolved = (base_dir / filename).resolve()
        resolved.relative_to(base_dir)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="无效的文件名")
    return resolved


class PromptUpdate(BaseModel):
    """Prompt 更新模型"""
    content: str


@router.get("")
async def list_prompts(current_user: User = Depends(get_current_user)):
    """列出当前用户的 prompt 文件"""
    prompts_dir = _user_prompts_dir(current_user)
    if not prompts_dir.is_dir():
        return []
    return [f for f in os.listdir(prompts_dir) if f.endswith(".txt")]


@router.get("/{filename}")
async def get_prompt(filename: str, current_user: User = Depends(get_current_user)):
    """获取 prompt 文件内容（用户目录优先，缺失时非管理员可回读系统模板）"""
    prompts_dir = _user_prompts_dir(current_user)
    filepath = _safe_prompt_path(filename, prompts_dir)
    if not filepath.exists():
        if current_user.is_admin:
            raise HTTPException(status_code=404, detail="Prompt 文件未找到")
        system_fallback = _safe_prompt_path(filename, _SYSTEM_PROMPTS_DIR)
        if not system_fallback.exists():
            raise HTTPException(status_code=404, detail="Prompt 文件未找到")
        filepath = system_fallback

    async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
        content = await f.read()
    return {"filename": filepath.name, "content": content}


@router.put("/{filename}")
async def update_prompt(
    filename: str,
    prompt_update: PromptUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新 prompt 文件内容（写入用户自己的目录；系统模板不会被改动）"""
    prompts_dir = _user_prompts_dir(current_user)
    os.makedirs(prompts_dir, exist_ok=True)
    filepath = _safe_prompt_path(filename, prompts_dir)

    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(prompt_update.content)
        return {"message": f"Prompt 文件 '{filepath.name}' 更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件时出错: {e}")
