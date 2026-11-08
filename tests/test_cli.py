"""Offline integration tests; all API keys and addresses are synthetic."""
import base64
import fcntl
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import select
import stat
import subprocess
import tempfile
import termios
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Handler(BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args): pass
    def handle_api(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.__class__.requests.append((self.command, self.path, self.headers.get('Authorization'), self.headers.get('Content-Type'), data))
        if self.path == '/v4/domains/redirect.example':
            self.send_response(302); self.send_header('Location', '/v4/domains/mg.example.test'); self.end_headers(); return
        if b'reject@mg.example.test' in data:
            status, body = 503, {'error': 'synthetic-secret-should-not-appear'}
        elif self.path.startswith('/v4/domains/bad.example'):
            status, body = 400, {'error': 'synthetic-secret-should-not-appear'}
        elif self.path.startswith('/v4/domains?'):
            status, body = 200, {'items': [{'name': 'mg.example.test'}], 'total_count': 1}
        elif self.path.endswith('/credentials') and self.command == 'POST':
            status, body = 200, {'message': 'Created', 'credentials': {'password': 'synthetic-server-secret'}}
        elif self.path.startswith('/v3/domains/'):
            status, body = 200, {'items': [{'login': 'postmaster@mg.example.test'}], 'total_count': 1}
        else:
            status, body = 200, {'domain': {'name': 'mg.example.test', 'smtp_password': 'synthetic-server-secret'}, 'sending_dns_records': [{'record_type': 'TXT', 'value': 'public-dkim'}]}
        raw = json.dumps(body).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    do_GET = handle_api
    do_POST = handle_api
    do_PUT = handle_api

class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def setUp(self):
        Handler.requests = []
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, 'XDG_CONFIG_HOME': self.tmp.name, 'MAILGUN_API_KEY': 'local-test-key', 'MAILGUN_TEST_MODE': '1', 'MAILGUN_TEST_BASE_URL': f'http://127.0.0.1:{self.server.server_port}'}
    def tearDown(self): self.tmp.cleanup()
    def run_cli(self, *args, env=None):
        return subprocess.run([str(ROOT/'mailgun'), *args], cwd=ROOT, env=env or self.env, text=True, capture_output=True, timeout=10)
    def test_list_and_check_use_private_auth(self):
        result = self.run_cli('domains','list','--region','eu','--limit','2')
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['total_count'],1)
        self.assertEqual(Handler.requests[0][1],'/v4/domains?limit=2&skip=0')
        self.assertEqual(Handler.requests[0][2],'Basic '+base64.b64encode(b'api:local-test-key').decode())
        self.assertNotIn('local-test-key', result.stdout + result.stderr)
        check=self.run_cli('login','--check'); self.assertEqual(check.returncode,0,check.stderr); self.assertTrue(json.loads(check.stdout)['authenticated'])
    def test_domain_operations_and_redaction(self):
        for args,method,path in [(('domains','show','MG.EXAMPLE.TEST'),'GET','/v4/domains/mg.example.test'),(('domains','create','mg.example.test'),'POST','/v4/domains'),(('domains','verify','mg.example.test'),'PUT','/v4/domains/mg.example.test/verify')]:
            result=self.run_cli(*args); self.assertEqual(result.returncode,0,result.stderr); body=json.loads(result.stdout)
            self.assertEqual(body['domain']['smtp_password'],'[redacted]'); self.assertEqual(body['sending_dns_records'][0]['value'],'public-dkim')
            self.assertEqual(Handler.requests[-1][:2],(method,path))
        method, path, auth, content_type, payload = Handler.requests[-2]
        self.assertIn('multipart/form-data', content_type)
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+payload)
        parts={p.get_param('name',header='content-disposition'): p.get_content() for p in message.iter_parts()}
        self.assertEqual(parts['name'],'mg.example.test')
    def test_create_credential_keeps_password_private(self):
        output=Path(self.tmp.name)/'smtp.json'; result=self.run_cli('smtp','create','mg.example.test','postmaster@mg.example.test','--output',str(output))
        self.assertEqual(result.returncode,0,result.stderr); data=json.loads(output.read_text()); shown=json.loads(result.stdout)
        self.assertTrue(shown['created']); self.assertEqual(len(data['password']),64)
        self.assertNotIn(data['password'],result.stdout+result.stderr); self.assertNotIn('synthetic-server-secret',result.stdout+result.stderr)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
        method,path,auth,ct,body=Handler.requests[-1]
        msg=BytesParser(policy=default).parsebytes(('Content-Type: '+ct+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
        parts={p.get_param('name',header='content-disposition'):p.get_content() for p in msg.iter_parts()}
        self.assertEqual(parts['password'],data['password']); self.assertEqual(parts['login'],data['login'])
        again=self.run_cli('smtp','create','mg.example.test','postmaster@mg.example.test','--output',str(output)); self.assertNotEqual(again.returncode,0); self.assertEqual(len(Handler.requests),1)
    def test_invalid_values_and_server_errors_do_not_leak(self):
        invalid=self.run_cli('domains','show','evil.example/../other'); self.assertNotEqual(invalid.returncode,0); self.assertEqual(Handler.requests,[])
        error=self.run_cli('domains','show','bad.example'); self.assertNotEqual(error.returncode,0); self.assertNotIn('synthetic-secret-should-not-appear',error.stderr+error.stdout)
        self.assertNotIn('local-test-key',error.stderr+error.stdout)
    def test_test_mode_refuses_real_key(self):
        env={**self.env,'MAILGUN_API_KEY':'not-the-test-key'}; r=self.run_cli('domains','list',env=env)
        self.assertNotEqual(r.returncode,0); self.assertEqual(Handler.requests,[])
    def test_refuses_redirect_without_forwarding_credentials(self):
        result=self.run_cli('domains','show','redirect.example')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(Handler.requests),1)
        self.assertNotIn('local-test-key',result.stdout+result.stderr)
    def test_failed_credential_creation_keeps_recovery_file_without_secrets_in_output(self):
        output=Path(self.tmp.name)/'recovery.json'
        result=self.run_cli('smtp','create','mg.example.test','reject@mg.example.test','--output',str(output))
        self.assertNotEqual(result.returncode,0)
        credential=json.loads(output.read_text())
        self.assertEqual(credential['login'],'reject@mg.example.test')
        self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
        self.assertNotIn(credential['password'],result.stderr+result.stdout)
        self.assertNotIn('synthetic-secret-should-not-appear',result.stderr+result.stdout)
    def test_smtp_list_and_invalid_region(self):
        result=self.run_cli('smtp','list','mg.example.test','--region','eu')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['total_count'],1)
        self.assertEqual(Handler.requests[0][1],'/v3/domains/mg.example.test/credentials?limit=100&skip=0')
        invalid=self.run_cli('domains','list','--region','moon')
        self.assertNotEqual(invalid.returncode,0)
        self.assertEqual(len(Handler.requests),1)
    def test_interactive_login_validates_and_stores_private_key(self):
        master, slave = pty.openpty()
        env = {**self.env}
        env.pop('MAILGUN_API_KEY')
        def attach_terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        process = subprocess.Popen([str(ROOT/'mailgun'), 'login', '--region', 'eu'], cwd=ROOT,
                                   env=env, stdin=slave, stdout=slave, stderr=slave, preexec_fn=attach_terminal)
        os.close(slave)
        output = bytearray(); entered = False; deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try: chunk = os.read(master, 4096)
                    except OSError: break
                    output.extend(chunk)
                    if not entered and b'Mailgun API key:' in output:
                        os.write(master, b'local-test-key\r'); entered = True
                if process.poll() is not None and not ready: break
            process.wait(timeout=2)
        finally:
            if process.poll() is None: process.kill(); process.wait()
            os.close(master)
        self.assertTrue(entered)
        self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
        self.assertNotIn(b'local-test-key', output)
        path=Path(self.tmp.name)/'mailgun-cli'/'credentials.json'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)
        self.assertEqual(json.loads(path.read_text())['region'],'eu')

if __name__ == '__main__': unittest.main()
