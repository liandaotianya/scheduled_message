"""HTML 渲染：Jinja2 模板 -> 邮件正文。

关键约束（继承原 Coze 方案）：
渲染结果直接 return 字符串，交给 mailer 内联发送。
严禁"先写文件再引用路径"的发信方式。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, context: Dict[str, Any]) -> str:
    """渲染模板，返回 HTML 字符串。"""
    ctx = {
        "now": datetime.now(),
        "year": datetime.now().year,
        "month": datetime.now().month,
        **context,
    }
    html = _env.get_template(template_name).render(**ctx)
    return html


def base_context(title: str, subtitle: str = "") -> Dict[str, Any]:
    return {"title": title, "subtitle": subtitle}
