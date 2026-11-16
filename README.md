# wk

일할 때 쓰는 명령 모음입니다. 터미널에서 씁니다.

```
wk status      오늘 볼 것 (리뷰할 변경, 손볼 내 변경, 내 이슈, 할 일)
wk log 파일    안드로이드 로그에서 크래시·ANR 정리
wk weekly      주간 보고 초안
wk todo        할 일 (글 파일 todo.md)
wk mask 파일   사내 이름 가리기 / 되돌리기
wk init        설정 파일 wk.json 만들기
wk test        이 PC에서 제대로 도는지 확인
```

- 파이썬 표준 라이브러리만 씁니다. 설치할 것이 없습니다(파이썬 3.6 이상).
- 코드는 어디서나 같습니다. 쓰는 곳에 맞추는 일은 설정 파일 `wk.json` 하나로만 합니다.
- 사내 주소·계정·프로젝트 이름은 코드에 없습니다.
- `wk log`, `wk mask`, `wk todo`는 네트워크를 쓰지 않습니다. `wk status`와 `wk weekly`는 `wk.json`에 적은 주소에만 접속합니다.

## 받는 법

GitHub 저장소 화면에서 Code → Download ZIP으로 받아 풉니다. ZIP에는 git 연결 정보가 없어서, 받은 곳의 설정이나 수정이 저장소로 되돌아갈 길이 없습니다. `git clone`으로 받지 않는 것을 권합니다.

## 처음 한 번

```
python wk.py test
python wk.py init
```

- `test`에서 `전부 통과`가 나오면 그 PC에서 쓸 수 있습니다. 가짜 자료와 내 PC 안의 가짜 서버만 씁니다.
- `init`은 지금 폴더에 `wk.json`을 만듭니다. 주소와 아이디를 채웁니다.
- 윈도우에서는 이 폴더를 PATH에 넣으면 `wk status`처럼 짧게 쓸 수 있습니다(`wk.cmd`). 넣지 않으면 `python 경로/wk.py status`로 씁니다.

`wk.json`은 지금 폴더에서 먼저 찾고, 없으면 도구 폴더에서 찾습니다. 다른 파일을 쓰려면 `-c 파일`을 붙입니다.

## wk status — 오늘 볼 것

Gerrit, Jira, 할 일에서 지금 나를 기다리는 것만 뽑습니다. 아침에 한 번 돌리는 용도입니다.

```
wk status
wk status --only gerrit
wk status --demo
```

- **나를 기다리는 변경**: Gerrit이 내 차례라고 표시한 변경. 이 기능이 없는 옛 Gerrit에서는 이 칸이 빠집니다.
- **리뷰 요청받은 변경**: 내가 리뷰어로 들어간 열린 변경.
- **내 변경**: 내가 올린 열린 변경. 검증 거부, 미해결 댓글, 충돌, 머지 가능 여부를 옆에 붙입니다.
- **내 이슈**: 내게 배정된 끝나지 않은 이슈. 기한이 지났거나 사흘 안이면 표시합니다.
- **할 일**: `todo.md`의 남은 일.

무엇을 뽑을지는 `wk.json`의 `status` 칸에서 검색식(Gerrit `query`, Jira `jql`)과 제목을 바꿉니다.

## wk log — 안드로이드 로그 분석

logcat, bugreport, ANR traces, tombstone에서 크래시와 ANR만 골라 같은 것끼리 묶습니다.

```
wk log logcat.txt
wk log bugreport.zip -o report.md
wk log logs/ --pkg com.example --context 30
adb logcat -d | wk log -
```

찾는 것

- 자바 크래시 (FATAL EXCEPTION) — 가장 안쪽 Caused by 기준으로 묶음
- 네이티브 크래시 (logcat의 DEBUG 블록, tombstone 파일)
- ANR (logcat의 `ANR in`, traces 파일의 main 스레드 상태와 잠금을 쥔 스레드)
- 워치독, OutOfMemoryError, 저메모리 종료, 프로세스 종료

옵션

- `--pkg 글자` 이 글자가 들어간 프로세스만
- `--context 숫자` 크래시 직전 같은 프로세스 로그 줄 수 (기본 15)
- `--top 숫자` 상세로 보여 줄 종류 수 (기본 20)
- `--json` JSON으로 출력
- `-o 파일` 파일로 저장

읽는 형식: `logcat -v threadtime`(기본), `-v time`, `-v brief`, 연도·uid가 붙은 것, zip, gz, 폴더.

`wk.json`의 `log` 칸으로 더할 수 있는 것

- `line_patterns` 기본으로 못 읽는 줄 형식을 정규식으로 더합니다. 이름 붙은 그룹 `ts`, `pid`, `tid`, `level`, `tag`, `msg`를 씁니다. 틀에 든 것은 안드로이드 스튜디오 Logcat 창에서 복사한 형식입니다.
- `continuation_lines` 머리말 없이 들여 쓴 줄(스택)을 앞 줄에 붙입니다.
- `events` 따로 찾고 싶은 로그를 `name`, `pattern`(필수), `tag`, `levels`로 적습니다. 보고서에 그 이름으로 집계됩니다.

`android_log.py`는 이 파일 하나만 다른 PC에 복사해 `python android_log.py 파일`로 써도 됩니다.

## wk weekly — 주간 보고 초안

지난 며칠의 내 git 커밋, Gerrit 변경, Jira 이슈를 이슈 번호별로 묶어 완료와 진행 중으로 나눕니다. `todo.md`에서 이번 주에 끝낸 일은 완료에, 남은 일은 다음 주 계획에 들어갑니다.

```
wk weekly --demo
wk weekly -o weekly.md
wk weekly --prompt -o weekly_prompt.md
```

- `--demo` 접속 없이 가짜 자료로 모양만 봅니다.
- `--prompt` 사내 AI 대화창에 그대로 붙여 넣을 주문서를 맨 위에 붙입니다.
- `--only git,gerrit` 일부만 가져옵니다.
- `--days 14` 기간을 바꿉니다.
- `--json` 글 대신 자료로 내보냅니다.

한 곳이 실패해도 나머지로 초안을 만들고, 실패한 곳은 맨 위에 적습니다.

## wk todo — 할 일

Jira·Gerrit에 없는 개인 메모용입니다. 보통의 체크 목록 글 파일(`todo.md`)이라 편집기로 직접 고쳐도 됩니다.

```
wk todo
wk todo add 로그 수집 범위 정리
wk todo done 2
wk todo rm 3
wk todo all
```

번호는 `wk todo`가 보여 주는 남은 일의 번호입니다. 끝낸 일에는 끝낸 날짜가 붙습니다.

## wk mask — 가림

AI에 붙여 넣기 전에 사내 이름을 `PKG_001` 같은 가짜 이름으로 바꾸고, 답을 받은 뒤 되돌립니다.

```
wk mask mask crash.txt -o crash_masked.txt
wk mask unmask answer.txt -o answer_restored.txt
```

- 기본으로 가리는 것: 메일 주소, URL의 호스트, MAC, IP (127.0.0.1 등은 그대로)
- `wk.json`의 `mask` 칸에서 `words`에는 그대로 찾을 낱말, `patterns`에는 정규식을 분류 이름 아래에 적습니다.
- 같은 이름은 항상 같은 가짜 이름으로 바뀝니다. 대응표는 `mask_map.json`에 쌓입니다.
- `mask_map.json`은 그 PC에만 둡니다.

규칙에 없는 이름은 가려지지 않습니다. 붙여 넣기 전에 결과를 한 번 훑어보세요.
`mask.py`도 이 파일 하나만 복사해 쓸 수 있습니다.

## wk.json 채우는 법

`wk init`이 만든 파일에서 필요한 칸만 고칩니다. 쓰지 않는 칸은 지워도 됩니다.

- `git_repos` 내 PC의 저장소 경로들. `author`를 비우면 저장소의 `user.email`로 찾습니다.
- `gerrit.url`, `gerrit.user` Gerrit 주소와 아이디. 비밀번호는 Gerrit 설정 화면의 HTTP 비밀번호입니다.
- `jira.url`, `jira.user` Jira 주소와 아이디.
- `auth`에는 `basic`, `digest`(옛 Gerrit), `bearer`(개인 토큰, 아이디 불필요), `none`을 쓸 수 있습니다. 쿠키·SSO처럼 다른 방식이면 `"auth": "none"`에 `"headers": {"Cookie": "${환경변수이름}"}`처럼 직접 넣습니다.
- `password_env` 비밀번호를 담아 둔 환경 변수 이름. 없으면 실행할 때 한 번 물어봅니다. 비밀번호는 파일에 적지 않습니다.
- `gerrit.query_mine`, `gerrit.query_reviewed`, `jira.jql` 주간 보고에 가져올 범위. `{days}`는 기간으로 바뀝니다.
- `gerrit.api_prefix`, `jira.api_path` 서버 주소 모양이 다를 때.
- `status` 오늘 볼 것의 칸 제목과 검색식.
- `report.title`, `report.sections` 주간 보고 제목과 칸 이름. `extra`의 첫 칸에 남은 할 일이 들어갑니다.
- `report.issue_key_pattern` 이슈 번호 규칙(정규식). 커밋 제목에 없으면 본문에서도 찾습니다.
- `prompt_file` `--prompt`에 쓸 주문서 글 파일. 비우면 기본 문구를 씁니다.
- `todo_file` 할 일 파일 경로. 상대 경로는 `wk.json`이 있는 폴더 기준입니다.
- `ssl.ca_file` 사내 인증서 파일 경로. 인증서 오류가 날 때 넣습니다. 그래도 안 되면 `"verify": false`.
- `no_proxy` 사내 주소인데 프록시를 타서 실패하면 `true`.
