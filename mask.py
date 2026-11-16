#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""가림 도구.

로그나 보고서를 AI에 붙여 넣기 전에 사내 이름(패키지, 도메인, IP, 사람, 이슈 번호)을
PKG_001 같은 가짜 이름으로 바꾸고, 답을 받은 뒤 원래 이름으로 되돌린다.
대응표(mask_map.json)는 이 PC에만 남는다. 밖으로 내보내지 않는다.
파이썬 표준 라이브러리만 쓴다(3.6 이상). 네트워크를 쓰지 않는다.

    wk mask mask crash.txt -o crash_masked.txt
    wk mask unmask answer.txt -o answer_restored.txt
    type crash.txt | wk mask mask - > crash_masked.txt

이 파일 하나만 복사해 `python mask.py mask 파일` 로 써도 된다.
가릴 이름은 wk.json 의 mask 칸에 적는다.
"""
import argparse
import collections
import io
import json
import os
import re
import sys

BUILTIN = collections.OrderedDict([
    ('email', ('MAIL', r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')),
    ('url_host', ('HOST', r'(?<=://)[\w.-]+')),
    ('mac', ('MAC', r'\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b')),
    ('ip', ('IP', r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
])
KEEP = {'127.0.0.1', '0.0.0.0', '255.255.255.255', 'localhost'}
DEFAULT_RULES = {'builtin': list(BUILTIN), 'words': {}, 'patterns': {}}


def load_json(path, default):
    if path and os.path.exists(path):
        with io.open(path, encoding='utf-8') as f:
            return json.load(f)
    return default


def read_text(path):
    if path == '-':
        return io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8-sig', errors='replace').read()
    with io.open(path, encoding='utf-8-sig', errors='replace') as f:
        return f.read()


def write_text(path, text):
    if path:
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        sys.stderr.write('저장: %s\n' % path)
    else:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)


def compile_rules(rules):
    """(분류, 정규식) 목록을 우선순위대로 하나의 정규식으로 합친다."""
    parts = []
    for cat, words in rules.get('words', {}).items():
        for w in sorted(words, key=len, reverse=True):
            if w:
                parts.append((cat, re.escape(w)))
    for cat, pats in rules.get('patterns', {}).items():
        for p in pats:
            parts.append((cat, p))
    for name in rules.get('builtin', []):
        if name in BUILTIN:
            parts.append(BUILTIN[name])
    if not parts:
        return None, []
    rx = re.compile('|'.join('(?P<g%d>%s)' % (i, p) for i, (_, p) in enumerate(parts)))
    return rx, [cat.upper() for cat, _ in parts]


def do_mask(text, rules, mapping):
    rx, cats = compile_rules(rules)
    if rx is None:
        return text, collections.Counter()
    forward = mapping.setdefault('forward', {})
    counters = mapping.setdefault('counters', {})
    used = collections.Counter()

    def repl(m):
        orig = m.group(0)
        if orig in KEEP:
            return orig
        cat = cats[int(m.lastgroup[1:])]
        if orig not in forward:
            counters[cat] = counters.get(cat, 0) + 1
            forward[orig] = '%s_%03d' % (cat, counters[cat])
        used[cat] += 1
        return forward[orig]

    return rx.sub(repl, text), used


def do_unmask(text, mapping):
    back = dict((v, k) for k, v in mapping.get('forward', {}).items())
    if not back:
        return text, 0
    rx = re.compile(r'(?<![A-Za-z0-9_])(%s)(?![A-Za-z0-9_])' %'|'.join(re.escape(t) for t in sorted(back, key=len, reverse=True)))
    count = [0]

    def repl(m):
        count[0] += 1
        return back[m.group(1)]

    return rx.sub(repl, text), count[0]


def load_section(path, name):
    """wk.json 에서 이 도구의 칸만 읽는다. 찾는 순서: 지정한 경로 → 지금 폴더 → 도구 폴더."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in ([path] if path else [os.path.join(os.getcwd(), 'wk.json'), os.path.join(here, 'wk.json')]):
        if os.path.exists(p):
            with io.open(p, encoding='utf-8-sig') as f:
                return json.load(f).get(name) or {}
    if path:
        raise SystemExit('설정 파일이 없습니다: ' + path)
    return {}


def main(argv=None, prog=None):
    ap = argparse.ArgumentParser(prog=prog, description='사내 이름을 가짜 이름으로 바꾸고, 다시 되돌립니다.')
    ap.add_argument('mode', choices=['mask', 'unmask'])
    ap.add_argument('input', help='입력 파일. 표준 입력은 -')
    ap.add_argument('-o', '--out', help='결과를 저장할 파일(없으면 화면에 출력)')
    ap.add_argument('-c', '--config', help='설정 파일 (기본 wk.json 의 mask 칸, 없으면 기본 규칙만)')
    ap.add_argument('--map', default='mask_map.json', help='대응표 파일 (기본 mask_map.json)')
    args = ap.parse_args(argv)

    mapping = load_json(args.map, {})
    text = read_text(args.input)
    if args.mode == 'mask':
        rules = load_section(args.config, 'mask') or DEFAULT_RULES
        out, used = do_mask(text, rules, mapping)
        with io.open(args.map, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
        write_text(args.out, out)
        summary = ', '.join('%s %d곳' % kv for kv in sorted(used.items())) or '바꾼 곳 없음'
        sys.stderr.write('가림: %s\n대응표: %s (이 파일은 PC 밖으로 내보내지 마세요)\n' % (summary, args.map))
    else:
        out, n = do_unmask(text, mapping)
        write_text(args.out, out)
        sys.stderr.write('되돌림: %d곳\n' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
