"""任务②：AI 日报

触发：每月单号（排除 7/23 号）17:03
目标：扫描最新 AI 资讯，5 个分类各 8 条共 40 条
核心逻辑：赚钱和快速落地，信息差降低竞争
产出：HTML 存档到 data/archive/ + 发送邮件
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from core import config as cfg
from core import fetcher, issue_no, llm, mailer, render

log = logging.getLogger(__name__)

TASK_KEY = "ai-daily"
TASK_CFG = "tasks.ai_daily"

SYSTEM = (
    "你是 AI 行业情报分析师，服务对象是独立开发者和技术创业者。"
    "你只关心「能不能赚钱」和「能不能快速落地」，对纯概念、纯融资新闻不感兴趣。"
    "你给出的每条信息都必须有可点击的真实链接，没有链接的内容一律不输出。"
)

PROMPT_TMPL = """
请基于下面的原始信息，整理一份 AI 日报。

## 分类与条数要求
{categories}

每个分类 {per_cat} 条，合计 {total} 条。

## 各分类的具体要求

**提高开发效率的工具**
AI Skill、GitHub 项目、CLI 工具、自动化脚本，即拿即用。
判断标准：今天看到，今天就能用上。

**可产品化开源项目**
近 10 天增长最快的项目，star 在 500-3000 区间的优先（增速比总量重要）。
排除已有 2 万+ star 的成熟项目——那些没有信息差价值。

**近 10 天可落地信息差**
知道的人少、有时间窗口、门槛不高的赚钱机会。
判断标准：看到之后能在两周内动手做的。

**其他优质资讯**
有实际案例或数据支撑的行业动态，不要纯观点和纯融资消息。

**日常痛点+解决方案**
真实痛点必须匹配到具体的 GitHub 项目 / 开源库 / AI 工具方案。
找不到现成方案的，在 solution 字段标注「待造」。

## 原始信息
{raw}

## 输出要求
严格输出 JSON 对象，格式：
{{
  "highlights": ["今日亮点1", "今日亮点2", "今日亮点3"],
  "sections": [
    {{
      "name": "分类名称（必须是上面分类之一）",
      "items": [
        {{
          "title": "标题",
          "url": "原文链接（必须来自原始信息，无链接不入选）",
          "desc": "说明，50字以内，讲清是什么",
          "difficulty": "落地难度：低/中/高",
          "value": "赚钱潜力：低/中/高"
        }}
      ]
    }}
  ]
}}

highlights 给 3-5 条。只输出 JSON，不要任何解释文字。
"""


def run(overrides: Dict[str, Any] | None = None) -> bool:
    overrides = overrides or {}
    now = datetime.now()
    per_cat = int(overrides.get("items_per_category") or cfg.get(f"{TASK_CFG}.items_per_category", 8))
    categories = cfg.get(f"{TASK_CFG}.categories", [])
    total = per_cat * len(categories)

    issue = issue_no.next_issue_no(TASK_KEY, now)
    title = f"AI日报 {now.strftime('%Y-%m-%d')}"
    log.info("开始执行 %s", title)

    # ---- 1. 抓取 ----
    # 排除搜索源：实测博查搜「AI 工具 开源」返回的多是盘点/汇总类二手稿，
    # 反而挤占 GitHub Trending、HackerNews 这类一手源的位置
    raw_items = fetcher.fetch_all(
        limit=40, keyword="AI 工具 开源 项目", task="ai_daily", exclude=["联网搜索"]
    )
    if not raw_items:
        log.error("未抓取到任何原始信息，任务中止")
        return False

    # ---- 2. LLM 整理 ----
    prompt = PROMPT_TMPL.format(
        categories="\n".join(f"- {c}（{per_cat}条）" for c in categories),
        per_cat=per_cat,
        total=total,
        raw=fetcher.format_for_prompt(raw_items, per_item=200),
    )

    try:
        result: Dict[str, Any] = llm.ask(prompt, system=SYSTEM, expect_json=True)
    except llm.LLMError as exc:
        log.error("LLM 调用失败，任务中止: %s", exc)
        return False

    sections = (result or {}).get("sections") or []
    if not sections:
        log.error("LLM 未产出任何分类内容，任务中止")
        return False

    total_items = sum(len(s.get("items") or []) for s in sections)
    log.info("共生成 %d 个分类、%d 条内容", len(sections), total_items)

    # ---- 3. 渲染 ----
    html = render.render(
        "ai_daily.html.j2",
        {
            "title": title,
            "issue": issue,
            "highlights": result.get("highlights") or [],
            "sections": sections,
            "total_items": total_items,
        },
    )

    # ---- 4. 存档 ----
    if cfg.get(f"{TASK_CFG}.archive", True):
        issue_no.archive(
            TASK_KEY, issue, html, now, title=title, subject=f"AI日报 {now.strftime('%Y-%m-%d')}"
        )

    # ---- 5. 发信（正文内联） ----
    subject = f"AI日报 {now.strftime('%Y-%m-%d')}"
    mailer.send(subject, html, dry_run=bool(overrides.get("dry_run")))

    # ---- 6. 回写期号 ----
    issue_no.commit_issue_no(TASK_KEY, issue, now)
    log.info("任务完成: %s", title)
    return True
