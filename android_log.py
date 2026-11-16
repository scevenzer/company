#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""안드로이드 로그 분석기.

logcat / bugreport / ANR traces / tombstone 파일에서 크래시·ANR만 골라
같은 것끼리 묶고, 처음 터진 시각과 직전 로그를 붙여 한 장으로 정리한다.
파이썬 표준 라이브러리만 쓴다(3.6 이상). 네트워크를 쓰지 않는다.

    wk log logcat.txt
    wk log bugreport.zip -o report.md
    wk log logs/ --pkg com.example --context 30
    adb logcat -d | wk log -

이 파일 하나만 복사해 `python android_log.py 파일` 로 써도 된다.
못 읽는 줄 형식이나 따로 찾고 싶은 로그는 wk.json 의 log 칸에 더한다.
"""
import argparse
import collections
import gzip
import io
import json
import os
import re
import sys
import zipfile

Entry = collections.namedtuple('Entry', 'ts pid tid level tag msg')

LINE_RE = re.compile(
    r'^(?:(?:\d{4}-)?(\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+)\s+)?'
    r'(?:'
    r'(?:\S+\s+)??(\d+)\s+(\d+)\s+([VDIWEFA])\s+(.*?)\s*:(?: |$)(.*)'  # threadtime
    r'|([VDIWEFA])/(.*?)\(\s*(\d+)\):(?: |$)(.*)'                      # brief / time
    r')$')
TRACE_START = re.compile(r'^----- pid (\d+) at (.+?) -----')
TRACE_END = re.compile(r'^----- end \d+ -----')
THREAD_HEAD = re.compile(r'^"(.+?)"(?: daemon)?(?: prio=\d+)? tid=(\d+) (\w+)')
START_PROC = re.compile(r'Start proc (\d+):([^/\s]+)/')
FATAL_SIGNAL = re.compile(r'Fatal signal (\d+) \((\w+)\)(.*)')
ONE_LINERS = [
    ('died', re.compile(r'Process (\S+) \(pid (\d+)\) has died')),
    ('lmk', re.compile(r"Kill(?:ing)? '([^']+)' \((\d+)\)")),
    ('watchdog', re.compile(r'WATCHDOG KILLING SYSTEM PROCESS: (.*)')),
    ('oom', re.compile(r'Throwing OutOfMemoryError "?(.*?)"?$')),
]
SKIP_EXT = ('.png', '.jpg', '.jpeg', '.pb', '.bin', '.mp4', '.zip', '.gz',
            '.proto', '.perfetto-trace', '.apk', '.so', '.dex', '.hprof')

KIND_NAME = collections.OrderedDict([
    ('watchdog', '워치독'),
    ('native', '네이티브 크래시'),
    ('java', '자바 크래시'),
    ('anr', 'ANR'),
    ('anr_trace', 'ANR 스택(traces)'),
    ('oom', '메모리 부족(OOM)'),
    ('custom', '사용자 규칙'),
    ('lmk', '저메모리 종료'),
    ('died', '프로세스 종료'),
])
MINOR = ('lmk', 'died')


def parse_line(line, extra=()):
    m = LINE_RE.match(line)
    if m:
        ts = m.group(1)
        if ts:
            ts = ' '.join(ts.split())[:18]
        if m.group(7):
            return Entry(ts, int(m.group(9)), None, m.group(7), m.group(8).strip(), m.group(10))
        if ts:
            return Entry(ts, int(m.group(2)), int(m.group(3)), m.group(4), m.group(5), m.group(6))
    for rx in extra:  # 설정 파일의 line_patterns (이름 붙은 그룹: ts pid tid level tag msg)
        m = rx.match(line)
        if m:
            d = m.groupdict()
            ts = d.get('ts')
            if ts:
                ts = re.sub(r'^\d{4}-', '', ' '.join(ts.split()))[:18]
            return Entry(ts, int(d.get('pid') or 0), int(d['tid']) if d.get('tid') else None,
                         d.get('level') or 'I', (d.get('tag') or '').strip(), d.get('msg') or '')
    return None


def strip_lineno(frame):
    return re.sub(r':\d+\)', ')', frame)


def short(text, n=160):
    text = ' '.join(text.split())
    return text if len(text) <= n else text[:n - 1] + '…'


class Block(object):
    LIMIT = {'java': 400, 'anr': 60, 'native': 300}

    def __init__(self, kind, entry, src, lineno, snapshot):
        self.kind = kind
        self.first = entry
        self.src = src
        self.lineno = lineno
        self.snapshot = snapshot
        self.msgs = [entry.msg]
        self.idle = 0
        self.limit = self.LIMIT[kind]

    def accept(self, e):
        f = self.first
        if e.pid != f.pid or e.tag != f.tag:
            return False
        if self.kind == 'anr':
            return e.ts == f.ts and e.tid == f.tid and not e.msg.startswith('ANR in ')
        if self.kind == 'java':
            return 'FATAL EXCEPTION' not in e.msg
        return '*** *** ***' not in e.msg


class Analyzer(object):
    def __init__(self, context=15, cfg=None):
        cfg = cfg or {}
        self.context = context
        self.extra_lines = [re.compile(x) for x in cfg.get('line_patterns', [])]
        self.continuation = bool(cfg.get('continuation_lines'))
        self.custom = [(c['name'], re.compile(c['pattern']), c.get('tag'), c.get('levels'))
                       for c in cfg.get('events', [])]
        self.events = []
        self.tag_err = collections.Counter()
        self.files = []
        self.pidname = {}
        self.fatal_signals = []

    # ---------- 읽기 ----------
    def feed(self, name, lines):
        recent = collections.deque(maxlen=3000)
        blocks = []
        plain = None
        first_trace = True
        count = 0
        first_ts = last_ts = None
        last = None
        for lineno, line in enumerate(lines, 1):
            count = lineno
            line = line.rstrip('\r\n')
            e = parse_line(line, self.extra_lines)
            if (e is None and self.continuation and plain is None and last is not None and line.strip()
                    and (line[:1] in ' \t' or line.startswith('Caused by:'))):
                e = last._replace(msg=line)  # 머리말 없이 이어지는 줄(스택 등)은 앞 줄에 붙인다
            if e is None:
                s = line.strip()
                tm = TRACE_START.match(s)
                if s.startswith('*** *** ***'):
                    self._close_plain(plain, name)
                    plain = {'kind': 'tomb', 'lines': [], 'lineno': lineno}
                elif tm:
                    self._close_plain(plain, name)
                    plain = {'kind': 'trace', 'lines': [], 'lineno': lineno,
                             'pid': int(tm.group(1)), 'when': tm.group(2), 'first': first_trace}
                    first_trace = False
                elif plain:
                    if plain['kind'] == 'trace' and TRACE_END.match(s):
                        self._close_plain(plain, name)
                        plain = None
                    else:
                        plain['lines'].append(line)
                        if len(plain['lines']) > (400 if plain['kind'] == 'tomb' else 20000):
                            self._close_plain(plain, name)
                            plain = None
                continue

            if plain and plain['kind'] == 'tomb':
                self._close_plain(plain, name)
                plain = None
            if e.ts:
                if first_ts is None:
                    first_ts = e.ts
                last_ts = e.ts
            if e.level in 'EFA':
                self.tag_err[e.tag] += 1

            still = []
            for b in blocks:
                if b.accept(e):
                    b.msgs.append(e.msg)
                    b.idle = 0
                else:
                    b.idle += 1
                if b.idle > 300 or len(b.msgs) >= b.limit:
                    self._finish(b)
                else:
                    still.append(b)
            blocks = still

            kind = self._trigger(e)
            if kind:
                keep = []
                for b in blocks:
                    if b.kind == kind and b.first.pid == e.pid:
                        self._finish(b)
                    else:
                        keep.append(b)
                blocks = keep
                blocks.append(Block(kind, e, name, lineno, list(recent)))
            else:
                self._one_line(e, name, lineno, recent)
            recent.append(e)
            last = e

        for b in blocks:
            self._finish(b)
        self._close_plain(plain, name)
        self.files.append({'name': name, 'lines': count, 'first': first_ts, 'last': last_ts})

    @staticmethod
    def _trigger(e):
        if e.tag == 'AndroidRuntime' and 'FATAL EXCEPTION' in e.msg:
            return 'java'
        if e.tag in ('ActivityManager', 'ActivityTaskManager') and e.msg.startswith('ANR in '):
            return 'anr'
        if e.tag == 'DEBUG' and '*** *** ***' in e.msg:
            return 'native'
        return None

    def _one_line(self, e, src, lineno, recent=()):
        if e.tag == 'ActivityManager':
            m = START_PROC.search(e.msg)
            if m:
                self.pidname[int(m.group(1))] = m.group(2)
        if e.tag == 'libc':
            m = FATAL_SIGNAL.search(e.msg)
            if m:
                self.fatal_signals.append((e, src, lineno, m))
                return
        for kind, rx in ONE_LINERS:
            m = rx.search(e.msg)
            if not m:
                continue
            if kind == 'died' and e.tag != 'ActivityManager':
                continue
            if kind in ('died', 'lmk'):
                proc, pid, title = m.group(1), int(m.group(2)), short(e.msg)
                sig = proc
            elif kind == 'watchdog':
                proc, pid, title = 'system_server', e.pid, short(m.group(1))
                sig = re.sub(r'\d+', 'N', title)
            else:
                proc, pid, title = self.pidname.get(e.pid), e.pid, 'OutOfMemoryError: ' + short(m.group(1))
                sig = (proc or '') + re.sub(r'\d+', 'N', m.group(1))
            self._add(kind, e.ts, proc, pid, title, sig, [e.msg], [], src, lineno)
            return
        for name, rx, tag, levels in self.custom:  # 설정 파일의 events
            if (tag and e.tag != tag) or (levels and e.level not in levels):
                continue
            m = rx.search(e.msg)
            if not m:
                continue
            proc = m.groupdict().get('proc') or self.pidname.get(e.pid)
            sig = name + '|' + re.sub(r'0x[0-9a-fA-F]+|\d+', 'N', e.msg)
            self._add('custom', e.ts, proc, e.pid, short(e.msg), sig, ['%s: %s' % (e.tag, e.msg)],
                      self._context(list(recent), e.pid), src, lineno, label=name)
            return

    def _add(self, kind, ts, proc, pid, title, sig, detail, context, src, lineno, label=None):
        self.events.append({'kind': kind, 'label': label or KIND_NAME[kind],
                            'ts': ts, 'proc': proc, 'pid': pid, 'title': title,
                            'sig': sig, 'detail': detail, 'context': context,
                            'src': src, 'lineno': lineno})

    def _context(self, snapshot, pid):
        if not self.context or pid is None:
            return []
        rows = [x for x in snapshot if x.pid == pid][-self.context:]
        return ['%s %s %s: %s' % (x.ts or '', x.level, x.tag, x.msg) for x in rows]

    # ---------- 블록 마무리 ----------
    def _finish(self, b):
        getattr(self, '_fin_' + b.kind)(b)

    def _fin_java(self, b):
        proc, pid = None, b.first.pid
        if 'SYSTEM PROCESS' in b.first.msg:
            proc = 'system_server'
        exc = root = None
        frames, first_frames = [], None
        for m in b.msgs[1:]:
            pm = re.match(r'Process: (\S+?),? PID: (\d+)', m.strip())
            if pm:
                proc, pid = pm.group(1), int(pm.group(2))
                continue
            s = m.strip()
            if s.startswith('at '):
                frames.append(s[3:])
            elif s.startswith('Caused by: '):
                if first_frames is None:
                    first_frames = frames
                root, frames = s[11:], []
            elif not s or s.startswith('...'):
                continue
            elif exc is None:
                exc = s
        head = root or exc or b.first.msg
        if not frames and first_frames:
            frames = first_frames
        sig = head.split(':')[0] + '|' + '|'.join(strip_lineno(f) for f in frames[:3])
        proc = proc or self.pidname.get(pid)
        self._add('java', b.first.ts, proc, pid, short(head), sig,
                  [m.rstrip() for m in b.msgs[:60]], self._context(b.snapshot, pid), b.src, b.lineno)

    def _fin_anr(self, b):
        m = re.match(r'ANR in (\S+)(?: \((.*?)\))?', b.first.msg)
        proc = m.group(1) if m else None
        pid, reason = None, ''
        for line in b.msgs[1:]:
            pm = re.match(r'\s*PID: (\d+)', line)
            rm = re.match(r'\s*Reason: (.*)', line)
            if pm:
                pid = int(pm.group(1))
            elif rm:
                reason = rm.group(1)
        norm = re.sub(r'0x[0-9a-fA-F]+|\d+', 'N', reason)
        self._add('anr', b.first.ts, proc, pid, short(reason or b.first.msg), '%s|%s' % (proc, norm),
                  [x.rstrip() for x in b.msgs[:25]], self._context(b.snapshot, pid), b.src, b.lineno)

    def _fin_native(self, b):
        self._native(b.msgs, b.first.ts, b.src, b.lineno, b.snapshot)

    def _native(self, msgs, ts, src, lineno, snapshot):
        proc = pid = None
        signal = abort = ''
        frames, detail = [], []
        for line in msgs:
            s = line.strip()
            pm = re.search(r'pid: (\d+), tid: (\d+), name: (.*?)\s+>>> (.*?) <<<', s)
            sm = re.search(r'signal (\d+) \((\w+)\), code (-?\d+) \((\w+)\)(?:, fault addr (\S+))?', s)
            am = re.search(r"Abort message: '?(.*?)'?$", s)
            fm = re.match(r'#(\d+)\s+pc\s+(\S+)\s+(\S+)(?:\s+\((.*)\))?', s)
            if pm and pid is None:
                pid, proc = int(pm.group(1)), pm.group(4)
                detail.append(s)
            elif sm and not signal:
                signal = '%s (%s)' % (sm.group(2), sm.group(4))
                if sm.group(5):
                    signal += ' fault addr ' + sm.group(5)
                detail.append(s)
            elif am and not abort:
                abort = am.group(1)
                detail.append(s)
            elif fm:
                func = re.sub(r'\+\d+$', '', fm.group(4) or '')
                frames.append((os.path.basename(fm.group(3)), func))
                if len(frames) <= 25:
                    detail.append(s)
        if pid is None and not signal and not frames:
            return
        top = ' — %s (%s)' % frames[0] if frames else ''
        title = (signal or '네이티브 크래시') + top
        if abort:
            title += " — abort: " + abort
        sig = signal.split(' ')[0] + '|' + '|'.join('%s:%s' % f for f in frames[:3])
        self._add('native', ts, proc, pid, short(title), sig, detail,
                  self._context(snapshot, pid), src, lineno)

    def _close_plain(self, plain, src):
        if not plain:
            return
        if plain['kind'] == 'tomb':
            self._native(plain['lines'], None, src, plain['lineno'], [])
            return
        cmd = None
        threads, cur = [], None
        for line in plain['lines']:
            s = line.strip()
            if s.startswith('Cmd line: '):
                cmd = s[10:]
            hm = THREAD_HEAD.match(s)
            if hm:
                cur = {'name': hm.group(1), 'tid': hm.group(2), 'state': hm.group(3), 'lines': [s]}
                threads.append(cur)
            elif cur is not None and s:
                cur['lines'].append(s)
        main = next((t for t in threads if t['name'] == 'main'), None)
        if not main or not (plain['first'] or main['state'] == 'Blocked'):
            return
        frames = [x[3:] for x in main['lines'] if x.startswith('at ')]
        detail = main['lines'][:30]
        title = 'main 스레드 ' + main['state']
        hm = re.search(r'held by thread (\d+)', '\n'.join(main['lines']))
        if hm:
            title += ' — 스레드 %s이(가) 잠금 보유' % hm.group(1)
            holder = next((t for t in threads if t['tid'] == hm.group(1)), None)
            if holder:
                detail += ['', '(잠금을 쥔 스레드)'] + holder['lines'][:20]
        if frames:
            title += ' — ' + frames[0]
        when = plain['when']
        wm = re.match(r'\d{4}-(\d\d-\d\d \d\d:\d\d:\d\d)', when)
        sig = '%s|%s|%s' % (cmd, main['state'], '|'.join(strip_lineno(f) for f in frames[:3]))
        self._add('anr_trace', wm.group(1) if wm else None, cmd, plain['pid'], short(title), sig,
                  detail, [], src, plain['lineno'])

    # ---------- 정리 ----------
    def finalize(self, pkg=None):
        native = [ev for ev in self.events if ev['kind'] == 'native']
        with_ts = set((ev['pid'], ev['sig']) for ev in native if ev['ts'])
        self.events = [ev for ev in self.events
                       if not (ev['kind'] == 'native' and not ev['ts'] and (ev['pid'], ev['sig']) in with_ts)]
        native_pids = set(ev['pid'] for ev in native)
        for e, src, lineno, m in self.fatal_signals:
            if e.pid in native_pids:
                continue
            proc = self.pidname.get(e.pid)
            self._add('native', e.ts, proc, e.pid,
                      short('%s%s — 백트레이스 없음' % (m.group(2), m.group(3))),
                      '%s|%s|nobt' % (m.group(2), proc), [e.msg], [], src, lineno)
        self.fatal_signals = []
        if pkg:
            self.events = [ev for ev in self.events if not ev['proc'] or pkg in ev['proc']]
        self.events.sort(key=lambda ev: (ev['ts'] or '~', ev['lineno']))

    def groups(self):
        out = collections.OrderedDict()
        for ev in self.events:
            if ev['kind'] in MINOR:
                continue
            g = out.setdefault((ev['kind'], ev['sig']), {'sample': ev, 'count': 0, 'last': ev['ts'], 'procs': []})
            g['count'] += 1
            g['last'] = ev['ts'] or g['last']
            if ev['proc'] and ev['proc'] not in g['procs']:
                g['procs'].append(ev['proc'])
        order = list(KIND_NAME)
        return sorted(out.values(), key=lambda g: (-g['count'], order.index(g['sample']['kind'])))


def render(an, top=20, timeline=100):
    w = []
    w.append('# 안드로이드 로그 분석')
    w.append('')
    for f in an.files:
        span = ' · %s ~ %s' % (f['first'], f['last']) if f['first'] else ''
        w.append('- 파일: %s (%s줄%s)' % (f['name'], format(f['lines'], ','), span))
    groups = an.groups()
    major = [ev for ev in an.events if ev['kind'] not in MINOR]

    w += ['', '## 한눈에', '']
    if not major:
        w.append('크래시·ANR을 찾지 못했습니다.')
    order = list(KIND_NAME)
    tally = collections.OrderedDict()
    for ev in sorted(major, key=lambda ev: order.index(ev['kind'])):
        t = tally.setdefault(ev['label'], [0, set()])
        t[0] += 1
        t[1].add(ev['sig'])
    for label, (n, sigs) in tally.items():
        w.append('- %s %d건 (%d종류)' % (label, n, len(sigs)))

    if major:
        w += ['', '## 시간순', '']
        for ev in major[:timeline]:
            w.append('- `%s` %s · %s · %s' % (ev['ts'] or '시각 없음', ev['label'],
                                             ev['proc'] or 'pid %s' % ev['pid'], ev['title']))
        if len(major) > timeline:
            w.append('- … 외 %d건' % (len(major) - timeline))

        w += ['', '## 상세 (많이 난 순서)']
        for i, g in enumerate(groups[:top], 1):
            ev = g['sample']
            w += ['', '### %d. %s — %s (%d회)' % (i, ev['label'], ev['title'], g['count']), '']
            w.append('- 프로세스: %s (pid %s)' % (', '.join(g['procs']) or '알 수 없음', ev['pid']))
            if g['count'] > 1:
                w.append('- 처음: %s / 마지막: %s' % (ev['ts'], g['last']))
            else:
                w.append('- 시각: %s' % (ev['ts'] or '시각 없음'))
            w.append('- 위치: %s %d번째 줄' % (ev['src'], ev['lineno']))
            w += ['', '```text'] + ev['detail'] + ['```']
            if ev['context']:
                w += ['', '직전 로그 (같은 프로세스)', '', '```text'] + ev['context'] + ['```']
        if len(groups) > top:
            w += ['', '… 외 %d종류는 --top 값을 키우면 보입니다.' % (len(groups) - top)]

    minor = collections.OrderedDict()
    for ev in an.events:
        if ev['kind'] in MINOR:
            minor.setdefault(ev['proc'], collections.Counter())[ev['kind']] += 1
    if minor:
        w += ['', '## 프로세스 종료·저메모리 종료', '']
        for proc, c in sorted(minor.items(), key=lambda kv: -sum(kv[1].values()))[:30]:
            w.append('- %s: %s' % (proc, ', '.join('%s %d회' % (KIND_NAME[k], n) for k, n in c.items())))

    if an.tag_err:
        w += ['', '## 오류 로그가 많은 태그 (E·F)', '']
        for tag, n in an.tag_err.most_common(15):
            w.append('- %s: %s줄' % (tag, format(n, ',')))
    return '\n'.join(w) + '\n'


def sources(paths):
    for p in paths:
        if p == '-':
            yield '<stdin>', io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8-sig', errors='replace')
        elif os.path.isdir(p):
            found = []
            for root, _, names in os.walk(p):
                found += [os.path.join(root, n) for n in names
                          if n.lower().endswith(('.zip', '.gz')) or not n.lower().endswith(SKIP_EXT)]
            for item in sources(sorted(found)):
                yield item
        elif p.lower().endswith('.zip'):
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if info.filename.endswith('/') or info.file_size == 0:
                        continue
                    if info.filename.lower().endswith(SKIP_EXT):
                        continue
                    with z.open(info) as f:
                        yield p + '!' + info.filename, io.TextIOWrapper(f, encoding='utf-8', errors='replace')
        elif p.lower().endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8', errors='replace') as f:
                yield p, f
        else:
            with io.open(p, encoding='utf-8-sig', errors='replace') as f:
                yield p, f


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
    ap = argparse.ArgumentParser(prog=prog, description='안드로이드 로그에서 크래시·ANR을 골라 정리합니다.')
    ap.add_argument('paths', nargs='+', help='logcat·bugreport·traces·tombstone 파일, 폴더, zip, gz. 표준 입력은 -')
    ap.add_argument('-o', '--out', help='결과를 저장할 파일(없으면 화면에 출력)')
    ap.add_argument('--pkg', help='이 글자가 들어간 프로세스만 본다 (예: com.example)')
    ap.add_argument('--context', type=int, default=15, help='크래시 직전 로그 줄 수 (기본 15)')
    ap.add_argument('--top', type=int, default=20, help='상세로 보여 줄 종류 수 (기본 20)')
    ap.add_argument('--json', action='store_true', help='마크다운 대신 JSON으로 출력')
    ap.add_argument('-c', '--config', help='설정 파일 (기본 wk.json 의 log 칸, 없으면 기본 규칙만)')
    args = ap.parse_args(argv)

    an = Analyzer(context=args.context, cfg=load_section(args.config, 'log'))
    for name, lines in sources(args.paths):
        an.feed(name, lines)
    an.finalize(pkg=args.pkg)
    if args.json:
        text = json.dumps({'files': an.files, 'events': an.events}, ensure_ascii=False, indent=1)
    else:
        text = render(an, top=args.top)
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
