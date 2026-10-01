"""调度入口：判断当前这一刻该跑哪个任务。

由 GitHub Actions 的两个 cron 触发：
    北京时间 23:23  -> 槽位 deals
    北京时间 23:37  -> 槽位 report

判断逻辑（从 config.yaml 读取，改规则不用动 workflow）：
    23:23 槽：双号且非排除日 -> 长春薅羊毛
    23:37 槽：单号且非排除日 -> AI日报
              日期命中 run_days -> 用户痛点快报（与 AI日报同槽，可并行）

用法：
    python scripts/dispatch.py                  # 按当前时间自动判断
    python scripts/dispatch.py --slot deals     # 强制指定槽位
    python scripts/dispatch.py --task ai_daily  # 强制指定任务
    python scripts/dispatch.py --dry-run        # 不发信，只验证流程
    python scripts/dispatch.py --date 2026-09-23  # 模拟指定日期
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config as cfg  # noqa: E402
from tasks import ai_daily, changchun_deals, pain_points  # noqa: E402

ALL_TASKS = {
    "changchun_deals": changchun_deals,
    "ai_daily": ai_daily,
    "pain_points": pain_points,
}

# 槽位 -> 该槽位可能执行的任务
SLOTS = {
    "deals": ["changchun_deals"],
    "report": ["ai_daily", "pain_points"],
}


def setup_logging() -> None:
    level = getattr(logging, str(cfg.get("runtime.log_level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def day_matches(task_key: str, when: datetime) -> bool:
    """判断某个任务今天是否应该执行。

    这是整个方案的触发规则核心，务必与原始日历规则精确一致。
    """
    base = f"tasks.{task_key}"
    if not cfg.get(f"{base}.enabled", True):
        return False

    day = when.day
    exclude = cfg.get(f"{base}.exclude_days", []) or []
    if day in exclude:
        return False

    mode = cfg.get(f"{base}.days", "even")

    if mode == "special":
        return day in (cfg.get(f"{base}.run_days", []) or [])
    if mode == "even":
        return day % 2 == 0
    if mode == "odd":
        return day % 2 == 1
    if mode == "all":
        return True
    return False


def resolve(when: datetime, slot: str | None = None) -> list[str]:
    """返回该时刻需要执行的任务列表（已应用开关与日期规则）。"""
    candidates = SLOTS.get(slot, []) if slot else list(ALL_TASKS.keys())
    return [key for key in candidates if day_matches(key, when)]


def main() -> int:
    parser = argparse.ArgumentParser(description="定时任务调度入口")
    parser.add_argument("--slot", choices=list(SLOTS), help="槽位：deals / report")
    parser.add_argument("--task", choices=list(ALL_TASKS), help="强制指定单个任务")
    parser.add_argument("--date", help="模拟日期，格式 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="不发信，只验证流程")
    parser.add_argument("--to", help="临时覆盖收件人")
    parser.add_argument("--force", action="store_true", help="忽略日期规则强制执行")
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger("dispatch")

    when = datetime.now()
    if args.date:
        when = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=when.hour, minute=when.minute
        )

    log.info("调度时刻: %s  槽位: %s", when.strftime("%Y-%m-%d %H:%M"), args.slot or "自动")

    if args.task:
        targets = [args.task]
    elif args.force:
        targets = list(ALL_TASKS.keys())
    else:
        targets = resolve(when, args.slot)

    if not targets:
        log.info("今天此刻没有需要执行的任务，正常退出")
        return 0

    log.info("本次将执行: %s", ", ".join(targets))

    overrides = {}
    if args.to:
        # 收件人覆盖通过环境变量透传给 mailer
        import os

        os.environ["MAIL_TO_OVERRIDE"] = args.to
    if args.dry_run:
        overrides["dry_run"] = True

    results = {}
    for key in targets:
        module = ALL_TASKS.get(key)
        if module is None:
            log.error("未知任务: %s", key)
            results[key] = False
            continue
        log.info("---- 开始执行任务: %s ----", key)
        try:
            results[key] = module.run(overrides)
        except Exception as exc:  # noqa: BLE001 - 单任务失败不影响其他
            log.exception("任务 %s 执行异常", key, exc_info=exc)
            results[key] = False

    log.info("---- 执行结果 ----")
    for key, ok in results.items():
        log.info("  %-18s %s", key, "成功" if ok else "失败")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
