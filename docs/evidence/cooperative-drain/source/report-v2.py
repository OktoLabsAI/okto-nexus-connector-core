import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path('D:/Projetos/Techridy/okto-nexus-connector-core')
out = Path(__file__).parent
prior = out / 'core-drain-source-report.json'
report = json.loads(prior.read_text(encoding='utf-8'))
report['prior_report'] = {'path': str(prior), 'sha256': hashlib.sha256(prior.read_bytes()).hexdigest()}
report['candidate'] = 'v2-public-shared-journal-composition'
paths = [row['path'] for row in report['files']] + [
    'src/nexus_connector_core/__init__.py', 'tests/test_cooperative_drain_composition.py']
report['files'] = [{'path': path, 'sha256': hashlib.sha256((root/path).read_bytes()).hexdigest()} for path in paths]
xml = out/'composition-initial.xml'
cases = ET.fromstring(xml.read_bytes()).findall('.//testcase')
assert len(cases) == 50 and all(c.find('failure') is None and c.find('error') is None for c in cases)
report['reports'].append({'path': str(xml), 'sha256': hashlib.sha256(xml.read_bytes()).hexdigest(),
                         'tests': 50, 'failures': 0, 'errors': 0, 'skipped': 0})
identities = set()
for row in report['reports']:
    identities.update((c.get('classname'), c.get('name')) for c in ET.fromstring(Path(row['path']).read_bytes()).findall('.//testcase'))
report['unique_final_test_identities'] = len(identities)
report['unique_final_outcomes'] = {'passed': len(identities)}
report['qualification_boundary'] = ('209 prior regression identities passed before additive public composition delta; '
    '50 directly affected identities passed after it, including 8 new shared-journal cases. No claim of one immutable 217-case run.')
report['contract']['composition'] = ('drain_status includes owned_sessions and activity_revision; drain_revision() is a synchronous '
    'memory-only token. combine_drain_status(reports) may resolve only exact claims retained by one other owner of the SAME journal. '
    'Host checks all revisions after all awaits. Missing fields, orphan, opening mismatch or duplicate owners stay UNKNOWN.')
report['limitations'].append('An empty runtime set does not prove an empty historical journal; the host must inspect its already-owned journal or remain UNKNOWN.')
target = out/'core-drain-source-report-v2.json'
target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                  'unique': len(identities), 'final_delta_tests': 50}))
