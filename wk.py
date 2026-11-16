#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wk — 일할 때 쓰는 명령 모음. 파이썬 표준 라이브러리만 쓴다(3.6 이상).

    wk status      오늘 볼 것 (리뷰할 변경, 손볼 내 변경, 내 이슈, 할 일)
    wk log 파일    안드로이드 로그에서 크래시·ANR 정리
    wk weekly      주간 보고 초안
    wk todo        할 일 (글 파일 todo.md)
    wk mask 파일   사내 이름 가리기 / 되돌리기
    wk init        설정 파일 wk.json 만들기
    wk test        이 PC에서 제대로 도는지 확인

명령마다 `wk 명령 -h` 로 옵션을 볼 수 있다.
"""
import importlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMANDS = {'status': 'status', 'log': 'android_log', 'weekly': 'weekly_report', 'todo': 'todo', 'mask': 'mask'}


def init():
    target = os.path.join(os.getcwd(), 'wk.json')
    if os.path.exists(target):
        print('이미 있습니다: ' + target)
        return 1
    shutil.copyfile(os.path.join(HERE, 'wk.sample.json'), target)
    print('만들었습니다: %s\n주소와 아이디를 채운 뒤 `wk status` 로 확인하세요. 비밀번호는 적지 않습니다.' % target)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__.strip())
        return 0
    name, rest = argv[0], argv[1:]
    if name == 'init':
        return init()
    if name == 'test':
        return subprocess.call([sys.executable, os.path.join(HERE, 'tests', 'run_tests.py')])
    if name not in COMMANDS:
        print('모르는 명령입니다: %s\n' % name)
        print(__doc__.strip())
        return 2
    sys.path.insert(0, HERE)
    return importlib.import_module(COMMANDS[name]).main(rest, prog='wk ' + name)


if __name__ == '__main__':
    sys.exit(main())
