"""Same regression guard as test_config_flow_schemas.py, applied to the
wifi_geolocation integration's config flow -- its per-backend credential
schemas and its priority-field schema must all survive
voluptuous_serialize.convert() the way HA's frontend requires.

The priority schema uses one plain int field per backend (0 = disabled,
1+ = priority) rather than a reorderable multi-select: HA's SelectSelector
with multiple=True turned out, in live testing against a real HA
instance, to only support *picking* options, not manually reordering them
afterward. Plain int/vol.Range carries zero risk of that kind of surprise
either way -- see config_flow.py's docstring.
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


def test_priority_schema_is_frontend_serializable(schemas):
    schema = schemas["_priority_schema"](defaults={})
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


def test_beacondb_has_no_credential_schema(schemas, const):
    # BeaconDB needs no API key -- it must be absent from the credential
    # queue entirely, not present with an empty schema.
    assert const.BACKEND_BEACONDB not in schemas["_CREDENTIAL_SCHEMAS"]


def _serialize(schema):
    voluptuous_serialize.convert(
        schema, custom_serializer=lambda _schema: voluptuous_serialize.UNSUPPORTED
    )
