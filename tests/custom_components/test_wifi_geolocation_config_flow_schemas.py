"""Same regression guard as test_config_flow_schemas.py, applied to the
wifi_geolocation integration's config flow -- its per-backend credential
schemas, its reorderable SelectSelector schema, and its numeric-priority
fallback schema must all survive voluptuous_serialize.convert() the way
HA's frontend requires.

Two schemas exist for backend selection/priority: a reorderable
SelectSelector (used when _selector_patch.py's runtime patch applies
cleanly -- see that module and config_flow.py's docstring for why the
patch exists at all) and a numeric-priority-field fallback (used if it
doesn't). Both must independently be frontend-serializable and correctly
round-trip through _parse_selected_backends.
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


@pytest.fixture(scope="module", autouse=True)
def _patched(schemas):
    # _reorder_schema() assumes the caller (normally _backend_field_schema)
    # already applied the reorder patch -- do that once for this module's
    # direct _reorder_schema tests.
    assert schemas["patch_select_selector_reorder"]() is True


def test_priority_schema_is_frontend_serializable(schemas):
    schema = schemas["_priority_schema"](defaults={})
    _serialize(schema)


def test_reorder_schema_is_frontend_serializable(schemas, const):
    schema = schemas["_reorder_schema"](current=[const.BACKEND_GOOGLE])
    _serialize(schema)


def test_credential_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_CREDENTIAL_SCHEMAS"].values():
        _serialize(schema)


def test_priority_schema_has_a_field_per_backend(schemas):
    schema = schemas["_priority_schema"](defaults={})
    field_names = {marker.schema for marker in schema.schema}
    prefix = schemas["CONF_PRIORITY_PREFIX"]
    for backend in schemas["BACKEND_PRIORITY_ORDER"]:
        assert f"{prefix}{backend}" in field_names


def test_reorder_schema_offers_every_priority_ordered_backend(schemas, const):
    schema = schemas["_reorder_schema"](current=[const.BACKEND_GOOGLE])
    (selector_instance,) = schema.schema.values()
    offered = {option["value"] for option in selector_instance.config["options"]}
    assert offered == set(schemas["BACKEND_PRIORITY_ORDER"])


def test_reorder_schema_allows_multiple_and_reorder(schemas, const):
    schema = schemas["_reorder_schema"](current=[const.BACKEND_GOOGLE])
    (selector_instance,) = schema.schema.values()
    assert selector_instance.config["multiple"] is True
    assert selector_instance.config["reorder"] is True


def test_backends_from_priorities_orders_by_priority_not_input_order(schemas, const):
    backends_from_priorities = schemas["_backends_from_priorities"]
    priority_field = schemas["_priority_field"]

    user_input = {priority_field(b): 0 for b in schemas["BACKEND_PRIORITY_ORDER"]}
    user_input[priority_field(const.BACKEND_WIGLE)] = 2
    user_input[priority_field(const.BACKEND_BEACONDB)] = 1

    assert backends_from_priorities(user_input) == [
        const.BACKEND_BEACONDB,
        const.BACKEND_WIGLE,
    ]


def test_priorities_from_backend_list_round_trips(schemas, const):
    priorities_from_backend_list = schemas["_priorities_from_backend_list"]
    backends_from_priorities = schemas["_backends_from_priorities"]
    priority_field = schemas["_priority_field"]

    ordered = [const.BACKEND_BEACONDB, const.BACKEND_WIGLE]
    priorities = priorities_from_backend_list(ordered)

    user_input = {priority_field(b): 0 for b in schemas["BACKEND_PRIORITY_ORDER"]}
    for backend, priority in priorities.items():
        user_input[priority_field(backend)] = priority

    assert backends_from_priorities(user_input) == ordered


def test_parse_selected_backends_prefers_direct_list(schemas, const):
    parse_selected_backends = schemas["_parse_selected_backends"]
    ordered = [const.BACKEND_BEACONDB, const.BACKEND_WIGLE]

    assert parse_selected_backends({schemas["CONF_BACKENDS"]: ordered}) == ordered


def test_parse_selected_backends_falls_back_to_priorities(schemas, const):
    parse_selected_backends = schemas["_parse_selected_backends"]
    priority_field = schemas["_priority_field"]

    user_input = {priority_field(b): 0 for b in schemas["BACKEND_PRIORITY_ORDER"]}
    user_input[priority_field(const.BACKEND_WIGLE)] = 1

    assert parse_selected_backends(user_input) == [const.BACKEND_WIGLE]


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
