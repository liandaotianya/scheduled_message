"""联网搜索插件（补齐原方案 search_web 能力）。

原 Coze 版任务用 search_web 限定近 7 天、分品类搜 4-5 轮，是薅羊毛条数的主要来源。
静态站点抓取（如本地宝）更新量有限，搜索聚合能显著扩大候选池。

三级通道，按可用性自动降级：
    1. 搜索服务 API（需免费 Key，中文覆盖最好）
       - SERPER_API_KEY：Google 结果，2500 次/月
       - BOCHA_API_KEY：博查（百度中文），本地信息更全
    2. 自建搜索服务（无限量、无 Key，需服务器）
       - SEARXNG_URL：自建 SearXNG，输出 JSON 格式
    3. 公共搜索引擎网页解析（无 Key，反爬成功率随机）

约定接口：fetch(keyword, limit) -> List[dict]，每个 dict 含 title / url / summary。
全部通道不可用时返回空列表，不影响其他信息源。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

TIMEOUT = 25
# 每个关键词最多保留条数
PER_KEYWORD = 10
# 多次搜索之间的间隔，避免触发限流
GAP = 2.0
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 分任务的关键词组：不同任务的目标完全不同，必须分开搜，
# 否则薅羊毛的 8 组词会把 AI 日报 / 痛点快报的候选池全部占满。
DEAL_KEYWORDS = [
    "长春 消费券 发放 抢券 活动",
    "长春 云闪付 消费券 优惠",
    "长春 加油站 加油优惠 活动",
    "长春 工会 职工 福利 优惠",
    "长春 亲子 免费 活动 周末",
    "长春 商场 门店 限时 折扣 活动",
    "长春 景区 门票 优惠 活动",
    "长春 美食 优惠券 活动",
]

AI_KEYWORDS = [
    "AI 工具 开源 项目 GitHub 2026",
    "AI Agent 框架 新发布 实测",
    "独立开发者 变现 AI 产品 案例",
    "GitHub trending star 增长 快 项目",
    "AI 提效 编程 工具 更新",
]

PAIN_KEYWORDS = [
    "吐槽 难用 换一个 国产 App",
    "用户 抱怨 麻烦 没有 小程序",
    "求推荐 工具 找不到 浪费时间",
    "老年人 不会 用 智能手机 打车",
    "家长 焦虑 鸡娃 工具 抱怨",
    "上班 通勤 打卡 加班 痛点 吐槽",
]

# 任务 -> 关键词组（按 sources.yaml 里配置的源名 + 调用方任务名匹配）
TASK_KEYWORDS = {
    "deals": DEAL_KEYWORDS,
    "ai_daily": AI_KEYWORDS,
    "pain_points": PAIN_KEYWORDS,
}


def _pick_keywords(task_hint: str, keyword: str) -> List[str]:
    """按任务选择关键词组；传入的 keyword 永远排在最前。"""
    terms = list(TASK_KEYWORDS.get(task_hint) or DEAL_KEYWORDS)
    if keyword and keyword not in terms:
        terms.insert(0, keyword)
    return terms

SearchFn = Callable[[str, int], List[Dict[str, str]]]


# ---------------------------------------------------------------- 通道 1：搜索 API

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


# ---------------------------------------------------------------- 通道 2：自建 SearXNG

def _search_searxng(keyword: str, limit: int) -> List[Dict[str, str]]:
    base = os.environ["SEARXNG_URL"].rstrip("/")
    resp = requests.get(
        f"{base}/search",
        params={"q": keyword, "format": "json", "language": "zh"},
        timeout=TIMEOUT,
        headers={"User-Agent": UA},
    )
    resp.raise_for_status()
    rows: List[Dict[str, str]] = []
    for hit in resp.json().get("results", [])[:limit]:
        rows.append(
            {
                "title": (hit.get("title") or "").strip(),
                "url": (hit.get("url") or "").strip(),
                "summary": (hit.get("content") or "").strip(),
            }
        )
    return rows


# ---------------------------------------------------------------- 通道 3：公共引擎网页

def _parse_bing(keyword: str, limit: int) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup

    resp = requests.get(
        "https://cn.bing.com/search",
        params={"q": keyword, "setlang": "zh-CN", "count": limit},
        timeout=TIMEOUT,
        headers={"User-Agent": UA},
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "lxml")
    rows: List[Dict[str, str]] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if a is None:
            continue
        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()
        if not title or not url.startswith("http"):
            continue
        cap = li.select_one(".b_caption p") or li.select_one("p")
        rows.append(
            {
                "title": title,
                "url": url,
                "summary": (cap.get_text(" ", strip=True) if cap else ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_ddg(keyword: str, limit: int) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup

    resp = requests.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": keyword},
        timeout=TIMEOUT,
        headers={"User-Agent": UA},
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "lxml")
    rows: List[Dict[str, str]] = []
    for a in soup.select("a.result-link"):
        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()
        if not title or not url.startswith("http"):
            continue
        rows.append({"title": title, "url": url, "summary": ""})
        if len(rows) >= limit:
            break
    return rows


def _parse_mojeek(keyword: str, limit: int) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup

    resp = requests.get(
        "https://www.mojeek.com/search",
        params={"q": keyword},
        timeout=TIMEOUT,
        headers={"User-Agent": UA},
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "lxml")
    rows: List[Dict[str, str]] = []
    for li in soup.select("ul.results-standard li"):
        a = li.select_one("a.title") or li.select_one("h2 a")
        if a is None:
            continue
        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()
        if not title or not url.startswith("http"):
            continue
        p = li.select_one("p.s")
        rows.append(
            {
                "title": title,
                "url": url,
                "summary": (p.get_text(" ", strip=True) if p else ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _api_channels() -> List[SearchFn]:
    fns: List[SearchFn] = []
    if os.environ.get("SEARXNG_URL"):
        fns.append(_search_searxng)
    if os.environ.get("SERPER_API_KEY"):
        fns.append(_search_serper)
    if os.environ.get("BOCHA_API_KEY"):
        fns.append(_search_bocha)
    return fns


WEB_ENGINES: List[tuple[str, SearchFn]] = [
    ("bing", _parse_bing),
    ("ddg", _parse_ddg),
    ("mojeek", _parse_mojeek),
]


def _search(keyword: str, limit: int) -> List[Dict[str, str]]:
    """按通道优先级取结果：先 API/自建服务，再依次试公共引擎。"""
    for fn in _api_channels():
        try:
            rows = fn(keyword, limit)
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001 - 单通道失败换下一个
            log.warning("搜索通道 %s 失败: %s", fn.__name__, exc)

    for name, fn in WEB_ENGINES:
        try:
            rows = fn(keyword, limit)
        except Exception as exc:  # noqa: BLE001
            log.warning("公共引擎 %s 失败: %s", name, exc)
            continue
        if rows:
            log.info("公共引擎 %s 可用（%d 条）", name, len(rows))
            return rows
    return []


def fetch(
    keyword: str = "",
    limit: int = 40,
    keywords: List[str] | None = None,
    task: str = "",
) -> List[Dict[str, Any]]:
    """按任务选定的关键词多轮搜索并去重，补充静态源之外的候选。

    task 传入任务标识（deals / ai_daily / pain_points）以选择对应关键词组；
    未识别时退回薅羊毛词组。
    """
    terms = list(keywords) if keywords else _pick_keywords(task, keyword)

    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, term in enumerate(terms):
        if idx:
            time.sleep(GAP)
        try:
            hits = _search(term, PER_KEYWORD)
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
    """面板展示用：当前可用通道。"""
    return json.dumps(
        {
            "searxng": bool(os.environ.get("SEARXNG_URL")),
            "serper": bool(os.environ.get("SERPER_API_KEY")),
            "bocha": bool(os.environ.get("BOCHA_API_KEY")),
        },
        ensure_ascii=False,
    )
