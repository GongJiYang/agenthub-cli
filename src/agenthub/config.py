"""配置加载模块：从 ~/.agenthub/config.yaml 加载 AppConfig。"""

from pathlib import Path

import yaml

from .models import AppConfig, LLMConfig

CONFIG_PATH = Path("~/.agenthub/config.yaml").expanduser()

_DEFAULT_CONFIG = AppConfig(
    api_base_url="https://api.agenthub.example.com",
    llm=LLMConfig(
        provider="claude-code",
        model="claude-opus-4-5",
        api_key=None,
    ),
    workspace_root="",
)


class ConfigError(Exception):
    """配置文件格式非法时抛出。"""


def load_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    """加载配置，不存在时返回默认值并提示，格式错误时抛出 ConfigError。"""
    if not config_path.exists():
        print(
            f"提示：配置文件 {config_path} 不存在，使用内置默认配置。"
            f"\n      可创建该文件以自定义配置。"
        )
        return _DEFAULT_CONFIG

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"无法读取配置文件 {config_path}：{e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 解析失败：{e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"配置文件格式非法：顶层结构必须是映射（mapping），实际得到 {type(data).__name__}")

    try:
        api_base_url = data.get("api_base_url", _DEFAULT_CONFIG.api_base_url)
        if not isinstance(api_base_url, str):
            raise ConfigError(f"配置项 api_base_url 必须是字符串，实际得到 {type(api_base_url).__name__}")

        llm_data = data.get("llm", {})
        if not isinstance(llm_data, dict):
            raise ConfigError(f"配置项 llm 必须是映射（mapping），实际得到 {type(llm_data).__name__}")

        provider = llm_data.get("provider", _DEFAULT_CONFIG.llm.provider)
        if provider not in ("claude-code", "anthropic"):
            raise ConfigError(
                f"配置项 llm.provider 必须是 'claude-code' 或 'anthropic'，实际得到 {provider!r}"
            )

        model = llm_data.get("model", _DEFAULT_CONFIG.llm.model)
        if not isinstance(model, str):
            raise ConfigError(f"配置项 llm.model 必须是字符串，实际得到 {type(model).__name__}")

        api_key = llm_data.get("api_key", _DEFAULT_CONFIG.llm.api_key)
        if api_key is not None and not isinstance(api_key, str):
            raise ConfigError(f"配置项 llm.api_key 必须是字符串或 null，实际得到 {type(api_key).__name__}")

        workspace_root = data.get("workspace_root", _DEFAULT_CONFIG.workspace_root)
        if not isinstance(workspace_root, str):
            raise ConfigError(f"配置项 workspace_root 必须是字符串，实际得到 {type(workspace_root).__name__}")

    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"配置文件解析出错：{e}") from e

    return AppConfig(
        api_base_url=api_base_url,
        llm=LLMConfig(provider=provider, model=model, api_key=api_key),
        workspace_root=workspace_root,
    )
