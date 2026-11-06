# 무료 테스트 배포로 변경됨

현재 render.yaml은 Free 웹서비스 1개만 생성하며 영구 디스크를 사용하지 않습니다. 아래 유료 운영 안내는 추후 전환 시 참고용입니다. 15분간 접속이 없으면 절전 상태가 되며, 절전·재시작·재배포 시 파일과 편집 내용이 사라집니다. 완성한 덱은 즉시 다운로드하세요. CLOVA OCR 비용과 플랫폼 사용량 한도는 별도입니다.

# MCQ를 Render에 배포하기

Render 전용 설정이 준비되어 있습니다. 직접 서버를 설치하거나 SSH에 접속할 필요가 없습니다. 실제 서비스 생성에는 GitHub 저장소 연결과 Render 계정이 필요합니다.

## 1. GitHub 저장소 준비

GitHub에서 `mcq-web`이라는 **비공개(Private)** 저장소를 만듭니다. 압축을 풀고 `mcq-web` 폴더 안의 파일을 저장소 최상위에 올립니다. 최상위에 `render.yaml`, `Dockerfile`, `backend`, `frontend`가 있어야 합니다. ZIP 파일 자체를 올리면 배포되지 않습니다.

현재 패키지는 실행 데이터와 비밀키를 포함하지 않습니다. 앞으로도 `.env`, `data`, `node_modules`는 올리지 마세요. `.env.example`은 빈 설정 양식이므로 포함합니다.

ChatGPT에서 업로드를 이어서 진행하려면 GitHub 연결 설정에서 해당 저장소 접근을 허용하고 저장소 주소를 알려주세요. 저장소를 공개로 바꿀 필요는 없습니다.

## 2. Render 연결

1. https://dashboard.render.com/ 에 로그인합니다.
2. **New → Blueprint**에서 GitHub 저장소를 연결합니다. GitHub 권한은 이 저장소에만 부여해도 됩니다.
3. 준비한 저장소를 선택하고 Blueprint 경로 `render.yaml`을 사용합니다.
4. 서비스와 디스크에 표시되는 비용을 확인하고 배포합니다. 이 설정은 무료 체험 구성이 아닙니다.

설정 내용:

| 항목 | 값 |
|---|---|
| 서비스 | `mcq-web` |
| 실행 방식 | Docker, Python 프로세스 1개 |
| 위치 | Singapore |
| 인스턴스 | Starter |
| 영구 디스크 | 1GB, `/data` |
| 상태 확인 | `/api/config` |
| 접속 코드 | Render가 무작위 생성 |
| OCR 호출 한도 | 서버 전체 하루 50회 시도 |
| 자동 재배포 | 꺼짐 — 변경 후 수동 배포 |

소규모 테스트 운영을 위한 시작 구성입니다. 파일이 많으면 저장 공간 또는 메모리를 늘려야 할 수 있습니다. 초기 인스턴스 크기는 실제 PDF 처리량을 검증한 뒤 조정합니다.

최신 요금은 https://render.com/pricing 에서 확인하세요. 서비스·디스크 비용 외에 초과 사용량, 세금, CLOVA 이용료가 발생할 수 있습니다. 결제 금액은 Render 화면에서 최종 확인합니다.

## 3. API 없이 먼저 접속 확인

배포가 Live로 바뀌면 Render 서비스 화면의 `https://…onrender.com` 주소를 엽니다. Environment에서 자동 생성된 `MCQ_ACCESS_CODE` 값을 확인하여 MCQ 첫 화면에 입력합니다. 이 코드는 허용할 사용자에게만 전달합니다.

**샘플 문제로 먼저 둘러보기 → 원본 확인·검토 완료 → 덱 다운로드**로 기본 동작을 확인합니다. 기존 Anki 앱에 가져와 이미지·선지·정답을 확인하세요. 여기까지는 네이버 API가 필요하지 않습니다.

## 4. CLOVA 연결

Render 서비스의 **Environment**에서 다음 값을 추가합니다.

- `CLOVA_OCR_URL`: General OCR의 전체 API Gateway Invoke URL
- `CLOVA_OCR_SECRET`: OCR 도메인의 Secret Key

저장하고 재배포합니다. 키를 GitHub 코드나 채팅에 넣지 마세요. 두 값이 준비되면 MCQ 화면의 OCR 옵션이 활성화됩니다. 실제 시험지 한 장으로 인식·분리 결과를 확인한 뒤 사용 범위를 늘리세요.

## 5. 운영 확인

- 업로드·저장 후 수동 재배포하여 같은 브라우저에서 작업이 유지되는지 확인합니다.
- 원본을 삭제하려면 앱의 작업 삭제 기능을 사용합니다. 약 24시간 후 자동 정리도 동작합니다.
- 오류가 나면 Render의 Logs에서 확인하되 비밀키나 시험지 내용은 공유하지 않습니다.
- `Permission denied: /data`가 발생하면 디스크 쓰기 권한을 확인해야 합니다. 런타임은 Docker의 `mcq` 사용자(UID 10001)로 실행됩니다.
- 단일 프로세스 작업 큐를 사용하므로 인스턴스/워커 수를 임의로 늘리지 마세요.
- 배포 중 진행 중이던 OCR 작업은 중단될 수 있습니다. 사용 중인 작업을 마친 뒤 재배포하세요.

## 현재 완료 상태

배포 파일 준비 및 로컬 YAML 검증 완료. GitHub 원격 업로드, Render 서비스 생성, 실제 컨테이너 실행·OCR 호출은 아직 수행하지 않았습니다.

공식 문서: https://render.com/docs/blueprint-spec · https://render.com/docs/docker · https://render.com/docs/disks
