"""Per-harness observation coverage; transport contact never refreshes identity."""
from __future__ import annotations

from collections import Counter
from typing import Mapping

MAX_OBSERVATION_AGE_MS = 300_000
OBSERVATION_STATES = frozenset({'PENDING', 'PRESENT', 'ABSENT', 'FAILED'})


def build_observations(catalog, candidates, observations):
    adapters = {row['adapter_id'] for row in catalog['runtimes'] if row['discoverable']}
    present = {candidate.adapter_id for candidate in candidates}
    if observations is None:
        return [dict(adapter_id=adapter, state='PRESENT' if adapter in present else 'ABSENT',
                     observation_age_ms=0, error_code=None) for adapter in sorted(adapters)]
    if not isinstance(observations, Mapping) or set(observations) != adapters:
        raise ValueError('observations must cover exactly the discoverable catalog')
    if any(not isinstance(row, Mapping) or row.get('adapter_id', adapter) != adapter
           for adapter, row in observations.items()):
        raise ValueError('observation identity differs from its adapter key')
    fields = {'state', 'observation_age_ms', 'error_code'}
    if any(set(row) not in (fields, fields | {'adapter_id'}) for row in observations.values()):
        raise ValueError('observation requires state, age and error code only')
    return [dict(observations[adapter], adapter_id=adapter) for adapter in sorted(adapters)]


def verify_observations(snapshot):
    """Check complete coverage and forbid evidence of unobserved installations."""
    catalog = snapshot['catalog']['runtimes']
    expected = sorted(row['adapter_id'] for row in catalog if row['discoverable'])
    if len(expected) != len(set(expected)):
        raise ValueError('duplicate discoverable catalog entries')
    observations = snapshot['observations']
    if not isinstance(observations, list) or [row['adapter_id'] for row in observations] != expected:
        raise ValueError('observation coverage is incomplete, duplicate or unsorted')
    candidates = Counter(row['adapter_id'] for row in snapshot['evidence'])
    availability = Counter(row['adapter_id'] for row in snapshot['availability']['availability'])
    if (set(candidates) | set(availability)) - set(expected):
        raise ValueError('evidence belongs to an unobserved adapter')
    for row in observations:
        if set(row) != {'adapter_id', 'state', 'observation_age_ms', 'error_code'}:
            raise ValueError('unexpected observation fields')
        adapter, state, age, error = (row[key] for key in
            ('adapter_id', 'state', 'observation_age_ms', 'error_code'))
        if state not in OBSERVATION_STATES:
            raise ValueError('unknown observation state')
        if state in ('PRESENT', 'ABSENT'):
            if type(age) is not int or not 0 <= age <= MAX_OBSERVATION_AGE_MS or error is not None:
                raise ValueError('completed observation requires bounded age and no failure')
            if (state == 'PRESENT') != bool(candidates[adapter]):
                raise ValueError('observation state differs from candidate evidence')
            if availability[adapter] != (candidates[adapter] or 1):
                raise ValueError('completed observation has inconsistent availability')
            if state == 'ABSENT' and any(value['candidate_ref'] or value['state'] != 'NOT_INSTALLED'
                    for value in snapshot['availability']['availability'] if value['adapter_id'] == adapter):
                raise ValueError('absent observation must explicitly report no installation')
        else:
            if candidates[adapter] or availability[adapter] or age is not None:
                raise ValueError('pending or failed observation cannot contain usable evidence')
            if state == 'PENDING' and error is not None:
                raise ValueError('pending observation cannot report a failure')
            if state == 'FAILED' and (not isinstance(error, str) or not 1 <= len(error) <= 80
                    or not error[0].isupper() or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in error)):
                raise ValueError('failed observation requires a path-free error code')


def inventory_observation_fresh(snapshot, adapter_id, *, elapsed_ms=0, ttl_ms=120_000):
    """Evaluate a verified publication for ONE adapter, including transport age.

    A fresh ABSENT observation is usable evidence of absence, not permission to
    launch. Candidate, binding, producer and authority checks remain mandatory.
    The receiver supplies time elapsed since its own monotonic receipt anchor.
    """
    from .executor_inventory import verify_executor_inventory_snapshot
    verify_executor_inventory_snapshot(snapshot)
    if type(elapsed_ms) is not int or elapsed_ms < 0 or type(ttl_ms) is not int or ttl_ms <= 0:
        raise ValueError('freshness requires nonnegative elapsed time and a positive TTL')
    row = next((row for row in snapshot['observations'] if row['adapter_id'] == adapter_id), None)
    return bool(row and row['state'] in ('PRESENT', 'ABSENT') and
                row['observation_age_ms'] + snapshot['observation_age_ms'] + elapsed_ms < ttl_ms)
