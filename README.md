# work_tools

사내에서 쓰는 작은 도구 세 개입니다.

- 파이썬 표준 라이브러리만 씁니다. 설치할 것이 없습니다(파이썬 3.6 이상).
- 도구 하나가 파일 하나입니다. 필요한 파일만 복사해도 됩니다.
- 사내 주소·계정·프로젝트 이름은 코드에 없습니다. 회사 PC에서 설정 파일에 채웁니다.
- `android_log.py`와 `mask.py`는 네트워크를 쓰지 않습니다. `weekly_report.py`는 설정 파일에 적은 주소에만 접속합니다.

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

읽는 형식: `logcat -v threadtime`(기본), `-v time`, `-v brief`, 연도·uid가 붙은 것, zip, gz, 폴더.
안드로이드 스튜디오 Logcat 창에서 복사한 형식은 읽지 못합니다. `adb logcat`으로 받은 것을 넣어 주세요.

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
