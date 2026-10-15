# 심사 및 배포 확인 문서

상태: **등록 전 준비**. 결제·스토어 업로드·게시·서명은 아직 하지 않았습니다. 데모는 모든 사용자에게 제공되며 심사자만 다른 기능을 보게 하는 코드가 없습니다.

## 단일 목적

토스증권 웹에서 선택한 종목을 사용자의 로컬 투자 데스크와 연결하고, 같은 탭 옆에서 계좌 조회와 사용자가 확인한 소수점 분할 주문을 수행하도록 돕습니다.

## 권한 설명

| 권한/호스트 | 사용 이유 |
| --- | --- |
| `storage` | 종목 동기화 on/off, 검증된 종목 코드 캐시, 현재 탭 연결 정보. API 키는 저장하지 않음 |
| `sidePanel` | 현재 Chrome 창의 토스 탭 옆에 모아 UI 표시 |
| `nativeMessaging` | 고정된 `com.moa_invest.launcher` 연결 도구에 `ensure-server` 명령만 전송. 키·주문 요청이나 임의 실행 명령은 지원하지 않음 |
| `https://tossinvest.com/*`, `https://www.tossinvest.com/*` | 토스 종목 URL/링크의 변경을 읽고 검증된 다른 종목 페이지로 이동. 주문 버튼·입력·쿠키를 조작하지 않음 |
| `https://wts-info-api.tossinvest.com/*` | 선택한 티커와 종목 코드 변환용 공개 메타데이터 GET. `credentials: omit` 사용 |
| `http://127.0.0.1:8765/*`, `http://localhost:8765/*` | 모아 로컬 탭 인식과 선택 종목 연결. 패널 프레임 주소는 `127.0.0.1`로 고정 |

전체 사이트·`history`·`cookies`·`debugger`·클립보드 권한을 요구하지 않습니다. 실제로 쓰지 않는 권한을 나중 기능을 위해 미리 추가하지 않습니다.

## 데이터 사용 신고 초안

`PRIVACY.md`가 기준입니다. **개발자 서버가 없다는 이유로 무조건 '데이터 사용 없음'을 선택하지 마세요.** 등록 시 최신 체크박스 정의와 아래 처리 범위를 대조합니다.

- 웹 탐색/사용자 활동: 허용된 토스/모아 탭의 URL·제목·ID와 선택 종목. 일반 방문 이력 전체는 읽지 않음.
- 인증 정보: PC 연결 도구가 API 키·토큰 처리. 확장 JavaScript/저장소로 전달하지 않음.
- 금융 정보: PC 서버와 격리된 로컬 화면에서 계좌·잔액·보유 내역·주문을 처리.
- 광고·판매·신용 평가 목적 사용 없음. 핵심 기능 이외 목적 전송 없음.
- 외부 요청 대상은 토스의 공개 종목 조회 API와 공식 Open API. 안내 링크 클릭 시 GitHub 접속.

스토어 개인정보 문구는 확장 부분과 PC 도구의 차이를 설명하되 전체 제품의 처리 내용을 숨기지 않습니다.

## 실행 코드·로컬 서버 공개

확장 권한이 있는 페이지의 스크립트는 ZIP 안에 포함됩니다. `eval`, 동적 원격 스크립트, 원격 설정 기반 명령 실행은 사용하지 않습니다. **그러나 패널은 별도 출처의 로컬 HTTP iframe에서 Python 도구가 제공한 HTML/JS UI를 로드합니다.** 따라서 설명 없이 '외부 코드 전혀 없음'으로 신고하지 않습니다.

이 프레임은 확장 API에 접근할 수 없으며, 서버가 허용하는 부모는 고정된 모아 확장 origin뿐입니다. 프레임과 확장 메시지 경계는 종목과 상태만 허용합니다. Python 도구의 소스, 동일 버전 패키지와 이 프로토콜을 심사 자료로 함께 제공합니다. 공식 MV3 정책은 확장 API에서 격리된 iframe을 구분하지만, 기능 파악 가능성과 데이터 정책 준수를 요구합니다. 이 해석이 승인 보장은 아니며 최종 신고·심사는 별도로 확인해야 합니다.

## 키나 실제 주문 없이 확인하기

1. 확장 폴더를 로드하고 아이콘 → **사용 안내 · 개인정보**를 엽니다.
2. **연결 없이 데모 보기**를 누릅니다. Python/PC 도구/API 키/토스 로그인이 필요 없습니다.
3. 가상 종목을 고르고 매수·매도, 총금액·총수량을 바꿉니다. $100은 $9 × 11회 + $1, 합계 12회입니다. 데모는 계산과 화면 예시만 제공하며 실제 계좌·주문 검증을 대신하지 않습니다.
4. 개발자 도구에서 데모는 외부 요청·Chrome Native Messaging 호출을 하지 않는지 확인합니다. CSP의 `connect-src 'none'`, `frame-src 'none'`이 네트워크/프레임 연결을 차단합니다.
5. 실제 패널: Windows 시험 패키지를 풀고 `MoaHelper.exe --self-test`로 가짜 계좌 없이 로컬 HTTP/번들 UI만 확인합니다. 이 검사에는 레지스트리·키·DB·증권사 호출이 없습니다.
6. `Install.cmd`로 연결 도구 등록 후 패널을 열어 자동 시작과 키 입력 화면을 확인합니다. 심사 전용 Windows 사용자처럼 기존 키가 없는 환경을 사용합니다. 실제 개인 키를 심사 자료로 제공하지 않습니다.
7. 실주문 검증 대신 `python -m unittest discover -s tests -q`로 모의 브로커의 중복 방지, 불확실한 결과, 키 변경 차단, 분할 매수/매도 검사를 실행합니다. 이 테스트가 실제 API 심사의 대체 승인을 의미하지는 않습니다.

## 스토어 ID가 정해진 후

현재 `manifest.key`는 로드 개발용 ID를 고정합니다. 향후 Google 대시보드에서 할당한 실제 ID와 동일하다고 가정하지 않습니다. 공개 키를 확보한 뒤 아래 세 곳을 함께 변경하고 빌드 검사를 통과시킵니다.

1. `browser_extension/manifest.json`의 공개 `key`.
2. `order_ui/extension.py`의 정확한 origin (native host 허용 목록과 서버 CSP도 여기에서 파생).
3. `order_ui/static/panel-bridge.js`의 정확한 부모 origin.

스토어 ID가 바뀐 PC에서는 연결 도구를 다시 등록하고 기존 개발 확장의 제거·데이터 보존을 안내해야 합니다. 와일드카드 origin 허용으로 우회하지 않습니다. 이 단계는 실제 스토어 등록을 결정한 뒤 수행합니다.

## 아직 남은 출시 조건

- 개발자 계정·2단계 인증·배포자 연락처와 실제 개인정보 URL 최종 확인.
- Windows 실행 파일의 코드 서명과 설치/업데이트 배포 경로 결정. 현재 ZIP은 **unsigned 시험 배포본**.
- 별도 Python이 없는 깨끗한 Windows PC에서 설치·재부팅·재등록·제거 검증.
- 실제 Chrome의 패널·nativeMessaging·양방향 종목 선택 실사용 검증.
- 기존 주문 기록/키가 있는 설치에서 업데이트·중복 실행·기록 보존 검증.
- 가상 데이터 스크린샷 최종 규격·소개문·권한/데이터 신고 대조.
- 로컬 프레임/PC 도구 전체 기능을 재현할 수 있는 제출 자료 확보, 웹 조회 endpoint 사용 범위·관련 서비스 조건 확인.
- 배포 승인 전에는 스토어 업로드/제출/결제/게시하지 않음.

## 공식 참고 자료 (2026-10-16 확인)

- [개인정보 및 권한 신고](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy)
- [Manifest V3 코드 요구 사항과 격리된 iframe](https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements)
- [확장 공개 키와 ID 일치](https://developer.chrome.com/docs/extensions/reference/manifest/key)
- [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [스토어 등록 절차](https://developer.chrome.com/docs/webstore/publish)
