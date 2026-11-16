#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""세 도구가 제대로 도는지 가짜 자료로 확인한다. 회사 PC에 옮긴 뒤 먼저 한 번 돌려 본다.

    python tests/run_tests.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import android_log  # noqa: E402
import mask  # noqa: E402
import weekly_report  # noqa: E402

SAMPLES = os.path.join(ROOT, 'samples')


def test_android_log():
    an = android_log.Analyzer(context=5)
    for name in ('sample_logcat.txt', 'sample_traces.txt'):
        with io.open(os.path.join(SAMPLES, name), encoding='utf-8') as f:
            an.feed(name, f)
    an.finalize()
    kinds = [ev['kind'] for ev in an.events]
    assert kinds.count('java') == 2, kinds
    assert kinds.count('anr') == 1, kinds
    assert kinds.count('native') == 1, kinds
    assert kinds.count('anr_trace') == 1, kinds
    assert kinds.count('oom') == 1, kinds
    assert kinds.count('lmk') == 1, kinds
    assert kinds.count('died') == 3, kinds
    groups = an.groups()
    top = groups[0]
    assert top['count'] == 2 and top['sample']['kind'] == 'java', top
    assert 'NullPointerException' in top['sample']['title']
    assert any('load cart' in line for line in top['sample']['context'])
    native = next(ev for ev in an.events if ev['kind'] == 'native')
    assert native['proc'] == 'com.example.camera' and native['pid'] == 5000, native
    assert 'SIGSEGV' in native['title'] and 'libimgproc.so' in native['title'], native['title']
    anr = next(ev for ev in an.events if ev['kind'] == 'anr')
    assert anr['proc'] == 'com.example.shop' and anr['pid'] == 4500, anr
    assert any('SyncWorker' in line for line in anr['context']), anr['context']
    trace = next(ev for ev in an.events if ev['kind'] == 'anr_trace')
    assert 'Blocked' in trace['title'] and '14' in trace['title'], trace['title']
    assert any('SyncManager.pull' in line for line in trace['detail'])
    oom = next(ev for ev in an.events if ev['kind'] == 'oom')
    assert oom['proc'] == 'com.example.gallery', oom
    text = android_log.render(an)
    assert '자바 크래시 2건 (1종류)' in text, text

    an2 = android_log.Analyzer()
    with io.open(os.path.join(SAMPLES, 'sample_logcat.txt'), encoding='utf-8') as f:
        an2.feed('x', f)
    an2.finalize(pkg='com.example.camera')
    assert set(ev['proc'] for ev in an2.events) == {'com.example.camera'}

    brief = ['E/AndroidRuntime( 777): FATAL EXCEPTION: main',
             'E/AndroidRuntime( 777): Process: com.example.old, PID: 777',
             'E/AndroidRuntime( 777): java.lang.IllegalStateException: boom',
             'E/AndroidRuntime( 777): \tat com.example.old.Main.run(Main.java:10)']
    an3 = android_log.Analyzer()
    an3.feed('brief', brief)
    an3.finalize()
    assert an3.events[0]['title'] == 'java.lang.IllegalStateException: boom', an3.events


def test_mask():
    rules = {'builtin': ['email', 'url_host', 'mac', 'ip'],
             'words': {'NAME': ['홍길동']},
             'patterns': {'PKG': [r'com\.mycompany(?:\.\w+)+'], 'ISSUE': [r'\b[A-Z][A-Z0-9]+-\d+\b']}}
    src = ('홍길동이 APP-101 을 고쳤다. com.mycompany.shop.cart.CartLoader 에서 죽음.\n'
           '서버 10.20.30.40, 로컬 127.0.0.1, https://gerrit.mycompany.com/c/1 , a.b@mycompany.com\n'
           'com.mycompany.shop.cart.CartLoader 다시 나옴, APP-101 도 다시.')
    mapping = {}
    out, used = mask.do_mask(src, rules, mapping)
    for word in ('홍길동', 'APP-101', 'mycompany', '10.20.30.40'):
        assert word not in out, (word, out)
    assert '127.0.0.1' in out
    assert out.count('PKG_001') == 2 and out.count('ISSUE_001') == 2, out
    back, n = mask.do_unmask(out, mapping)
    assert back == src, back
    out2, _ = mask.do_mask('APP-101 과 APP-202', rules, mapping)
    assert out2 == 'ISSUE_001 과 ISSUE_002', out2


class Fake(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Fake.seen.append((self.path, self.headers.get('Authorization')))
        if self.path.startswith('/gerrit/a/changes/'):
            if 'reviewer' in self.path:
                rows = [{'_number': 4533, 'subject': 'APP-120 Review me', 'status': 'MERGED', 'project': 'p', 'branch': 'main'}]
            else:
                rows = [{'_number': 4521, 'subject': 'APP-101 Fix NPE', 'status': 'MERGED', 'project': 'p', 'branch': 'main'},
                        {'_number': 4550, 'subject': 'Tidy build files', 'status': 'NEW', 'project': 'p', 'branch': 'main'}]
            body = ")]}'\n" + json.dumps(rows)
        elif self.path.startswith('/jira/rest/api/2/search'):
            body = json.dumps({'issues': [
                {'key': 'APP-101', 'fields': {'summary': '빈 장바구니 크래시', 'issuetype': {'name': 'Bug'},
                                              'status': {'name': 'Resolved', 'statusCategory': {'key': 'done'}}}},
                {'key': 'APP-117', 'fields': {'summary': '동기화 ANR', 'issuetype': {'name': 'Bug'},
                                              'status': {'name': 'In Progress', 'statusCategory': {'key': 'indeterminate'}}}}]})
        else:
            self.send_error(404)
            return
        data = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_weekly():
    server = HTTPServer(('127.0.0.1', 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % server.server_port
    os.environ['WT_TEST_PW'] = 'secret'
    cfg = {'days': 7, 'no_proxy': True,
           'gerrit': {'url': base + '/gerrit', 'user': 'me', 'password_env': 'WT_TEST_PW'},
           'jira': {'url': base + '/jira', 'password_env': 'WT_TEST_PW', 'auth': 'bearer'}}
    tmp = tempfile.mkdtemp()
    cfg_path, out_path = os.path.join(tmp, 'config.json'), os.path.join(tmp, 'weekly.md')
    with io.open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    with contextlib.redirect_stderr(io.StringIO()):
        weekly_report.main(['-c', cfg_path, '-o', out_path, '--prompt'])
    server.shutdown()
    with io.open(out_path, encoding='utf-8') as f:
        text = f.read()
    done = text.split('## 완료')[1].split('## 진행 중')[0]
    doing = text.split('## 진행 중')[1].split('## 이슈 번호 없는 작업')[0]
    assert 'APP-101' in done and 'Gerrit 4521 MERGED' in done, text
    assert 'APP-117' in doing, text
    assert 'Gerrit 4550 NEW: Tidy build files' in text.split('## 이슈 번호 없는 작업')[1], text
    assert 'Gerrit 4533' in text.split('## 리뷰한 변경')[1], text
    assert text.startswith('아래 자료로'), text[:40]
    auths = dict((p.split('?')[0], a) for p, a in Fake.seen)
    assert auths['/gerrit/a/changes/'].startswith('Basic '), auths
    assert auths['/jira/rest/api/2/search'] == 'Bearer secret', auths

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        weekly_report.main(['--demo'])
    assert 'APP-125' in buf.getvalue()


if __name__ == '__main__':
    for fn in (test_android_log, test_mask, test_weekly):
        fn()
        print('통과: ' + fn.__name__)
    print('전부 통과')
