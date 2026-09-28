"""Installation identity for the binding selector (C11/A11-01).

Four identities stay separated - collapsing any two of them is the
defect this module closes:

1. ``adapter_id`` - the MECHANISM (which adapter talks to this kind of
   runtime). Single source: the Core's registry.
2. ``fingerprint``/``build_identity`` - the CONTENT (which bytes were
   observed, which build is qualified). Two byte-identical copies are,
   correctly, the SAME build; qualification grants stay untouched.
3. installation ref (here) - the SELECTABLE LOCAL INSTALLATION: one
   physical target set (canonical executable + launch script when
   present) on ONE host. Byte-identical copies in distinct locations
   are DISTINCT installations with DISTINCT refs and the SAME build
   identity.
4. the AGENT - canonical identity and authorization belong to the
   Nexus Server; an installation is never an agent or a user.

Derivation contract:

* Opaque and path-free: ``nexus-install-v1:<sha256hex>`` over a
  domain-separated canonical form (scheme, adapter_id, canonical
  executable, canonical launch script). The hash of a path is not
  encryption: hosts that must not correlate paths between hosts scope
  or salt via their own port - that privacy policy is deliberately
  NOT imposed here (uniqueness is the requirement being closed).
* Versioned: the ``v1`` in the scheme marks the derivation algorithm;
  changing canonicalization bumps the scheme and requires migration.
* Stable: the same physical target set enumerates to the same ref on
  the same host, independent of inventory order or repetition.
* Alias policy: entries that resolve (symlinks, PATH duplicates) to
  the SAME canonical target are ONE installation - discovery keeps a
  single row per ref; two DISTINCT targets never share a ref.
* Move/rename changes the canonical target, hence the ref: the old ref
  becomes stale (typed "not found") and requires reselection.
* A content UPDATE keeps the ref (same target) but changes the build
  evidence: the old revision/fingerprint no longer match and
  prepare/open keeps refusing drift (C4 stat-snapshot recheck).

Scope: refs are meaningful within the inventory of the EXECUTING host
that produced them. ``executor_id``/``inventory_revision``/TTL are the
host envelope around a selection - a ref from another executor does
not resolve against this inventory (typed "not found"). Knowing a ref
grants NOTHING: authorization stays with the agent's Server policy
and the target is revalidated at prepare/open.
"""

from __future__ import annotations

import hashlib
import os
from typing import Iterable

from .models import CoreError, InstallationCandidate, Inventory

#: Domain + algorithm version of the derivation (part of every ref).
INSTALLATION_REF_SCHEME = "nexus-install-v1"

#: Stable typed codes for the public resolver.
REF_NOT_FOUND = "INSTALLATION_REF_NOT_FOUND"
REF_AMBIGUOUS = "INSTALLATION_REF_AMBIGUOUS"


def _canonical(target: str | None) -> str:
    if not target:
        return ""
    # Resolves symlinks (aliases collapse to one installation) and
    # normalizes case/shape per the LOCAL host; missing targets keep
    # the normalized path so the derivation stays deterministic.
    return os.path.realpath(os.path.normpath(target))


def installation_ref(adapter_id: str, executable: str,
                     launch_script: str | None = None) -> str:
    """Derive the opaque, path-free ref of ONE local installation.

    Distinct canonical targets -> distinct refs; identical bytes at
    distinct targets keep distinct refs with the same build identity.
    """
    payload = "\0".join((INSTALLATION_REF_SCHEME, adapter_id,
                         _canonical(executable),
                         _canonical(launch_script)))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{INSTALLATION_REF_SCHEME}:{digest}"


def effective_installation_ref(candidate: InstallationCandidate) -> str:
    """The candidate's installation ref - explicit when discovery
    filled it, derived otherwise (same algorithm, same inputs)."""
    if candidate.installation_ref:
        return candidate.installation_ref
    return installation_ref(candidate.adapter_id, candidate.executable,
                            candidate.launch_script)


def resolve_installation(
        candidates: "Inventory | Iterable[InstallationCandidate]",
        adapter_id: str, candidate_ref: str) -> InstallationCandidate:
    """Resolve ONE selection to exactly one local candidate (public).

    The input is ``adapter_id`` + ``candidate_ref`` as presented by the
    availability projection of the SAME host inventory. Paths stay on
    the host: the resolved :class:`InstallationCandidate` feeds the
    existing composition (``create_runtime(candidates=...)`` /
    ``prepare``), which revalidates the target before any effect.

    * exactly one match -> that candidate;
    * no match -> typed ``INSTALLATION_REF_NOT_FOUND`` (missing or
      stale - e.g. moved installation, other executor's inventory);
    * more than one DISTINCT match -> typed
      ``INSTALLATION_REF_AMBIGUOUS``: reselection is required, never a
      silent ``candidates[0]``/order-based choice.

    Legacy migration (projection v1): a v1 ``candidate_ref`` was the
    candidate's ``fingerprint`` (content identity). Such a ref still
    resolves when the CURRENT inventory proves exactly one target with
    that content; when two or more installations share the bytes the
    legacy ref is ambiguous BY CONSTRUCTION and the typed ambiguity
    error requires explicit reselection with a v2 installation ref.
    Unknown adapter IDs stay ``CAPABILITY_UNSUPPORTED``.
    """
    if isinstance(candidates, Inventory):
        items = tuple(candidates.candidates)
    else:
        items = tuple(candidates)
    if not isinstance(adapter_id, str) or not isinstance(candidate_ref, str):
        raise CoreError("VALIDATION_ERROR", "resolve_installation")
    pool = [item for item in items
            if isinstance(item, InstallationCandidate)
            and item.adapter_id == adapter_id]
    if not pool and not any(
            isinstance(item, InstallationCandidate)
            and item.adapter_id == adapter_id for item in items):
        from .native.registry import adapter_specs
        if adapter_id not in {spec.adapter_id
                              for spec in adapter_specs()}:
            raise CoreError("CAPABILITY_UNSUPPORTED",
                            "resolve_installation")

    exact = [item for item in pool
             if effective_installation_ref(item) == candidate_ref]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Identical duplicate rows (same target recorded twice) are one
        # installation; DISTINCT targets under one ref is impossible by
        # construction - guard anyway, never choose by order.
        distinct = {(item.executable, item.launch_script)
                    for item in exact}
        if len(distinct) == 1:
            return exact[0]
        raise CoreError(REF_AMBIGUOUS, "resolve_installation",
                        retry_safe=True,
                        message=f"{len(exact)} installations share ref "
                                f"{candidate_ref!r}; reselection with an "
                                f"installation ref is required")

    # Legacy projection-v1 ref (content fingerprint): migrate only when
    # the inventory proves EXACTLY ONE target with that content.
    legacy = [item for item in pool if item.fingerprint == candidate_ref]
    if len(legacy) == 1:
        return legacy[0]
    if len(legacy) > 1:
        raise CoreError(REF_AMBIGUOUS, "resolve_installation",
                        retry_safe=True,
                        message=f"legacy v1 ref matches {len(legacy)} "
                                f"installations with identical bytes; "
                                f"explicit reselection is required")
    raise CoreError(REF_NOT_FOUND, "resolve_installation",
                    retry_safe=True,
                    message=f"no installation matches ref "
                            f"{candidate_ref!r} in this inventory "
                            f"(missing, stale or foreign executor)")


__all__ = ["INSTALLATION_REF_SCHEME", "REF_NOT_FOUND", "REF_AMBIGUOUS",
           "installation_ref", "effective_installation_ref",
           "resolve_installation"]
