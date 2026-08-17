"""
Unit tests for farm_agent.tenancy.tenant — TDD RED gate.

Coverage:
- Layer precedence: YAML > env > default
- Missing-secret raises RuntimeError naming the key
- Traversal guard: ../../etc/passwd → empty dict
- SIGNAL_FARMER_MAP object form parses to dict[str,str]
- SIGNAL_FARMER_MAP missing → {}
- FARMOS_INTEGRATION bool coercion (YAML bool, env string '1'/'0')
- Numeric field coercion (int/float)
- SIGNAL_GROUP_ID empty string normalised to None
- strains loaded from YAML
"""

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal env that satisfies all _must_env secrets.
MINIMAL_SECRET_ENV: dict[str, str] = {
    "SIGNAL_SENDER": "+10000000000",
    "TIMESCALE_PASSWORD": "s3cret",
    "ANTHROPIC_API_KEY": "sk-test",
    "FARMOS_PASSWORD": "fp-test",
    "SIGNAL_RECIPIENT": "+10000000001",
}


def _env(**overrides: str) -> dict[str, str]:
    """Return MINIMAL_SECRET_ENV merged with overrides."""
    e = dict(MINIMAL_SECRET_ENV)
    e.update(overrides)
    return e


# ---------------------------------------------------------------------------
# Import the module under test (after RED stub is written it will exist)
# ---------------------------------------------------------------------------

from farm_agent.tenancy import tenant as _tenant_mod  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Layer precedence tests
# ---------------------------------------------------------------------------


def test_pick_yaml_wins_over_env_and_default(tmp_path, monkeypatch):
    """YAML value takes precedence over env and hardcoded default."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "mossrock"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text(
        "FARMOS_URL: http://yaml-farmos:9999\n"
    )
    cfg = _tenant_mod.load(_env(TENANT_ID="mossrock", FARMOS_URL="http://env-farmos:1234"))
    assert cfg.farmos_url == "http://yaml-farmos:9999"


def test_pick_env_wins_over_default(tmp_path, monkeypatch):
    """Env value wins when YAML doesn't supply the key."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", FARMOS_URL="http://env-only:5555"))
    assert cfg.farmos_url == "http://env-only:5555"


def test_hardcoded_default_used_when_no_yaml_no_env(tmp_path, monkeypatch):
    """Hardcoded default is used when neither YAML nor env supplies the key."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    env = _env(TENANT_ID="t1")
    # FARMOS_URL not in env; default is the config.js fallback
    cfg = _tenant_mod.load(env)
    assert cfg.farmos_url == "http://10.68.155.50:18080"


# ---------------------------------------------------------------------------
# 2. Missing-secret RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_key", [
    "SIGNAL_SENDER",
    "TIMESCALE_PASSWORD",
    "ANTHROPIC_API_KEY",
])
def test_missing_secret_raises_runtime_error(tmp_path, monkeypatch, missing_key):
    """Missing required secret raises RuntimeError naming the key."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    env = _env(TENANT_ID="t1")
    del env[missing_key]
    with pytest.raises(RuntimeError, match=missing_key):
        _tenant_mod.load(env)


def test_missing_farmos_password_does_not_raise(tmp_path, monkeypatch):
    """FARMOS_PASSWORD missing uses empty string default (back-compat, not mustEnv).

    config.js: farmosPassword: env.FARMOS_PASSWORD || ''
    Missing FARMOS_PASSWORD must NOT raise; it silently defaults to ''.
    """
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    env = _env(TENANT_ID="t1")
    del env["FARMOS_PASSWORD"]
    cfg = _tenant_mod.load(env)
    assert cfg.farmos_password == ""


def test_empty_signal_sender_raises(tmp_path, monkeypatch):
    """Empty string SIGNAL_SENDER is treated as missing (falsy check)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    env = _env(TENANT_ID="t1", SIGNAL_SENDER="")
    with pytest.raises(RuntimeError, match="SIGNAL_SENDER"):
        _tenant_mod.load(env)


# ---------------------------------------------------------------------------
# 3. Path-traversal guard
# ---------------------------------------------------------------------------


def test_traversal_filename_returns_empty(tmp_path, monkeypatch):
    """_load_tenant_file with traversal path returns empty dict (does not escape)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    result = _tenant_mod._load_tenant_file("../../etc", "passwd")
    assert result == {}


def test_traversal_via_tenant_id(tmp_path, monkeypatch):
    """Traversal attempt via tenant_id component is blocked."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    result = _tenant_mod._load_tenant_file("../../../etc", "passwd")
    assert result == {}


def test_missing_tenant_dir_returns_empty(tmp_path, monkeypatch):
    """Missing tenant directory returns empty dict gracefully."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    result = _tenant_mod._load_tenant_file("nonexistent", "config.yaml")
    assert result == {}


# ---------------------------------------------------------------------------
# 4. SIGNAL_FARMER_MAP parsing
# ---------------------------------------------------------------------------


def test_farmer_map_object_form_from_yaml(tmp_path, monkeypatch):
    """Object form in YAML (e164 → slug) is parsed to dict[str, str]."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "mossrock"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text(
        "SIGNAL_FARMER_MAP:\n"
        '  "+59892893012": f1\n'
        '  "+59891840205": bot\n'
    )
    cfg = _tenant_mod.load(_env(TENANT_ID="mossrock"))
    assert cfg.signal_farmer_map == {"+59892893012": "f1", "+59891840205": "bot"}


def test_farmer_map_missing_yields_empty(tmp_path, monkeypatch):
    """No SIGNAL_FARMER_MAP in YAML or env yields empty dict."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.signal_farmer_map == {}


def test_farmer_map_env_string_form(tmp_path, monkeypatch):
    """Legacy comma-separated '+phone:slug,...' string in env is parsed."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(
        TENANT_ID="t1",
        SIGNAL_FARMER_MAP="+59892893012:f1,+59891840205:bot",
    ))
    assert cfg.signal_farmer_map == {"+59892893012": "f1", "+59891840205": "bot"}


# ---------------------------------------------------------------------------
# 5. FARMOS_INTEGRATION bool coercion
# ---------------------------------------------------------------------------


def test_farmos_integration_yaml_bool_true(tmp_path, monkeypatch):
    """YAML boolean true → farmos_integration=True."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("FARMOS_INTEGRATION: true\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.farmos_integration is True


def test_farmos_integration_yaml_bool_false(tmp_path, monkeypatch):
    """YAML boolean false → farmos_integration=False."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("FARMOS_INTEGRATION: false\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.farmos_integration is False


def test_farmos_integration_env_string_one(tmp_path, monkeypatch):
    """Env string '1' → farmos_integration=True (legacy format)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", FARMOS_INTEGRATION="1"))
    assert cfg.farmos_integration is True


def test_farmos_integration_env_string_zero(tmp_path, monkeypatch):
    """Env string '0' → farmos_integration=False."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", FARMOS_INTEGRATION="0"))
    assert cfg.farmos_integration is False


def test_farmos_integration_default_false(tmp_path, monkeypatch):
    """No FARMOS_INTEGRATION anywhere → farmos_integration=False (default)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.farmos_integration is False


# ---------------------------------------------------------------------------
# 6. Numeric field coercion
# ---------------------------------------------------------------------------


def test_int_field_from_env(tmp_path, monkeypatch):
    """Integer fields are coerced from env strings."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    # Phase 63 D-03: ALERT_PI_OFFLINE_MIN moved to ChamberConfig; retargeted onto
    # a retained int field so the coercion coverage survives the move.
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", CAPTURE_RETENTION_DAYS="99"))
    assert cfg.capture_retention_days == 99
    assert isinstance(cfg.capture_retention_days, int)


def test_float_field_from_env(tmp_path, monkeypatch):
    """Float fields are coerced from env strings."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    # Phase 63 D-03: ALERT_RH_TARGET moved to ChamberConfig; retargeted onto a
    # retained float field so the coercion coverage survives the move.
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", DRAFT_NUDGE_FRACTION="0.55"))
    assert cfg.draft_nudge_fraction == 0.55
    assert isinstance(cfg.draft_nudge_fraction, float)


def test_int_default_used_when_absent(tmp_path, monkeypatch):
    """Integer defaults are applied when the env key is absent."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    # config.js:174 default for ALERT_RECEIVE_POLL_SEC is 30
    assert cfg.receive_poll_sec == 30


# ---------------------------------------------------------------------------
# 6b. Extraction config (Phase 64 / MUSHY-76)
# ---------------------------------------------------------------------------


def test_extraction_defaults(tmp_path, monkeypatch):
    """Extraction knobs default to Node's config.js values when unset."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.extraction_confidence_threshold == 0.7
    assert cfg.draft_idle_gap_min == 30
    assert cfg.max_askback_turns == 3


def test_extraction_confidence_threshold_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", EXTRACTION_CONFIDENCE_THRESHOLD="0.55"))
    assert cfg.extraction_confidence_threshold == 0.55


def test_extraction_confidence_threshold_out_of_range_falls_back_to_default(tmp_path, monkeypatch):
    """Mirrors config.js clampThreshold(): out-of-range override falls back to 0.7."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", EXTRACTION_CONFIDENCE_THRESHOLD="4.2"))
    assert cfg.extraction_confidence_threshold == 0.7
    cfg_neg = _tenant_mod.load(_env(TENANT_ID="t1", EXTRACTION_CONFIDENCE_THRESHOLD="-0.1"))
    assert cfg_neg.extraction_confidence_threshold == 0.7


def test_draft_idle_gap_min_and_max_askback_turns_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", DRAFT_IDLE_GAP_MIN="45", MAX_ASKBACK_TURNS="5"))
    assert cfg.draft_idle_gap_min == 45
    assert cfg.max_askback_turns == 5


# ---------------------------------------------------------------------------
# 7. SIGNAL_GROUP_ID normalisation
# ---------------------------------------------------------------------------


def test_signal_group_id_empty_string_becomes_none(tmp_path, monkeypatch):
    """Empty string SIGNAL_GROUP_ID (from YAML or env) normalises to None."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "mossrock"
    tenant_dir.mkdir()
    # mossrock config.yaml sets SIGNAL_GROUP_ID: ""
    (tenant_dir / "config.yaml").write_text('SIGNAL_GROUP_ID: ""\n')
    cfg = _tenant_mod.load(_env(TENANT_ID="mossrock"))
    assert cfg.signal_group_id is None


def test_signal_group_id_real_value_preserved(tmp_path, monkeypatch):
    """Non-empty SIGNAL_GROUP_ID is preserved as-is."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", SIGNAL_GROUP_ID="abc123base64=="))
    assert cfg.signal_group_id == "abc123base64=="


# ---------------------------------------------------------------------------
# 8. strains from YAML
# ---------------------------------------------------------------------------


def test_strains_loaded_from_yaml(tmp_path, monkeypatch):
    """STRAIN_CODES list from strains.yaml is loaded into cfg.strains."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    (tenant_dir / "strains.yaml").write_text(
        "STRAIN_CODES:\n  - SHI\n  - KOY\n  - MAI\n"
    )
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.strains == ["SHI", "KOY", "MAI"]


def test_strains_default_empty_list(tmp_path, monkeypatch):
    """No strains.yaml → strains defaults to []."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.strains == []


# ---------------------------------------------------------------------------
# 9. TenantConfig is frozen
# ---------------------------------------------------------------------------


def test_tenant_config_is_frozen(tmp_path, monkeypatch):
    """TenantConfig is a frozen dataclass — assignment raises."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    with pytest.raises((AttributeError, TypeError)):
        cfg.tenant_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 10. FND-02 gate: no other business module reads os.environ
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. TENANTS_BASE path correctness (no monkeypatch -- catches off-by-one)
# ---------------------------------------------------------------------------


def test_tenants_base_name_is_tenants():
    """TENANTS_BASE must resolve to a directory named 'tenants'.

    This test does NOT monkeypatch TENANTS_BASE so any off-by-one in the
    parent-count is caught immediately (CR-02 regression guard).
    """
    assert _tenant_mod.TENANTS_BASE.name == "tenants", (
        f"TENANTS_BASE.name must be 'tenants', got {_tenant_mod.TENANTS_BASE.name!r}. "
        f"Full path: {_tenant_mod.TENANTS_BASE}"
    )


def test_tenants_base_parent_is_repo_root():
    """TENANTS_BASE.parent must be the repo root (contains pyproject.toml / CLAUDE.md).

    Guards against off-by-one where TENANTS_BASE.parent == src/ (wrong).
    """
    parent = _tenant_mod.TENANTS_BASE.parent
    # The repo root contains CLAUDE.md (unique enough identifier).
    assert (parent / "CLAUDE.md").exists(), (
        f"TENANTS_BASE.parent does not look like the repo root "
        f"(no CLAUDE.md found). TENANTS_BASE={_tenant_mod.TENANTS_BASE}. "
        f"Parent={parent}"
    )


# ---------------------------------------------------------------------------
# 10. FND-02 gate: no other business module reads os.environ
# ---------------------------------------------------------------------------


def test_no_other_module_reads_os_environ():
    """FND-02: grep that os.environ is only read in the sanctioned config loaders.

    Phase 63 D-02 adds chamber/config.py as the second (and only other) env
    reader: the chamber knob set is env-only, with no tenant-YAML layer. It is
    allowlisted here rather than being allowed to read secrets -- it takes
    identity/secrets by injection from an already-loaded TenantConfig and only
    reads its own ALERT_*/TZ/BRIDGE_* knobs from env.
    """
    import subprocess

    farm_agent_dir = (
        Path(__file__).parent.parent / "farm_agent"
    )
    result = subprocess.run(
        [
            "grep",
            "-r",
            "os.environ",
            "--include=*.py",
            str(farm_agent_dir),
        ],
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if "tenancy/tenant.py" not in line
        and "boot.py" not in line
        and "chamber/config.py" not in line
    ]
    assert hits == [], (
        "FND-02 VIOLATION: the following files read os.environ directly:\n"
        + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# 12. signal_api_url — Phase 57 foundation field
# ---------------------------------------------------------------------------


def test_signal_api_url_default(tmp_path, monkeypatch):
    """signal_api_url defaults to 'http://signal-cli:8080' when SIGNAL_API_URL unset."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.signal_api_url == "http://signal-cli:8080"


def test_signal_api_url_env_override(tmp_path, monkeypatch):
    """SIGNAL_API_URL env var overrides the default."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", SIGNAL_API_URL="http://my-signal:9999"))
    assert cfg.signal_api_url == "http://my-signal:9999"


# ---------------------------------------------------------------------------
# 13. signal_additional_senders — Phase 57 foundation field
# ---------------------------------------------------------------------------


def test_signal_additional_senders_default_empty(tmp_path, monkeypatch):
    """signal_additional_senders defaults to [] when SIGNAL_ADDITIONAL_SENDERS unset."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1"))
    assert cfg.signal_additional_senders == []


def test_signal_additional_senders_parses_comma_list(tmp_path, monkeypatch):
    """SIGNAL_ADDITIONAL_SENDERS '+1,+2 , ' parses to ['+1', '+2'] (strip, drop empties)."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", SIGNAL_ADDITIONAL_SENDERS="+1,+2 , "))
    assert cfg.signal_additional_senders == ["+1", "+2"]


def test_signal_additional_senders_empty_string_yields_empty(tmp_path, monkeypatch):
    """Explicit empty string for SIGNAL_ADDITIONAL_SENDERS yields []."""
    monkeypatch.setattr(_tenant_mod, "TENANTS_BASE", tmp_path)
    tenant_dir = tmp_path / "t1"
    tenant_dir.mkdir()
    (tenant_dir / "config.yaml").write_text("{}\n")
    cfg = _tenant_mod.load(_env(TENANT_ID="t1", SIGNAL_ADDITIONAL_SENDERS=""))
    assert cfg.signal_additional_senders == []


# ---------------------------------------------------------------------------
# 14. mask_number — Phase 57 foundation helper (module-level pure function)
# ---------------------------------------------------------------------------


def test_mask_number_typical():
    """mask_number('+15551234567') == '+1XXXXXX4567'."""
    assert _tenant_mod.mask_number("+15551234567") == "+1XXXXXX4567"


def test_mask_number_short_string():
    """mask_number('short') == 'XXXX' (len < 6 guard)."""
    assert _tenant_mod.mask_number("short") == "XXXX"


def test_mask_number_non_string():
    """mask_number(non-str) == 'XXXX'."""
    assert _tenant_mod.mask_number(None) == "XXXX"   # type: ignore[arg-type]
    assert _tenant_mod.mask_number(12345) == "XXXX"  # type: ignore[arg-type]
