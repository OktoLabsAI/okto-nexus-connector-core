from pathlib import Path
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET

root=Path(__file__).parent
source=root/'core-v2-final-source'
out=root/'core-v2-fixture-path-reports'
out.mkdir()
proof=json.loads((root/'core-v2-final-reports/inputs.json').read_text())
def verify():
    for name, expected in proof['source_hashes'].items():
        assert hashlib.sha256((source/name).read_bytes()).hexdigest()==expected,name
verify()
env={k:v for k,v in os.environ.items() if k.upper() in {
    'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP'}}
env['SystemRoot']=os.environ['SYSTEMROOT']
for name in ('USERPROFILE','APPDATA','LOCALAPPDATA'):
    env[name]=str(root/'isolated-env'/name.lower())
env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
prior=Path(r'C:/Users/jpamb/AppData/Local/Temp/svc07-core-drain-9_qowaku/regression.xml')
modules=sorted({c.get('classname') for c in ET.parse(prior).iter('testcase')}|{'tests.test_cooperative_drain_composition'})
config=out/'pytest.ini'
config.write_text('[pytest]\nasyncio_mode=auto\nasyncio_default_fixture_loop_scope=function\npythonpath='+(source/'tests').as_posix()+' '+source.as_posix()+'\n')
python=str(root/'venv/Scripts/python.exe')
command=[python,'-I','-X','utf8','-m','pytest','-p','pytest_asyncio.plugin','-p','no:cacheprovider',
    '-c',str(config),'--import-mode=importlib','--basetemp',str(out/'tmp'),'-q','--tb=short',
    '--junitxml',str(out/'tests.xml'),str(source/'tests/test_r4_runtime_leases.py')+'::test_revocation_fences_copied_factory_after_environment_wait']
with (out/'tests.txt').open('wb') as log:
    result=subprocess.run(command,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
verify()
cases=list(ET.parse(out/'tests.xml').iter('testcase'))
summary={'command':command,'exit':result.returncode,'changed_inputs':[],
    'tests':len(cases),'failures':sum(c.find('failure') is not None or c.find('error') is not None for c in cases),
    'fixture_import_fix':'Copied tests and their frozen parent added for tests.regression imports; src is absent from sys.path and application remains installed noneditable wheel.',
    'package_inputs':'../core-v2-final-reports/inputs.json'}
(out/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
with (out/'pip-check.txt').open('wb') as log:
    check=subprocess.run([python,'-m','pip','check'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
print(json.dumps({'exit':result.returncode,'tests':len(cases),'failures':summary['failures'],'pip_check':check.returncode}))
raise SystemExit(result.returncode or check.returncode)
