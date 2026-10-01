"""LLM 调用层：Gemini 主通道 + DeepSeek 兜底，统一 ask() 入口。

两个通道都用兼容 OpenAI / Gemini 的 REST 接口直接调，避免引入重量级 SDK。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from . import config as cfg

log = logging.getLogger(__name__)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"


class LLMError(RuntimeError):
    """所有通道都失败时抛出。"""


# ---------------------------------------------------------------- 通道实现

def _call_gemini(prompt: str, system: str, timeout: int, model: str) -> str:
    api_key = _env("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("缺少 GEMINI_API_KEY")

    url = GEMINI_ENDPOINT.format(model=model)
    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": cfg.get("llm.temperature", 0.7),
            "maxOutputTokens": 8192,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    resp = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Gemini 返回结构异常: {str(data)[:300]}") from exc


def _call_deepseek(prompt: str, system: str, timeout: int, model: str) -> str:
    api_key = _env("DEEPSEEK_API_KEY")
    if not api_key:
        raise LLMError("缺少 DEEPSEEK_API_KEY")

    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        DEEPSEEK_ENDPOINT,
        json={
            "model": model,
            "messages": messages,
            "temperature": cfg.get("llm.temperature", 0.7),
            "stream": False,
        },
        timeout=timeout,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    if resp.status_code != 200:
        raise LLMError(f"DeepSeek HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"DeepSeek 返回结构异常: {str(data)[:300]}") from exc


_CHANNELS = {
    "gemini": _call_gemini,
    "deepseek": _call_deepseek,
}


def _env(name: str) -> Optional[str]:
    import os

    return os.environ.get(name) or None


# ---------------------------------------------------------------- 对外接口

def ask(
    prompt: str,
    system: str = "",
    expect_json: bool = False,
    max_retries: Optional[int] = None,
) -> Any:
    """调用 LLM。

    Args:
        prompt: 用户提示词
        system: 系统提示词
        expect_json: 为 True 时解析返回内容为 JSON 并返回 Python 对象
        max_retries: 每个通道的重试次数，默认读配置

    Returns:
        字符串，或 expect_json=True 时的 Python 对象

    Raises:
        LLMError: 主通道与兜底通道全部失败
    """
    primary = cfg.get("llm.primary", "gemini")
    fallback = cfg.get("llm.fallback", "deepseek")
    models = cfg.get("llm.models", {}) or {}
    timeout = cfg.get("llm.timeout", 180)
    retries = max_retries if max_retries is not None else cfg.get("llm.max_retries", 2)

    order = [primary]
    if fallback and fallback != primary:
        order.append(fallback)

    errors: List[str] = []
    for channel in order:
        fn = _CHANNELS.get(channel)
        if fn is None:
            errors.append(f"{channel}: 未知通道")
            continue
        model = models.get(channel, "")
        for attempt in range(1, retries + 1):
            try:
                text = fn(prompt, system, timeout, model)
                if expect_json:
                    return _parse_json(text)
                return text
            except Exception as exc:  # noqa: BLE001 - 需要跨通道兜底
                errors.append(f"{channel}#{attempt}: {exc}")
                log.warning("LLM 通道 %s 第 %d 次尝试失败: %s", channel, attempt, exc)
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 10))
        log.warning("LLM 通道 %s 已耗尽，切换下一通道", channel)

    raise LLMError("所有 LLM 通道均失败:\n" + "\n".join(errors))


def _parse_json(text: str) -> Any:
    """从 LLM 返回里抠出 JSON，容忍 ```json 围栏和前后废话。"""
    cleaned = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 退一步：找第一个 { 或 [ 到最后一个配对括号
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise LLMError(f"无法从返回内容解析 JSON（前 300 字）: {cleaned[:300]}")
