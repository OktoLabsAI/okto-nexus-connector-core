from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

root=Path(__file__).parent
repo=Path(r'D:/Projetos/Techridy/okto-nexus-connector-core')
source_reports=Path(r'C:/Users/jpamb/AppData/Local/Temp/svc07-core-drain-9_qowaku')
dest=repo/'docs/evidence/cooperative-drain'
dest.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def copy(source,name):
    target=dest/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
for p in source_reports.iterdir():
    if p.is_file() and p.suffix in {'.json','.xml','.py'}:copy(p,'source/'+p.name)
report=json.loads((source_reports/'core-drain-source-report-v2.json').read_text())
for item in report['files']:assert sha(repo/item['path'])==item['sha256'],item['path']
for folder,names in {
    'core-v2-reports':['build.txt'],
    'core-v2-final-reports':['build.txt','install.txt','inputs.json','tests.txt','tests.xml'],
    'core-v2-installed-reports':['tests.txt','tests.xml','pytest.ini','result.json','pip-check.txt'],
    'core-v2-qualified-reports':['tests.txt','tests.xml','pytest.ini','result.json','pip-check.txt'],
    'core-v2-fixture-path-reports':['tests.txt','tests.xml','pytest.ini','result.json','pip-check.txt'],
}.items():
    for name in names:copy(root/folder/name,'installed/'+folder+'/'+name)
for name in ['core-candidate-1-status.json','core-source.json','qualify_core_v2_initial.py',
             'qualify_core_v2.py','retry_core_installed_initial.py','retry_core_installed_full.py',
             'retry_core_installed.py','third-party.txt','curate_core.py']:
    copy(root/name,'scripts/'+name)
final=list(ET.parse(root/'core-v2-qualified-reports/tests.xml').iter('testcase'))
retry=list(ET.parse(root/'core-v2-fixture-path-reports/tests.xml').iter('testcase'))
assert len(final)==217 and len({c.get('name') for c in final})==217
bad=[c for c in final if c.find('failure') is not None or c.find('error') is not None]
assert len(bad)==1 and len(retry)==1 and retry[0].get('name')==bad[0].get('name')
assert retry[0].find('failure') is None and retry[0].find('error') is None
proof=json.loads((root/'core-v2-final-reports/inputs.json').read_text())
assert (root/'core-v2-fixture-path-reports/pip-check.txt').read_text().strip()=='No broken requirements found.'
summary={'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
    'wheel_sha256':proof['sha256'],'payload_files':proof['source_wheel_installed_identical_files'],
    'installed_unique_passed':217,'full_selection':{'passed':216,'failed':1},
    'targeted_fixture_import_retry':{'passed':1,'failed':0},
    'retry_reason':'Existing fixture imports tests.regression; add frozen test parent, not src, to pytest pythonpath. No product/test/wheel byte changes.',
    'prior_preparation_failures':['Build used global Python with isolated profile hiding its user-installed build module.',
        'First collection omitted legacy sibling fixture path.',
        'Second collection used Windows backslashes in pytest pythonpath; corrected to forward slashes.'],
    'source_unique_passed':217,'source_counts_are_not_additive_with_installed':True,
    'source_files':report['files'],'scenarios':['idle and active native work','pending decision with valid controls',
        'new productive work fenced','journal and event producers','uncertain ownership',
        'bounded/coalesced reads','shared-journal multi-owner and orphan','same-operation recovery'],
    'limits':['Synthetic peers and real SQLite on Windows, no provider inference or personal credentials.',
        'Quiescence is a point-in-time observation, not native death or authority.',
        'Hosts must compare public revisions after awaits and retain storage while readers/producers exist.',
        'Nexus and Connector integration is a separate milestone; no full R3/M1/M2 acceptance claimed.']}
(dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(dest/'milestone.md').write_text('''# Cooperative drain — Core 0.0.14 feature candidate

The runtime can now fence new productive work and observe existing work without
invoking shutdown containment. Authorized decisions, receipts and results remain
available. The host chooses when proven quiescence or explicit operator force
permits its existing containment path. Unknown ownership never becomes success.

Public additions: begin_drain(), drain_status(), drain_revision() and pure
combine_drain_status(). Shared-journal aggregation resolves only an exact claim
retained by another known owner; orphans and changed revisions remain pending.
R4 stopped refusals accept RUNTIME_DRAINING without changing wire authority.

Durable change: additive operation_actions metadata committed with admission;
receipt hashes and operations_v2 stay unchanged. Historical unknown actions are
not inferred or backfilled. Custom journals must implement the new admission
keywords and passive snapshot API. Existing shutdown semantics are preserved.
Reverting code leaves the additive table harmlessly present; unresolved records
written without metadata are conservative on a later upgrade.

Validation: 217 unique source cases and 217 unique installed cases, not added
together. The immutable installed full selection passed216 and had one fixture
import failure; that one case passed after adding the copied test parent to
pytest's fixture path. Product, tests and wheel bytes were unchanged. Earlier
preparation/collection failures and source fixture failures are retained.
All166 package payload files match source, wheel and installed bytes. pip check
passed; source Ruff review found no new issues against12 retained baseline items.

Only synthetic native peers and disposable SQLite/state were used. No provider,
personal vault or OS service was invoked. Host integration and actual M1 remain
separate qualification gates. Scripts, input hashes, dependency versions, XML
and exact-byte manifest are retained here.
''',encoding='utf-8')
items=[{'path':p.relative_to(dest).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
       for p in sorted(dest.rglob('*')) if p.is_file()]
(dest/'artifact-manifest.json').write_text(json.dumps({'artifacts':items,'excludes':['this manifest','homes','databases','raw provider logs','wheel binary']},indent=2)+'\n')
print(json.dumps({'files':len(items)+1,'installed_unique_passed':217,'wheel_sha256':proof['sha256']}))
