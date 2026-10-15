# 로컬 배포 패키지 만들기

이 명령은 로컬 `dist/`에 파일을 만들 뿐, 스토어 등록·업로드·결제·게시·레지스트리 등록을 하지 않습니다.

## 확장 ZIP

```powershell
python scripts/build_release.py
```

결과: `dist/moa-chrome-0.5.0.zip`, `dist/SHA256SUMS.txt`.

필요한 확장 파일만 허용 목록으로 묶습니다. `.env`, DB, 설치 PC 경로, 테스트 자료, 스크린샷은 확장 ZIP에 포함하지 않습니다. 공개 키에서 파생한 ID와 서버/프레임 origin의 일치, 권한 변경, 비밀정보 패턴도 확인합니다. 저장소를 통째로 압축해 배포하지 마세요.

## Python 포함 Windows 시험 패키지

Windows에서 다음을 실행합니다. 가상 환경은 빌드 도구 전용이며 사용자의 전역 Python을 변경하지 않습니다.

```powershell
python -m venv build/venv
build/venv/Scripts/python -m pip install -r requirements-build.txt
build/venv/Scripts/python scripts/build_release.py --windows
```

결과: 확장 ZIP, `dist/moa-windows-0.7.0-unsigned.zip`, `dist/SHA256SUMS.txt`.

Windows ZIP에는 Python 런타임, `MoaHelper.exe`, 로컬 UI, `Install.cmd`, `Uninstall.cmd`, 개인정보·보안 안내가 포함됩니다. 실제 키·주문 DB·원본 `.env`는 포함하지 않습니다. 사용자는 전체 압축을 풀고 `Install.cmd`를 한 번 실행합니다. 설치 위치가 바뀌면 다시 등록해야 합니다. 소스 버전과 병행 설치할 필요는 없습니다.

빌드 중 임시 번들에서 **Python 경로가 없는 PATH**로 `--self-test`를 실행해 번들 UI와 임시 localhost HTTP 응답을 확인합니다. 키 저장소·DB·증권사 API·레지스트리에는 접근하지 않습니다. 이 검사는 별도 Python이 없는 깨끗한 PC에서 실제 Chrome 설치 과정을 확인한 것과 같지는 않습니다.

패키지는 **코드 서명되지 않은 시험 배포본**입니다. 서명된 설치 프로그램, 자동 업데이트, 사용자 주문 기록 마이그레이션은 아직 제공하지 않습니다. 보안 경고를 끄거나 우회하는 설치 절차는 제공하지 않습니다. 코드 서명과 최종 배포 승인 후 정식 배포 경로를 결정하세요.

버전 업데이트 전에 소스/스토어/Windows 도구의 확장 ID가 일치해야 합니다. 실제 스토어 ID 전환은 [REVIEW.md](REVIEW.md#스토어-id가-정해진-후)를 따릅니다.

## 검증

```powershell
python -m unittest discover -s tests -q
node --test tests/test_symbol_sync.cjs tests/test_launcher.cjs tests/test_demo.cjs
python scripts/check_public_tree.py --staged
```

CI는 Windows와 Linux에서 테스트·확장 패키징을 수행하고 Windows에서 Python 포함 ZIP을 빌드/자체 검사합니다. CI 또한 스토어 제출이나 게시를 하지 않습니다.
