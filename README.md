# work_tools

사내에서 쓰는 작은 도구 세 개입니다.

- 파이썬 표준 라이브러리만 씁니다. 설치할 것이 없습니다(파이썬 3.6 이상).
- 도구 하나가 파일 하나입니다. 필요한 파일만 복사해도 됩니다.
- 사내 주소·계정·프로젝트 이름은 코드에 없습니다. 회사 PC에서 설정 파일에 채웁니다.
- `android_log.py`와 `mask.py`는 네트워크를 쓰지 않습니다. `weekly_report.py`는 설정 파일에 적은 주소에만 접속합니다.

- 코드는 어디서나 같습니다. 쓰는 곳에 맞추는 일은 설정 파일(`config.json`, `android_log.json`, `rules.json`)로만 합니다.

## 받는 법

GitHub 저장소 화면에서 Code → Download ZIP으로 받아 풉니다. ZIP에는 git 연결 정보가 없어서, 받은 곳에서 고친 것이나 설정 파일이 저장소로 되돌아갈 길이 없습니다. `git clone`으로 받지 않는 것을 권합니다.

## 처음 한 번

```
python tests/run_tests.py
```

`전부 통과`가 나오면 그 PC에서 쓸 수 있습니다. 가짜 자료와 내 PC 안의 가짜 서버만 씁니다.

## 1. android_log.py — 안드로이드 로그 분석

logcat, bugreport, ANR traces, tombstone에서 크래시와 ANR만 골라 같은 것끼리 묶습니다.

```
python android_log.py logcat.txt
python android_log.py bugreport.zip -o report.md
python android_log.py logs/ --pkg com.example --context 30
adb logcat -d | python android_log.py -
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

- `--config 파일` 추가 규칙 파일 (기본 `android_log.json`, 없으면 기본 규칙만)

읽는 형식: `logcat -v threadtime`(기본), `-v time`, `-v brief`, 연도·uid가 붙은 것, zip, gz, 폴더.

추가 규칙 (`android_log.sample.json`을 `android_log.json`으로 복사해 고칩니다)

- `line_patterns` 기본으로 못 읽는 줄 형식을 정규식으로 더합니다. 이름 붙은 그룹 `ts`, `pid`, `tid`, `level`, `tag`, `msg`를 씁니다. 틀에 든 것은 안드로이드 스튜디오 Logcat 창에서 복사한 형식입니다.
- `continuation_lines` 머리말 없이 들여 쓴 줄(스택)을 앞 줄에 붙입니다.
- `events` 따로 찾고 싶은 로그를 `name`, `pattern`(필수), `tag`, `levels`로 적습니다. 보고서에 그 이름으로 집계됩니다.

## 2. weekly_report.py — 주간 보고 초안

지난 며칠의 내 git 커밋, Gerrit 변경, Jira 이슈를 모아 이슈 번호별로 묶습니다.

```
python weekly_report.py --demo
copy config.sample.json config.json      (값을 채운 뒤)
python weekly_report.py -o weekly.md
python weekly_report.py --prompt -o weekly_prompt.md
```

- `--demo` 접속 없이 가짜 자료로 모양만 봅니다.
- `--prompt` 사내 AI 대화창에 그대로 붙여 넣을 주문서를 맨 위에 붙입니다.
- `--only git,gerrit` 일부만 가져옵니다.
- `--days 14` 기간을 바꿉니다.

config.json 채우는 법

- `git_repos` 내 PC의 저장소 경로들. `author`를 비우면 저장소의 `user.email`로 찾습니다.
- `gerrit.url`, `gerrit.user` Gerrit 주소와 아이디. 비밀번호는 Gerrit 설정 화면의 HTTP 비밀번호입니다. 옛 버전이면 `"auth": "digest"`.
- `jira.url`, `jira.user` Jira 주소와 아이디. 개인 토큰을 쓰면 `"auth": "bearer"`(아이디 불필요).
- `password_env` 비밀번호를 담아 둔 환경 변수 이름. 없으면 실행할 때 물어봅니다. 비밀번호는 파일에 적지 않습니다.
- `auth`에는 `basic`, `digest`, `bearer`, `none`을 쓸 수 있습니다. 쿠키·SSO처럼 다른 방식이면 `"auth": "none"`에 `"headers": {"Cookie": "${환경변수이름}"}`처럼 직접 넣습니다.
- `gerrit.query_mine`, `gerrit.query_reviewed`, `jira.jql` 가져올 범위. `{days}`는 기간으로 바뀝니다.
- `gerrit.api_prefix`, `jira.api_path` 서버 주소 모양이 다를 때.
- `report.title`, `report.sections` 보고서 제목과 칸 이름. `extra`에 적은 칸은 빈 칸으로 붙습니다.
- `report.issue_key_pattern` 이슈 번호 규칙(정규식). 커밋 제목에 없으면 본문에서도 찾습니다.
- `prompt_file` `--prompt`에 쓸 주문서 글 파일. 비우면 기본 문구를 씁니다.
- `ssl.ca_file` 사내 인증서 파일 경로. 인증서 오류가 날 때 넣습니다. 그래도 안 되면 `"verify": false`.
- `no_proxy` 사내 주소인데 프록시를 타서 실패하면 `true`.

한 곳이 실패해도 나머지로 초안을 만들고, 실패한 곳은 맨 위에 적습니다.
`config.json`은 `.gitignore`에 들어 있어 저장소에 올라가지 않습니다.

## 3. mask.py — 가림 도구

AI에 붙여 넣기 전에 사내 이름을 `PKG_001` 같은 가짜 이름으로 바꾸고, 답을 받은 뒤 되돌립니다.

```
copy rules.sample.json rules.json        (우리 회사 이름으로 고친 뒤)
python mask.py mask crash.txt -o crash_masked.txt
python mask.py unmask answer.txt -o answer_restored.txt
```

- 기본으로 가리는 것: 메일 주소, URL의 호스트, MAC, IP (127.0.0.1 등은 그대로)
- `rules.json`의 `words`에는 그대로 찾을 낱말, `patterns`에는 정규식을 분류 이름 아래에 적습니다.
- 같은 이름은 항상 같은 가짜 이름으로 바뀝니다. 대응표는 `mask_map.json`에 쌓입니다.
- `mask_map.json`과 `rules.json`은 그 PC에만 둡니다. `.gitignore`에 들어 있습니다.

규칙에 없는 이름은 가려지지 않습니다. 붙여 넣기 전에 결과를 한 번 훑어보세요.
