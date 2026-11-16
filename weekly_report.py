#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주간 보고 수집기.

지난 며칠 동안의 내 git 커밋, Gerrit 변경, Jira 이슈를 모아
이슈 번호별로 묶은 주간 보고 초안(마크다운)을 만든다.
파이썬 표준 라이브러리만 쓴다(3.6 이상). 설정 파일에 적은 사내 주소 말고는 접속하지 않는다.

    python weekly_report.py --demo                 # 가짜 자료로 모양 보기
    python weekly_report.py -c config.json -o weekly.md
    python weekly_report.py -c config.json --prompt   # 사내 AI에 붙여 넣을 주문서 포함
    python weekly_report.py -c config.json --only git,gerrit

비밀번호는 설정 파일에 적지 않는다. 환경 변수(password_env)에서 읽고, 없으면 물어본다.
"""
import argparse
import base64
import collections
import datetime
import getpass
import io
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

KEY_RE = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')

PROMPT = """아래 자료로 주간 보고를 써 주세요.
- 칸은 네 개: 완료 / 진행 중 / 다음 주 계획 / 이슈·도움이 필요한 점
- 한 줄에 한 가지만, 이슈 번호는 그대로 둡니다.
- 커밋·리뷰 제목을 그대로 옮기지 말고 무슨 일을 했는지 한 문장으로 풀어 씁니다.
- 자료에 없는 내용은 지어내지 말고 비워 둡니다.

--- 자료 ---
"""


def secret(cfg, label):
    env = cfg.get('password_env')
    if env and os.environ.get(env):
        return os.environ[env]
    if sys.stdin.isatty():
        return getpass.getpass('%s 비밀번호(또는 토큰): ' % label)
    raise RuntimeError('%s 비밀번호가 없습니다. 환경 변수 %s 를 넣어 주세요.' % (label, env or '(password_env 미설정)'))


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


def fetch_git(cfg, days):
    out = []
    for repo in cfg.get('git_repos', []):
        author = cfg.get('author')
        if not author:
            p = subprocess.run(['git', '-C', repo, 'config', 'user.email'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            author = p.stdout.decode('utf-8', 'replace').strip()
        cmd = ['git', '-C', repo, 'log', '--all', '--no-merges', '--since=%d days ago' % days,
               '--date=short', '--pretty=format:%h%x1f%ad%x1f%s%x1f%b%x1e']
        if author:
            cmd.append('--author=' + author)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise RuntimeError('%s: %s' % (repo, p.stderr.decode('utf-8', 'replace').strip()))
        name = os.path.basename(os.path.normpath(repo))
        for rec in p.stdout.decode('utf-8', 'replace').split('\x1e'):
            parts = rec.strip('\r\n').split('\x1f')
            if len(parts) == 4:
                out.append({'repo': name, 'hash': parts[0], 'date': parts[1], 'subject': parts[2], 'body': parts[3]})
    return out


def fetch_gerrit(cfg, days, net):
    g = cfg['gerrit']
    base = g['url'].rstrip('/')
    prefix = g.get('api_prefix')
    if prefix is None:
        prefix = '/a' if (g.get('user') or g.get('auth') == 'bearer') else ''

    def query(q):
        url = '%s%s/changes/?q=%s&n=200' % (base, prefix, urllib.parse.quote(q))
        text = http_get(url, g, 'Gerrit', net)
        if text.startswith(")]}'"):
            text = text.split('\n', 1)[1]
        rows = []
        for c in json.loads(text):
            rows.append({'number': c.get('_number'), 'subject': c.get('subject', ''), 'status': c.get('status', ''),
                         'project': c.get('project', ''), 'branch': c.get('branch', ''),
                         'url': '%s/c/%s/+/%s' % (base, c.get('project', ''), c.get('_number'))})
        return rows

    mine = query(g.get('query_mine', 'owner:self -age:{days}d').format(days=days))
    reviewed = query(g.get('query_reviewed', 'reviewer:self -owner:self -age:{days}d').format(days=days))
    return mine, reviewed


def fetch_jira(cfg, days, net):
    j = cfg['jira']
    base = j['url'].rstrip('/')
    jql = j.get('jql', 'assignee = currentUser() AND updated >= -{days}d ORDER BY updated DESC').format(days=days)
    url = '%s%s?jql=%s&fields=summary,status,issuetype&maxResults=200' % (
        base, j.get('api_path', '/rest/api/2/search'), urllib.parse.quote(jql))
    data = json.loads(http_get(url, j, 'Jira', net))
    out = []
    for it in data.get('issues', []):
        f = it.get('fields', {})
        st = f.get('status') or {}
        out.append({'key': it['key'], 'summary': f.get('summary', ''), 'status': st.get('name', ''),
                    'category': (st.get('statusCategory') or {}).get('key', ''),
                    'type': (f.get('issuetype') or {}).get('name', ''), 'url': '%s/browse/%s' % (base, it['key'])})
    return out


def demo_data():
    commits = [
        {'repo': 'shop-app', 'hash': 'a1b2c3d', 'date': '2026-11-10', 'subject': 'APP-101 Fix NPE in CartLoader when cart is empty'},
        {'repo': 'shop-app', 'hash': 'b2c3d4e', 'date': '2026-11-12', 'subject': 'APP-117 Add retry to sync worker (WIP)'},
        {'repo': 'shop-app', 'hash': 'c3d4e5f', 'date': '2026-11-13', 'subject': 'Clean up unused resources'},
    ]
    mine = [
        {'number': 4521, 'subject': 'APP-101 Fix NPE in CartLoader when cart is empty', 'status': 'MERGED',
         'project': 'platform/shop-app', 'branch': 'main', 'url': 'https://gerrit.example.com/c/platform/shop-app/+/4521'},
        {'number': 4540, 'subject': 'APP-117 Add retry to sync worker', 'status': 'NEW',
         'project': 'platform/shop-app', 'branch': 'main', 'url': 'https://gerrit.example.com/c/platform/shop-app/+/4540'},
    ]
    reviewed = [
        {'number': 4533, 'subject': 'APP-120 Migrate settings screen to Compose', 'status': 'MERGED',
         'project': 'platform/shop-app', 'branch': 'main', 'url': 'https://gerrit.example.com/c/platform/shop-app/+/4533'},
    ]
    issues = [
        {'key': 'APP-101', 'summary': '빈 장바구니에서 앱이 죽는 문제', 'status': 'Resolved', 'category': 'done', 'type': 'Bug',
         'url': 'https://jira.example.com/browse/APP-101'},
        {'key': 'APP-117', 'summary': '동기화 중 ANR', 'status': 'In Progress', 'category': 'indeterminate', 'type': 'Bug',
         'url': 'https://jira.example.com/browse/APP-117'},
        {'key': 'APP-125', 'summary': '로그 수집 범위 검토', 'status': 'Open', 'category': 'new', 'type': 'Task',
         'url': 'https://jira.example.com/browse/APP-125'},
    ]
    return commits, mine, reviewed, issues


SECTIONS = {'done': '완료', 'doing': '진행 중', 'loose': '이슈 번호 없는 작업', 'reviewed': '리뷰한 변경',
            'extra': ['다음 주 계획', '이슈·도움이 필요한 점']}


def build(commits, mine, reviewed, issues, days, errors, today=None, opts=None):
    opts = opts or {}
    names = dict(SECTIONS, **(opts.get('sections') or {}))
    key_re = re.compile(opts['issue_key_pattern']) if opts.get('issue_key_pattern') else KEY_RE
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=days)
    items = collections.OrderedDict()
    for it in issues:
        items[it['key']] = {'issue': it, 'changes': [], 'commits': []}
    loose_changes, loose_commits = [], []
    change_subjects = set(c['subject'] for c in mine)

    for c in mine:
        m = key_re.search(c['subject'])
        if m:
            items.setdefault(m.group(0), {'issue': None, 'changes': [], 'commits': []})['changes'].append(c)
        else:
            loose_changes.append(c)
    for c in commits:
        if c['subject'] in change_subjects:
            continue
        m = key_re.search(c['subject']) or key_re.search(c.get('body', ''))
        if m:
            items.setdefault(m.group(0), {'issue': None, 'changes': [], 'commits': []})['commits'].append(c)
        else:
            loose_commits.append(c)

    def is_done(v):
        if v['issue']:
            return v['issue']['category'] == 'done'
        return bool(v['changes']) and all(c['status'] == 'MERGED' for c in v['changes']) and not v['commits']

    def change_line(c):
        return 'Gerrit %s %s: %s (%s, %s)' % (c['number'], c['status'], c['subject'], c['project'], c['branch'])

    def section(title, rows):
        out = ['', '## ' + title, '']
        if not rows:
            out.append('- (없음)')
        for key, v in rows:
            if v['issue']:
                out.append('- [%s] %s — %s' % (key, v['issue']['summary'], v['issue']['status']))
            else:
                out.append('- [%s] (Jira 목록에 없음)' % key)
            for c in v['changes']:
                out.append('  - ' + change_line(c))
            for c in v['commits']:
                out.append('  - 커밋 %s (%s, %s): %s' % (c['hash'], c['repo'], c['date'], c['subject']))
        return out

    w = ['# %s (%s ~ %s)' % (opts.get('title', '주간 보고'), start.strftime('%m-%d'), today.strftime('%m-%d'))]
    for e in errors:
        w += ['', '> ⚠ ' + e]
    w += section(names['done'], [(k, v) for k, v in items.items() if is_done(v)])
    w += section(names['doing'], [(k, v) for k, v in items.items() if not is_done(v)])
    if loose_changes or loose_commits:
        w += ['', '## ' + names['loose'], '']
        w += ['- ' + change_line(c) for c in loose_changes]
        w += ['- 커밋 %s (%s, %s): %s' % (c['hash'], c['repo'], c['date'], c['subject']) for c in loose_commits]
    if reviewed:
        w += ['', '## ' + names['reviewed'], '']
        w += ['- ' + change_line(c) for c in reviewed]
    for title in names['extra']:
        w += ['', '## ' + title, '', '- ']
    return '\n'.join(w) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='git·Gerrit·Jira에서 내 한 주를 모아 주간 보고 초안을 만듭니다.')
    ap.add_argument('-c', '--config', default='config.json', help='설정 파일 (기본 config.json)')
    ap.add_argument('-o', '--out', help='결과를 저장할 파일(없으면 화면에 출력)')
    ap.add_argument('--days', type=int, help='며칠 치를 볼지 (기본은 설정 파일 값 또는 7)')
    ap.add_argument('--only', help='가져올 곳만 고르기: git,gerrit,jira')
    ap.add_argument('--prompt', action='store_true', help='사내 AI에 붙여 넣을 주문서를 맨 위에 붙인다')
    ap.add_argument('--demo', action='store_true', help='가짜 자료로 모양만 본다(접속 없음)')
    args = ap.parse_args(argv)

    errors = []
    cfg = {}
    if args.demo:
        days = args.days or 7
        commits, mine, reviewed, issues = demo_data()
    else:
        with io.open(args.config, encoding='utf-8-sig') as f:
            cfg = json.load(f)
        days = args.days or cfg.get('days', 7)
        only = set((args.only or 'git,gerrit,jira').split(','))
        commits, mine, reviewed, issues = [], [], [], []

        def attempt(name, fn):
            try:
                return fn()
            except urllib.error.HTTPError as e:
                errors.append('%s 가져오기 실패: HTTP %s %s' % (name, e.code, e.reason))
            except Exception as e:  # 한 곳이 안 돼도 나머지는 계속
                errors.append('%s 가져오기 실패: %s' % (name, e))
            return None

        if 'git' in only and cfg.get('git_repos'):
            commits = attempt('git', lambda: fetch_git(cfg, days)) or []
        if 'gerrit' in only and (cfg.get('gerrit') or {}).get('url'):
            got = attempt('Gerrit', lambda: fetch_gerrit(cfg, days, cfg))
            if got:
                mine, reviewed = got
        if 'jira' in only and (cfg.get('jira') or {}).get('url'):
            issues = attempt('Jira', lambda: fetch_jira(cfg, days, cfg)) or []
        for e in errors:
            sys.stderr.write('⚠ %s\n' % e)

    text = build(commits, mine, reviewed, issues, days, errors, opts=cfg.get('report'))
    if args.prompt:
        prompt = PROMPT
        if cfg.get('prompt_file'):
            with io.open(cfg['prompt_file'], encoding='utf-8-sig') as f:
                prompt = f.read().rstrip('\n') + '\n'
        text = prompt + '\n' + text
    if args.out:
        with io.open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
        sys.stderr.write('저장: %s\n' % args.out)
    else:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
