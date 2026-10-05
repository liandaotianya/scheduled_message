"""联网搜索插件（补齐原方案 search_web 能力）。

原 Coze 版任务用 search_web 限定近 7 天、分品类搜 4-5 轮，是薅羊毛条数的主要来源。
静态站点抓取（如本地宝）更新量有限，搜索聚合能显著扩大候选池。

支持的搜索服务（二选一，通过环境变量传入 Key）：
    SERPER_API_KEY  —— Google 搜索结果，中文覆盖好，免费额度 2500 次/月
    BOCHA_API_KEY   —— 博查（百度中文搜索），免费额度较大，中文本地信息更全

约定接口：fetch(keyword, limit) -> List[dict]，每个 dict 含 title / url / summary。
未配置 Key 时返回空列表，不影响其他信息源。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

TIMEOUT = 25
# 每个关键词最多保留条数
PER_KEYWORD = 10
# 多次搜索之间的间隔，避免触发限流
GAP = 2.0

# 薅羊毛分品类关键词（对齐原方案「分品类搜 4-5 轮」）
DEFAULT_KEYWORDS = [
    "长春 消费券 发放 抢券 活动",
    "长春 云闪付 消费券 优惠",
    "长春 加油站 加油优惠 活动",
    "长春 工会 职工 福利 优惠",
    "长春 亲子 免费 活动 周末",
    "长春 商场 门店 限时 折扣 活动",
    "长春 景区 门票 优惠 活动",
    "长春 美食 优惠券 活动",
]


def _search_serper(keyword: str, limit: int) -> List[Dict[str, str]]:
    key = os.environ["SERPER_API_KEY"]
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": keyword, "gl": "cn", "hl": "zh-cn", "num": limit},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows: List[Dict[str, str]] = []
    for hit in resp.json().get("organic", [])[:limit]:
        rows.append(
            {
                "title": (hit.get("title") or "").strip(),
                "url": (hit.get("link") or "").strip(),
                "summary": (hit.get("snippet") or "").strip(),
            }
        )
    return rows


def _search_bocha(keyword: str, limit: int) -> List[Dict[str, str]]:
    key = os.environ["BOCHA_API_KEY"]
    resp = requests.post(
        "https://api.bochaai.com/v1/web-search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": keyword, "count": min(limit, 10), "summary": True},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    rows: List[Dict[str, str]] = []
    for hit in (data.get("webPages") or {}).get("value", [])[:limit]:
        rows.append(
            {
                "title": (hit.get("name") or "").strip(),
                "url": (hit.get("url") or "").strip(),
                "summary": (hit.get("summary") or hit.get("snippet") or "").strip(),
            }
        )
    return rows


def _provider() -> Any:
    if os.environ.get("SERPER_API_KEY"):
        return _search_serper
    if os.environ.get("BOCHA_API_KEY"):
        return _search_bocha
    return None


def fetch(
    keyword: str = "", limit: int = 40, keywords: List[str] | None = None
) -> List[Dict[str, Any]]:
    """按分品类关键词多轮搜索并去重，补充本地静态源之外的候选。"""
    search = _provider()
    if search is None:
        log.warning("未配置搜索服务 Key（SERPER_API_KEY / BOCHA_API_KEY），跳过搜索聚合")
        return []

    terms: List[str] = list(keywords or DEFAULT_KEYWORDS)
    if keyword and keyword not in terms:
        terms.insert(0, keyword)

    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, term in enumerate(terms):
        if idx:
            time.sleep(GAP)
        try:
            hits = search(term, PER_KEYWORD)
        except Exception as exc:  # noqa: BLE001 - 单轮失败不影响整体
            log.warning("搜索「%s」失败: %s", term, exc)
            continue
        for hit in hits:
            if not hit["title"] or not hit["url"].startswith("http"):
                continue
            key = hit["url"].split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            hit["title"] = f"[{term}] {hit['title']}"
            rows.append(hit)
        if len(rows) >= limit:
            break

    log.info("搜索聚合：%d 个关键词共 %d 条", len(terms), len(rows))
    return rows[:limit]


def dump_config() -> str:
    """面板展示用：当前是否已配置搜索服务。"""
    return json.dumps(
        {
            "serper": bool(os.environ.get("SERPER_API_KEY")),
            "bocha": bool(os.environ.get("BOCHA_API_KEY")),
        },
        ensure_ascii=False,
    )
