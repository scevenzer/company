# -*- coding: utf-8 -*-
"""wk 도구들이 같이 쓰는 것: 설정 파일(wk.json) 읽기와 Gerrit·Jira 접속.

설정 파일에 적은 주소 말고는 접속하지 않는다. 비밀번호는 환경 변수나 실행 중 입력으로만 받는다.
"""
import base64
import getpass
import io
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

CONFIG_NAME = 'wk.json'
HERE = os.path.dirname(os.path.abspath(__file__))
_secrets = {}


def load_config(path=None, required=False):
    """wk.json 을 읽는다. 찾는 순서: 지정한 경로 → 지금 폴더 → 도구 폴더."""
    candidates = [path] if path else [os.path.join(os.getcwd(), CONFIG_NAME), os.path.join(HERE, CONFIG_NAME)]
    for p in candidates:
        if os.path.exists(p):
            with io.open(p, encoding='utf-8-sig') as f:
                cfg = json.load(f)
            cfg['_dir'] = os.path.dirname(os.path.abspath(p))
            return cfg
    if required or path:
        raise SystemExit('설정 파일이 없습니다: %s\n`wk init` 으로 wk.json 을 만든 뒤 값을 채워 주세요.' % (path or CONFIG_NAME))
    return {'_dir': os.getcwd()}


def resolve(cfg, rel):
    """설정 파일에 적은 상대 경로는 설정 파일이 있는 폴더 기준으로 본다."""
    return rel if os.path.isabs(rel) else os.path.join(cfg.get('_dir') or os.getcwd(), rel)


def write_out(text, out=None):
    if out:
        with io.open(out, 'w', encoding='utf-8') as f:
            f.write(text)
        sys.stderr.write('저장: %s\n' % out)
    else:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)


def secret(cfg, label):
    env = cfg.get('password_env')
    if env and os.environ.get(env):
        return os.environ[env]
    if label not in _secrets:  # 한 번 실행에 한 번만 묻는다
        if not sys.stdin.isatty():
            raise RuntimeError('%s 비밀번호가 없습니다. 환경 변수 %s 를 넣어 주세요.' % (label, env or '(password_env 미설정)'))
        _secrets[label] = getpass.getpass('%s 비밀번호(또는 토큰): ' % label)
    return _secrets[label]


def expand(value):
    """${이름} 을 환경 변수 값으로 바꾼다."""
    return re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), ''), value)


def http_get(url, cfg, label, net):
    handlers = []
    sslcfg = net.get('ssl', {})
    ctx = ssl.create_default_context(cafile=sslcfg.get('ca_file') or None)
    if sslcfg.get('verify') is False:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    if net.get('no_proxy'):
        handlers.append(urllib.request.ProxyHandler({}))
    headers = {'Accept': 'application/json'}
    for k, v in (cfg.get('headers') or {}).items():  # 쿠키·SSO 등 다른 인증은 여기로
        headers[k] = expand(v)
    auth = cfg.get('auth', 'basic')
    if auth == 'none':
        pass
    elif auth == 'bearer':
        headers['Authorization'] = 'Bearer ' + secret(cfg, label)
    elif cfg.get('user'):
        pw = secret(cfg, label)
        if auth == 'digest':
            mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            mgr.add_password(None, url, cfg['user'], pw)
            handlers.append(urllib.request.HTTPDigestAuthHandler(mgr))
        else:
            token = base64.b64encode(('%s:%s' % (cfg['user'], pw)).encode('utf-8')).decode('ascii')
            headers['Authorization'] = 'Basic ' + token
    opener = urllib.request.build_opener(*handlers)
    with opener.open(urllib.request.Request(url, headers=headers), timeout=net.get('timeout', 30)) as r:
        return r.read().decode('utf-8', 'replace')


def gerrit_query(cfg, query, options=()):
    """Gerrit 변경 검색. 받은 그대로의 목록에 화면 주소(url)만 붙여 돌려준다."""
    g = cfg['gerrit']
    base = g['url'].rstrip('/')
    prefix = g.get('api_prefix')
    if prefix is None:
        prefix = '/a' if (g.get('user') or g.get('auth') == 'bearer') else ''
    url = '%s%s/changes/?q=%s&n=200%s' % (base, prefix, urllib.parse.quote(query), ''.join('&o=' + o for o in options))
    text = http_get(url, g, 'Gerrit', cfg)
    if text.startswith(")]}'"):
        text = text.split('\n', 1)[1]
    rows = json.loads(text)
    for c in rows:
        c['url'] = '%s/c/%s/+/%s' % (base, c.get('project', ''), c.get('_number'))
    return rows


def jira_search(cfg, jql, fields):
    """Jira 이슈 검색. 받은 그대로의 목록에 화면 주소(url)만 붙여 돌려준다."""
    j = cfg['jira']
    base = j['url'].rstrip('/')
    url = '%s%s?jql=%s&fields=%s&maxResults=200' % (
        base, j.get('api_path', '/rest/api/2/search'), urllib.parse.quote(jql), fields)
    rows = json.loads(http_get(url, j, 'Jira', cfg)).get('issues', [])
    for it in rows:
        it['url'] = '%s/browse/%s' % (base, it.get('key'))
    return rows
