#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""할 일 — 글 파일(todo.md) 하나에 적는다.

Jira·Gerrit에 없는 개인 메모용이다. 파일은 보통의 체크 목록이라 편집기로 직접 고쳐도 된다.
남은 일은 `wk status` 에 보이고, 주간 보고의 다음 주 계획에 들어간다. 이번 주에 끝낸 일은 완료에 들어간다.

    wk todo                    남은 일 보기
    wk todo add 로그 수집 범위 정리
    wk todo done 2             2번을 끝냄으로
    wk todo rm 3               3번 지우기
    wk todo all                끝낸 일까지 보기
"""
import argparse
import datetime
import io
import os
import re
import sys

import wkcore

LINE = re.compile(r'^(\s*[-*] \[)([ xX])(\] )(.*)$')
DONE_MARK = re.compile(r'\s*\(완료 (\d{4}-\d\d-\d\d)\)\s*$')


def path_of(cfg):
    return wkcore.resolve(cfg, cfg.get('todo_file') or 'todo.md')


def read_lines(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8-sig') as f:
        return f.read().splitlines()


def write_lines(path, lines):
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def parse(lines):
    items = []
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if not m:
            continue
        text = m.group(4).strip()
        dm = DONE_MARK.search(text)
        items.append({'line': i, 'done': m.group(2) != ' ', 'text': DONE_MARK.sub('', text),
                      'done_at': dm.group(1) if dm else None})
    return items


def open_items(cfg):
    return [t['text'] for t in parse(read_lines(path_of(cfg))) if not t['done']]


def done_since(cfg, start):
    """start(YYYY-MM-DD) 이후에 끝낸 일. 끝낸 날이 안 적힌 것은 넣지 않는다."""
    return [t['text'] for t in parse(read_lines(path_of(cfg))) if t['done'] and t['done_at'] and t['done_at'] >= start]


def pick(opened, numbers):
    chosen = []
    for n in numbers:
        if not 1 <= n <= len(opened):
            raise SystemExit('%d번이 없습니다. 남은 일은 %d개입니다.' % (n, len(opened)))
        chosen.append(opened[n - 1])
    return chosen


def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(prog=prog, description='할 일을 글 파일(todo.md)에 적고 봅니다.')
    ap.add_argument('action', nargs='?', default='list', choices=['list', 'add', 'done', 'rm', 'all'])
    ap.add_argument('rest', nargs='*', help='add 는 내용, done·rm 은 번호')
    ap.add_argument('-c', '--config', help='설정 파일 (기본 wk.json)')
    args = ap.parse_args(argv)

    path = path_of(wkcore.load_config(args.config))
    lines = read_lines(path)
    out = []
    if args.action == 'add':
        text = ' '.join(args.rest).strip()
        if not text:
            raise SystemExit('내용을 적어 주세요. 예: wk todo add 로그 수집 범위 정리')
        if not lines:
            lines = ['# 할 일', '']
        lines.append('- [ ] ' + text)
        write_lines(path, lines)
        out.append('추가: ' + text)
    elif args.action in ('done', 'rm'):
        try:
            numbers = [int(x) for x in args.rest]
        except ValueError:
            raise SystemExit('번호를 적어 주세요. 예: wk todo %s 2' % args.action)
        if not numbers:
            raise SystemExit('번호를 적어 주세요. 예: wk todo %s 2' % args.action)
        chosen = pick([t for t in parse(lines) if not t['done']], numbers)
        today = datetime.date.today().isoformat()
        for t in sorted(chosen, key=lambda t: -t['line']):
            if args.action == 'rm':
                del lines[t['line']]
                out.append('지움: ' + t['text'])
            else:
                m = LINE.match(lines[t['line']])
                lines[t['line']] = '%sx%s%s (완료 %s)' % (m.group(1), m.group(3), t['text'], today)
                out.append('끝냄: ' + t['text'])
        write_lines(path, lines)
        out.reverse()

    items = parse(lines)
    opened = [t for t in items if not t['done']]
    out.append('남은 일 %d개 (%s)' % (len(opened), path))
    out += ['%3d. %s' % (i, t['text']) for i, t in enumerate(opened, 1)]
    if args.action == 'all':
        done = [t for t in items if t['done']]
        out.append('끝낸 일 %d개' % len(done))
        out += ['   ✓ %s%s' % (t['text'], ' (%s)' % t['done_at'] if t['done_at'] else '') for t in done]
    wkcore.write_out('\n'.join(out) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
