#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주간 보고 — 지난 며칠의 내 git 커밋, Gerrit 변경, Jira 이슈, 할 일을 모아 초안을 만든다.

이슈 번호별로 묶어 완료와 진행 중으로 나눈다. 결과는 마크다운 글이다.

    wk weekly --demo               가짜 자료로 모양 보기
    wk weekly -o weekly.md
    wk weekly --prompt             사내 AI에 붙여 넣을 주문서 포함
    wk weekly --only git,gerrit
    wk weekly --json               다른 프로그램이 읽을 자료로
"""
import argparse
import collections
import datetime
import io
import json
import os
import re
import subprocess
import sys
import urllib.error

import todo
import wkcore

KEY_RE = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')

PROMPT = """아래 자료로 주간 보고를 써 주세요.
- 칸은 네 개: 완료 / 진행 중 / 다음 주 계획 / 이슈·도움이 필요한 점
- 한 줄에 한 가지만, 이슈 번호는 그대로 둡니다.
- 커밋·리뷰 제목을 그대로 옮기지 말고 무슨 일을 했는지 한 문장으로 풀어 씁니다.
- 자료에 없는 내용은 지어내지 말고 비워 둡니다.

--- 자료 ---
"""

SECTIONS = {'done': '완료', 'doing': '진행 중', 'loose': '이슈 번호 없는 작업', 'reviewed': '리뷰한 변경',
            'extra': ['다음 주 계획', '이슈·도움이 필요한 점']}


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


def fetch_gerrit(cfg, days):
    g = cfg['gerrit']

    def query(q):
        return [{'number': c.get('_number'), 'subject': c.get('subject', ''), 'status': c.get('status', ''),
                 'project': c.get('project', ''), 'branch': c.get('branch', ''), 'url': c['url']}
                for c in wkcore.gerrit_query(cfg, q.format(days=days))]

    return (query(g.get('query_mine', 'owner:self -age:{days}d')),
            query(g.get('query_reviewed', 'reviewer:self -owner:self -age:{days}d')))


def fetch_jira(cfg, days):
    jql = cfg['jira'].get('jql', 'assignee = currentUser() AND updated >= -{days}d ORDER BY updated DESC')
    out = []
    for it in wkcore.jira_search(cfg, jql.format(days=days), 'summary,status,issuetype'):
        f = it.get('fields', {})
        st = f.get('status') or {}
        out.append({'key': it['key'], 'summary': f.get('summary', ''), 'status': st.get('name', ''),
                    'category': (st.get('statusCategory') or {}).get('key', ''),
                    'type': (f.get('issuetype') or {}).get('name', ''), 'url': it['url']})
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


def collect(commits, mine, reviewed, issues, days, errors, today=None, opts=None, todo_open=(), todo_done=()):
    """모은 자료를 이슈 번호별로 묶는다. 글로 바꾸기 전의 자료다."""
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

    def slim(c):
        return dict((k, c[k]) for k in ('repo', 'hash', 'date', 'subject'))

    rows = []
    for key, v in items.items():
        issue = v['issue'] or {}
        rows.append({'key': key, 'summary': issue.get('summary', ''), 'status': issue.get('status', ''),
                     'type': issue.get('type', ''), 'url': issue.get('url', ''), 'in_jira': bool(v['issue']),
                     'done': is_done(v), 'changes': v['changes'], 'commits': [slim(c) for c in v['commits']]})
    return {'title': opts.get('title', '주간 보고'), 'start': start.isoformat(), 'end': today.isoformat(),
            'days': days, 'errors': list(errors), 'sections': names, 'items': rows,
            'loose_changes': loose_changes, 'loose_commits': [slim(c) for c in loose_commits],
            'reviewed': reviewed, 'todo_open': list(todo_open), 'todo_done': list(todo_done)}


def render_md(data):
    names = data['sections']

    def change_line(c):
        return 'Gerrit %s %s: %s (%s, %s)' % (c['number'], c['status'], c['subject'], c['project'], c['branch'])

    def commit_line(c):
        return '커밋 %s (%s, %s): %s' % (c['hash'], c['repo'], c['date'], c['subject'])

    def issue_lines(rows):
        out = []
        for it in rows:
            if it['in_jira']:
                out.append('- [%s] %s — %s' % (it['key'], it['summary'], it['status']))
            else:
                out.append('- [%s] (Jira 목록에 없음)' % it['key'])
            out += ['  - ' + change_line(c) for c in it['changes']]
            out += ['  - ' + commit_line(c) for c in it['commits']]
        return out

    def section(title, lines, empty='- (없음)'):
        return ['', '## ' + title, ''] + (lines or [empty])

    w = ['# %s (%s ~ %s)' % (data['title'], data['start'][5:], data['end'][5:])]
    for e in data['errors']:
        w += ['', '> ⚠ ' + e]
    w += section(names['done'], issue_lines([it for it in data['items'] if it['done']])
                 + ['- ' + t for t in data.get('todo_done', [])])
    w += section(names['doing'], issue_lines([it for it in data['items'] if not it['done']]))
    if data['loose_changes'] or data['loose_commits']:
        w += section(names['loose'], ['- ' + change_line(c) for c in data['loose_changes']]
                     + ['- ' + commit_line(c) for c in data['loose_commits']])
    if data['reviewed']:
        w += section(names['reviewed'], ['- ' + change_line(c) for c in data['reviewed']])
    for i, title in enumerate(names['extra']):
        w += section(title, ['- ' + t for t in data.get('todo_open', [])] if i == 0 else [], empty='- ')
    return '\n'.join(w) + '\n'


def build(commits, mine, reviewed, issues, days, errors, today=None, opts=None, todo_open=(), todo_done=()):
    return render_md(collect(commits, mine, reviewed, issues, days, errors, today=today, opts=opts,
                             todo_open=todo_open, todo_done=todo_done))


def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(prog=prog, description='git·Gerrit·Jira·할 일에서 내 한 주를 모아 주간 보고 초안을 만듭니다.')
    ap.add_argument('-c', '--config', help='설정 파일 (기본 wk.json)')
    ap.add_argument('-o', '--out', help='결과를 저장할 파일(없으면 화면에 출력)')
    ap.add_argument('--days', type=int, help='며칠 치를 볼지 (기본은 설정 파일 값 또는 7)')
    ap.add_argument('--only', default='git,gerrit,jira,todo', help='가져올 곳만 고르기: git,gerrit,jira,todo')
    ap.add_argument('--prompt', action='store_true', help='사내 AI에 붙여 넣을 주문서를 맨 위에 붙인다')
    ap.add_argument('--json', action='store_true', help='글 대신 자료(JSON)로 출력한다')
    ap.add_argument('--demo', action='store_true', help='가짜 자료로 모양만 본다(접속 없음)')
    args = ap.parse_args(argv)

    errors = []
    cfg = {}
    todo_open, todo_done = [], []
    if args.demo:
        days = args.days or 7
        commits, mine, reviewed, issues = demo_data()
    else:
        cfg = wkcore.load_config(args.config, required=True)
        days = args.days or cfg.get('days', 7)
        only = set(args.only.split(','))
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
            got = attempt('Gerrit', lambda: fetch_gerrit(cfg, days))
            if got:
                mine, reviewed = got
        if 'jira' in only and (cfg.get('jira') or {}).get('url'):
            issues = attempt('Jira', lambda: fetch_jira(cfg, days)) or []
        if 'todo' in only:
            start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
            todo_open, todo_done = todo.open_items(cfg), todo.done_since(cfg, start)
        for e in errors:
            sys.stderr.write('⚠ %s\n' % e)

    data = collect(commits, mine, reviewed, issues, days, errors, opts=cfg.get('report'),
                   todo_open=todo_open, todo_done=todo_done)
    if args.json:
        text = json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    else:
        text = render_md(data)
        if args.prompt:
            prompt = PROMPT
            if cfg.get('prompt_file'):
                with io.open(wkcore.resolve(cfg, cfg['prompt_file']), encoding='utf-8-sig') as f:
                    prompt = f.read().rstrip('\n') + '\n'
            text = prompt + '\n' + text
    wkcore.write_out(text, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
