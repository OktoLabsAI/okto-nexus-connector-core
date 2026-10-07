"""Portable configuration discovery, independent of credentials and launch authority.

Native availability and Core application support are deliberately separate. A
catalogue is not permission to execute, nor proof an account can use a model.
Hosts can supply observations from their authenticated native control channel;
passive discovery never starts a session or reads login files.
"""
from copy import deepcopy
from hashlib import sha256

from .models import CoreError, HarnessSettings
from .protocol import canonical_json

CONFIGURATION_SCHEMA_VERSION = 1

_CHOICES = {
    'codex_app_server': {
        'effort': ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'),
        'approval_policy': ('on-request', 'never', 'untrusted', 'on-failure'),
        'sandbox': ('read-only', 'workspace-write', 'danger-full-access'),
        'user_input': ('enabled', 'disabled'),
        'inherit_global_mcps': ('enabled', 'disabled')},
    'claude_stream': {
        'effort': ('low', 'medium', 'high', 'xhigh', 'max'),
        'permission_mode': ('default', 'manual', 'acceptEdits', 'plan', 'auto', 'dontAsk', 'bypassPermissions'),
        'inherit_global_mcps': ('enabled', 'disabled')},
    'pi_rpc': {'effort': ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'), 'provider': ()},
}


def validate_harness_settings(adapter_id, values):
    """Validate supported launch fields before hashing or any native effect."""
    if adapter_id not in _CHOICES or not isinstance(values, dict) or set(values) - set(_CHOICES[adapter_id]):
        raise CoreError('VALIDATION_ERROR', 'harness_settings')
    for name, value in values.items():
        choices = _CHOICES[adapter_id][name]
        if (not isinstance(value, str) or not 1 <= len(value) <= 200 or
                any(ord(c) < 32 for c in value) or (choices and value not in choices)):
            raise CoreError('VALIDATION_ERROR', 'harness_settings')
    return HarnessSettings(**values)


def harness_settings_dict(settings):
    from dataclasses import asdict
    if type(settings) is not HarnessSettings:
        raise CoreError('VALIDATION_ERROR', 'harness_settings')
    return {k: v for k, v in asdict(settings).items() if v is not None}


def validate_harness_configuration(configuration, values):
    """Validate a selection against a host-owned discovery description.

    Hosts must bind the description to the selected installation/account; this
    function validates values, not the authenticity/freshness of observations.
    An omitted value preserves the native/Core default. No defaults are silently
    copied into explicit user settings. Returns an independent selection object.
    """
    if not isinstance(configuration, dict) or not isinstance(values, dict):
        raise CoreError('VALIDATION_ERROR', 'harness_configuration')
    adapter = configuration.get('adapter_id')
    selected = dict(values)
    model = selected.pop('model', None)
    if 'model' in values and (not isinstance(model, str) or not 1 <= len(model) <= 200 or
                              any(ord(c) < 32 for c in model)):
        raise CoreError('VALIDATION_ERROR', 'harness_configuration')
    validate_harness_settings(adapter, selected)
    for field in configuration['parameters']:
        name = field['name']
        if name in values and field['availability'] == 'observed' and field['type'] == 'enum':
            if values[name] not in field['values']:
                raise CoreError('VALIDATION_ERROR', 'harness_configuration')
        if name in configuration.get('constraints', {}) and name not in values:
            if field['default_source'] == 'core_adapter' and field['default'] not in field['values']:
                raise CoreError('VALIDATION_ERROR', 'harness_configuration',
                                message='An explicit setting is required by the harness policy.')
    if model is not None and configuration['models']:
        models = [m for m in configuration['models'] if m['id'] == model and
                  (adapter != 'pi_rpc' or not selected.get('provider') or
                   m['provider'] == selected['provider'])]
        if len(models) != 1:
            raise CoreError('VALIDATION_ERROR', 'harness_configuration')
        if adapter == 'codex_app_server' and 'effort' in selected and selected['effort'] not in models[0]['efforts']:
            raise CoreError('VALIDATION_ERROR', 'harness_configuration')
    return deepcopy(values)


def codex_thread_settings(settings):
    values = harness_settings_dict(settings)
    validate_harness_settings('codex_app_server', values)
    result = {}
    if settings.approval_policy is not None:
        result['approvalPolicy'] = settings.approval_policy
    if settings.sandbox is not None:
        result['sandbox'] = settings.sandbox
    if settings.effort is not None:
        result['config'] = {'model_reasoning_effort': settings.effort}
    if settings.user_input is not None:
        result.setdefault('config', {})['features.default_mode_request_user_input'] = settings.user_input == 'enabled'
    return result


def _field(name, label, native, *, applied=False, values=None, scope="session"):
    return dict(name=name, label=label, type="enum" if values else "string",
                native_parameter=native, core_applies=applied, scope=scope,
                default=None, default_source="harness", values=values or [],
                availability="requires_native_observation")


def discover_harness_configuration(adapter_id, *, version=None, candidate_ref=None,
                                   native_models=None, cli_help=None, thinking_levels=None,
                                   requirements=None, native_parameters=None):
    """Describe configuration and normalize optional, host-observed capabilities.

    ``native_models`` is the result of Codex model/list or Pi
    get_available_models, NOT a user-provided model allowlist. ``cli_help`` is
    host-captured Claude --help. Neither is persisted verbatim or executed.
    Unknown versions/absent observations remain visibly unverified. Values are
    native spellings: no invented cross-provider effort or permission modes.
    """
    if adapter_id not in {"codex_app_server", "claude_stream", "pi_rpc"}:
        raise CoreError("CAPABILITY_UNSUPPORTED", "configuration_discovery")
    if version is not None and (not isinstance(version, str) or len(version) > 160):
        raise CoreError("VALIDATION_ERROR", "configuration_discovery")
    if candidate_ref is not None and (not isinstance(candidate_ref, str) or not 1 <= len(candidate_ref) <= 256):
        raise CoreError("VALIDATION_ERROR", "configuration_discovery")
    fields = [_field("model", "Model", "model" if adapter_id == "codex_app_server" else "--model", applied=True)]
    if adapter_id == "codex_app_server":
        fields += [_field("effort", "Reasoning effort", "turn/start.effort", scope="turn"),
                   _field("approval_policy", "Harness approval policy", "approvalPolicy"),
                   _field("sandbox", "Execution sandbox", "sandbox"),
                   _field("user_input", "User questions in default mode (experimental)",
                          "thread/start.config.features.default_mode_request_user_input")]
        input_methods = ["item/tool/requestUserInput", "mcpServer/elicitation/request"]
        discovery = ["model/list", "configRequirements/read"]
        fields[2].update(default="on-request", default_source="core_adapter")
        fields[3].update(default="read-only", default_source="core_adapter")
    elif adapter_id == "claude_stream":
        fields += [_field("effort", "Effort", "--effort"),
                   _field("permission_mode", "Harness permission mode", "--permission-mode")]
        input_methods = ["control_request:can_use_tool/AskUserQuestion"]
        discovery = ["--help"]
    else:
        fields += [_field("provider", "Provider", "set_model.provider"),
                   _field("effort", "Thinking level", "set_thinking_level.level")]
        input_methods = ["extension_ui_request"]
        discovery = ["get_available_models", "get_available_thinking_levels", "get_state"]

    for item in fields:
        item['core_applies'] = True
        if item['name'] in _CHOICES[adapter_id]:
            item['values'] = list(_CHOICES[adapter_id][item['name']])
            item['type'] = 'enum' if item['values'] else 'string'
            item['availability'] = 'core_contract'
    if adapter_id == 'codex_app_server':
        fields[1].update(native_parameter='thread/start.config.model_reasoning_effort', scope='session')
    if adapter_id == 'pi_rpc':
        fields[1]['native_parameter'] = '--provider'
        fields[2]['native_parameter'] = '--thinking'
    models = []
    if native_models is not None:
        if adapter_id == "claude_stream" or not isinstance(native_models, dict):
            raise CoreError("VALIDATION_ERROR", "configuration_discovery")
        rows = native_models.get("data") if adapter_id == "codex_app_server" else native_models.get("models")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise CoreError("VALIDATION_ERROR", "configuration_discovery")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            model = row.get("model", row.get("id"))
            provider = row.get("provider") if adapter_id == "pi_rpc" else None
            if (not isinstance(model, str) or not 1 <= len(model) <= 200 or
                    any(ord(c) < 32 for c in model) or
                    (adapter_id == 'pi_rpc' and (not isinstance(provider, str) or
                     not 1 <= len(provider) <= 200 or any(ord(c) < 32 for c in provider)))):
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            key = (provider, model)
            if key in seen:
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            seen.add(key)
            efforts = row.get("supportedReasoningEfforts", []) if adapter_id == "codex_app_server" else []
            if not isinstance(efforts, list) or len(efforts) > 32:
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            levels = []
            for entry in efforts:
                value = entry.get("reasoningEffort") if isinstance(entry, dict) else None
                if not isinstance(value, str) or not 1 <= len(value) <= 40:
                    raise CoreError("VALIDATION_ERROR", "configuration_discovery")
                levels.append(value)
            default = row.get("defaultReasoningEffort") if adapter_id == "codex_app_server" else None
            if default is not None and default not in levels:
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            models.append(dict(id=model, provider=provider, efforts=levels, default_effort=default))
        fields[0].update(availability="observed", type="enum",
                         values=list(dict.fromkeys(m["id"] for m in models)))
        if adapter_id == 'pi_rpc':
            fields[1].update(availability='observed', type='enum',
                             values=list(dict.fromkeys(m['provider'] for m in models)))

    # Managed requirements restrict choices; they never grant execution. Keep
    # only the fields understood by this contract, not the raw policy document.
    constraints = {}
    if requirements is not None:
        if adapter_id != 'codex_app_server' or not isinstance(requirements, dict):
            raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
        for source, target in [('allowedApprovalPolicies', 'approval_policy'),
                               ('allowedSandboxModes', 'sandbox')]:
            allowed = requirements.get(source)
            if allowed is None:
                continue
            if (not isinstance(allowed, list) or len(allowed) > 32 or
                    any(not isinstance(v, str) or not 1 <= len(v) <= 80 for v in allowed)):
                raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
            constraints[target] = list(dict.fromkeys(allowed))
            field = next(f for f in fields if f['name'] == target)
            field['values'] = [v for v in field['values'] if v in allowed]
            field.update(availability='observed', type='enum')

    if thinking_levels is not None:
        if (adapter_id != "pi_rpc" or not isinstance(thinking_levels, dict) or
                not isinstance(thinking_levels.get("levels"), list) or
                not 1 <= len(thinking_levels["levels"]) <= 32 or
                any(not isinstance(v, str) or not 1 <= len(v) <= 40 for v in thinking_levels["levels"])):
            raise CoreError("VALIDATION_ERROR", "configuration_discovery")
        next(f for f in fields if f['name'] == 'effort').update(
            type="enum", availability="observed", values=list(dict.fromkeys(thinking_levels['levels'])))

    # Parse only bounded CLI choice declarations, not arbitrary help prose.
    if cli_help is not None:
        if adapter_id != "claude_stream" or not isinstance(cli_help, str) or len(cli_help) > 131072:
            raise CoreError("VALIDATION_ERROR", "configuration_discovery")
        import re
        for item in fields:
            flag = re.escape(item["native_parameter"])
            match = re.search(r"(?m)^\s*" + flag + r"\s+[^\n]*(?:\n(?!\s*--)[^\n]*)*", cli_help)
            if match:
                item["availability"] = "observed"
                choices = re.search(r'\((?:choices:\s*)?((?:"?[A-Za-z][A-Za-z0-9_-]*"?\s*,\s*)+"?[A-Za-z][A-Za-z0-9_-]*"?)\)', match[0])
                if choices:
                    item.update(type="enum", values=[v.strip().strip('"') for v in choices[1].split(',')])

    # Hosts may reconstruct a redacted Claude help observation from the public
    # event without retaining or relaying arbitrary raw CLI output.
    if native_parameters is not None:
        if adapter_id != 'claude_stream' or not isinstance(native_parameters, list) or len(native_parameters) > len(fields):
            raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
        seen_fields = set()
        for observation in native_parameters:
            if not isinstance(observation, dict) or set(observation) != {'name','type','values'}:
                raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
            name, kind, values = observation['name'], observation['type'], observation['values']
            field = next((f for f in fields if f['name'] == name), None)
            if (field is None or name in seen_fields or kind not in ('enum','string') or
                    not isinstance(values, list) or len(values) > 32 or
                    any(not isinstance(v,str) or not 1 <= len(v) <= 200 or any(ord(c)<32 for c in v) for v in values)):
                raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
            seen_fields.add(name)
            field.update(type=kind, values=list(dict.fromkeys(values)), availability='observed')

    if adapter_id in ('codex_app_server', 'claude_stream'):
        fields.append(dict(name='inherit_global_mcps', label='Include global harness MCPs',
            type='enum', native_parameter='core.mcp_inheritance', core_applies=True,
            scope='session', default=None, default_source='nexus_policy',
            values=['enabled', 'disabled'], availability='core_contract'))
    value = dict(schema_version=CONFIGURATION_SCHEMA_VERSION, adapter_id=adapter_id,
                 version=version, candidate_ref=candidate_ref, parameters=fields,
                 models=models, constraints=constraints, discovery_methods=discovery,
                 human_input=dict(native_methods=input_methods,
                     core_bridge="implemented_version_qualification_required",
                     recipient_policy="originating_interlocutor",
                     recipient_routing_implemented=False,
                     separate_from_tool_approval=True),
                 nexus_tool_approval=dict(values=["ask", "always_allow"], scope="nexus_tools_only"))
    value["schema_revision"] = "sha256:" + sha256(canonical_json(value)).hexdigest()
    return deepcopy(value)


async def query_harness_configuration(adapter_id, request, *, version=None, candidate_ref=None,
                                      include_requirements=False):
    """Read capabilities through an already-authorized host native channel.

    The host owns channel lifetime, timeout, authentication and candidate
    correlation. No prompt, set_model, configuration write or approval is sent.
    Claude uses captured CLI help via discover_harness_configuration instead.
    Transport failures propagate; they must not be displayed as empty success.
    """
    if adapter_id == "codex_app_server":
        rows, cursor, visited = [], None, set()
        for _ in range(20):
            params = {"limit": 50, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            page = await request("model/list", params)
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise CoreError("VALIDATION_ERROR", "configuration_discovery")
            rows.extend(page['data'])
            cursor = page.get('nextCursor')
            if cursor is None:
                requirements = None
                if include_requirements:
                    observed = await request('configRequirements/read', {})
                    if not isinstance(observed, dict) or 'requirements' not in observed:
                        raise CoreError('VALIDATION_ERROR', 'configuration_discovery')
                    requirements = observed['requirements']
                return discover_harness_configuration(adapter_id, version=version,
                    candidate_ref=candidate_ref, native_models={'data': rows}, requirements=requirements)
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096 or cursor in visited:
                break
            visited.add(cursor)
        raise CoreError("VALIDATION_ERROR", "configuration_discovery")
    if adapter_id == "pi_rpc":
        models = await request("get_available_models", {})
        return discover_harness_configuration(adapter_id, version=version,
            candidate_ref=candidate_ref, native_models=models)
    raise CoreError("CAPABILITY_UNSUPPORTED", "configuration_discovery")


def observe_transport_configuration(adapter_id, transport, *, version=None):
    """Adapter-owned synchronous observation on its initialized transport.

    Run on a worker, never on the host event loop. No channel is created here.
    The total request budget bounds pagination even when every page is slow.
    """
    import asyncio
    import time
    deadline = time.monotonic() + 15

    async def request(method, params):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Configuration discovery deadline exceeded.')
        value = transport.request(method, params, timeout_s=min(5, remaining))
        if adapter_id == 'pi_rpc':
            if not isinstance(value, dict) or value.get('success') is not True:
                raise CoreError('CAPABILITY_UNSUPPORTED', 'configuration_discovery')
            value = value.get('data')
        return value

    return asyncio.run(query_harness_configuration(adapter_id, request, version=version,
                     include_requirements=adapter_id == 'codex_app_server'))
