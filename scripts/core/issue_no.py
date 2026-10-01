"""期数计数管理。

规则（继承原 Coze 方案）：
- 读取 data/issue_counter.json 作为基准
- 扫描当月已有产物取最大期号，取两者较大的 +1
- 执行后回写计数文件
- 自检：文件名 / 标题 / 邮件主题 三处期数必须一致
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
COUNTER_PATH = ROOT / "data" / "issue_counter.json"
ARCHIVE_DIR = ROOT / "data" / "archive"


def _read_counter() -> Dict[str, Any]:
    if not COUNTER_PATH.exists():
        return {}
    try:
        return json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("issue_counter.json 解析失败，按空处理")
        return {}


def _write_counter(data: Dict[str, Any]) -> None:
    COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    COUNTER_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _scan_existing_max(task: str, year: int, month: int) -> int:
    """扫描 data/archive/YYYY-MM/ 下已有文件，取最大期号。"""
    folder = ARCHIVE_DIR / f"{year:04d}-{month:02d}"
    if not folder.exists():
        return 0

    max_no = 0
    for path in folder.glob(f"{task}-*.html"):
        stem = path.stem  # 例如 changchun-deals-2026-09-3
        parts = stem.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            max_no = max(max_no, int(parts[1]))
    return max_no


def next_issue_no(task: str, when: datetime | None = None) -> int:
    """计算下一个期号（不写回）。"""
    when = when or datetime.now()
    counter = _read_counter()

    key = f"{when.year:04d}-{when.month:02d}"
    stored = int((counter.get(task) or {}).get(key, 0))
    scanned = _scan_existing_max(task, when.year, when.month)

    return max(stored, scanned) + 1


def commit_issue_no(task: str, issue_no: int, when: datetime | None = None) -> None:
    """执行成功后回写期号计数。"""
    when = when or datetime.now()
    counter = _read_counter()

    key = f"{when.year:04d}-{when.month:02d}"
    counter.setdefault(task, {})[key] = int(issue_no)
    counter[task]["_updated_at"] = when.isoformat(timespec="seconds")

    _write_counter(counter)
    log.info("期号已回写: task=%s %s -> %d", task, key, issue_no)


def archive(
    task: str,
    issue_no: int,
    html: str,
    when: datetime | None = None,
    title: str = "",
    subject: str = "",
) -> Path:
    """存档 HTML 并做三处期数一致性自检。"""
    when = when or datetime.now()
    folder = ARCHIVE_DIR / f"{when.year:04d}-{when.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{task}-{when.strftime('%Y-%m-%d')}-{issue_no}.html"
    path = folder / filename

    # 三处一致性自检：期号数字必须都出现
    checks = {"filename": filename}
    if title:
        checks["title"] = title
    if subject:
        checks["subject"] = subject

    for label, text in checks.items():
        if str(issue_no) not in text:
            log.warning("期号一致性自检未通过：%s=%r 不含期号 %d", label, text, issue_no)

    path.write_text(html, encoding="utf-8")
    log.info("已存档: %s", path)
    return path
