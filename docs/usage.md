# 사용 가이드

[← 모아 소개로 돌아가기](../README.md)

## 실행과 화면 설정

`run.bat`은 추가 브라우저 탭 없이 서버만 실행합니다. 확장의 사이드 패널을 사용하거나, 별도 탭을 열려면 다음 명령을 사용하세요.

```powershell
python -m order_ui.server --open
```

주소: http://127.0.0.1:8765

- 화면 위 테마 선택: **시스템 / 라이트 / 다크**. 브라우저에 저장되고 시스템 모드에서는 OS 테마 변경도 따라갑니다.
- **매수 / 매도**, **총금액 / 총수량** 선택 → 종목·전체 규모 입력 → 미리보기 → 안내 체크 → 분할 주문 시작. 확인 문구를 타이핑할 필요는 없습니다.
- **내 투자**에서 실제 계좌의 보유 종목·수량·평가금·손익을 조회합니다. 종목 선택 시 주문창에 티커와 보유 수량·평균 매입가가 연결됩니다. 선택만으로 주문을 보내거나 입력 금액을 변경하지 않습니다.
- 평가금액/수익률/종목명 정렬, 종목 검색, 현재가/평가금 전환, 미국 USD/국내 KRW 조회를 지원합니다. 국내 종목은 조회 전용입니다. 목록은 페이지가 보일 때 30초마다 갱신하며 수동 새로고침도 가능합니다.
- 손익은 통화별 수수료 전 금액 기준입니다. 달러와 원화를 섞어 합산하거나 원화 환산 수익률을 달러 수익률로 표시하지 않습니다. API가 제공하지 않은 수치는 `—`로 표시합니다.
- 좁은 창에서는 보유 목록과 주문창을 2열로 유지하고, 620px 미만에서는 세로로 배치합니다. 다크 기본 배경은 `#101013`, 패널은 `#17171c`입니다.
- 앱의 **하루 누적 주문 한도와 총 주문 횟수 제한은 없습니다.** 실제 주문 가능 금액·매도 가능 수량과 증권사 제한은 적용됩니다.
- 주문 기록에 접수 건수와 금액/수량을 표시합니다. **남은 주문 중단**은 아직 전송하지 않은 주문을 멈추며 이미 전송한 주문을 취소하지 않습니다.
- 실행 중에는 Python 서버를 유지해야 합니다. 브라우저를 닫아도 서버가 살아 있으면 실행이 계속됩니다. 서버 종료 후 자동 재개하지 않습니다.

**실주문 켜기 / 실주문 끄기**는 서버 재시작 없이 변경됩니다. 주문 DB에 저장되어 같은 데이터 폴더를 쓰는 UI·CLI에서 공유합니다. 저장된 선택이 `TOSS_ORDER_EXECUTION_ENABLED`보다 우선하며 환경 변수는 최초 기본값입니다. 모드 변경 시 기존 미리보기는 만료되고 진행 중 분할 주문의 다음 전송도 중단합니다. 모드 변경 자체는 주문을 보내지 않습니다.

## 분할 방식

| 방향 | 입력 | 실제 API 요청 |
| --- | --- | --- |
| 매수 | 총금액 | `$9` 금액 주문 반복 + 마지막 잔액 |
| 매수 | 총수량 | 미리보기 현재가 × 수량을 센트 단위 올림한 **고정 총금액**으로 환산 후 `$9`씩 금액 주문 |
| 매도 | 총금액 | `$9` 금액 주문 반복 + 마지막 잔액 |
| 매도 | 총수량 | 각 주문 직전 현재가로 `$9 / 현재가`를 소수점 6자리 내림하여 수량 주문. 마지막 주문은 남은 수량 |

예: 총 `$100` → `$9 × 11회 + $1` = 12건. 주가 `$200`에서 `0.1주` 매도 → `0.045주 + 0.045주 + 0.01주` 예상. 가격이 달라지면 매도 수량 분할 횟수도 달라집니다.

API는 소수점 **수량 매수**를 지원하지 않아 매수의 목표 수량은 예상치입니다. 총수량 매수는 최종 확인한 예산을 유지하며 실제 체결 수량을 보장하지 않습니다. 수량 매도는 전부 접수되면 요청 수량 합계가 목표와 같지만 접수는 체결 완료가 아닙니다.

공식 수수료 안내는 **주문 건당 실제 체결금액 $10 이하**를 면제 기준으로 설명합니다. 이 앱은 여유를 두어 $9를 기준으로 분할합니다. 수량 시장가 주문은 체결 시세가 변하면 $10를 넘을 수 있고 세금·제비용은 별도입니다. 실제 면제 여부는 증권사 체결·수수료 내역을 확인해야 합니다.

## API 키 등록

Windows에서 화면의 **API 키 설정** 또는 사이드 패널의 같은 버튼을 누릅니다. Client ID와 Client Secret을 입력하면 계좌 조회로 검증한 뒤 `moa-invest/toss-api/v1` Windows 자격 증명에 한 쌍으로 저장합니다. 원본 프로그램의 저장 항목은 수정하지 않습니다.

저장 후 서버 재시작 없이 연결됩니다. 저장한 값은 다시 표시하지 않으며 입력칸은 전송·닫기 후 비웁니다. 다른 OS에서는 화면 저장을 지원하지 않고 환경 변수 설정을 사용합니다.

키 검증 시작 전에 실주문을 끄고 모든 미리보기를 만료시킵니다. 검증 실패 시 기존 키를 유지하지만 실주문은 꺼진 상태로 남습니다. 진행 중·불확실한 주문이 있으면 변경을 거절합니다. DB에 변경 중 상태를 먼저 기록하므로 프로세스 중단이나 Windows 저장 실패가 발생해도 주문을 차단합니다. **키 재등록**으로 복구하세요. 동일한 데이터 폴더를 사용하는 다른 서버/CLI는 이전 키로 계속 주문할 수 없으며 재시작해야 합니다. 별도 데이터 폴더나 원본 프로그램의 주문은 조율하지 않습니다.

새로 등록한 키의 OAuth 토큰은 메모리에만 유지하며 기존 평문 토큰 캐시 설정은 사용하지 않습니다. 등록 정보는 기존 환경 변수보다 우선하므로 환경 변수만 바꾸어 등록된 키를 교체할 수 없습니다.

## 기존 Windows 인증 공유

기존 프로그램이 `stock_llm_alert_project` 이름으로 저장한 `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`을 **Windows 자격 증명 관리자에서 직접 읽습니다.** 같은 Windows 사용자로 실행하면 재입력이 필요하지 않습니다. 키를 브라우저로 전달하거나 `.env`로 복사하지 않습니다.

OAuth 토큰은 기본적으로 메모리에만 보관합니다. 기존 프로그램과 토큰 발급을 조율해야 하는 경우에만 보호된 로컬 경로를 `TOSS_TOKEN_CACHE_PATH`로 명시할 수 있습니다. 이 호환용 파일은 평문 토큰이므로 공유·백업·공개 대상에서 제외해야 합니다. 자세한 경계와 웹 키 등록 계획은 [보안 안내](../SECURITY.md)를 확인하세요.

```env
TOSS_KEYRING_SERVICE=stock_llm_alert_project
# TOSS_TOKEN_CACHE_PATH=
TOSS_ORDER_EXECUTION_ENABLED=false
```

키 조회 우선순위: 모아 전용 Windows 저장 키 → 프로세스 환경 변수 → `.env` → Windows 사용자/시스템 환경 변수 → Windows 자격 증명 관리자. 다른 OS에서는 환경 변수 또는 `Settings` 주입을 사용합니다. 다른 PC에 옮길 때는 `.env.example`로 경로를 재설정하세요. 토큰·DB·`.env`는 Git에서 제외합니다.

## UI와 모듈의 분리

Windows Chrome 확장 자동 실행: 프로젝트의 `install-extension.bat`을 한 번 실행한 후 확장에서 패널이나 **새 탭으로 열기**를 사용하면 로컬 서버가 자동 시작됩니다. Python 3.11 이상은 계속 필요합니다. API 키는 기존 Windows 자격 증명 관리자에 남습니다. [등록·업데이트·해제 안내](../browser_extension/README.md#자동-실행-등록해제)

```text
toss_fractional/       재사용 가능한 독립 Python 라이브러리
  auth.py             OAuth·공유 토큰 캐시·파일 잠금
  credentials.py      Windows 저장 키 읽기
  http.py, client.py   HTTP 및 계좌·시세·주문 API
  config.py           설정 주입
  service.py          계좌·실행 모드·기존 단건 매수 호환 API
  batch.py            분할 계획·순차 실행·중단·진행 상태
  store.py            SQLite 상태·중복 방지
  cli.py              UI 없는 명령행 진입점
order_ui/
  server.py           로컬 HTTP 어댑터
  native_host.py      Chrome 요청으로 정해진 서버만 자동 실행
  static/             HTML / CSS / JavaScript UI
tests/                실제 주문 없이 동작하는 테스트
```

의존 방향: `UI → HTTP 어댑터 → 라이브러리 → Toss API`. 라이브러리는 UI나 원본 프로젝트를 import하지 않습니다. 기존 `FractionalBuyService.preview/submit`는 호환용 단건 매수 메서드이며 해당 메서드의 1회 최대 $9.99 설정은 분할 주문의 총액 제한이 아닙니다. 일일 제한 설정은 제거되어 이전 환경 변수는 적용되지 않습니다.

## 다른 Python 프로젝트에서 사용

```powershell
python -m pip install .
```

```python
from pathlib import Path
from toss_fractional import Settings, create_service
from toss_fractional.config import read_env

service = create_service(Settings.from_env(read_env(Path("path/to/.env"))))
preview = service.preview_batch(
    "AAPL", "100.00", account_seq="your-account-seq",
    side="BUY", basis="AMOUNT",  # SELL, QUANTITY도 지원
)
# 여기까지는 읽기와 로컬 미리보기 저장만 수행합니다.

# 사용자가 미리보기를 확인하고 실주문 모드를 활성화한 후에만 호출:
# result = service.start_batch(
#     preview["batchId"],
#     acknowledged=user_acknowledged,
#     background=False,  # 완료/중단까지 현재 호출에서 실행
# )
# status = service.batch_status(preview["batchId"])
# service.stop_batch(preview["batchId"])
```

`FractionalTradeService(broker, settings, store, interval=0.5)`로 브로커·저장소를 주입할 수 있습니다. `start_batch(background=True)` 기본값은 백그라운드 스레드이므로 호출한 프로세스를 유지해야 합니다. CLI는 `background=False`, HTTP 서버는 `True`를 사용합니다. 같은 계좌를 여러 프로세스에서 다루면 동일한 `TOSS_DATA_DIR`을 지정해 중복 방지 상태를 공유하세요. 다른 프로그램이 보내는 주문까지 조율하지는 않습니다.

## 명령행

```powershell
python -m toss_fractional setup
python -m toss_fractional holdings --account ACCOUNT_SEQ
python -m toss_fractional batch-preview AAPL 100 --side BUY --basis AMOUNT --account ACCOUNT_SEQ
python -m toss_fractional batch-preview AAPL 0.1 --side SELL --basis QUANTITY --account ACCOUNT_SEQ
python -m toss_fractional batch-history
python -m toss_fractional batch-status BATCH_ID
python -m toss_fractional batch-stop BATCH_ID
python -m toss_fractional orders --account ACCOUNT_SEQ --status OPEN
```

미리보기 유효 시간은 120초입니다. 실주문 모드에서 `--acknowledge`를 주어야 시작합니다. 기존 호출자와의 호환을 위해 `--confirm` 인수는 선택적으로 남아 있으며, 전달한 경우에만 일치를 검사합니다.

```powershell
python -m toss_fractional batch-start BATCH_ID --acknowledge
```

## 상태 처리

- 금액은 센트, 수량은 소수점 6자리까지 허용합니다. NaN·무한대·음수는 거절합니다. 입력 파싱 범위는 양수 10억 이하이며 하루 한도가 아닙니다.
- 시작 직전 전체 주문 가능 자원을, 각 전송 직전 잔액 또는 매도 가능 수량을 다시 확인합니다. 일부만 접수되고 나머지가 중단될 수 있습니다.
- 동일 계좌의 동시 분할 실행은 차단합니다. 같은 batchId를 다시 시작해도 이미 시도한 주문을 재전송하지 않습니다. 각각 고유하고 영속적인 35자 `clientOrderId`를 사용합니다.
- 주문 POST의 통신 실패·429·5xx에는 재시도하지 않습니다. 명시적 401 거절만 토큰 복구 후 한 번 재시도합니다.
- `RUNNING` 순차 전송, `STOPPING` 중단 요청, `STOPPED` 남은 주문 중단, `SUBMITTED` 전체 **접수**, `REJECTED` 거절로 중단입니다.
- `UNKNOWN`은 타임아웃·5xx·잘못된 응답 등으로 결과를 확정할 수 없는 상태입니다. 180초 이상 실행 heartbeat가 없으면 조회 시 `INTERRUPTED`로 표시하고 자동 재개하지 않습니다.
- 불확실한 상태는 같은 계좌의 추가 전송을 차단합니다. 이 버전은 자동 원장 대조·해제 기능이 없으므로 실제 주문 내역과 DB를 대조한 후 운영자가 복구해야 합니다.
- `batch_status`는 최근 자식 주문 20건을 반환하며 전체 기록은 SQLite에 유지합니다. UI의 접수 건수는 체결 건수가 아닙니다.
- 소수점 주문 시간은 미국 정규장 시작부터 종료 1시간 전까지이며 휴장·조기 폐장은 API가 최종 판정합니다.
- HTTP 서버는 `127.0.0.1`에만 바인딩하고 Host·Origin·CSRF를 검사합니다.
