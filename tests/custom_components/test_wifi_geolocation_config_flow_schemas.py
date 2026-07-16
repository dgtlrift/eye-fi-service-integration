"""Same regression guard as test_config_flow_schemas.py, applied to the
wifi_geolocation integration's config flow -- its per-backend credential
schemas and the backend-selection/priority-order schema must all survive
voluptuous_serialize.convert() the way HA's frontend requires.

The backend-selection schema uses HA's own SelectSelector (a first-class,
recognized class -- not a bare custom function), which is the whole point:
it's the thing that avoids repeating the real 500-error bug this project
hit once already (see test_config_flow_schemas.py). _custom_serializer
below stands in for what HA's real frontend serializer does for Selector
instances.
"""

import sys

import pytest
import voluptuous_serialize

from _ha_stub import load_config_flow_schemas


@pytest.fixture(scope="module")
def schemas():
    return load_config_flow_schemas("wifi_geolocation")


@pytest.fixture(scope="module")
def const(schemas):
    # BACKEND_BEACONDB isn't imported by config_flow.py itself (unused
    # there now), but is needed here -- grab it from the const module
    # load_config_flow_schemas already registered in sys.modules.
    return sys.modules["custom_components.wifi_geolocation.const"]


def test_backend_select_schema_is_frontend_serializable(schemas):
    schema = schemas["_backend_select_schema"](default=[schemas["BACKEND_GOOGLE"]])
    _serialize(schema)


def test_credential_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_CREDENTIAL_SCHEMAS"].values():
        _serialize(schema)


def test_backend_select_schema_offers_every_priority_ordered_backend(schemas):
    schema = schemas["_backend_select_schema"](default=[schemas["BACKEND_GOOGLE"]])
    (selector_instance,) = schema.schema.values()
    offered = {option["value"] for option in selector_instance.config["options"]}
    assert offered == set(schemas["BACKEND_PRIORITY_ORDER"])


def test_backend_select_schema_allows_multiple(schemas):
    schema = schemas["_backend_select_schema"](default=[schemas["BACKEND_GOOGLE"]])
    (selector_instance,) = schema.schema.values()
    assert selector_instance.config["multiple"] is True


def test_beacondb_has_no_credential_schema(schemas, const):
    # BeaconDB needs no API key -- it must be absent from the credential
    # queue entirely, not present with an empty schema.
    assert const.BACKEND_BEACONDB not in schemas["_CREDENTIAL_SCHEMAS"]


def _serialize(schema):
    from homeassistant.helpers import selector

    def custom_serializer(value):
        if isinstance(value, selector.SelectSelector):
            return {"selector": {"select": value.config}}
        return voluptuous_serialize.UNSUPPORTED

    voluptuous_serialize.convert(schema, custom_serializer=custom_serializer)
