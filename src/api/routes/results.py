"""
结果文件管理路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from enum import Enum

from pydantic import BaseModel
from urllib.parse import quote

from src.services.price_history_service import build_price_history_insights
from src.services.result_export_service import build_results_csv
from src.services.result_file_service import (
    enrich_records_with_price_insight,
    validate_result_filename,
)
from src.api.dependencies import get_current_user
from src.infrastructure.persistence.user_repository import User
from src.services.result_storage_service import (
    build_result_ndjson,
    delete_result_file_records,
    list_result_filenames,
    load_all_result_records,
    load_result_blacklist_keywords,
    load_visible_result_item_ids,
    query_result_records,
    result_file_exists,
    save_result_blacklist_keywords,
    update_item_status,
)


router = APIRouter(prefix="/api/results", tags=["results"])

DEFAULT_EXPORT_FILENAME = "export.csv"


def _user_scope(current_user: User) -> int | None:
    """管理员可见全部结果文件，普通用户仅限本人。"""
    return None if current_user.is_admin else current_user.id


def _build_download_headers(export_name: str) -> dict[str, str]:
    ascii_name = export_name.encode("ascii", "ignore").decode("ascii")
    if ascii_name != export_name or not ascii_name:
        ascii_name = DEFAULT_EXPORT_FILENAME
    encoded_name = quote(export_name, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{encoded_name}"
        )
    }


@router.get("/files")
async def get_result_files(current_user: User = Depends(get_current_user)):
    """获取当前用户的结果文件列表"""
    return {"files": await list_result_filenames(user_id=_user_scope(current_user))}


@router.get("/files/{filename:path}")
async def download_result_file(filename: str, current_user: User = Depends(get_current_user)):
    """下载指定的结果文件"""
    if ".." in filename or filename.startswith("/"):
        return {"error": "非法的文件路径"}
    scope = _user_scope(current_user)
    if not filename.endswith(".jsonl") or not await result_file_exists(filename, scope):
        return {"error": "文件不存在"}
    return Response(
        content=await build_result_ndjson(filename, scope),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/files/{filename:path}")
async def delete_result_file(filename: str, current_user: User = Depends(get_current_user)):
    """删除指定的结果文件"""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="非法的文件路径")
    if not filename.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="只能删除 .jsonl 文件")
    deleted_rows = await delete_result_file_records(filename, user_id=_user_scope(current_user))
    if deleted_rows <= 0:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"message": f"文件 {filename} 已成功删除"}


@router.get("/{filename}")
async def get_result_file_content(
    filename: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    recommended_only: bool = Query(False),  # 兼容旧参数，等价于 ai_recommended_only
    ai_recommended_only: bool = Query(False),
    keyword_recommended_only: bool = Query(False),
    include_hidden: bool = Query(False),
    sort_by: str = Query("crawl_time"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(get_current_user),
):
    """读取指定的 .jsonl 文件内容，支持分页、筛选和排序"""
    if ai_recommended_only and keyword_recommended_only:
        raise HTTPException(status_code=400, detail="AI推荐筛选与关键词推荐筛选不能同时开启。")

    if recommended_only and not ai_recommended_only and not keyword_recommended_only:
        ai_recommended_only = True

    try:
        validate_result_filename(filename)
        total_items, items = await query_result_records(
            filename,
            ai_recommended_only=ai_recommended_only,
            keyword_recommended_only=keyword_recommended_only,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            limit=limit,
            include_hidden=include_hidden,
            user_id=_user_scope(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取结果文件时出错: {exc}")
    if total_items <= 0 and not await result_file_exists(filename, _user_scope(current_user)):
        raise HTTPException(status_code=404, detail="结果文件未找到")
    paginated_results = enrich_records_with_price_insight(
        items, filename, user_id=_user_scope(current_user)
    )

    return {
        "total_items": total_items,
        "page": page,
        "limit": limit,
        "items": paginated_results
    }


@router.get("/{filename}/insights")
async def get_result_file_insights(filename: str, current_user: User = Depends(get_current_user)):
    try:
        validate_result_filename(filename)
        keyword = filename.replace("_full_data.jsonl", "")
        scope = _user_scope(current_user)
        visible_item_ids = load_visible_result_item_ids(filename, scope)
        return build_price_history_insights(
            keyword, visible_item_ids=visible_item_ids, user_id=scope
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{filename}/export")
async def export_result_file_content(
    filename: str,
    recommended_only: bool = Query(False),
    ai_recommended_only: bool = Query(False),
    keyword_recommended_only: bool = Query(False),
    include_hidden: bool = Query(False),
    sort_by: str = Query("crawl_time"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(get_current_user),
):
    if ai_recommended_only and keyword_recommended_only:
        raise HTTPException(status_code=400, detail="AI推荐筛选与关键词推荐筛选不能同时开启。")
    if recommended_only and not ai_recommended_only and not keyword_recommended_only:
        ai_recommended_only = True

    try:
        validate_result_filename(filename)
        results = await load_all_result_records(
            filename,
            ai_recommended_only=ai_recommended_only,
            keyword_recommended_only=keyword_recommended_only,
            sort_by=sort_by,
            sort_order=sort_order,
            include_hidden=include_hidden,
            user_id=_user_scope(current_user),
        )
        csv_text = build_results_csv(
            enrich_records_with_price_insight(
                results, filename, user_id=_user_scope(current_user)
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导出结果文件时出错: {exc}")
    if not results and not await result_file_exists(filename, _user_scope(current_user)):
        raise HTTPException(status_code=404, detail="结果文件未找到")

    export_name = filename.replace(".jsonl", ".csv")
    headers = _build_download_headers(export_name)
    return Response(content=csv_text, media_type="text/csv; charset=utf-8", headers=headers)


class ItemStatus(str, Enum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    EXPIRED = "expired"


class UpdateStatusRequest(BaseModel):
    status: ItemStatus


class BlacklistRulesRequest(BaseModel):
    keywords: list[str]


@router.patch("/{filename}/items/{item_id}/status")
async def patch_item_status(
    filename: str,
    item_id: str,
    body: UpdateStatusRequest,
    current_user: User = Depends(get_current_user),
):
    """更新指定商品的状态（active/hidden/expired）"""
    try:
        validate_result_filename(filename)
        updated = await update_item_status(
            filename, item_id, body.status.value, user_id=_user_scope(current_user)
        )
        if not updated:
            raise HTTPException(status_code=404, detail="商品未找到")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "状态已更新", "status": body.status.value}


@router.get("/{filename}/blacklist-rules")
async def get_result_blacklist_rules(filename: str, current_user: User = Depends(get_current_user)):
    try:
        validate_result_filename(filename)
        keywords = await load_result_blacklist_keywords(
            filename, user_id=_user_scope(current_user)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"keywords": keywords}


@router.put("/{filename}/blacklist-rules")
async def put_result_blacklist_rules(
    filename: str,
    body: BlacklistRulesRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        validate_result_filename(filename)
        keywords = await save_result_blacklist_keywords(
            filename, body.keywords, user_id=_user_scope(current_user)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "黑名单规则已更新", "keywords": keywords}
