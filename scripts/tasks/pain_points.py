"""任务③：用户痛点快报

触发：每月 7、16、23、30 号 23:37
目标：收集社交平台真实用户吐槽，20 条
严格筛选：纯软件 / AI 可落地解决的痛点，宁缺毋滥
6 大场景：居家日用、通勤出行、育儿生活、上班族职场、养老便民、日常消费餐饮
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from core import config as cfg
from core import fetcher, issue_no, llm, mailer, render

log = logging.getLogger(__name__)

TASK_KEY = "pain-points"
TASK_CFG = "tasks.pain_points"

SYSTEM = (
    "你是产品机会挖掘者，专门从用户的抱怨里找出可以做成产品的真痛点。"
    "你只认可能用软件或 AI 解决的痛点，例如网站、小程序、App、AI助手、浏览器插件、自动化脚本。"
    "纯情绪宣泄、纯服务态度问题、纯硬件问题一律排除。"
)

PROMPT_TMPL = """
请从下面的原始信息里，提炼 {total} 条**真实用户痛点**。

## 场景分布（共 6 个，每个约 3-4 条）
{scenes}

## 收录标准（缺一不可）
1. 是真实用户在社交平台上的吐槽，不是厂商的产品宣传
2. 必须能用软件 / AI 解决：网站、小程序、App、AI助手、浏览器插件、自动化脚本
3. 痛点要具体，能说清"在什么场景下、遇到什么麻烦"
4. 宁缺毋滥：宁可少于 {total} 条，也不要凑数

## 绝对排除
- 纯情绪宣泄、没有具体场景的抱怨
- 纯服务态度、纯硬件质量、纯价格问题
- 已经有大厂成熟产品完美解决的（除非你对现有方案不满意，要说明为什么）
- 编造的痛点

## 重点寻找这 8 个高价值方向
{focus_areas}

## 原始信息
{raw}

## 输出要求
严格输出 JSON 数组，每个元素：
{{
  "scene": "所属场景（必须是上面场景之一）",
  "pain": "痛点描述，一句话说清用户遇到什么麻烦",
  "quote": "用户原话（来自原始信息，简短引用）",
  "high_value": "是否属于 8 个高价值方向之一，是则写方向名，否则写「否」",
  "solution": "可行的解决思路，30字以内；如果目前没有现成方案标注「待造」",
  "url": "来源链接",
  "difficulty": "实现难度：低/中/高"
}}

只输出 JSON 数组，不要任何解释文字。
"""

FOCUS_AREAS = [
    "信息聚合",
    "决策辅助",
    "效率工具",
    "自动化替代人工",
    "个性化推荐",
    "跨平台数据打通",
    "内容生成",
    "小众群体服务",
]


def run(overrides: Dict[str, Any] | None = None) -> bool:
    overrides = overrides or {}
    now = datetime.now()
    total = int(overrides.get("total_items") or cfg.get(f"{TASK_CFG}.total_items", 20))
    scenes = cfg.get(f"{TASK_CFG}.scenes", [])

    issue = issue_no.next_issue_no(TASK_KEY, now)
    title = f"用户痛点快报 {now.month}月第{issue}期"
    log.info("开始执行 %s", title)

    # ---- 1. 抓取（重点覆盖吐槽类场景） ----
    raw_items = fetcher.fetch_all(limit=50, keyword="吐槽 痛点 难用")
    if not raw_items:
        log.error("未抓取到任何原始信息，任务中止")
        return False

    # ---- 2. LLM 提炼 ----
    prompt = PROMPT_TMPL.format(
        total=total,
        scenes="\n".join(f"- {s}（约 3-4 条）" for s in scenes),
        focus_areas="\n".join(f"  {i}. {a}" for i, a in enumerate(FOCUS_AREAS, 1)),
        raw=fetcher.format_for_prompt(raw_items, per_item=200),
    )

    try:
        pains: List[Dict[str, Any]] = llm.ask(prompt, system=SYSTEM, expect_json=True)
    except llm.LLMError as exc:
        log.error("LLM 调用失败，任务中止: %s", exc)
        return False

    if not isinstance(pains, list) or not pains:
        log.error("LLM 未产出合格痛点，任务中止")
        return False

    if len(pains) < total:
        log.warning("本期仅提炼出 %d 条，低于目标 %d 条", len(pains), total)

    # ---- 3. 渲染 ----
    html = render.render(
        "pain_points.html.j2",
        {
            "title": title,
            "issue": issue,
            "pains": pains,
            "scenes": scenes,
            "summary": f"本期共提炼 {len(pains)} 条可落地痛点",
        },
    )

    # ---- 4. 发信（正文内联） ----
    subject = f"用户痛点快报 {now.month}月第{issue}期 本期{len(pains)}条"
    mailer.send(subject, html, dry_run=bool(overrides.get("dry_run")))

    # ---- 5. 回写期号 ----
    issue_no.commit_issue_no(TASK_KEY, issue, now)
    log.info("任务完成: %s", title)
    return True
