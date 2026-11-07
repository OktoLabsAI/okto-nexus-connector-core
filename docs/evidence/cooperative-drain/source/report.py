import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path('D:/Projetos/Techridy/okto-nexus-connector-core')
OUT = Path(__file__).parent
PRODUCT = ['src/nexus_connector_core/' + name for name in (
    'drain.py', 'runtime.py', 'kernel.py', 'journal.py', 'ports.py',
    'native/runtime_bridge.py', 'operation_refusal_r4.py')]
TESTS = ['tests/test_cooperative_drain.py', 'tests/test_r4_stopped_refusal.py']

def run(*argv, cwd=ROOT):
    result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result

def sha(data):
    return hashlib.sha256(data).hexdigest()

baseline = OUT / 'baseline-lint'
baseline.mkdir(exist_ok=True)
lint_files = ['runtime.py', 'journal.py', 'kernel.py', 'native/runtime_bridge.py']
for name in lint_files:
    relative = 'src/nexus_connector_core/' + name
    original = run('rtk', 'proxy', 'git', 'show', 'HEAD:' + relative)
    assert original.returncode == 0
    target = baseline / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(original.stdout)
lint = {}
for label, paths in (
    ('baseline', [str(baseline / name) for name in lint_files]),
    ('current', [str(ROOT / 'src/nexus_connector_core' / name) for name in lint_files]),
):
    result = run(sys.executable, '-m', 'ruff', 'check', '--output-format=json', *paths)
    (OUT / f'ruff-{label}.json').write_bytes(result.stdout)
    rows = json.loads(result.stdout)
    lint[label] = sorted((Path(r['filename']).name, r['code'], r['message']) for r in rows)
assert lint['baseline'] == lint['current']
reports = []
unique = {}
for filename in ('initial.xml', 'directed.xml', 'regression.xml'):
    path = OUT / filename
    tree = ET.fromstring(path.read_bytes())
    cases = tree.findall('.//testcase')
    counts = {'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0}
    for case in cases:
        outcome = next((kind for kind in ('failure', 'error', 'skipped') if case.find(kind) is not None), 'passed')
        if outcome != 'passed':
            counts[{'failure': 'failures', 'error': 'errors', 'skipped': 'skipped'}[outcome]] += 1
        unique[(case.get('classname'), case.get('name'))] = outcome
    reports.append({'path': str(path), 'sha256': sha(path.read_bytes()), **counts})
result = {
    'scope': 'SVC-07 Core cooperative drain only; synthetic native peers, real SQLite',
    'base_commit': run('rtk', 'proxy', 'git', 'rev-parse', 'HEAD').stdout.decode().strip(),
    'product_frozen': True,
    'files': [{'path': path, 'sha256': sha((ROOT / path).read_bytes())} for path in PRODUCT + TESTS],
    'reports': reports,
    'unique_final_test_identities': len(unique),
    'unique_final_outcomes': {kind: sum(value == kind for value in unique.values()) for kind in set(unique.values())},
    'initial_failures': 'Two helper failures called nonexistent runtime.receipt; corrected to journal.get_receipt. No product change needed for those failures.',
    'lint': {'new_and_clean_touched_files': 'passed', 'existing_baseline_findings_unchanged': len(lint['baseline']),
             'comparison': 'same filename/code/message multisets; shifted line numbers ignored'},
    'durable_change': 'Additive operation_actions metadata, atomic with admission, no receipt/hash changes; legacy missing metadata stays unknown. No inferred backfill.',
    'contract': {'begin_drain': 'sync owner-loop fence only; idempotent, no close/interrupt/renewal',
                 'drain_status': 'passive bounded read; RUNNING/BUSY/UNKNOWN/QUIESCENT, quiescent boolean, metadata resources',
                 'bounds': '256 rows + sentinel per journal query and 256 resources; one shared read per runtime, one-second await budget',
                 'preserved': 'current authorized native decisions, interrupt/close, events/ack/reconciliation and authorized receipt replay'},
    'limitations': ['Not a proof of process death or future inactivity.',
                    'Legacy unknown action, uncertain native outcome, missing ACK or unresolved ownership remains non-quiescent.',
                    'No real provider, personal credentials, OS service campaign, wheel build, commit or push by this agent.'],
}
(OUT / 'core-drain-source-report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'report': str(OUT / 'core-drain-source-report.json'), 'unique': len(unique),
                  'lint_baseline_unchanged': len(lint['baseline']), 'reports': reports}, indent=2))
