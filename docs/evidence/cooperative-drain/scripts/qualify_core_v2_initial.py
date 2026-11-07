from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

root = Path(__file__).parent
repo = Path(r'D:/Projetos/Techridy/okto-nexus-connector-core')
source = root / 'core-v2-source'
source.mkdir()
shutil.copytree(repo / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
shutil.copytree(repo / 'tests', source / 'tests', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for name in ('pyproject.toml','README.md','LICENSE'):
    shutil.copyfile(repo / name, source / name)
reports = root / 'core-v2-reports'
reports.mkdir()
python = root / 'venv/Scripts/python.exe'
env = {k:v for k,v in os.environ.items() if k.upper() in {
    'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP'}}
env['SystemRoot'] = os.environ['SYSTEMROOT']
for name in ('USERPROFILE','APPDATA','LOCALAPPDATA'):
    home = root / 'isolated-env' / name.lower()
    home.mkdir(parents=True, exist_ok=True)
    env[name] = str(home)
env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')

def hashes():
    return {p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('src/nexus_connector_core','tests') for p in (source/folder).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts}

def run(name, args, *, cwd=root):
    with (reports/(name+'.txt')).open('wb') as log:
        result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps({'step':name,'exit':result.returncode}),flush=True)
    if result.returncode: raise SystemExit(result.returncode)

before = hashes()
run('build', [sys.executable,'-m','build','--wheel','--no-isolation','--outdir',str(root/'core-v2-wheels')],cwd=source)
wheel = next((root/'core-v2-wheels').glob('*.whl'))
run('install', [sys.executable,'-m','uv','pip','install','--python',str(python),'--no-deps',str(wheel)])
with zipfile.ZipFile(wheel) as z:
    names = [n for n in z.namelist() if n.startswith('nexus_connector_core/') and not n.endswith('/')]
    for name in names:
        assert z.read(name)==(source/'src'/name).read_bytes()==(root/'venv/Lib/site-packages'/name).read_bytes(),name
proof = {'wheel':str(wheel),'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'source_wheel_installed_identical_files':len(names),'source_hashes':before,
    'environment_names':sorted(env),'personal_profile_forwarded':False,'provider_credentials_forwarded':False}
(reports/'inputs.json').write_text(json.dumps(proof,indent=2)+'\n')
prior=Path(r'C:/Users/jpamb/AppData/Local/Temp/svc07-core-drain-9_qowaku/regression.xml')
modules=sorted({c.get('classname') for c in ET.parse(prior).iter('testcase')}|{'tests.test_cooperative_drain_composition'})
config=root/'core-v2-pytest.ini'
config.write_text('[pytest]\nasyncio_mode=auto\nasyncio_default_fixture_loop_scope=function\n')
command=[str(python),'-I','-X','utf8','-m','pytest','-p','pytest_asyncio.plugin','-p','no:cacheprovider',
    '-c',str(config),'--import-mode=importlib','--basetemp',str(reports/'tmp'),
    '-q','--tb=short','--junitxml',str(reports/'tests.xml')]
command += [str(source/(m.replace('.','/')+'.py')) for m in modules]
run('tests',command)
after=hashes()
assert before==after
(reports/'result.json').write_text(json.dumps({'command':command,'changed_inputs':[],
    'passed':len(list(ET.parse(reports/'tests.xml').iter('testcase')))},indent=2)+'\n')
run('pip-check',[str(python),'-m','pip','check'])
