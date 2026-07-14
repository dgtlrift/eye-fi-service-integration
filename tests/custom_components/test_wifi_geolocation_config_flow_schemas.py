"""Same regression guard as test_config_flow_schemas.py, applied to the
wifi_geolocation integration's config flow -- its per-backend credential
schemas and boolean-toggle main schema must all survive
voluptuous_serialize.convert() the way HA's frontend requires.
"""

import pytest
import voluptuous_serialize

from _ha_stub import load_config_flow_schemas


@pytest.fixture(scope="module")
def schemas():
    return load_config_flow_schemas("wifi_geolocation")


def test_main_schema_is_frontend_serializable(schemas):
    _serialize(schemas["_MAIN_SCHEMA"])


def test_credential_schemas_are_frontend_serializable(schemas):
    for schema in schemas["_CREDENTIAL_SCHEMAS"].values():
        _serialize(schema)


def test_main_schema_has_a_toggle_per_priority_ordered_backend(schemas):
    enable_prefix = schemas["CONF_ENABLE_PREFIX"]
    field_names = {marker.schema for marker in schemas["_MAIN_SCHEMA"].schema}
    for backend in schemas["BACKEND_PRIORITY_ORDER"]:
        assert f"{enable_prefix}{backend}" in field_names


def test_beacondb_has_no_credential_schema(schemas):
    # BeaconDB needs no API key -- it must be absent from the credential
    # queue entirely, not present with an empty schema.
    assert schemas["BACKEND_BEACONDB"] not in schemas["_CREDENTIAL_SCHEMAS"]


def _serialize(schema):
    voluptuous_serialize.convert(
        schema, custom_serializer=lambda _schema: voluptuous_serialize.UNSUPPORTED
    )
