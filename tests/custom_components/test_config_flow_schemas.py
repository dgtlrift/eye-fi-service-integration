"""Regression test for a real bug: HA's frontend serializes every
config-flow schema via ``voluptuous_serialize.convert()`` before sending it
to the browser. A bare custom function used as a validator (e.g.
``vol.All(str, my_func)``) can't be serialized and raises ValueError at
form-render time — a 500 error on "Add Integration" that only ever shows up
against a real Home Assistant instance, never in a plain py_compile/unit
test. This test catches that class of bug without needing `homeassistant`
installed, since voluptuous_serialize itself has no HA dependency.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import voluptuous_serialize

REPO_ROOT = Path(__file__).resolve().parents[2]
EYEFI_DIR = REPO_ROOT / "custom_components" / "eyefi"


def _stub_homeassistant() -> None:
    """Module-level `from homeassistant import ...` in config_flow.py only
    needs to resolve for exec() to run the schema-building code below it —
    none of the stubbed classes are ever instantiated here."""
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


def _load_config_flow_schemas() -> ModuleType:
    """Import const.py and just the schema objects from config_flow.py,
    without needing the real `homeassistant` package installed."""
    _stub_homeassistant()

    package = ModuleType("custom_components")
    package.__path__ = [str(REPO_ROOT / "custom_components")]
    sys.modules.setdefault("custom_components", package)

    eyefi_package = ModuleType("custom_components.eyefi")
    eyefi_package.__path__ = [str(EYEFI_DIR)]
    sys.modules["custom_components.eyefi"] = eyefi_package

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.eyefi.const", EYEFI_DIR / "const.py"
    )
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.eyefi.const"] = const_module
    const_spec.loader.exec_module(const_module)

    # config_flow.py imports homeassistant.*, which isn't installed here —
    # so we exec just the module-level schema-building source (everything
    # before the first `class`) against a namespace with `.const` already
    # satisfied, sidestepping the homeassistant dependency entirely.
    source = (EYEFI_DIR / "config_flow.py").read_text()
    schema_source = source.split("\nclass ", 1)[0]

    namespace: dict = {"__name__": "custom_components.eyefi.config_flow"}
    exec(compile(schema_source, str(EYEFI_DIR / "config_flow.py"), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def schemas():
    return _load_config_flow_schemas()


def test_card_schema_is_frontend_serializable(schemas):
    _serialize(schemas["_CARD_SCHEMA"])


def test_destination_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_DESTINATION_SCHEMAS"].values():
        _serialize(schema)


def test_local_path_destination_schemas_are_frontend_serializable(schemas):
    build_destination_schema = schemas["_build_destination_schema"]
    for destination in schemas["_LOCAL_PATH_DESTINATIONS"]:
        _serialize(build_destination_schema(destination, "/config/eyefi_downloads"))


def test_local_path_destination_default_is_subfolder_of_download_dir(schemas):
    build_destination_schema = schemas["_build_destination_schema"]
    for destination in schemas["_LOCAL_PATH_DESTINATIONS"]:
        schema = build_destination_schema(destination, "/config/eyefi_downloads")
        (marker,) = schema.schema.keys()
        assert marker.default() == "/config/eyefi_downloads/photos"


def test_geotag_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_GEOTAG_SCHEMAS"].values():
        _serialize(schema)


def _serialize(schema):
    # UNSUPPORTED (not None) signals "no special handling" to voluptuous_serialize,
    # matching HA's real cv.custom_serializer — returning None here would mask
    # exactly the bug this test exists to catch.
    voluptuous_serialize.convert(
        schema, custom_serializer=lambda _schema: voluptuous_serialize.UNSUPPORTED
    )
