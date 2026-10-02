"""长春本地宝活动资讯抓取插件。

数据源：http://cc.bendibao.com/xiuxian/huodongnews/（长春活动资讯列表）
列表页结构规整（h3>a 标题 / p.desc 摘要 / p.from 日期），为静态 HTML，抓取稳定。
详情页 302 跳转到移动版 m.cc.bendibao.com，正文含完整的时间、地点、参与方式。

约定接口：fetch(keyword, limit) -> List[dict]，每个 dict 含 title / url / summary。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

log = logging.getLogger(__name__)

LIST_URL = "http://cc.bendibao.com/xiuxian/huodongnews/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 25
# 详情页正文最多截取长度（喂给 LLM 的原始信息不必全文）
DETAIL_CHARS = 500
# 详情页最多抓几篇（控制总耗时）
DETAIL_MAX = 10


def _strip_html(text: str) -> str:
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        return text


def _fetch_listing() -> List[Dict[str, str]]:
    """抓列表页，返回 [{title, url, summary, date_str}]。"""
    resp = requests.get(LIST_URL, timeout=TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "lxml")
    items: List[Dict[str, str]] = []
    for li in soup.select("#listNewsTimeLy li"):
        a = li.select_one("h3 a")
        if a is None:
            continue
        title = (a.get_text() or "").strip()
        url = (a.get("href") or "").strip()
        if not title or not url:
            continue
        desc = ""
        p_desc = li.select_one("p.desc")
        if p_desc is not None:
            desc = p_desc.get_text(" ", strip=True)
        date_str = ""
        p_from = li.select_one("p.from")
        if p_from is not None:
            date_str = p_from.get_text(strip=True)[:10]
        items.append(
            {"title": title, "url": url, "summary": desc, "date_str": date_str}
        )
    if not items:
        # 站点有「渐进式锁定」反爬：请求过频时列表页会被替换成验证码页
        raise RuntimeError("本地宝列表页被拦截（疑似触发反爬验证）或结构已变化")


def _recent_enough(date_str: str, days: int) -> bool:
    """列表是倒序的，但个别条目可能是很久以前的旧文，按日期过滤。"""
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str or "")
    if not m:
        return True  # 解析不出日期的先放行，交给 LLM 判断
    try:
        d = datetime(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return True
    return d >= datetime.now() - timedelta(days=days)


def _fetch_detail(url: str) -> str:
    """抓详情页正文片段（302 跳转到移动版，requests 自动跟随）。"""
    try:
        resp = requests.get(
            url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
    except Exception as exc:  # noqa: BLE001 - 单篇详情失败不影响整体
        log.debug("详情页抓取失败 %s: %s", url, exc)
        return ""

    html = resp.text
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = _strip_html(html)
    # 详情页偶发拼图验证码拦截，此时没有正文，放弃详情只用列表摘要
    if "拼图验证" in text or "请完成" in text[:200]:
        return ""
    # 导语之后是正文主体，从「导语」开始截取能拿到最浓缩的信息
    i = text.find("导语")
    if i < 0:
        return ""
    return text[i : i + DETAIL_CHARS]


def fetch(keyword: str = "", limit: int = 15, recent_days: int = 7) -> List[Dict[str, Any]]:
    """对外接口：返回本地宝最新活动条目（含详情页正文片段）。

    站点有渐进式反爬（锁定约 10 分钟），被拦时等 65 秒重试一次。
    """
    listing: List[Dict[str, str]] = []
    for attempt in (1, 2):
        try:
            listing = _fetch_listing()
            break
        except Exception as exc:  # noqa: BLE001 - 单源失败不影响整体
            log.warning("本地宝列表抓取失败（第 %d 次）: %s", attempt, exc)
            if attempt == 1:
                time.sleep(65)
    if not listing:
        return []

    fresh = [it for it in listing if _recent_enough(it.get("date_str", ""), recent_days)]
    log.info("本地宝列表 %d 条，近期 %d 条", len(listing), len(fresh))

    rows: List[Dict[str, Any]] = []
    for idx, it in enumerate(fresh[: max(limit, 1)]):
        summary = it.get("summary", "")
        # 前 N 条抓详情页充实信息（时间/地点/参与方式通常在正文里）
        if idx < DETAIL_MAX:
            if idx:
                time.sleep(1.5)  # 站点有频率反爬，请求间留间隔
            detail = _fetch_detail(it["url"])
            if detail:
                summary = f"{summary}（详情：{detail}）"
        rows.append(
            {
                "title": it["title"],
                "url": it["url"],
                "summary": summary[:600],
            }
        )
    return rows
