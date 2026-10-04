"""Portable, non-secret harness settings shared by hosts and configuration UIs."""
import json

from .harness_configuration import discover_harness_configuration, validate_harness_configuration
from .models import CoreError

MAX_CONFIGURATION_FILE_BYTES = 65536


def parse_harness_configuration_file(text, *, adapter_id=None, configuration=None):
    """Read values only; a file cannot supply observations, credentials or authority."""
    def invalid():
        raise CoreError('VALIDATION_ERROR', 'configuration_file',
                        message='Expected a version 1 nexus-harness-config file for the selected harness.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                invalid()
            result[key] = value
        return result
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_CONFIGURATION_FILE_BYTES:
        invalid()
    try:
        value = json.loads(text.removeprefix('\ufeff'), object_pairs_hook=unique)
    except (ValueError, RecursionError):
        invalid()
    if (not isinstance(value, dict) or set(value) != {'format', 'version', 'adapter_id', 'settings'}
            or value['format'] != 'nexus-harness-config' or type(value['version']) is not int
            or value['version'] != 1 or not isinstance(value['adapter_id'], str)
            or adapter_id is not None and value['adapter_id'] != adapter_id):
        invalid()
    schema = configuration if configuration is not None else discover_harness_configuration(value['adapter_id'])
    if schema['adapter_id'] != value['adapter_id']:
        invalid()
    value['settings'] = validate_harness_configuration(schema, value['settings'])
    return value


def export_harness_configuration_file(adapter_id, settings):
    value = dict(format='nexus-harness-config', version=1, adapter_id=adapter_id, settings=settings)
    return parse_harness_configuration_file(json.dumps(value, ensure_ascii=False), adapter_id=adapter_id)
