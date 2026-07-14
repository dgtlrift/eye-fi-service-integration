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


def load_config_flow_schemas(integration_domain: str) -> ModuleType:
    """Import <integration_domain>/const.py for real, then exec just the
    module-level (pre-`class`) source of its config_flow.py against a
    namespace with `.const` already satisfied and homeassistant stubbed."""
    stub_homeassistant()

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

    source = (integration_dir / "config_flow.py").read_text()
    schema_source = source.split("\nclass ", 1)[0]

    namespace: dict = {"__name__": f"custom_components.{integration_domain}.config_flow"}
    exec(compile(schema_source, str(integration_dir / "config_flow.py"), "exec"), namespace)
    return namespace
