"""邮件发送：QQ 邮箱 SMTP。

强制规则（继承原 Coze 方案，务必遵守）：
    HTML 正文必须"直接内联"传入 send()，
    严禁"先写到一个本地文件、再把文件路径交给发信逻辑"。
    因为发信环节读不到文件时会自行生成兜底内容，
    导致收件人看到的不是真实结果。
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import List, Optional

from . import config as cfg

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    pass


def _recipients(raw: str) -> List[str]:
    return [addr.strip() for addr in str(raw).replace(";", ",").split(",") if addr.strip()]


def send(
    subject: str,
    html_body: str,
    to: Optional[str] = None,
    sender: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """发送 HTML 邮件。

    Args:
        subject: 邮件主题
        html_body: HTML 正文（内联字符串，不接受文件路径）
        to: 收件人，默认读 config
        sender: 发件人，默认读 config
        dry_run: True 时只打日志不真发

    Returns:
        是否发送成功
    """
    if not html_body or not html_body.strip():
        raise MailError("HTML 正文为空，拒绝发送")
    if html_body.lstrip().startswith(("/", "\\", "./", "..")) and len(html_body) < 300:
        raise MailError(
            "疑似传入了文件路径而非 HTML 正文。正文必须内联字符串传入。"
        )

    mail_cfg = cfg.get("mail", {}) or {}
    to_override = os.environ.get("MAIL_TO_OVERRIDE")
    to_addr = _recipients(to or to_override or mail_cfg.get("to", ""))
    from_addr = sender or mail_cfg.get("from") or os.environ.get("MAIL_FROM", "")
    prefix = mail_cfg.get("subject_prefix", "") or ""
    full_subject = f"{prefix}{subject}"

    if not to_addr or not from_addr:
        raise MailError("收件人或发件人为空，请检查 config.yaml 的 mail 段")

    if dry_run or not mail_cfg.get("send_enabled", True):
        log.info("[dry-run] 主题=%s 收件人=%s 正文长度=%d", full_subject, to_addr, len(html_body))
        return True

    auth_code = os.environ.get("MAIL_AUTH_CODE")
    if not auth_code:
        raise MailError("缺少 MAIL_AUTH_CODE（QQ 邮箱 SMTP 授权码）")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(full_subject, "utf-8")
    msg["From"] = formataddr(("AI 日报机器人", from_addr))
    msg["To"] = ", ".join(to_addr)
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    host = mail_cfg.get("smtp_host", "smtp.qq.com")
    port = int(mail_cfg.get("smtp_port", 465))

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as server:
                server.login(from_addr, auth_code)
                server.sendmail(from_addr, to_addr, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=ctx)
                server.login(from_addr, auth_code)
                server.sendmail(from_addr, to_addr, msg.as_string())
    except smtplib.SMTPException as exc:
        raise MailError(f"SMTP 发送失败: {exc}") from exc

    log.info("邮件已发送: %s -> %s", full_subject, to_addr)
    return True
