"""手动执行入口：供管理面板 / 手动 workflow 调用。

与 dispatch.py 的区别：
- dispatch.py 按时间自动判断该跑什么（定时触发用）
- run_manual.py 由人明确指定跑什么，参数从命令行或 JSON 传入

用法：
    python scripts/run_manual.py --task ai_daily
    python scripts/run_manual.py --task all --dry-run
    python scripts/run_manual.py --task changchun_deals --to other@qq.com
    python scripts/run_manual.py --json '{"task":"ai_daily","overrides":{"items_per_category":3}}'
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config as cfg  # noqa: E402
from tasks import ai_daily, changchun_deals, pain_points  # noqa: E402

ALL_TASKS = {
    "changchun_deals": changchun_deals,
    "ai_daily": ai_daily,
    "pain_points": pain_points,
}

# 面板参数名 -> 任务内部识别名
OVERRIDE_KEYS = {
    "min_items",
    "recent_days",
    "items_per_category",
    "total_items",
    "dry_run",
}


def setup_logging() -> None:
    level = getattr(logging, str(cfg.get("runtime.log_level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="手动执行任务")
    parser.add_argument("--task", required=True, help="任务名，或 all 表示全部")
    parser.add_argument("--json", help="JSON 参数串，可含 overrides 字段")
    parser.add_argument("--to", help="临时覆盖收件人")
    parser.add_argument("--dry-run", action="store_true", help="不发信")
    parser.add_argument("--min-items", type=int)
    parser.add_argument("--items-per-category", type=int)
    parser.add_argument("--total-items", type=int)
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger("manual")

    overrides: dict = {}
    if args.json:
        try:
            payload = json.loads(args.json)
            overrides.update(payload.get("overrides") or {})
        except json.JSONDecodeError as exc:
            log.error("--json 解析失败: %s", exc)
            return 2

    if args.min_items:
        overrides["min_items"] = args.min_items
    if args.items_per_category:
        overrides["items_per_category"] = args.items_per_category
    if args.total_items:
        overrides["total_items"] = args.total_items
    if args.dry_run:
        overrides["dry_run"] = True

    if args.to:
        os.environ["MAIL_TO_OVERRIDE"] = args.to

    targets = list(ALL_TASKS) if args.task == "all" else [args.task]
    for key in targets:
        if key not in ALL_TASKS:
            log.error("未知任务: %s，可选: %s", key, ", ".join(ALL_TASKS))
            return 2

    overrides = {k: v for k, v in overrides.items() if k in OVERRIDE_KEYS}

    results = {}
    for key in targets:
        log.info("---- 手动执行: %s ----", key)
        try:
            results[key] = ALL_TASKS[key].run(overrides)
        except Exception as exc:  # noqa: BLE001
            log.exception("任务 %s 执行异常", key, exc_info=exc)
            results[key] = False

    log.info("---- 执行结果 ----")
    for key, ok in results.items():
        log.info("  %-18s %s", key, "成功" if ok else "失败")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
