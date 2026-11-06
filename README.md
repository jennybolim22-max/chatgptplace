# MCQ · Make Cards Quickly

시험지 PDF·PNG·JPG를 원본 이미지와 객관식 선지가 있는 Anki 덱으로 만드는 웹서비스입니다. React 화면과 Python/FastAPI 서버로 구성되며, 자체 서버에서 실행합니다. 브라우저에서는 별도 OCR 프로그램이 필요하지 않습니다.

## 구현 범위

- 파일 업로드, PDF 페이지 이미지 변환, 처리 상태 표시
- CLOVA General OCR V2 연결: 한영 혼합 텍스트와 좌표 추출
- 단일 열 시험지의 문제 번호 기반 분리 및 다음 페이지 연결
- 원본 대조, 앞면 경계 지정, 문제 나누기·합치기, 페이지 영역 연결·자르기
- 2~10개 선지 편집, 단일·복수 정답, 파란 글자 정답 후보
- 누락·번호 불일치·낮은 신뢰도·일부 의심 문자를 검토 대상으로 표시
- 검토한 문제를 실제 `.apkg`로 내보내기, 카드 미리보기
- API 키 없이 쓸 수 있는 수동 편집과 샘플 문제
- 브라우저별 작업 분리, 선택적 공용 접속 코드, 자동 자료 정리, OCR 일일 한도

정답을 추론하거나 `OH → 애`처럼 문자를 일괄 교체하지 않습니다. 원본 대조 후 사용자가 확정합니다. 기존 Barley 노트 유형에 의존하지 않는 독립된 MCQ 카드 템플릿을 포함합니다.

## 서버 관리 없이 배포: Render

`RENDER_DEPLOY.md`의 순서대로 GitHub와 Render를 연결합니다. `render.yaml`에 유료 Starter 서비스, 영구 디스크, HTTPS 쿠키와 접속 코드가 설정되어 있습니다. 네이버 키 없이 먼저 배포하고 나중에 Render 환경변수에 추가할 수 있습니다. 실제 서비스 생성 전 비용을 확인하세요.

## 직접 실행: Docker Compose

Docker Engine/Desktop와 Compose가 준비된 컴퓨터 또는 서버에서 프로젝트 폴더를 엽니다.

```bash
cp .env.example .env
docker compose up -d --build
```

브라우저에서 `http://localhost:8080`에 접속합니다. **샘플 문제로 먼저 둘러보기**를 누르면 OCR 없이 편집·다운로드를 체험할 수 있습니다. Windows PowerShell에서는 첫 명령 대신 `Copy-Item .env.example .env`를 사용합니다.

- `.env`의 OCR 두 항목이 비어 있어도 수동 편집은 작동합니다.
- 서버에 배포한 경우 기본 포트는 서버 내부에서만 접근할 수 있습니다. 아래 서버 배포 항목을 참고하세요.
- 시작/종료: `docker compose up -d`, `docker compose down`
- 상태/로그: `docker compose ps`, `docker compose logs --tail=100 app`
- 환경변수 변경 후: `docker compose up -d --force-recreate app`
- `docker compose down -v`는 작업 데이터 볼륨까지 삭제합니다.

## CLOVA OCR 연결

NAVER Cloud의 **CLOVA General OCR**에서 API Gateway Invoke URL과 Secret Key를 발급받아 서버의 `.env`에 입력합니다. IAM Access Key/Secret Key가 아니라 OCR 도메인의 Secret Key를 사용합니다.

```dotenv
CLOVA_OCR_URL=https://발급받은주소.apigw.ntruss.com/발급받은경로
CLOVA_OCR_SECRET=발급받은_OCR_Secret_Key
OCR_DAILY_LIMIT=200
```

위 URL은 형식 예시입니다. 콘솔에서 받은 전체 URL을 그대로 넣으세요. 구현은 `https://*.apigw.ntruss.com` 주소만 허용합니다. 다른 유형의 엔드포인트를 받았다면 주소 검증 부분을 확인해야 합니다.

키는 서버에서만 읽습니다. 프런트엔드 코드, `VITE_` 환경변수, Git, 채팅에 비밀키를 넣지 마세요. 실제 네이버 전송은 사용자가 OCR 동의를 하고 자동 변환 또는 전체 OCR을 실행할 때 발생합니다.

- V2 JSON 요청에 PNG 페이지 한 장씩 Base64로 보냅니다. 언어는 `ko`이며 공식 API의 한국어·영어 인식을 사용합니다.
- 호출 제한은 서버 전체 UTC 날짜 기준 요청 시도 수입니다. 실패한 요청도 횟수에 포함됩니다. 실제 요금 상한을 보장하는 기능은 아니므로 네이버 콘솔 사용량도 확인하세요.
- 성공한 페이지 결과는 해당 작업에 캐시합니다. OCR 재실행은 캐시를 재사용하고 미완료 페이지만 다시 요청합니다.
- 전체 OCR 재실행은 수동 편집한 문제 구성을 새 인식 결과로 바꿉니다. 실행 전에 화면에서 확인합니다.
- 공식 API 문서: https://api.ncloud-docs.com/docs/ai-application-service-ocr-ocr

## 할당 서버 배포

기본 구성은 Linux 서버에서 Docker Compose로 실행하고, 서버의 HTTPS 리버스 프록시가 `127.0.0.1:8080`으로 연결하는 방식입니다. 프로젝트 내부 Nginx가 업로드 크기와 요청 시간을 설정합니다. HTTPS 인증서는 기존 서버/호스팅 관리 화면에서 연결해야 합니다.

1. 프로젝트를 서버에 복사하고 `.env`를 만듭니다.
2. 공유하기 전에 `MCQ_ACCESS_CODE`에 긴 임의의 공용 접속 코드를 설정합니다. 이는 회원 계정 기능이 아니라 소규모 사용자를 위한 접근 제한입니다.
3. Docker Compose로 실행하고 `/api/config` 및 샘플 덱을 확인합니다.
4. 도메인의 HTTPS 프록시 대상을 서버의 `127.0.0.1:8080`으로 지정합니다. 기존 프록시도 업로드 32MB 이상, 읽기 제한 시간 300초 이상을 허용해야 합니다.
5. HTTPS 연결이 된 후 `COOKIE_SECURE=true`로 변경하고 app을 재시작합니다. HTTP에서 true로 설정하면 세션이 유지되지 않을 수 있습니다.
6. 실제 시험지 1개로 OCR과 Anki 가져오기를 검증한 뒤 사용자를 안내합니다.

공개 서버 연결 정보는 이 프로젝트에 포함되지 않습니다. Docker가 없는 서버, 학교 공용 서버의 포트 제한, 기존 Nginx 구성 등에 따라 배포 설정이 달라집니다. 컨테이너는 비루트 사용자로 실행됩니다.

**운영 제약:** 이 버전은 Uvicorn 프로세스 1개로 실행해야 합니다. 작업 큐와 PDF 렌더링 잠금이 프로세스 내부에 있습니다. 여러 워커/서버로 확장하려면 외부 작업 큐·공유 저장소로 바꿔야 합니다. PDF 렌더링은 스레드 간 직렬화합니다.

## Docker 없이 실행

Python 3.12와 Node.js 22 이상을 사용합니다. 배포 ZIP에는 빌드된 화면(`frontend/dist`)도 들어 있으므로, 화면을 수정하지 않을 때는 npm 명령을 생략할 수 있습니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

먼저 `.env.example`을 `.env`로 복사하세요. Windows PowerShell의 가상환경 활성화는 `.venv\Scripts\Activate.ps1`입니다. 접속 주소는 `http://localhost:8000`입니다. 개발 시 별도 터미널에서 `npm run dev --prefix frontend`를 실행하면 Vite 화면의 `/api` 요청은 8000번 서버로 전달됩니다.

## 사용 순서

1. 시험지와 덱 이름을 선택합니다. API 연결 후에는 자동 문자 인식을 켤 수 있습니다.
2. 원본을 보고 문제 분리를 확인합니다. 한 페이지 전체가 한 문제로 잡혔다면 **문제 나누기**로 분할합니다.
3. 문제를 넘겨 연결해야 하면 **다음과 합치기** 또는 **페이지 연결 및 자르기**를 사용합니다. 나누기·합치기는 기존 선지와 정답 입력을 초기화합니다.
4. 원본에서 선지가 시작되는 위치 위쪽을 클릭하여 앞면 경계를 지정합니다. 경계 위 이미지가 Anki 질문 앞면이 됩니다.
5. 선지 개수와 내용을 수정하고 정답 번호를 선택합니다. 여러 번호를 선택하면 복수 정답 카드가 됩니다.
6. **원본 확인 · 검토 완료**를 누릅니다. 내보낼 모든 문제가 검토 완료되면 다운로드 버튼이 활성화됩니다. 불필요한 문제는 포함 체크를 해제합니다.
7. `.apkg`를 기존 Anki 앱에서 가져옵니다. 앞면에서 선지를 고르고 Anki의 답 보기로 정답을 확인합니다.

영역을 변경한 경우 **변경사항 저장**을 눌러 원본 합성 이미지를 갱신하세요. 동일 작업을 여러 탭에서 수정해 충돌하면 마지막 화면을 다시 열어야 합니다. 계정 동기화가 없으므로 작업 목록은 같은 브라우저 세션에서만 접근할 수 있습니다.

## 현재 제한

- 파일 하나당 30MB, PDF 50페이지, 브라우저별 작업 5개, 서버 전체 100개 작업
- 단일 열 문항을 우선 지원합니다. `122 문제...`, `122. 문제...` 형태의 문제 번호와 `1)`, `①` 형태의 선지 번호를 기준으로 분리합니다.
- `1. 선지` 형식, 다단 편집, 표·수식·머리말·각주, 문항 번호 없는 시험지는 자동 분리가 부정확할 수 있어 수동 검토가 필요합니다.
- 한자가 실제 문항에 있는 경우에도 검토 표시가 생길 수 있습니다. 파란색은 정답 후보일 뿐이며 색상의 의미를 자동으로 확정하지 않습니다.
- 원본은 웹용 이미지로 렌더링하므로 작은 글자, 저해상도 스캔은 정확도에 영향을 줍니다.
- 자료는 마지막 서버 저장/처리 후 약 24시간 뒤 정리합니다. 정리 작업은 10분 간격입니다. 중요한 덱은 내려받으세요.
- 회원가입, 학습 통계, Anki 계정 직접 동기화는 포함하지 않습니다.
- 실제 CLOVA 응답 품질과 Mac/Windows의 Anki 앱별 카드 동작은 API 키 연결 및 실기기 검증이 남아 있습니다.

## 코드 구성

| 경로 | 역할 |
|---|---|
| `frontend/src/main.jsx` | 업로드, 편집, 미리보기, 다운로드 화면 |
| `frontend/src/style.css` | 반응형 UI 스타일 |
| `backend/main.py` | API, 세션, 작업 저장·처리, OCR 요청 |
| `backend/engine.py` | PDF 렌더링, 분리, 선지 추출, Anki 템플릿·덱 생성 |
| `tests/test_app.py` | 주요 API·데이터 흐름 자동 테스트 |
| `Dockerfile`, `compose.yaml`, `deploy/nginx.conf` | 서버 실행 구성 |
| `.env.example` | 환경변수 양식 |
| `TESTING.md` | 검증 결과와 남은 확인 항목 |

## 테스트 실행

```bash
pip install pytest
python -m pytest tests -q
```

테스트는 임시 데이터 폴더와 가짜 OCR 응답을 사용합니다. 실제 OCR 비용은 발생하지 않습니다.
