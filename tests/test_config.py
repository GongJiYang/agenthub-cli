"""config.py 单元测试：默认配置、格式错误路径。"""

import pytest
import yaml

from agenthub.config import ConfigError, load_config
from agenthub.models import AppConfig, LLMConfig


# ── 辅助函数 ──────────────────────────────────────────


def write_yaml(path, data):
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


# ── 文件不存在时使用默认值 ────────────────────────────


def test_load_config_missing_file_returns_default(tmp_path, capsys):
    cfg = load_config(config_path=tmp_path / "config.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.api_base_url == "https://api.agenthub.example.com"
    assert cfg.llm.provider == "claude-code"
    assert cfg.llm.model == "claude-opus-4-5"
    assert cfg.llm.api_key is None


def test_load_config_missing_file_prints_hint(tmp_path, capsys):
    load_config(config_path=tmp_path / "config.yaml")
    out = capsys.readouterr().out
    assert "不存在" in out or "默认" in out


# ── 正常加载 ──────────────────────────────────────────


def test_load_config_full(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {
        "api_base_url": "https://custom.example.com",
        "llm": {"provider": "anthropic", "model": "claude-3-5-sonnet", "api_key": "sk-test"},
    })
    cfg = load_config(config_path=p)
    assert cfg.api_base_url == "https://custom.example.com"
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.model == "claude-3-5-sonnet"
    assert cfg.llm.api_key == "sk-test"


def test_load_config_partial_uses_defaults(tmp_path):
    """只提供部分字段时，其余字段使用默认值。"""
    p = tmp_path / "config.yaml"
    write_yaml(p, {"llm": {"provider": "anthropic", "model": "claude-3-haiku"}})
    cfg = load_config(config_path=p)
    assert cfg.api_base_url == "https://api.agenthub.example.com"
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.api_key is None


def test_load_config_api_key_null(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"api_base_url": "https://x.com", "llm": {"provider": "claude-code", "model": "m", "api_key": None}})
    cfg = load_config(config_path=p)
    assert cfg.llm.api_key is None


# ── 格式非法时抛出 ConfigError ────────────────────────


def test_load_config_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("key: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(config_path=p)


def test_load_config_non_mapping_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_path=p)


def test_load_config_invalid_provider_raises(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"llm": {"provider": "openai", "model": "gpt-4"}})
    with pytest.raises(ConfigError, match="provider"):
        load_config(config_path=p)


def test_load_config_invalid_api_base_url_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"api_base_url": 12345})
    with pytest.raises(ConfigError, match="api_base_url"):
        load_config(config_path=p)


def test_load_config_invalid_llm_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"llm": "not-a-mapping"})
    with pytest.raises(ConfigError, match="llm"):
        load_config(config_path=p)


def test_load_config_invalid_model_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"llm": {"provider": "claude-code", "model": 42}})
    with pytest.raises(ConfigError, match="model"):
        load_config(config_path=p)


def test_load_config_invalid_api_key_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    write_yaml(p, {"llm": {"provider": "claude-code", "model": "m", "api_key": 123}})
    with pytest.raises(ConfigError, match="api_key"):
        load_config(config_path=p)
