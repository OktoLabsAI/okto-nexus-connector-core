"""Physical journal creation intent; never execution, release or audit proof."""
from dataclasses import dataclass
import re
from typing import Protocol

from .models import SessionKey
from .models import CoreError


def validate_journal_name(name):
    # Single portable basename, not a tool-controlled path or Windows device.
    if type(name) is not str or re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,119}\.db', name) is None:
        raise ValueError('Invalid managed journal name.')
    stem = name[:-3]
    if stem in {'owned-slots', 'con', 'prn', 'aux', 'nul',
                *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}:
        raise ValueError('Reserved managed journal name.')


@dataclass(frozen=True, slots=True)
class JournalLocation:
    name: str
    # None explicitly declares one shared-host journal, as used by Connector.
    session: SessionKey | None = None

    def __post_init__(self):
        validate_journal_name(self.name)
        if self.session is not None:
            if type(self.session) is not SessionKey or any(
                    type(value) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) is None
                    for value in (self.session.server_id, self.session.executor_id, self.session.session_id)):
                raise ValueError('Invalid managed journal session.')


@dataclass(frozen=True, slots=True)
class JournalRegistration:
    location: JournalLocation
    revision: int


@dataclass(frozen=True, slots=True)
class JournalLocationPage:
    registrations: tuple[JournalRegistration, ...]
    high_water_revision: int
    next_after_revision: int | None


@dataclass(frozen=True, slots=True)
class JournalRegistryHead:
    store_id: str
    revision: int
    digest: str
    complete: bool


@dataclass(frozen=True, slots=True)
class JournalAuditAnchor:
    store_id: str
    nonce: str
    revision: int
    digest: str


def require_audit_snapshot_not_rolled_back(host_anchor: JournalAuditAnchor | None,
                                            core_anchor: JournalAuditAnchor | None,
                                            head: JournalRegistryHead) -> None:
    """Fence definite Core rollback before a host admits native work.

    A head ahead of the host is allowed: new registrations may have committed
    after the last paired audit. That case still requires the host's full
    physical audit and does not by itself authorize a fast startup.
    """
    if host_anchor is None:
        return
    if (type(host_anchor) is not JournalAuditAnchor
            or type(head) is not JournalRegistryHead
            or type(core_anchor) is not JournalAuditAnchor
            or not head.complete
            or host_anchor.store_id != head.store_id
            or core_anchor.store_id != head.store_id
            or head.revision < host_anchor.revision
            or (head.revision == host_anchor.revision
                and head.digest != host_anchor.digest)
            or core_anchor.revision < host_anchor.revision
            or (core_anchor.revision == host_anchor.revision
                and core_anchor.digest != host_anchor.digest)):
        raise CoreError('PROFILE_DRIFT', 'journal_audit_snapshot')


class JournalLocationRegistry(Protocol):
    """Host storage port. Registration must precede productive file creation."""
    async def physical_store_id(self) -> str: ...
    async def journal_registry_head(self) -> JournalRegistryHead: ...
    async def advance_journal_registry_head(self, *, limit: int = 128) -> JournalRegistryHead: ...
    async def journal_audit_anchor(self) -> JournalAuditAnchor | None: ...
    async def stage_journal_audit_anchor(self, *, nonce: str,
                                         head: JournalRegistryHead) -> JournalAuditAnchor: ...
    async def register_journal_locations(self, locations: tuple[JournalLocation, ...]) -> tuple[JournalRegistration, ...]: ...
    async def journal_location(self, name: str) -> JournalRegistration | None: ...
    async def journal_location_page(self, *, after_revision: int = 0,
                                   high_water_revision: int | None = None,
                                   limit: int = 128) -> JournalLocationPage: ...
