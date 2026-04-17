from __future__ import annotations

import os

from langchain_deepseek import ChatDeepSeek

DEFAULT_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_MAX_RETRIES = 2


def set_optional_env(name: str) -> None:
    value = os.getenv(name)
    if value:
        os.environ[name] = value


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def format_runtime_error(error: Exception, *, timeout_seconds: int | None = None) -> str:
    error_name = type(error).__name__
    message = str(error).strip()
    lowered = f"{error_name} {message}".lower()

    if "timeout" in lowered:
        return (
            f"请求超时，已在 {timeout_seconds or DEFAULT_LLM_TIMEOUT_SECONDS} 秒后中止本轮调用。"
            "请稍后重试，或缩小问题范围后再试。"
        )
    if "connection" in lowered or "api_connection" in lowered:
        return "模型服务连接失败，本轮已安全结束。请检查网络或稍后重试。"
    return f"调用失败：{error_name}。本轮已安全结束，请稍后重试。"


def build_llm(*, timeout_seconds: int, max_retries: int) -> ChatDeepSeek:
    return ChatDeepSeek(
        model="deepseek-chat",
        temperature=0,
        max_tokens=None,
        timeout=timeout_seconds,
        max_retries=max_retries,
    )