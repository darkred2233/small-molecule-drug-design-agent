"""
YAML配置加载器

支持环境变量替换和多环境配置
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path = "config.yaml") -> dict[str, Any]:
    """
    加载YAML配置文件

    支持环境变量替换：${VAR_NAME}
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 替换环境变量
    content = _replace_env_vars(content)

    # 解析YAML
    config = yaml.safe_load(content)

    return config


def _replace_env_vars(content: str) -> str:
    """替换环境变量"""

    def replace_match(match):
        var_name = match.group(1)
        default_value = match.group(2) if match.lastindex >= 2 else None

        value = os.getenv(var_name, default_value)

        if value is None:
            raise ValueError(f"环境变量未设置且无默认值: {var_name}")

        return value

    # 支持 ${VAR} 和 ${VAR:default}
    pattern = r'\$\{([A-Z_][A-Z0-9_]*?)(?::([^}]*))?\}'
    return re.sub(pattern, replace_match, content)


def get_nested_value(config: dict, key_path: str, default: Any = None) -> Any:
    """
    获取嵌套配置值

    例如: get_nested_value(config, "llm.providers.qwen.api_key")
    """
    keys = key_path.split(".")
    value = config

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


# 全局配置缓存
_global_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """获取全局配置"""
    global _global_config

    if _global_config is None:
        _global_config = load_config()

    return _global_config
