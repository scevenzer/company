#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""오늘 볼 것 — Gerrit·Jira·할 일에서 지금 나를 기다리는 것만 뽑는다.

    wk status
    wk status --only gerrit
    wk status --demo            접속 없이 모양 보기

무엇을 뽑을지는 wk.json 의 status 칸에서 바꾼다(Gerrit 검색식, Jira JQL).
"""
import argparse
import datetime
import sys
import urllib.error

import todo
import wkcore

GERRIT_OPTIONS = ['LABELS', 'DETAILED_ACCOUNTS', 'SUBMITTABLE']
GERRIT_SECTIONS = [
    # optional: 이 검색식을 모르는 옛 Gerrit 에서는 조용히 건너뛴다
    {'title': '나를 기다리는 변경', 'query': 'attention:self status:open', 'optional': True},
    {'title': '리뷰 요청받은 변경', 'query': 'status:open reviewer:self -owner:self'},
    {'title': '내 변경', 'query': 'status:open owner:self', 'mine': True},
]
JIRA_SECTIONS = [
    {'title': '내 이슈', 'jql': 'assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC, updated DESC'},
]
JIRA_FIELDS = 'summary,status,priority,updated,duedate'


def change_flags(c):
    """내 변경에서 손봐야 할 것을 짧은 말로 뽑는다."""
    flags = []
    if c.get('work_in_progress'):
        flags.append('WIP')
    for name, v in sorted((c.get('labels') or {}).items()):
        if 'rejected' in v:
            flags.append(name + ' 거부')
        elif 'disliked' in v:
            flags.append(name + ' -1')
    n = c.get('unresolved_comment_count') or 0
    if n:
        flags.append('댓글 %d개 미해결' % n)
    if c.get('mergeable') is False:
        flags.append('충돌')
    if c.get('submittable'):
        flags.append('머지 가능')
    return flags


def change_lines(c, mine):
    head = '- %s %s' % (c.get('_number'), c.get('subject', ''))
    if mine:
        flags = change_flags(c)
        if flags:
            head += ' — ' + ' · '.join(flags)
    else:
        owner = c.get('owner') or {}
        who = owner.get('name') or owner.get('username')
        if who:
            head += ' — 작성자 ' + who
    return [head, '  %s · %s · %s' % (c.get('project', ''), c.get('branch', ''), c.get('url', ''))]


def issue_lines(it, today):
    f = it.get('fields') or {}
    tags = [(f.get('status') or {}).get('name'), (f.get('priority') or {}).get('name')]
    head = '- %s [%s] %s' % (it.get('key'), ' · '.join(t for t in tags if t), f.get('summary', ''))
    notes = []
    due = f.get('duedate')
    if due:
        left = (datetime.date(*map(int, due[:10].split('-'))) - today).days
        if left < 0:
            notes.append('기한 지남 ' + due[5:10])
        elif left <= 3:
            notes.append('기한 ' + due[5:10])
    updated = (f.get('updated') or '')[:10]
    if updated and (today - datetime.date(*map(int, updated.split('-')))).days <= 1:
        notes.append('최근 바뀜')
    if notes:
        head += ' — ' + ' · '.join(notes)
    return [head, '  ' + it.get('url', '')]


def section(title, rows, count=None, error=None):
    out = ['', '## %s (%d)' % (title, len(rows) if count is None else count)]
    if error:
        out.append('⚠ 가져오기 실패: ' + error)
    out += rows or ([] if error else ['- 없음'])
    return out


def describe(e):
    if isinstance(e, urllib.error.HTTPError):
        return 'HTTP %s %s' % (e.code, e.reason)
    return str(e)


def build(cfg, only, gerrit_fetch, jira_fetch, todo_items, now=None):
    now = now or datetime.datetime.now()
    st = cfg.get('status') or {}
    out = ['# 오늘 볼 것 (%s)' % now.strftime('%m-%d %H:%M')]

    if 'gerrit' in only and (cfg.get('gerrit') or {}).get('url'):
        seen = set()
        for sec in st.get('gerrit') or GERRIT_SECTIONS:
            try:
                rows = gerrit_fetch(sec['query'])
            except Exception as e:  # 한 칸이 안 돼도 나머지는 계속
                if not sec.get('optional'):
                    out += section(sec['title'], [], 0, describe(e))
                continue
            lines = []
            for c in rows:
                if c.get('_number') in seen:
                    continue
                seen.add(c.get('_number'))
                lines += change_lines(c, sec.get('mine'))
            if lines or not sec.get('optional'):
                out += section(sec['title'], lines, len(lines) // 2)

    if 'jira' in only and (cfg.get('jira') or {}).get('url'):
        for sec in st.get('jira') or JIRA_SECTIONS:
            try:
                lines = []
                for it in jira_fetch(sec['jql']):
                    lines += issue_lines(it, now.date())
                out += section(sec['title'], lines, len(lines) // 2)
            except Exception as e:
                out += section(sec['title'], [], 0, describe(e))

    if 'todo' in only and todo_items is not None:
        out += section('할 일', ['- ' + t for t in todo_items])
    return '\n'.join(out) + '\n'


def demo():
    cfg = {'gerrit': {'url': 'https://gerrit.example.com'}, 'jira': {'url': 'https://jira.example.com'}}
    base = 'https://gerrit.example.com/c/platform/shop-app/+/'
    gerrit = {
        'attention:self status:open': [
            {'_number': 4533, 'subject': 'APP-120 Migrate settings screen to Compose', 'project': 'platform/shop-app',
             'branch': 'main', 'owner': {'name': 'Kim'}, 'url': base + '4533'}],
        'status:open reviewer:self -owner:self': [
            {'_number': 4533, 'subject': 'APP-120 Migrate settings screen to Compose', 'project': 'platform/shop-app',
             'branch': 'main', 'owner': {'name': 'Kim'}, 'url': base + '4533'},
            {'_number': 4561, 'subject': 'APP-131 Reduce cold start time', 'project': 'platform/shop-app',
             'branch': 'main', 'owner': {'name': 'Lee'}, 'url': base + '4561'}],
        'status:open owner:self': [
            {'_number': 4540, 'subject': 'APP-117 Add retry to sync worker', 'project': 'platform/shop-app', 'branch': 'main',
             'labels': {'Verified': {'rejected': {}}, 'Code-Review': {}}, 'unresolved_comment_count': 2, 'url': base + '4540'},
            {'_number': 4555, 'subject': 'APP-125 Narrow log collection scope', 'project': 'platform/shop-app', 'branch': 'main',
             'labels': {'Verified': {'approved': {}}, 'Code-Review': {'approved': {}}}, 'submittable': True, 'url': base + '4555'}],
    }
    today = datetime.date.today()
    jira = [
        {'key': 'APP-117', 'url': 'https://jira.example.com/browse/APP-117', 'fields': {
            'summary': '동기화 중 ANR', 'status': {'name': 'In Progress'}, 'priority': {'name': 'High'},
            'updated': today.isoformat() + 'T09:00:00.000+0900', 'duedate': (today + datetime.timedelta(days=2)).isoformat()}},
        {'key': 'APP-125', 'url': 'https://jira.example.com/browse/APP-125', 'fields': {
            'summary': '로그 수집 범위 검토', 'status': {'name': 'Open'}, 'priority': {'name': 'Medium'},
            'updated': '2026-01-05T09:00:00.000+0900', 'duedate': None}},
    ]
    return build(cfg, {'gerrit', 'jira', 'todo'}, lambda q: gerrit[q], lambda jql: jira, ['팀 주간 회의 자료 정리'])


def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(prog=prog, description='Gerrit·Jira·할 일에서 지금 나를 기다리는 것을 뽑습니다.')
    ap.add_argument('-c', '--config', help='설정 파일 (기본 wk.json)')
    ap.add_argument('-o', '--out', help='결과를 저장할 파일(없으면 화면에 출력)')
    ap.add_argument('--only', default='gerrit,jira,todo', help='볼 곳만 고르기: gerrit,jira,todo')
    ap.add_argument('--demo', action='store_true', help='가짜 자료로 모양만 본다(접속 없음)')
    args = ap.parse_args(argv)

    if args.demo:
        text = demo()
    else:
        cfg = wkcore.load_config(args.config, required=True)
        options = (cfg.get('status') or {}).get('gerrit_options', GERRIT_OPTIONS)
        text = build(cfg, set(args.only.split(',')),
                     lambda q: wkcore.gerrit_query(cfg, q, options),
                     lambda jql: wkcore.jira_search(cfg, jql, JIRA_FIELDS),
                     todo.open_items(cfg))
    wkcore.write_out(text, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
