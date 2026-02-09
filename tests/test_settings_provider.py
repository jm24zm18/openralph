from __future__ import annotations

import pytest

from openralph.openralph_cli.settings import ConfigLoadError, OpenRalphSettings, get_provider_config


def test_get_provider_config_prefers_role_model() -> None:
    s = OpenRalphSettings()
    s.agent_test_model = "model-test"
    s.agents_default_model = "model-default"
    s.proxy_model_id = "model-proxy"
    cfg = get_provider_config(s, role="test")
    assert cfg["model"] == "model-test"


def test_get_provider_config_falls_back_default_then_proxy() -> None:
    s = OpenRalphSettings()
    s.agents_default_model = "model-default"
    cfg = get_provider_config(s, role="unknown")
    assert cfg["model"] == "model-default"

    s.agents_default_model = ""
    cfg2 = get_provider_config(s, role="unknown")
    assert cfg2["model"] == s.proxy_model_id


def test_settings_load_invalid_toml_value_reports_field(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".openralph.toml").write_text('[proxy]\nlisten_port = "abc"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        OpenRalphSettings.load(repo)
    assert "proxy.listen_port" in str(exc.value)
