"""任务①：长春薅羊毛活动收集

触发：每月双号（排除 16/30 号）17:03
目标：收集长春本地线下限时优惠活动，宁缺毋滥，每期至少 5 条
核心标准：稀缺性优先、纯线下（有具体地址）、信息完整
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from core import config as cfg
from core import fetcher, issue_no, llm, mailer, render

log = logging.getLogger(__name__)

TASK_KEY = "changchun-deals"
TASK_CFG = "tasks.changchun_deals"

SYSTEM = (
    "你是长春本地生活情报编辑，专门挖掘线下真实可参与的优惠活动。"
    "你极度讨厌营销软文和线上平台通用活动，只认可有具体地址、"
    "有明确时间、有参与方式的线下活动。"
    "信息不足时你宁可不收录，也绝不编造地址、时间或参与方式。"
)

PROMPT_TMPL = """
请从下面的原始信息里，筛选出**长春本地**的**线下**限时优惠活动。

## 本期时间窗口
{recent_days} 天内

## 品类优先级（越靠前越优先收录）
{categories}

## 硬性标准
1. 稀缺性优先：线下专属、不常有、值得分享的活动优先
2. 纯线下：必须有具体地址（商场/门店/场馆名 + 大致位置）
3. 信息完整：时间、地点、参与方式三项齐全
4. 宁缺毋滥：可以少于 {min_items} 条，但每条都必须真实可用

## 绝对排除（出现任一即剔除）
- 线上平台通用活动（云闪付 / 美团 / 抖音 / 饿了么 / 信用卡 / 618 之类）
- 营销软文、无具体信息的推广
- 二手转卖、已过期活动
- 没有具体地址的活动
- 非长春地区的活动

## 原始信息
{raw}

## 输出要求
严格输出 JSON 数组，每个元素包含以下字段：
{{
  "title": "活动名称",
  "category": "所属品类（必须是上面品类之一）",
  "discount": "优惠力度（如 5折 / 免费 / 满100减30）",
  "time": "活动时间（如 9月20日-9月27日）",
  "location": "具体地点（含区域）",
  "content": "活动内容，40字以内",
  "age": "适合年龄（如 3-12岁 / 不限）",
  "how": "参与方式（如 现场报名 / 小程序预约）",
  "url": "来源链接（必须是原始信息里的真实链接）",
  "rarity": "稀缺性说明，20字以内"
}}

只输出 JSON，不要任何解释文字。如果确实找不到合格活动，输出 []。
"""


def run(overrides: Dict[str, Any] | None = None) -> bool:
    """执行任务。overrides 支持面板传入的临时覆盖参数。"""
    overrides = overrides or {}
    now = datetime.now()
    recent_days = int(overrides.get("recent_days") or cfg.get(f"{TASK_CFG}.search_recent_days", 7))
    min_items = int(overrides.get("min_items") or cfg.get(f"{TASK_CFG}.min_items", 5))
    categories = cfg.get(f"{TASK_CFG}.categories", [])

    # ---- 1. 取期号 ----
    issue = issue_no.next_issue_no(TASK_KEY, now)
    title = f"长春薅羊毛 {now.month}月第{issue}期"
    log.info("开始执行 %s", title)

    # ---- 2. 抓取 ----
    raw_items = fetcher.fetch_all(limit=30, keyword="长春 优惠 活动")
    if not raw_items:
        log.error("未抓取到任何原始信息，任务中止")
        return False

    # ---- 3. 交给 LLM 筛选整理 ----
    prompt = PROMPT_TMPL.format(
        recent_days=recent_days,
        categories="\n".join(f"  {i}. {c}" for i, c in enumerate(categories, 1)),
        min_items=min_items,
        raw=fetcher.format_for_prompt(raw_items),
    )

    try:
        deals: List[Dict[str, Any]] = llm.ask(prompt, system=SYSTEM, expect_json=True)
    except llm.LLMError as exc:
        log.error("LLM 调用失败，任务中止: %s", exc)
        return False

    if not isinstance(deals, list):
        log.error("LLM 返回格式异常，预期数组，实际 %s", type(deals).__name__)
        return False

    if len(deals) < min_items:
        log.warning("本期仅收集到 %d 条，低于目标 %d 条", len(deals), min_items)
    if not deals:
        log.error("本期无合格活动，跳过发送")
        return False

    # ---- 4. 渲染 ----
    html = render.render(
        "deals.html.j2",
        {
            "title": title,
            "issue": issue,
            "deals": deals,
            "summary": f"本期共收录 {len(deals)} 条优质线下活动",
        },
    )

    # ---- 5. 发信（正文内联） ----
    subject = f"【长春薅羊毛】{now.month}月第{issue}期 本期{len(deals)}条优质线下活动"
    mailer.send(subject, html, dry_run=bool(overrides.get("dry_run")))

    # ---- 6. 回写期号 ----
    issue_no.commit_issue_no(TASK_KEY, issue, now)
    log.info("任务完成: %s", title)
    return True
