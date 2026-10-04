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
    "你是长春本地生活情报编辑，专门挖掘稀缺薅羊毛机会：政府/平台限量消费券、"
    "限时线下活动、工会专属福利、早鸟票等。"
    "你的选稿铁律是稀缺：常年都有的常规折扣一律不要，只收『错过即无、错过等一年』的机会。"
    "你极度讨厌营销软文，只收录信息完整、真实可操作的优惠。"
    "信息不足时你宁可不收录，也绝不编造时间、规则或参与方式。"
)

PROMPT_TMPL = """
请从下面的原始信息里，筛选出**长春本地或长春可参与**的稀缺薅羊毛机会，分两类：

## A 类：线下活动
有具体地址（商场/门店/场馆名 + 大致位置）的限时优惠活动。

## B 类：优惠券 / 抢购类
云闪付消费券、加油优惠券、工会职工福利、限量商户券等。
必须给出：抢券/领取时间、领取入口、使用规则，三者齐全才可收录。

## 本期时间窗口
{recent_days} 天内（活动或抢券在此窗口内可操作）

## 品类优先级（越靠前越优先收录）
{categories}

## 稀缺性硬标准（核心！不满足即剔除）
- 限量：总量有限（如 消费券限量 X 万份、限量 100 张券）
- 限时：窗口短（如 仅 3 天、每日 10 点限量抢、本周日截止）
- 稀有：周期性稀缺（如 一年一度、早鸟价仅本周、免费名额有限需预约）
- 以上至少占一条；『长期有效、随时可买』的常规折扣一律剔除，哪怕折扣力度大

## 绝对排除（出现任一即剔除）
- 已过期或本期窗口内无法参与的
- 常年有效的常规会员折扣、常规团购价（无稀缺性）
- 营销软文、无具体规则的推广
- 二手转卖
- 与长春无关且长春用户无法参与的
- 原始信息里没有出处、疑似编造的内容

## 原始信息
{raw}

## 输出要求
1. 严格输出 JSON 数组，按稀缺程度从高到低排序（最急的排最前）
2. 每个元素包含以下字段：
{{
  "title": "活动或券的名称",
  "category": "所属品类（必须是上面品类之一）",
  "discount": "优惠力度（如 5折 / 免费 / 政府券满50减20）",
  "time": "活动时间或抢券时间",
  "location": "线下地址；B 类填使用范围（如 全市云闪付商户）",
  "content": "活动内容或使用规则，40字以内",
  "age": "适合人群（如 3-12岁亲子 / 工会会员 / 不限）",
  "how": "参与方式或领取入口（如 云闪付APP每日10点抢）",
  "url": "来源链接（必须是原始信息里的真实链接）",
  "rarity": "为什么现在不薅就没了，20字以内（如 限量1万份抢完即止 / 仅此3天 / 一年一度）"
}}

只输出 JSON，不要任何解释文字。如果确实找不到合格内容，输出 []。
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

    # ---- 2. 抓取（只取本地相关源，避免无关资讯稀释筛选）----
    raw_items = fetcher.fetch_by_tags(categories, limit=30, keyword="长春 优惠 活动")
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
