"""Physical journal creation intent; never execution, release or audit proof."""
from dataclasses import dataclass
import re
from typing import Protocol

from .models import SessionKey


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


class JournalLocationRegistry(Protocol):
    """Host storage port. Registration must precede productive file creation."""
    async def register_journal_locations(self, locations: tuple[JournalLocation, ...]) -> tuple[JournalRegistration, ...]: ...
    async def journal_location(self, name: str) -> JournalRegistration | None: ...
    async def journal_location_page(self, *, after_revision: int = 0,
                                   high_water_revision: int | None = None,
                                   limit: int = 128) -> JournalLocationPage: ...
