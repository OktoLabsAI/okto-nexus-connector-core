"""Shared host adapter for a replacement owner's interrupted managed launch."""
import asyncio

from ...models import CoreError
from ...process_launch_control import LaunchRecovery, ProcessLaunchController
from .launch_exclusion import HostLaunchExclusion
from .recovery import recover_launch_container


async def recover_process_launch(journal, session, *, connection_generation, validate_authority):
    launch = await journal.get_process_launch(session)
    if launch is None:
        return LaunchRecovery('NO_LAUNCH_INTENT')
    claim = await journal.get_session_claim(session)
    identity = launch.identity
    if (claim is None or claim.key != identity.key or claim.opening_operation_id != identity.opening_operation_id
            or claim.opening_connection_generation != identity.connection_generation
            or claim.opening_owner_generation != identity.owner_generation
            or type(connection_generation) is not int or connection_generation <= identity.connection_generation):
        raise CoreError('STALE_GENERATION', 'process_launch_recovery', possible_effect=True)
    controller = ProcessLaunchController(journal, HostLaunchExclusion())
    result = await controller.recover(identity, validate_authority=validate_authority,
        stop_container=recover_launch_container)
    if result.state == 'STOPPED' and result.record.stop_proof == 'NEVER_CLAIMED':
        await asyncio.to_thread(validate_authority)
        await journal.settle_unclaimed_process_launch(identity)
    return result
