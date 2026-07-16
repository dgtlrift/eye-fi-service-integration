"""Shared harness: load a config_flow.py's module-level schema-building
code without needing the real `homeassistant` package installed, so its
voluptuous schemas can be run through the real `voluptuous_serialize` the
way HA's frontend does. See test_config_flow_schemas.py for the bug this
guards against.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def stub_homeassistant() -> None:
    ha = ModuleType("homeassistant")
    config_entries_mod = ModuleType("homeassistant.config_entries")
    config_entries_mod.ConfigFlow = type("ConfigFlow", (), {})
    config_entries_mod.OptionsFlow = type("OptionsFlow", (), {})
    config_entries_mod.ConfigEntry = type("ConfigEntry", (), {})
    core_mod = ModuleType("homeassistant.core")
    core_mod.callback = lambda func: func
    data_entry_flow_mod = ModuleType("homeassistant.data_entry_flow")
    data_entry_flow_mod.FlowResult = dict

    ha.config_entries = config_entries_mod
    ha.core = core_mod
    ha.data_entry_flow = data_entry_flow_mod

    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.config_entries", config_entries_mod)
    sys.modules.setdefault("homeassistant.core", core_mod)
    sys.modules.setdefault("homeassistant.data_entry_flow", data_entry_flow_mod)


def stub_selector_and_cv() -> tuple[ModuleType, ModuleType]:
    """Stub homeassistant.helpers.selector/config_validation mirroring
    their real (pre-``reorder``-patch) shape closely enough to test
    ``_selector_patch.py``'s monkeypatch against, without needing the
    real homeassistant package installed. Returns (selector_mod, cv_mod)."""
    import voluptuous as vol

    helpers_mod = ModuleType("homeassistant.helpers")
    cv_mod = ModuleType("homeassistant.helpers.config_validation")
    cv_mod.boolean = vol.Coerce(bool)
    cv_mod.string = str

    selector_mod = ModuleType("homeassistant.helpers.selector")

    class SelectSelectorMode:
        LIST = "list"
        DROPDOWN = "dropdown"

    def select_option(value):
        return value

    def SelectOptionDict(*, value, label):
        return {"value": value, "label": label}

    def make_selector_config_schema(schema_dict):
        return vol.Schema(schema_dict)

    def _validate_selector_reorder_config(config):
        if config.get("reorder") and not config.get("multiple"):
            raise vol.Invalid("reorder can only be used when multiple is true")
        return config

    class SelectSelectorConfig(dict):
        __annotations__ = {
            "options": object,
            "multiple": bool,
            "custom_value": bool,
            "mode": object,
            "translation_key": str,
            "sort": bool,
        }

    class SelectSelector:
        """Mirrors HA's real Selector: a first-class callable validator
        (not a bare function), so voluptuous_serialize can be taught to
        recognize it via isinstance -- see test_wifi_geolocation_config_
        flow_schemas.py's custom_serializer."""

        CONFIG_SCHEMA = make_selector_config_schema(
            {
                vol.Required("options"): vol.All(vol.Any([str], [select_option])),
                vol.Optional("multiple", default=False): cv_mod.boolean,
                vol.Optional("custom_value", default=False): cv_mod.boolean,
                vol.Optional("mode"): cv_mod.string,
                vol.Optional("translation_key"): cv_mod.string,
                vol.Optional("sort", default=False): cv_mod.boolean,
            }
        )

        def __init__(self, config):
            self.config = self.CONFIG_SCHEMA(dict(config))

        def __call__(self, value):
            return value

    selector_mod.SelectSelectorMode = SelectSelectorMode
    selector_mod.select_option = select_option
    selector_mod.SelectOptionDict = SelectOptionDict
    selector_mod.make_selector_config_schema = make_selector_config_schema
    selector_mod._validate_selector_reorder_config = _validate_selector_reorder_config
    selector_mod.SelectSelectorConfig = SelectSelectorConfig
    selector_mod.SelectSelector = SelectSelector

    helpers_mod.selector = selector_mod
    helpers_mod.config_validation = cv_mod

    sys.modules["homeassistant.helpers"] = helpers_mod
    sys.modules["homeassistant.helpers.selector"] = selector_mod
    sys.modules["homeassistant.helpers.config_validation"] = cv_mod

    return selector_mod, cv_mod


def load_config_flow_schemas(integration_domain: str) -> ModuleType:
    """Import <integration_domain>/const.py (and _selector_patch.py, if
    present) for real, then exec just the module-level (pre-`class`)
    source of its config_flow.py against a namespace with those already
    satisfied and homeassistant stubbed."""
    stub_homeassistant()
    stub_selector_and_cv()

    integration_dir = REPO_ROOT / "custom_components" / integration_domain

    package = ModuleType("custom_components")
    package.__path__ = [str(REPO_ROOT / "custom_components")]
    sys.modules.setdefault("custom_components", package)

    integration_package = ModuleType(f"custom_components.{integration_domain}")
    integration_package.__path__ = [str(integration_dir)]
    sys.modules[f"custom_components.{integration_domain}"] = integration_package

    const_spec = importlib.util.spec_from_file_location(
        f"custom_components.{integration_domain}.const", integration_dir / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[f"custom_components.{integration_domain}.const"] = const_module
    const_spec.loader.exec_module(const_module)

    selector_patch_path = integration_dir / "_selector_patch.py"
    if selector_patch_path.is_file():
        patch_spec = importlib.util.spec_from_file_location(
            f"custom_components.{integration_domain}._selector_patch", selector_patch_path
        )
        patch_module = importlib.util.module_from_spec(patch_spec)
        sys.modules[f"custom_components.{integration_domain}._selector_patch"] = patch_module
        patch_spec.loader.exec_module(patch_module)

    source = (integration_dir / "config_flow.py").read_text()
    schema_source = source.split("\nclass ", 1)[0]

    namespace: dict = {"__name__": f"custom_components.{integration_domain}.config_flow"}
    exec(compile(schema_source, str(integration_dir / "config_flow.py"), "exec"), namespace)
    return namespace
