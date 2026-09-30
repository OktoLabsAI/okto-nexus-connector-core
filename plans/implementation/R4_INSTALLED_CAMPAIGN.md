# Installed R4 contract campaign

Date: September 30, 2026. Runtime baseline: `368c50d9b8496809a4865e32a774492db3e3549f`.
Core `0.2.28.dev0`, wheel SHA-256
`27df75100dea033ca5456f2d571eb41b6311fa3ce530a723ecd6c606d257953c`.

The runner `tools/run_r4_installed.py` runs from an external temporary
directory with `python -I`, imports Core from `site-packages`, and compares
every packaged Core file against the supplied wheel. It supplies only the
test helper namespace needed by existing regression tests. It records the
selected test hashes, loaded helper hashes, runner hash, Python/platform,
timing, pytest arguments, result hash and installed package file hashes.

Command from the Core repository:

```text
rtk proxy python -X utf8 tools/run_r4_installed.py --python C:/Users/jpamb/AppData/Local/Temp/okto-r4-pending-installed-py313/Scripts/python.exe --wheel artifacts/nexus_connector_core-0.2.28.dev0-py3-none-any.whl --report-dir plans/implementation/evidence/r4-installed-campaign
```

Result: **99 passed, no skips, failures or errors**. See
`evidence/r4-installed-campaign/manifest.json` and `results.xml`.
The selection includes the R4 codecs/reducers, lease application, containment,
decision/receipt bridges, control targeting, close policy, and historical R3
consumer conformance. These are synthetic contract cases. No provider,
product dispatcher, daemon or multi-host acceptance gate is closed.

Two earlier direct pytest invocations each passed 94 cases and failed one
because their isolated runner could not resolve a shared `tests` helper
namespace. The failures are preserved in `evidence/r4-installed-conformance.xml`
and `evidence/r4-installed-conformance-final.xml`; the latter filename does
not imply success. The test import was restored and the runner supplies the
test namespace explicitly. Runtime source and the wheel were unchanged.

This campaign contributes to M01. Full operation coverage through both
installed product hosts and the remaining delivery criteria are still open.
The R4 executable flag remains false.
