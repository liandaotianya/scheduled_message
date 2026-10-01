"""抓取层：统一从 RSS / 公开 API / 网页 / 插件取原始条目。

设计原则：
- 每个源独立 try/except，单源失败绝不影响整体
- 统一返回 Item 结构，交给 LLM 做二次筛选与整理
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from importlib import import_module
from typing import Any, Dict, List

import requests

from . import config as cfg

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; AIDailyBot/1.0; +https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 25


@dataclass
class Item:
    """统一的抓取条目。"""

    title: str
    url: str
    summary: str = ""
    source: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- 各类型抓取

def _fetch_rss(meta: Dict[str, Any], limit: int) -> List[Item]:
    import feedparser

    resp = requests.get(
        meta["url"], timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    items: List[Item] = []
    for entry in feed.entries[:limit]:
        items.append(
            Item(
                title=(entry.get("title") or "").strip(),
                url=(entry.get("link") or "").strip(),
                summary=_strip_html(
                    entry.get("summary") or entry.get("description") or ""
                )[:400],
                source=meta.get("_name", ""),
                tags=list(meta.get("tags") or []),
            )
        )
    return items


def _fetch_api(meta: Dict[str, Any], limit: int) -> List[Item]:
    """公开 JSON 接口。内置 HN 与 GitHub Search 两个特例。"""
    name = meta.get("_name", "")

    if name == "HackerNews":
        return _fetch_hn(meta, limit)

    if "api.github.com" in meta.get("url", ""):
        return _fetch_github(meta, limit)

    resp = requests.get(
        meta["url"],
        params=meta.get("params") or {},
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    resp.raise_for_status()
    payload = resp.json()

    items: List[Item] = []
    if isinstance(payload, list):
        for row in payload[:limit]:
            if not isinstance(row, dict):
                continue
            items.append(
                Item(
                    title=str(row.get("title") or row.get("name") or "").strip(),
                    url=str(
                        row.get("url")
                        or row.get("link")
                        or row.get("html_url")
                        or ""
                    ).strip(),
                    summary=str(row.get("content") or row.get("description") or "")[:400],
                    source=name,
                    tags=list(meta.get("tags") or []),
                )
            )
    return items


def _fetch_hn(meta: Dict[str, Any], limit: int) -> List[Item]:
    resp = requests.get(meta["url"], timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    ids = resp.json()[:limit]

    items: List[Item] = []
    item_tpl = meta.get("item_url", "")
    for sid in ids:
        try:
            detail = requests.get(
                item_tpl.format(id=sid), timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            ).json()
        except Exception:  # noqa: BLE001 - 单条失败跳过
            continue
        items.append(
            Item(
                title=str(detail.get("title") or "").strip(),
                url=str(detail.get("url") or f"https://news.ycombinator.com/item?id={sid}"),
                summary=f"score={detail.get('score', 0)} comments={detail.get('descendants', 0)}",
                source=meta.get("_name", "HackerNews"),
                tags=list(meta.get("tags") or []),
            )
        )
    return items


def _fetch_github(meta: Dict[str, Any], limit: int) -> List[Item]:
    from datetime import datetime, timedelta, timezone

    days_ago = (
        datetime.now(timezone.utc) - timedelta(days=10)
    ).strftime("%Y-%m-%d")

    params = dict(meta.get("params") or {})
    params["q"] = str(params.get("q", "")).replace("{days_ago}", days_ago)
    params["per_page"] = min(limit, 100)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    import os

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(meta["url"], params=params, timeout=TIMEOUT, headers=headers)
    resp.raise_for_status()
    payload = resp.json()

    items: List[Item] = []
    for repo in payload.get("items", []):
        stars = repo.get("stargazers_count", 0)
        items.append(
            Item(
                title=f"{repo.get('full_name', '')} (★{stars})",
                url=repo.get("html_url", ""),
                summary=(repo.get("description") or "")[:400],
                source=meta.get("_name", "GitHub"),
                tags=list(meta.get("tags") or []),
            )
        )
    return items


def _fetch_html(meta: Dict[str, Any], limit: int) -> List[Item]:
    from bs4 import BeautifulSoup

    resp = requests.get(
        meta["url"], timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "lxml")

    selector = meta.get("selector", "a")
    items: List[Item] = []
    seen: set[str] = set()
    for node in soup.select(selector):
        text = node.get_text(strip=True)
        href = node.get("href") or ""
        if not text or not href or href in seen:
            continue
        seen.add(href)
        items.append(
            Item(
                title=text,
                url=href,
                source=meta.get("_name", ""),
                tags=list(meta.get("tags") or []),
            )
        )
        if len(items) >= limit:
            break
    return items


def _fetch_plugin(meta: Dict[str, Any], limit: int, keyword: str = "") -> List[Item]:
    """插件位：动态导入 scripts/core/plugins/<module>.py。

    约定插件模块需暴露：
        fetch(keyword: str, limit: int) -> List[dict]
    每个 dict 至少包含 title 与 url。
    """
    module_name = meta.get("module")
    if not module_name:
        raise ValueError("plugin 类型缺少 module 字段")

    try:
        mod = import_module(f"core.plugins.{module_name}")
    except ImportError as exc:
        raise ImportError(
            f"插件 {module_name} 未实现，请创建 scripts/core/plugins/{module_name}.py"
        ) from exc

    rows = mod.fetch(keyword=keyword, limit=limit)
    return [
        Item(
            title=str(row.get("title", "")).strip(),
            url=str(row.get("url", "")).strip(),
            summary=str(row.get("summary", ""))[:400],
            source=meta.get("_name", module_name),
            tags=list(meta.get("tags") or []),
        )
        for row in rows
    ]


_FETCHERS = {
    "rss": _fetch_rss,
    "api": _fetch_api,
    "html": _fetch_html,
}

DEFAULT_LIMIT = 30


# ---------------------------------------------------------------- 对外接口

def fetch_source(
    name: str, meta: Dict[str, Any], limit: int = DEFAULT_LIMIT, keyword: str = ""
) -> List[Item]:
    """抓取单个源，失败返回空列表并记日志。"""
    meta = dict(meta)
    meta["_name"] = name
    stype = meta.get("type", "rss")

    try:
        if stype == "plugin":
            items = _fetch_plugin(meta, limit, keyword)
        else:
            fn = _FETCHERS.get(stype)
            if fn is None:
                raise ValueError(f"未知源类型: {stype}")
            items = fn(meta, limit)

        items = [i for i in items if i.title and i.url]
        log.info("源 %s 抓取到 %d 条", name, len(items))
        return items
    except Exception as exc:  # noqa: BLE001 - 单源失败不影响整体
        log.warning("源 %s 抓取失败: %s", name, exc)
        return []


def fetch_all(
    tag: str | None = None, limit: int = DEFAULT_LIMIT, keyword: str = ""
) -> List[Item]:
    """抓取所有已启用源（可按 tag 过滤），合并去重。"""
    merged: List[Item] = []
    seen: set[str] = set()

    for name, meta in cfg.enabled_sources(tag).items():
        for item in fetch_source(name, meta, limit, keyword):
            key = item.url.split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    log.info("抓取汇总（tag=%s）共 %d 条", tag, len(merged))
    return merged


def format_for_prompt(items: List[Item], per_item: int = 260) -> str:
    """把抓取结果压成适合塞进提示词的文本。"""
    lines: List[str] = []
    for idx, item in enumerate(items, 1):
        summary = item.summary[:per_item].replace("\n", " ")
        lines.append(f"{idx}. [{item.source}] {item.title}\n   URL: {item.url}\n   {summary}")
    return "\n".join(lines)


def _strip_html(text: str) -> str:
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        return text
