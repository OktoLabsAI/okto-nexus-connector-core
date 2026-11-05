"""Pure user-service definitions shared by host adapters.

No OS queries, files, subprocesses, Server policy, database or credentials are
owned here. Callers resolve their effective principal and paths, authorize the
operation, drain the application and compare installed definitions before any
mutation. Rendering a definition does not qualify an OS or install anything.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PureWindowsPath
import re
import subprocess
import xml.etree.ElementTree as ET

DEFINITION_REVISION = 1
TASK_NAMESPACE = 'http://schemas.microsoft.com/windows/2004/02/mit/task'


@dataclass(frozen=True)
class UserServiceDefinition:
    component: str
    instance_id: str
    principal: str
    executable: str
    arguments: tuple[str, ...]
    working_directory: str

    def __post_init__(self):
        if self.component not in {'server', 'connector'}:
            raise ValueError('Unknown service component')
        if not re.fullmatch(r'svc_[a-f0-9]{64}', self.instance_id):
            raise ValueError('Canonical service instance identity is required')
        if type(self.arguments) is not tuple:
            raise ValueError('Service arguments must be immutable literal arguments')
        values = (self.principal, self.executable, self.working_directory, *self.arguments)
        if (len(self.arguments) > 64 or any(type(item) is not str or not item or len(item) > 4096
                or any(ord(char) < 32 for char in item) for item in values)):
            raise ValueError('Invalid service definition value')

    @property
    def name(self) -> str:
        return f'OktoNexus-{self.component}-{self.instance_id[4:]}'

    @property
    def revision_digest(self) -> str:
        value = [DEFINITION_REVISION, self.component, self.instance_id, self.principal,
                 self.executable, self.arguments, self.working_directory]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest()


def windows_logon_task(definition: UserServiceDefinition) -> str:
    """Interactive user logon task; never a Windows Service or S4U fallback.

    The command must remain foreground. For a consoleless Windows installation,
    a host can select its environment's pythonw.exe and persist its own logs.
    Arguments contain only non-secret context references, supplied by the host.
    """
    if not re.fullmatch(r'S-1-\d+(?:-\d+)+', definition.principal):
        raise ValueError('Windows service principal must be an effective-user SID')
    if not all(PureWindowsPath(path).is_absolute()
               for path in (definition.executable, definition.working_directory)):
        raise ValueError('Windows service paths must be absolute')
    if any('%' in item for item in (definition.executable, definition.working_directory, *definition.arguments)):
        # Task Scheduler expands environment references in actions. Refuse an
        # ambiguous literal instead of silently selecting a different context.
        raise ValueError('Task action paths/arguments cannot contain environment expansion syntax')
    task = ET.Element('Task', {'version': '1.2', 'xmlns': TASK_NAMESPACE})
    def child(parent, tag, value=None, **attributes):
        result = ET.SubElement(parent, tag, attributes)
        if value is not None:
            result.text = value
        return result
    registration = child(task, 'RegistrationInfo')
    child(registration, 'Author', definition.principal)
    child(registration, 'Description', f'Okto Nexus {definition.component}; '
        f'instance={definition.instance_id}; definition_revision={DEFINITION_REVISION}; '
        f'configuration={definition.revision_digest}')
    trigger = child(child(task, 'Triggers'), 'LogonTrigger')
    child(trigger, 'Enabled', 'true')
    child(trigger, 'UserId', definition.principal)
    principal = child(child(task, 'Principals'), 'Principal', id='owner')
    child(principal, 'UserId', definition.principal)
    child(principal, 'LogonType', 'InteractiveToken')
    child(principal, 'RunLevel', 'LeastPrivilege')
    settings = child(task, 'Settings')
    for name, value in (
        ('MultipleInstancesPolicy', 'IgnoreNew'),
        ('DisallowStartIfOnBatteries', 'false'), ('StopIfGoingOnBatteries', 'false'),
        ('AllowHardTerminate', 'false'), ('StartWhenAvailable', 'true'),
        ('RunOnlyIfNetworkAvailable', 'false'), ('AllowStartOnDemand', 'true'),
        ('Enabled', 'true'), ('Hidden', 'false'), ('ExecutionTimeLimit', 'PT0S')):
        child(settings, name, value)
    restart = child(settings, 'RestartOnFailure')
    child(restart, 'Interval', 'PT1M')
    child(restart, 'Count', '3')
    action = child(child(task, 'Actions', Context='owner'), 'Exec')
    child(action, 'Command', definition.executable)
    child(action, 'Arguments', subprocess.list2cmdline(definition.arguments))
    child(action, 'WorkingDirectory', definition.working_directory)
    # COM receives a Unicode BSTR. An explicit UTF-8 declaration conflicts
    # with that transport; no declaration also permits UTF-8 file storage.
    return ET.tostring(task, encoding='unicode')


def windows_definition_digest(xml: str) -> str:
    """Fingerprint one observed native definition for compare-before-mutation.

    Persist the OS-exported definition's digest after registration. Do not assume
    a rendered template equals a normalized OS export. Unknown elements are
    retained in the fingerprint so user modifications are never discarded.
    """
    if (not isinstance(xml, str) or len(xml) > 131072
            or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper()):
        raise ValueError('Unsupported or oversized Task Scheduler definition')
    root = ET.fromstring(xml)
    if root.tag != f'{{{TASK_NAMESPACE}}}Task':
        raise ValueError('Expected a Task Scheduler definition')
    canonical = ET.canonicalize(xml_data=xml, strip_text=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
