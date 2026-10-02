"""Run R4 and historical contract cases against an exact installed Core wheel.

The selected Python must already contain pytest and the wheel. The child runs
with -I from a temporary directory, without adding application source to its
import path. A tests-only namespace makes shared regression helpers available.
This campaign proves technical contracts, not native provider qualification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile


CHILD = r'''
import hashlib
import json
from pathlib import Path
import platform
from datetime import datetime, timezone
import sys
import types
import zipfile

import nexus_connector_core as core
import pytest

tests, wheel, report_dir, runner = map(Path, sys.argv[1:])
installed = Path(core.__file__).resolve().parent
if 'site-packages' not in installed.parts:
    raise RuntimeError('Core must be imported from the installed environment.')
checked = {}
with zipfile.ZipFile(wheel) as archive:
    for name in archive.namelist():
        if not name.startswith('nexus_connector_core/') or name.endswith('/'):
            continue
        path = installed / name.removeprefix('nexus_connector_core/')
        expected = archive.read(name)
        if not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError('Installed Core differs from the selected wheel: ' + name)
        checked[name] = hashlib.sha256(expected).hexdigest()
if not checked:
    raise RuntimeError('The selected wheel does not contain Core package files.')

# Existing tests import helpers as tests.regression.* as well as test_runtime.
# Only the test namespace is supplied; the application stays in site-packages.
helpers = types.ModuleType('tests')
helpers.__path__ = [str(tests)]
sys.modules['tests'] = helpers
paths = sorted(tests.glob('test_r4*.py')) + [
    tests/'test_close_policy.py', tests/'test_control_targeting.py',
    tests/'test_consumer_conformance.py',
]
args = ['-c', 'pytest.ini', '--rootdir='+str(tests), '--confcutdir='+str(tests),
        *map(str, paths), '-q', '--tb=short',
        '--junitxml='+str(report_dir/'results.xml')]
report = {
    'scope': 'Installed R4 contracts and R3 historical bundle; synthetic peers',
    'core_version': core.__version__, 'installed_core': str(installed),
    'wheel': str(wheel), 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'isolated_interpreter': sys.flags.isolated == 1,
    'application_source_added_to_import_path': False,
    'package_files_sha256': checked, 'pytest_arguments': args,
    'test_source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    'provider_qualification': 'NOT_RUN', 'product_gate_closed': False,
    'started_at': datetime.now(timezone.utc).isoformat(),
    'python': sys.version, 'executable': sys.executable,
    'platform': platform.platform(), 'architecture': platform.machine(),
    'working_directory': str(Path.cwd()),
    'runner_sha256': hashlib.sha256(runner.read_bytes()).hexdigest(),
}
status = pytest.main(args)
report['finished_at'] = datetime.now(timezone.utc).isoformat()
loaded_tests = set()
for module in tuple(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename:
        path = Path(filename).resolve()
        if path.is_relative_to(tests) and path.is_file():
            loaded_tests.add(path)
report['loaded_test_helpers_sha256'] = {
    str(p.relative_to(tests)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(loaded_tests)
}
report['exit_code'] = int(status)
report['results_sha256'] = hashlib.sha256((report_dir/'results.xml').read_bytes()).hexdigest()
(report_dir/'manifest.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
raise SystemExit(status)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    # Unix venv interpreters are symlinks. Resolving the executable follows
    # the link out of the venv and silently tests the base interpreter instead.
    python, wheel, reports = args.python.absolute(), args.wheel.resolve(), args.report_dir.resolve()
    if not python.is_file() or not wheel.is_file():
        parser.error('The Python executable and Core wheel must exist.')
    reports.mkdir(parents=True, exist_ok=True)
    tests = Path(__file__).resolve().parents[1]/'tests'
    with tempfile.TemporaryDirectory(prefix='okto-r4-installed-') as directory:
        Path(directory, 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
        result = subprocess.run(
            [str(python), '-I', '-X', 'utf8', '-c', CHILD,
             str(tests), str(wheel), str(reports), str(Path(__file__).resolve())],
            cwd=directory, check=False)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
