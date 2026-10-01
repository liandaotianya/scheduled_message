"""配置加载：统一读取 config.yaml 与 sources.yaml，并加载 .env。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

# 项目根目录（scripts/core/config.py -> 上溯两级）
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "config.yaml"
SOURCES_PATH = ROOT / "config" / "sources.yaml"

_config_cache: Dict[str, Any] | None = None
_sources_cache: Dict[str, Any] | None = None


def _load_dotenv() -> None:
    """极简 .env 加载，避免额外依赖。已存在的环境变量不覆盖。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(reload: bool = False) -> Dict[str, Any]:
    """读取 config.yaml。"""
    global _config_cache
    if _config_cache is None or reload:
        _load_dotenv()
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            _config_cache = yaml.safe_load(fh) or {}
    return _config_cache


def load_sources(reload: bool = False) -> Dict[str, Any]:
    """读取 sources.yaml，返回 sources 段的字典。"""
    global _sources_cache
    if _sources_cache is None or reload:
        with SOURCES_PATH.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        _sources_cache = data.get("sources", {}) or {}
    return _sources_cache


def get(path: str, default: Any = None) -> Any:
    """按点号路径取值，例如 get("tasks.ai_daily.enabled")。"""
    node: Any = load_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def enabled_sources(tag: str | None = None) -> Dict[str, Dict[str, Any]]:
    """取已启用的抓取源；可按 tag 过滤。"""
    result: Dict[str, Dict[str, Any]] = {}
    for name, meta in load_sources().items():
        if not meta.get("enabled"):
            continue
        if tag and tag not in (meta.get("tags") or []):
            continue
        result[name] = meta
    return result
