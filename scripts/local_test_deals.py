"""薅羊毛任务本地测试脚本（一次性工具，不参与正式调度）

用途：在不上 Actions 的情况下验证链路各环节，定位问题出在哪一段。

必填环境变量：
    BOCHA_API_KEY   博查搜索 Key（没有则搜索环节返回 0 条）
    GEMINI_API_KEY  或 DEEPSEEK_API_KEY（没有则筛选环节会失败）

用法（Git Bash）：
    export BOCHA_API_KEY='你的key'
    export GEMINI_API_KEY='你的key'
    "C:/Users/thinkpad/.workbuddy/binaries/python/envs/default/Scripts/python.exe" scripts/local_test_deals.py

分段验证（不带密钥也能跑）：
    ... scripts/local_test_deals.py --stage fetch
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config as cfg  # noqa: E402
from core import fetcher, issue_no, llm, render  # noqa: E402
from tasks.changchun_deals import PROMPT_TMPL, SYSTEM  # noqa: E402

log = logging.getLogger("test")

KEYS = ("BOCHA_API_KEY", "SERPER_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")


def check_env() -> None:
    print("=" * 60)
    print("[0] 环境变量检查")
    print("=" * 60)
    missing = []
    for k in KEYS:
        v = os.environ.get(k)
        mark = "已设置" if v else "未设置"
        print(f"  {k:<18} {mark}")
        if not v and k in ("BOCHA_API_KEY",):
            missing.append(k)
    if missing:
        print(f"\n  ⚠️缺少 {', '.join(missing)}：搜索环节会返回 0 条候选")
    has_llm = os.environ.get("GEMINI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not has_llm:
        print("  ⚠️ 没有模型 Key：筛选环节必然失败，只能验证到抓取为止")
    print()


def stage_fetch(recent_days: int) -> int:
    print("=" * 60)
    print("[1] 抓取环节")
    print("=" * 60)
    categories = cfg.get("tasks.changchun_deals.categories", [])
    print(f"  品类：{'、'.join(categories)}")
    print(f"  有效窗口：{recent_days} 天\n")

    items = fetcher.fetch_by_tags(
        categories, limit=30, keyword="长春 优惠 活动", task="deals",
        recent_days=recent_days,
    )
    print(f"\n  候选合计：{len(items)} 条")
    srcs: dict = {}
    for i in items:
        srcs[i.source] = srcs.get(i.source, 0) + 1
    for k, v in srcs.items():
        print(f"    {k}: {v} 条")

    if not items:
        print("\n  ❌ 候选为 0，链路到此中断。请检查 BOCHA_API_KEY 是否配置。")
        return 0
    print("\n  前 5 条候选：")
    for i, it in enumerate(items[:5], 1):
        print(f"    {i}. {it.title[:56]}")
    return len(items)


def stage_llm(items: list) -> None:
    print("\n" + "=" * 60)
    print("[2] 筛选环节（调用模型）")
    print("=" * 60)
    recent_days = int(cfg.get("tasks.changchun_deals.search_recent_days", 3))
    categories = cfg.get("tasks.changchun_deals.categories", [])
    prompt = PROMPT_TMPL.format(
        recent_days=recent_days,
        categories="\n".join(f"  {i}. {c}" for i, c in enumerate(categories, 1)),
        min_items=int(cfg.get("tasks.changchun_deals.min_items", 5)),
        raw=fetcher.format_for_prompt(items),
    )
    print(f"  提示词长度：{len(prompt)} 字符，模型开始筛选（可能需要 30-60 秒）...")
    try:
        deals = llm.ask(prompt, system=SYSTEM, expect_json=True)
    except llm.LLMError as exc:
        print(f"\n  ❌ 模型调用失败：{exc}")
        return
    print(f"\n  ✅ 筛选出 {len(deals)} 条")
    for d in deals:
        print(f"    · [{d.get('category','')}] {str(d.get('title',''))[:44]}")
        print(f"      稀缺理由：{d.get('rarity','')}")

    # 渲染样张，便于直接看邮件效果
    html = render.render(
        "deals.html.j2",
        {
            "title": "长春薅羊毛（本地测试样张）",
            "issue": 0,
            "deals": deals,
            "summary": f"本期共收录 {len(deals)} 条稀缺机会",
            "empty_reason": "",
        },
    )
    out = Path(__file__).resolve().parent.parent / "preview_deals.html"
    out.write_text(html, encoding="utf-8")
    print(f"\n  邮件样张已生成：{out}")
    print("  用浏览器打开即可预览手机端效果（建议 F12 切到 iPhone 视口）")


def main() -> int:
    parser = argparse.ArgumentParser(description="薅羊毛任务本地测试")
    parser.add_argument("--stage", choices=["fetch", "full"], default="fetch",
                        help="fetch=只验抓取（不需密钥）；full=跑完整筛选")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    check_env()
    recent_days = int(cfg.get("tasks.changchun_deals.search_recent_days", 3))
    count = stage_fetch(recent_days)

    if args.stage == "full":
        stage_llm(fetcher.fetch_by_tags(
            cfg.get("tasks.changchun_deals.categories", []),
            limit=30, keyword="长春 优惠 活动", task="deals",
            recent_days=recent_days,
        ))
    else:
        print("\n  提示：加 --stage full 可连模型筛选一起验证（需配置模型 Key）")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
