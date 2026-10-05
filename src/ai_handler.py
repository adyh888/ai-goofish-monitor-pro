import asyncio
import base64
import json
import os
import re
import sys
import shutil
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests

# 设置标准输出编码为UTF-8，解决Windows控制台编码问题
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

from src.config import (
    AI_DEBUG_MODE,
    IMAGE_DOWNLOAD_HEADERS,
    IMAGE_SAVE_DIR,
    TASK_IMAGE_DIR_PREFIX,
    MODEL_NAME,
    ENABLE_RESPONSE_FORMAT,
    client,
)
from src.ai_message_builder import (
    build_analysis_text_prompt,
    build_user_message_content,
)
from src.services.ai_response_parser import (
    EmptyAIResponseError,
    extract_ai_response_content,
    parse_ai_response_json,
)
from src.services.ai_request_compat import (
    CHAT_COMPLETIONS_API_MODE,
    RESPONSES_API_MODE,
    build_ai_request_params,
    create_ai_response_async,
    is_chat_completions_api_unsupported_error,
    is_json_output_unsupported_error,
    is_responses_api_unsupported_error,
    is_temperature_unsupported_error,
    remove_temperature_param,
)
from src.services.notification_service import build_notification_service
from src.utils import (
    convert_goofish_link,
    get_spider_user_id,
    retry_on_failure,
    sanitize_filename,
)


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


from src.utils import get_spider_user_id  # noqa: E402  (爬虫用户上下文)


DEFAULT_IMAGE_DOWNLOAD_CONCURRENCY = max(
    1,
    _positive_int(os.getenv("IMAGE_DOWNLOAD_CONCURRENCY", "3"), 3),
)


def safe_print(text):
    """安全的打印函数，处理编码错误"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 如果遇到编码错误，尝试用ASCII编码并忽略无法编码的字符
        try:
            print(text.encode('ascii', errors='ignore').decode('ascii'))
        except:
            # 如果还是失败，打印一个简化的消息
            print("[输出包含无法显示的字符]")


def _build_debug_request_summary(api_mode: str, request_params: dict) -> dict:
    summary = {
        "api_mode": api_mode,
        "model": request_params.get("model"),
    }
    if "temperature" in request_params:
        summary["temperature"] = request_params["temperature"]
    if "max_output_tokens" in request_params:
        summary["max_output_tokens"] = request_params["max_output_tokens"]
    if "max_tokens" in request_params:
        summary["max_tokens"] = request_params["max_tokens"]
    if "text" in request_params:
        summary["text"] = request_params["text"]
    if "response_format" in request_params:
        summary["response_format"] = request_params["response_format"]
    if "input" in request_params:
        summary["input_content_types"] = [
            [item.get("type") for item in message.get("content", [])]
            for message in request_params["input"]
        ]
    if "messages" in request_params:
        summary["message_content_types"] = [
            _extract_message_content_types(message)
            for message in request_params["messages"]
        ]
    return summary


def _extract_message_content_types(message: dict) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return ["text"]
    if not isinstance(content, list):
        return [type(content).__name__]
    return [str(item.get("type")) for item in content if isinstance(item, dict)]


@retry_on_failure(retries=2, delay=3)
async def _download_single_image(url, save_path):
    """一个带重试的内部函数，用于异步下载单个图片。"""
    loop = asyncio.get_running_loop()
    # 使用 run_in_executor 运行同步的 requests 代码，避免阻塞事件循环
    response = await loop.run_in_executor(
        None,
        lambda: requests.get(url, headers=IMAGE_DOWNLOAD_HEADERS, timeout=20, stream=True)
    )
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


def _build_image_save_path(
    product_id: str,
    index: int,
    url: str,
    task_image_dir: str,
) -> str:
    clean_url = url.split('.heic')[0] if '.heic' in url else url
    file_name_base = os.path.basename(clean_url).split('?')[0]
    file_name = f"product_{product_id}_{index}_{file_name_base}"
    file_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
    if not os.path.splitext(file_name)[1]:
        file_name += ".jpg"
    return os.path.join(task_image_dir, file_name)


def build_task_image_dir(task_name, *, task_id: int | None = None) -> str:
    """任务图片目录：按 用户+任务 隔离，避免同名任务（跨用户或并发）互相清理。

    爬虫子进程内 user_id 取自 SPIDER_USER_ID 环境变量。
    """
    user_id = get_spider_user_id()
    parts = [f"u{user_id}"]
    if task_id:
        parts.append(f"t{int(task_id)}")
    safe_name = sanitize_filename(task_name)
    dir_name = f"{TASK_IMAGE_DIR_PREFIX}{'_'.join(parts)}_{safe_name}"
    return os.path.join(IMAGE_SAVE_DIR, dir_name)


async def download_all_images(
    product_id,
    image_urls,
    task_name="default",
    concurrency=None,
    task_id=None,
):
    """异步下载一个商品的所有图片。如果图片已存在则跳过。支持任务隔离。"""
    if not image_urls:
        return []

    # 为每个任务创建独立的图片目录
    task_image_dir = build_task_image_dir(task_name, task_id=task_id)
    os.makedirs(task_image_dir, exist_ok=True)

    urls = [url.strip() for url in image_urls if url.strip().startswith('http')]
    if not urls:
        return []

    max_concurrency = _positive_int(concurrency, DEFAULT_IMAGE_DOWNLOAD_CONCURRENCY)
    semaphore = asyncio.Semaphore(max_concurrency)
    total_images = len(urls)

    async def _download_one(index: int, url: str):
        save_path = _build_image_save_path(product_id, index, url, task_image_dir)
        if os.path.exists(save_path):
            safe_print(
                f"   [图片] 图片 {index}/{total_images} 已存在，跳过下载: {os.path.basename(save_path)}"
            )
            return save_path
        async with semaphore:
            safe_print(f"   [图片] 正在下载图片 {index}/{total_images}: {url}")
            if await _download_single_image(url, save_path):
                safe_print(
                    f"   [图片] 图片 {index}/{total_images} 已成功下载到: {os.path.basename(save_path)}"
                )
                return save_path
        return None

    tasks = [
        asyncio.create_task(_download_one(index, url))
        for index, url in enumerate(urls, start=1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    saved_paths = []
    for url, result in zip(urls, results):
        try:
            if isinstance(result, Exception):
                raise result
            if result:
                saved_paths.append(result)
        except Exception as e:
            safe_print(f"   [图片] 处理图片 {url} 时发生错误，已跳过此图: {e}")

    return saved_paths


def cleanup_task_images(task_name, task_id=None):
    """清理指定任务的图片目录（目录名含用户与任务 ID，与下载侧一致）。"""
    task_image_dir = build_task_image_dir(task_name, task_id=task_id)
    if os.path.exists(task_image_dir):
        try:
            shutil.rmtree(task_image_dir)
            safe_print(f"   [清理] 已删除任务 '{task_name}' 的临时图片目录: {task_image_dir}")
        except Exception as e:
            safe_print(f"   [清理] 删除任务 '{task_name}' 的临时图片目录时出错: {e}")
    else:
        safe_print(f"   [清理] 任务 '{task_name}' 的临时图片目录不存在: {task_image_dir}")


def cleanup_ai_logs(logs_dir: str, keep_days: int = 1) -> None:
    try:
        cutoff = datetime.now() - timedelta(days=keep_days)
        for filename in os.listdir(logs_dir):
            if not filename.endswith(".log"):
                continue
            try:
                timestamp = datetime.strptime(filename[:15], "%Y%m%d_%H%M%S")
            except ValueError:
                continue
            if timestamp < cutoff:
                os.remove(os.path.join(logs_dir, filename))
    except Exception as e:
        safe_print(f"   [日志] 清理AI日志时出错: {e}")


def encode_image_to_base64(image_path):
    """将本地图片文件编码为 Base64 字符串。"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        safe_print(f"编码图片时出错: {e}")
        return None


DEFAULT_PROMPT_VERSION = "EagleEye-V6.4"


def validate_ai_response_format(parsed_response):
    """验证AI响应的格式是否符合预期结构"""
    required_fields = [
        "is_recommended",
        "reason",
        "risk_tags",
        "criteria_analysis"
    ]

    # 检查顶层字段
    for field in required_fields:
        if field not in parsed_response:
            safe_print(f"   [AI分析] 警告：响应缺少必需字段 '{field}'")
            return False

    # prompt_version 是程序元数据，部分模型不回显；缺失时补齐而不是判失败
    if not parsed_response.get("prompt_version"):
        parsed_response["prompt_version"] = DEFAULT_PROMPT_VERSION

    # 检查criteria_analysis是否为字典且不为空
    criteria_analysis = parsed_response.get("criteria_analysis", {})
    if not isinstance(criteria_analysis, dict) or not criteria_analysis:
        safe_print("   [AI分析] 警告：criteria_analysis必须是非空字典")
        return False

    # 检查seller_type字段（所有商品都需要）
    if "seller_type" not in criteria_analysis:
        safe_print("   [AI分析] 警告：criteria_analysis缺少必需字段 'seller_type'")
        return False

    # 检查数据类型
    if not isinstance(parsed_response.get("is_recommended"), bool):
        safe_print("   [AI分析] 警告：is_recommended字段不是布尔类型")
        return False

    if not isinstance(parsed_response.get("risk_tags"), list):
        safe_print("   [AI分析] 警告：risk_tags字段不是列表类型")
        return False

    return True


@retry_on_failure(retries=3, delay=5)
async def send_ntfy_notification(product_data, reason, user_id=None):
    """兼容旧调用名，内部统一走 NotificationService（按任务归属人隔离配置）。"""
    resolved_user_id = user_id if user_id is not None else get_spider_user_id()
    service = build_notification_service(user_id=resolved_user_id)
    if not service.clients:
        safe_print(
            f"警告：用户 #{resolved_user_id} 未配置任何通知渠道，跳过通知。"
        )
        return {}

    results = await service.send_notification(product_data, reason)
    for channel, result in results.items():
        if result["success"]:
            safe_print(f"   -> {channel} 通知发送成功。")
            continue
        safe_print(f"   -> {channel} 通知发送失败: {result['message']}")
    return results


def _load_enabled_profiles():
    """读取当前任务归属人启用的 AI 模型配置（当前模型优先）。失败时返回空列表走 .env 兜底。"""
    try:
        from src.infrastructure.persistence.ai_profile_repository import (
            list_enabled_profiles_active_first_sync,
        )

        return list_enabled_profiles_active_first_sync(user_id=get_spider_user_id())
    except Exception as e:
        safe_print(f"   [AI分析] 读取多模型配置失败，回退到 .env 单模型配置: {e}")
        return []


def _build_profile_client(profile):
    import httpx
    from openai import AsyncOpenAI

    client_kwargs = {
        "api_key": profile.api_key or "no-key-required",
        "base_url": profile.base_url,
    }
    if profile.proxy_url:
        client_kwargs["http_client"] = httpx.AsyncClient(proxy=profile.proxy_url)
    return AsyncOpenAI(**client_kwargs)


async def _close_client_quietly(client) -> None:
    closer = getattr(client, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


async def get_ai_analysis(product_data, image_paths=None, prompt_text=""):
    """将完整的商品JSON数据和所有图片发送给 AI 进行分析（异步）。

    多模型 failover：从当前激活模型开始按优先级尝试，任一模型调用失败
    （额度用完/限流/认证失效/格式异常等）自动切换到下一个启用的模型；
    非首个候选成功时把激活位持久切换到该模型。
    """

    item_info = product_data.get('商品信息', {})
    product_id = item_info.get('商品ID', 'N/A')

    safe_print(f"\n   [AI分析] 开始分析商品 #{product_id} (含 {len(image_paths or [])} 张图片)...")
    safe_print(f"   [AI分析] 标题: {item_info.get('商品标题', '无')}")

    if not prompt_text:
        safe_print("   [AI分析] 错误：未提供AI分析所需的prompt文本。")
        return None

    product_details_json = json.dumps(product_data, ensure_ascii=False, indent=2)
    system_prompt = prompt_text

    if AI_DEBUG_MODE:
        safe_print("\n--- [AI DEBUG] ---")
        safe_print("--- PRODUCT DATA (JSON) ---")
        safe_print(product_details_json)
        safe_print("--- PROMPT TEXT (完整内容) ---")
        safe_print(prompt_text)
        safe_print("-------------------\n")

    image_data_urls = []
    if image_paths:
        for path in image_paths:
            base64_image = encode_image_to_base64(path)
            if base64_image:
                image_data_urls.append(f"data:image/jpeg;base64,{base64_image}")

    combined_text_prompt = build_analysis_text_prompt(
        product_details_json,
        system_prompt,
        include_images=bool(image_data_urls),
    )
    user_content = build_user_message_content(combined_text_prompt, image_data_urls)
    messages = [{"role": "user", "content": user_content}]

    # 保存最终传输内容到日志文件
    try:
        # 创建logs文件夹
        logs_dir = os.path.join("logs", "ai")
        os.makedirs(logs_dir, exist_ok=True)
        cleanup_ai_logs(logs_dir, keep_days=1)

        # 生成日志文件名（当前时间）
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{current_time}.log"
        log_filepath = os.path.join(logs_dir, log_filename)

        task_name = product_data.get("任务名称") or product_data.get("任务名") or "unknown"
        log_payload = {
            "timestamp": current_time,
            "task_name": task_name,
            "product_id": product_id,
            "title": item_info.get("商品标题", "无"),
            "image_count": len(image_data_urls),
        }
        log_content = json.dumps(log_payload, ensure_ascii=False)

        # 写入日志文件
        with open(log_filepath, 'w', encoding='utf-8') as f:
            f.write(log_content)

        safe_print(f"   [日志] AI分析请求已保存到: {log_filepath}")

    except Exception as e:
        safe_print(f"   [日志] 保存AI分析日志时出错: {e}")

    # 多模型 failover：候选 = 启用的模型配置（激活优先）；无配置时回退 .env 单模型
    profiles = _load_enabled_profiles()
    if profiles:
        candidates = list(profiles)
    elif client is not None:
        candidates = [None]  # None 代表 .env 兜底配置
    else:
        safe_print("   [AI分析] 错误：未配置任何 AI 模型（多模型配置为空且 .env 未配置），跳过分析。")
        return None

    last_error: Exception | None = None
    for idx, profile in enumerate(candidates):
        if profile is None:
            use_client = client
            model_name = MODEL_NAME
            profile_label = ".env配置"
        else:
            use_client = _build_profile_client(profile)
            model_name = profile.model_name
            profile_label = profile.name

        try:
            result = await _run_analysis_attempts(
                use_client, model_name, messages, product_id, profile_label
            )
            if idx > 0 and profile is not None:
                try:
                    from src.infrastructure.persistence.ai_profile_repository import (
                        set_active_profile_sync,
                    )

                    set_active_profile_sync(profile.id)
                    safe_print(f"   [AI分析] 当前模型已切换为 [{profile_label}]")
                except Exception as switch_error:
                    safe_print(f"   [AI分析] 切换当前模型失败: {switch_error}")
            return result
        except Exception as e:
            last_error = e
            if idx < len(candidates) - 1:
                safe_print(
                    f"   [AI分析] 模型[{profile_label}] 调用失败: {e}"
                )
                safe_print(
                    f"   [AI分析] 自动切换到下一个模型（还剩 {len(candidates) - idx - 1} 个候选）..."
                )
                continue
            raise
        finally:
            # 只关闭本次为 profile 新建的客户端；.env 兜底的 client 是进程级共享的，不能关
            if profile is not None:
                await _close_client_quietly(use_client)

    raise last_error  # pragma: no cover - 循环内必然 return 或 raise


async def _run_analysis_attempts(
    client, model_name, messages, product_id, profile_label
):
    """对单个模型执行带重试的分析调用（处理格式重试与 API 兼容性回退）。"""
    # 增强的AI调用，包含更严格的结构化输出控制和重试机制
    max_retries = 4
    api_mode = CHAT_COMPLETIONS_API_MODE
    use_response_format = ENABLE_RESPONSE_FORMAT
    use_temperature = True
    for attempt in range(max_retries):
        try:
            # 根据重试次数调整参数
            current_temperature = 0.1 if attempt == 0 else 0.05  # 重试时使用更低的温度

            from src.config import get_ai_request_params

            request_params = build_ai_request_params(
                api_mode,
                model=model_name,
                messages=messages,
                temperature=current_temperature,
                # 8192：推理型模型即使关闭思考失败时，思考文本也会挤占输出上限，
                # 4000 会导致最终 JSON 被截断
                max_output_tokens=8192,
                enable_json_output=use_response_format,
            )
            if not use_temperature:
                request_params = remove_temperature_param(request_params)

            request_params = get_ai_request_params(**request_params)

            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] {profile_label} 第{attempt + 1}次尝试 REQUEST ---")
                safe_print(
                    json.dumps(
                        _build_debug_request_summary(api_mode, request_params),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                safe_print("-----------------------------------\n")

            response = await create_ai_response_async(
                client,
                api_mode,
                request_params,
            )
            ai_response_content = extract_ai_response_content(response)

            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] {profile_label} 第{attempt + 1}次尝试 ---")
                safe_print("--- RAW AI RESPONSE ---")
                safe_print(ai_response_content)
                safe_print("---------------------\n")

            try:
                parsed_response = parse_ai_response_json(ai_response_content)

                # 验证响应格式
                if validate_ai_response_format(parsed_response):
                    safe_print(
                        f"   [AI分析] 模型[{profile_label}] 第{attempt + 1}次尝试成功，响应格式验证通过"
                    )
                    return parsed_response
                safe_print(f"   [AI分析] {profile_label} 第{attempt + 1}次尝试格式验证失败")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 准备第{attempt + 2}次重试...")
                    continue
                raise ValueError("AI响应格式缺少必需字段或字段类型不正确。")
            except json.JSONDecodeError as e:
                safe_print(f"   [AI分析] {profile_label} 第{attempt + 1}次尝试JSON解析失败: {e}")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 准备第{attempt + 2}次重试...")
                    continue
                raise e
            except EmptyAIResponseError as e:
                safe_print(f"   [AI分析] {profile_label} 第{attempt + 1}次尝试返回空响应: {e}")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 准备第{attempt + 2}次重试...")
                    continue
                raise e

        except Exception as e:
            if (
                api_mode == CHAT_COMPLETIONS_API_MODE
                and is_chat_completions_api_unsupported_error(e)
            ):
                api_mode = RESPONSES_API_MODE
                safe_print(
                    "   [AI分析] 当前服务未实现 Chat Completions API，后续重试将自动回退到 Responses API。"
                )
            elif api_mode == RESPONSES_API_MODE and is_responses_api_unsupported_error(e):
                api_mode = CHAT_COMPLETIONS_API_MODE
                safe_print(
                    "   [AI分析] 当前服务未实现 Responses API，后续重试将自动回退到 Chat Completions API。"
                )
            if use_response_format and is_json_output_unsupported_error(e):
                use_response_format = False
                safe_print(
                    "   [AI分析] 当前模型不支持结构化 JSON 输出，后续重试将自动禁用该参数。"
                )
            if use_temperature and is_temperature_unsupported_error(e):
                use_temperature = False
                safe_print(
                    "   [AI分析] 当前模型不支持 temperature 参数，后续重试将自动禁用该参数。"
                )
            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] {profile_label} 第{attempt + 1}次尝试 EXCEPTION ---")
                safe_print(repr(e))
                safe_print(traceback.format_exc())
                safe_print("-------------------------------------\n")
            safe_print(f"   [AI分析] {profile_label} 第{attempt + 1}次尝试AI调用失败: {e}")
            if attempt < max_retries - 1:
                safe_print(f"   [AI分析] 准备第{attempt + 2}次重试...")
                continue
            else:
                raise e
