"""Opt-in installed CLI contract check; isolated config, no model request."""
import json
import os
import shutil
import subprocess
import queue
import threading
import time

import pytest

from nexus_connector_core.harness_config import harness_http_template, process_http_arguments
from nexus_connector_core.mcp_inheritance import codex_mcp_names


@pytest.mark.skipif(os.environ.get('NEXUS_TEST_NATIVE_MCP') != '1' or not shutil.which('codex'),
                   reason='Opt-in installed Codex CLI check')
def test_native_codex_table_merge_preserves_or_disables_host_mcp(tmp_path):
    path = tmp_path/'config.toml'
    original = '[mcp_servers.external]\nurl="http://127.0.0.1:1/mcp"\n'
    path.write_text(original)
    env = dict(os.environ, CODEX_HOME=str(tmp_path))
    template = harness_http_template('codex_app_server','http://127.0.0.1:2/mcp','mcp-cap:fixture',
        entry_name='nexus_fixture',harness_is_local=True,loopback_reachable=True,
        approved_origins={'http://127.0.0.1:2'},format_qualified=True)
    for inherit in (False, True):
        args = process_http_arguments('codex_app_server',(template,),{'mcp-cap:fixture'},
            inherit_global_mcps=inherit,disabled_mcp_names=codex_mcp_names(env,str(tmp_path)))
        result = subprocess.run([shutil.which('codex'),*args,'mcp','list','--json'],env=env,
            cwd=tmp_path,capture_output=True,text=True,timeout=20)
        assert result.returncode == 0, result.stderr
        assert {x['name']:x['enabled'] for x in json.loads(result.stdout)} == {
            'external':inherit,'nexus_fixture':True}
    assert path.read_text() == original


@pytest.mark.skipif(os.environ.get('NEXUS_TEST_NATIVE_MCP') != '1' or not shutil.which('codex'),
                   reason='Opt-in installed Codex CLI check')
def test_native_codex_unavailable_optional_mcp_does_not_block_thread(tmp_path):
    path = tmp_path/'config.toml'
    path.write_text('[mcp_servers.external]\nurl="http://127.0.0.1:1/mcp"\nstartup_timeout_sec=1\n')
    from nexus_connector_core.environment import _ESSENTIALS
    env = {k:v for k,v in os.environ.items() if k.upper() in _ESSENTIALS}
    env.update(CODEX_HOME=str(tmp_path), OPENAI_API_KEY='isolated-test-no-model-request')
    messages = queue.Queue()
    process = subprocess.Popen([shutil.which('codex'),'app-server'],cwd=tmp_path,env=env,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    def reader():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
    thread = threading.Thread(target=reader,daemon=True)
    thread.start()
    def send(value):
        process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
    def response(request_id):
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            value = messages.get(timeout=max(.01,deadline-time.monotonic()))
            if value.get('id') == request_id:
                return value
        raise AssertionError('Native response timed out')
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'nexus-mcp-test','version':'1'}}})
        assert 'result' in response(1)
        send({'method':'initialized','params':{}})
        send({'id':2,'method':'thread/start','params':{'cwd':str(tmp_path)}})
        result = response(2)
        assert 'result' in result, result
        assert result['result']['thread']['id']
    finally:
        # Closing stdin terminates this disposable app-server without a model turn.
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # The npm Windows shim is a parent: terminate only its owned tree.
            import psutil
            root = psutil.Process(process.pid)
            children = root.children(recursive=True)
            for child in reversed(children):
                child.kill()
            root.kill()
            process.wait(timeout=5)
        thread.join(timeout=5)
        process.stdout.close()
