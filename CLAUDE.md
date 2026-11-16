# 이 폴더에서 일하는 AI에게

이 도구들은 회사 밖에서, 사내 정보를 하나도 모르는 상태로 만든 **공용 도구**입니다. 어느 회사에서든 쓸 수 있게 만들었고, 사내에 맞추는 일은 전부 **설정 파일**로 합니다.

사용자는 안드로이드 개발자이고 사내에서 git·Gerrit·Jira를 씁니다. 한국어 존댓말로 답해 주세요.

## 꼭 지킬 것

1. **코드(`*.py`)는 고치지 않습니다.** 사내에 맞추는 것은 설정 파일 세 개로만 합니다.
   - `config.json` — 주간 보고 (틀: `config.sample.json`)
   - `android_log.json` — 로그 분석 추가 규칙 (틀: `android_log.sample.json`)
   - `rules.json` — 가림 규칙 (틀: `rules.sample.json`)
2. **밖으로 내보내지 않습니다.** 이 폴더는 받아 온 사본이고, 받아 온 곳과 이어져 있지 않아야 합니다.
   - `git push`, 원격 추가, 업로드, 외부 전송을 하지 않습니다. 사용자가 시켜도 사내 값이 나갈 수 있다는 점을 먼저 알립니다.
   - 폴더에 `.git`이 있고 원격이 회사 밖 주소로 걸려 있으면 사용자에게 알리고 `git remote remove origin`을 권합니다.
3. 비밀번호와 토큰은 파일에 적지 않습니다. 환경 변수나 실행 중 입력으로만 받습니다.
4. 설정으로 안 되는 것이 나오면 코드를 고치지 말고, 아래 「설정으로 안 될 때」대로 메모만 남깁니다.

## 맞추는 순서

### 1. 그대로 도는지

```
python --version
python tests/run_tests.py
```

`전부 통과`가 나와야 합니다. 3.6 이상이면 돌게 만들었습니다. 실패하면 오류를 사용자에게 보여 주고 메모에 적습니다.

### 2. android_log.py

사용자가 이미 원인을 아는 로그(logcat, bugreport zip, traces, tombstone)를 받아 돌리고, 아는 크래시·ANR이 빠짐없이 잡히는지 비교합니다.

안 맞을 때 `android_log.json`으로 할 수 있는 것

- **줄 형식이 달라 못 읽을 때**: `line_patterns`에 정규식을 넣습니다. 이름 붙은 그룹 `ts`, `pid`, `tid`, `level`, `tag`, `msg`를 씁니다(`msg`만 필수). 틀에 든 것은 안드로이드 스튜디오 Logcat 창 형식입니다.
- **스택이 머리말 없이 이어지는 형식**: `"continuation_lines": true`. 들여 쓴 줄을 앞 줄에 붙입니다.
- **사내에서 따로 찾는 로그**(제조사·프레임워크 태그, 특정 오류 문구): `events`에 `name`, `pattern`을 넣습니다. `tag`와 `levels`로 좁힐 수 있습니다. 보고서에 `name`으로 따로 집계됩니다.

기본으로 잡는 것은 자바 크래시, 네이티브 크래시, ANR, 워치독, OOM, 저메모리 종료, 프로세스 종료입니다. 커널 패닉과 SELinux 거부는 기본으로 잡지 않으니, 필요하면 `events`로 더합니다.

### 3. weekly_report.py

`config.sample.json`을 `config.json`으로 복사해 사용자와 채우고, 한 곳씩 붙입니다.

```
python weekly_report.py --only git
python weekly_report.py --only gerrit
python weekly_report.py --only jira
```

`config.json`으로 할 수 있는 것

- **Gerrit 인증**: `auth`에 `basic`(HTTP 비밀번호), `digest`(옛 버전), `bearer`, `none`. 주소 앞머리는 `api_prefix`(기본은 인증이 있으면 `/a`).
- **Jira 인증·주소**: `auth`에 `basic`, `bearer`(개인 토큰), `none`. 검색 주소는 `api_path`.
- **쿠키·SSO 등 다른 인증**: `"auth": "none"`으로 두고 `headers`에 직접 넣습니다. 값 안의 `${이름}`은 환경 변수로 바뀝니다. 예: `"headers": {"Cookie": "${GERRIT_COOKIE}"}`
- **가져올 범위**: Gerrit은 `query_mine`, `query_reviewed`, Jira는 `jql`. `{days}`는 기간으로 바뀝니다.
- **인증서·프록시**: `ssl.ca_file`, `ssl.verify`, `no_proxy`.
- **이슈 번호 규칙**: `report.issue_key_pattern`. 커밋 제목에 없으면 본문에서도 찾습니다.
- **보고 양식**: `report.title`, `report.sections`로 칸 이름을 바꾸고 `extra`로 빈 칸을 더합니다. 사용자가 실제로 내는 양식의 칸 이름을 물어 맞춥니다.
- **AI 주문서 문구**: `prompt_file`에 글 파일 경로를 넣으면 `--prompt`가 그 글을 씁니다.

### 4. mask.py

`rules.sample.json`을 `rules.json`으로 복사해 사내 패키지 접두어, 도메인, 프로젝트·사람 이름 규칙을 채웁니다. 실제 로그 하나를 가려 보고, 남은 사내 이름이 없는지 사용자와 훑어봅니다.

## 설정으로 안 될 때

코드를 고치지 않고 `NEEDS.md` 파일에 메모만 남깁니다. 사용자가 이 메모를 손으로 밖에 가져가 도구를 만든 쪽에 전하므로, **사내 값은 한 글자도 넣지 않습니다.**

- 무엇이 안 됐는지 (도구 이름, 한 문장)
- 필요한 것을 일반적인 말로 (예: 「줄 앞에 장비 번호 칸이 하나 더 붙는 형식」, 「로그인 뒤 받은 쿠키로만 접속되는 방식」)
- 형식 예시가 필요하면 값은 전부 지어낸 것으로 (`com.example.app`, `ABC-123`, `10.0.0.1`)
- 오류 메시지는 주소·이름을 `mask.py`로 가린 뒤에

메모를 쓴 뒤 사용자에게 내용을 보여 주고, 사내 값이 섞이지 않았는지 같이 확인합니다.
