"""Tests for the temporary local reorder-support patch (see
_selector_patch.py's docstring for why it exists). Uses a fake
homeassistant.helpers.selector/config_validation mirroring HA's real
(pre-patch) shape, so these run without the real homeassistant package.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import voluptuous as vol

from _ha_stub import stub_selector_and_cv

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT / "custom_components" / "wifi_geolocation" / "_selector_patch.py"
)


def _load_patch_module():
    spec = importlib.util.spec_from_file_location("_selector_patch_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fresh_stub():
    """A fresh, unpatched fake selector module for each test."""
    selector_mod, cv_mod = stub_selector_and_cv()
    yield selector_mod, cv_mod
    for name in (
        "homeassistant",
        "homeassistant.helpers",
        "homeassistant.helpers.selector",
        "homeassistant.helpers.config_validation",
    ):
        sys.modules.pop(name, None)


def test_patch_adds_reorder_and_accepts_multiple_reorder(fresh_stub):
    selector_mod, _ = fresh_stub
    patch_module = _load_patch_module()

    assert patch_module.patch_select_selector_reorder() is True
    assert "reorder" in selector_mod.SelectSelectorConfig.__annotations__

    schema = selector_mod.SelectSelector.CONFIG_SCHEMA
    result = schema({"options": ["a", "b"], "multiple": True, "reorder": True})
    assert result["reorder"] is True


def test_patch_rejects_reorder_without_multiple(fresh_stub):
    selector_mod, _ = fresh_stub
    patch_module = _load_patch_module()
    patch_module.patch_select_selector_reorder()

    schema = selector_mod.SelectSelector.CONFIG_SCHEMA
    with pytest.raises(vol.Invalid):
        schema({"options": ["a", "b"], "reorder": True})


def test_patch_is_a_noop_when_already_natively_supported(fresh_stub):
    selector_mod, _ = fresh_stub
    selector_mod.SelectSelectorConfig.__annotations__["reorder"] = bool
    original_schema = selector_mod.SelectSelector.CONFIG_SCHEMA

    patch_module = _load_patch_module()
    assert patch_module.patch_select_selector_reorder() is True
    # Schema object untouched -- we didn't need to (and shouldn't) replace it.
    assert selector_mod.SelectSelector.CONFIG_SCHEMA is original_schema


def test_patch_fails_safely_if_internals_missing(fresh_stub):
    selector_mod, _ = fresh_stub
    del selector_mod.make_selector_config_schema

    patch_module = _load_patch_module()
    assert patch_module.patch_select_selector_reorder() is False
