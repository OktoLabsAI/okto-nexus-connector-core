"""Allocate a host container identity before durable admission, without spawning."""
import os
import sys
import uuid

from ...models import CoreError
from ...process_launch import ProcessLaunchIdentity, validate_launch_identity


def plan_process_launch(key, operation_id, context):
    token = uuid.uuid4().hex
    if sys.platform == 'win32':
        kind, container = 'windows_job', 'Global\\nexus-core-'+token
    elif sys.platform == 'linux':
        kind, container = 'linux_guardian', 'linux-guardian:'+token
    elif sys.platform == 'darwin':
        kind = 'darwin_launchd_coalition'
        container = f'darwin-launchd:ai.oktolabs.nexus-owned.{os.getpid()}.{token[:16]}'
    else:
        raise CoreError('CAPABILITY_UNSUPPORTED', 'process_launch', retry_safe=True)
    result = ProcessLaunchIdentity(key, operation_id, context.connection_generation,
        context.session_owner_generation, sys.platform, kind, container, uuid.uuid4().hex)
    validate_launch_identity(result)
    return result
