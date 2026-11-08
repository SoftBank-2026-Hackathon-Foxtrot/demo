# 치이카와 LIVE 개발·시연

## 실행 중인 로컬 화면

- 단독 앱: http://localhost:8000
- Redis 이전 시연 AWS 앱: http://localhost:18800
- Redis 이전 시연 GCP 앱: http://localhost:18801

이전 시연 스택은 단독 앱과 별도 Compose 프로젝트 `chiikawa-live`를 사용한다. 서로 다른 PostgreSQL·Valkey·S3Mock을 쓰므로 로그인과 주문도 별개다. AWS/GCP는 로컬 컨테이너의 역할 이름이며 실제 클라우드 배포를 뜻하지 않는다. 방송 무대의 세 친구는 각기 다른 박자의 CSS 애니메이션으로 춤춘다. 무대 오른쪽 위에서 정지·재개할 수 있고, 기기의 동작 줄이기 설정을 존중한다.

## 단독 실행

### 로컬 주문 시연

기본 화면에는 실제 남은 재고와 주문 집계, 관객용 ‘1개 주문 요청’ 버튼을 표시합니다. 이 버튼은 기존 구매 API로 실제 1개 주문을 접수하며, 같은 회차에서 로그인한 사용자가 확정한 누적 수량을 DB에서 조회합니다. 새로고침 후에도 유지되고 다른 사용자의 주문은 합산하지 않습니다. 응답이 유실되면 같은 키로 주문을 재확인하며 품절 후에도 이미 접수된 주문은 재확인할 수 있습니다.

발표 시에는 상단 LIVE 설정을 열고 ‘시작 재고’ 입력칸에 시작 수량을 넣고 주문 시작을 누릅니다. 자동 주문 시작·초당 주문 수·정지는 모두 이 설정에서만 표시합니다. 설정을 닫아도 자동 주문은 계속되며 관객의 수동 주문과 함께 같은 재고를 사용합니다. 수량을 수정하면 별도 상품 ID로 새 회차를 만들며, 이전 회차의 주문·재고는 삭제하거나 덮어쓰지 않습니다. 정지 후 수정 없이 재개하면 같은 회차를 이어갑니다. 준비 요청과 주문 배치는 재시도 키를 유지하며, 품절 후 재시도도 같은 결과를 조회합니다.

자동 주문을 시작하면 LIVE 설정의 시작 버튼이 비활성 ‘주문 중’ 표시로 바뀝니다. 수동 정지는 LIVE 설정의 ‘주문 정지’에서만 할 수 있으며 채팅 봇 실행에는 영향을 주지 않습니다. 품절·오류·화면 이탈에 따른 자동 정지는 유지합니다.

라이브 배포에도 API 프로세스마다 `ENABLE_ORDER_DEMO=1`을 설정해야 합니다. 설정이 없으면 서버는 404를 반환합니다. 화면은 이제 비활성화/구버전 API와 일반 조회 실패를 구분해 표시합니다. 프론트만 배포해서는 이 기능이 활성화되지 않습니다.

### AWS·GCP 라이브 서버에 적용하기

설정 대상은 플랫폼 서버가 아니라 치이카와 앱이 실행되는 각 AWS·GCP VM의 `app-api` 컨테이너입니다. IaC의 `modules/app_runtime/boot.sh.tftpl`은 `/etc/foxtrot/common.env`와 `/etc/foxtrot/api.env`를 읽어 이 컨테이너를 생성합니다.

1. 환경별 배포 입력 JSON의 `app.api_env`에 `"ENABLE_ORDER_DEMO": "1"`을 추가합니다. 기존 키는 유지합니다. 프로비저너 API의 camelCase 입력에서는 `app.apiEnv`입니다. AWS·GCP 양쪽에 적용해야 트래픽이 이동해도 주문 API가 유지됩니다.
2. 이 변경으로 새 앱 이미지를 빌드하고 레지스트리에 올린 뒤, 각 환경의 앱 이미지도 새 버전으로 지정해 재배포합니다. 이 저장소의 Dockerfile은 프론트와 백엔드를 한 이미지에 포함합니다. 기존 주문 Worker도 같은 버전으로 배포하고 실행 상태를 확인합니다.
3. 이미 실행 중인 VM에서 수동 적용하는 경우 `/etc/foxtrot/api.env`에 아래 한 줄을 추가하거나 기존 값을 수정한 뒤, 기존 네트워크·포트·환경 파일·실행 명령을 유지하여 새 이미지로 `app-api`를 재생성합니다. `docker restart`만 하면 새 환경변수나 이미지가 반영되지 않습니다. 파일 수정만으로는 다음 IaC 배포에 유지되지 않으므로 1번도 필요합니다.

```env
ENABLE_ORDER_DEMO=1
```

앱 VM에서 컨테이너 내부의 이 값만 확인합니다. 다른 환경변수나 비밀값은 출력하지 않습니다.

```sh
sudo docker exec app-api printenv ENABLE_ORDER_DEMO
# 출력: 1
```

로그인 후 라이브 화면에서 남은 재고에 수량을 입력하고 주문 시작을 누릅니다. `/api/live/orders`가 200을 반환하고 확정 주문이 늘면서 재고가 감소하면 정상입니다. 404의 `order demo is disabled`는 플래그 미적용, API 경로 자체가 없는 404는 구버전 이미지 여부를 확인합니다. 401은 로그인 문제이며 DB/Redis 오류는 앱·Worker 로그에서 확인합니다. 기존 데이터를 지우는 `/seed`는 실행하지 않습니다. 프론트 개발 서버나 플랫폼 서버에 이 값을 넣어도 API 컨테이너에는 전달되지 않습니다.

### 관객 입장과 채팅

봇 조작부는 기본 화면에 표시하지 않습니다. 상단 로고 옆 LIVE 버튼을 누르면 설정 창에서 봇을 시작·정지하고 속도를 변경할 수 있습니다. 이는 화면에서 설정을 접는 기능이며 관리자 권한 제어를 대신하지 않습니다.

주문 카드 오른쪽 입장 QR은 현재 사이트 주소와 현재 시연 상품 ID를 포함합니다. 관객은 QR로 입장한 뒤 닉네임으로 로그인하면 같은 회차의 재고와 채팅을 봅니다. 별도 공개 주소가 필요하면 빌드 시 `VITE_PUBLIC_JOIN_URL`을 지정합니다. localhost/127.0.0.1 QR은 다른 휴대폰에서 접근할 수 없으므로 실제 시연에서는 공개 라이브 주소로 배포해야 합니다. QR에는 세션 토큰을 넣지 않습니다.

사람이 보낸 새 채팅마다 무대 안의 랜덤 위치에서 작은 별 입자가 흩어지는 효과가 약 2.6초간 나타납니다. 한 개씩 대기시키지 않고 최대 10건을 동시에 표시하며 불투명한 배경이나 말풍선 테두리를 사용하지 않습니다. 별 아래에는 닉네임과 짧은 채팅만 붙이고 입력창 영역은 피합니다. 자동 채팅은 기존 작은 채팅 흐름에 남습니다. 서버가 Pub/Sub 메시지의 source를 human/bot으로 지정하며 클라이언트가 보낸 구분 값이나 닉네임을 신뢰하지 않습니다. 기록을 다시 읽을 때는 효과를 재생하지 않습니다. 일반 메시지의 DB 저장과 전송 경로는 유지합니다.

`docker compose -f docker-compose.yml -f compose.orders.local.yml up -d --build app worker1 worker2`로 실행합니다. 화면 개발 서버는 `web`에서 `npm run dev -- --host 127.0.0.1 --port 5173 --strictPort`로 실행합니다. 기존 데이터는 초기화하지 않습니다. `/seed`를 호출하지 않고 시연 전용 상품(9000001, 최초 재고 100,000개)을 한 번만 추가합니다.

모바일 라이브 화면의 남은 재고·접수된 참여·확정 주문·처리 대기는 한 API의 DB 스냅샷을 1초 간격으로 읽습니다. 이전 조회가 끝나야 다음 조회를 예약하며 화면 이탈/백그라운드에서는 polling을 멈춥니다. 조회 실패 시 숫자를 0으로 만들지 않고 `—`로 표시합니다. 우측 건/초는 최근 5초에 실제 확정된 주문 수 / 5이며 DB 단독 최대 처리 성능을 의미하지 않습니다.

주문 시작/정지와 채팅 시작/정지는 독립적입니다. 주문 입력은 목표 초당 1~100건이며 한 배치가 끝난 뒤 1초 후 다음 배치를 보냅니다. 처리 지연 후 누적 요청을 몰아서 보내지 않습니다. 주문은 실제 join_requests INSERT → Redis q:join → 기존 Worker의 재고 차감·orders INSERT·영수증 저장 경로를 사용합니다. 응답 유실 시 동일한 배치 키로 재시도하고 이미 처리 중인 요청은 정지 버튼으로 취소하지 않습니다. 화면 이탈 시 새로운 자동 주문 생성을 중지합니다.

시연 주문 API는 `ENABLE_ORDER_DEMO=1`로 명시적으로 활성화한 환경에서 세션 인증과 배치 크기 제한을 적용합니다. 일반 구매 API의 사용자 제한은 변경하지 않습니다. 같은 회차의 수치는 모든 시연 참여자를 합산합니다. 품절 결과는 별도로 표시합니다. 검증은 `python scripts/check_order_demo.py`로 실행하며 테스트 주문 5개를 생성하지만 데이터를 지우지는 않습니다.

```sh
docker compose up -d --build
# 새 환경에서만 실행. 기존 주문·채팅을 모두 초기화한다.
curl -X POST 'http://localhost:8000/seed?close_in_s=86400'
docker compose exec -T app python -u scripts/check_live.py
```

개발 서버는 `cd web && npm ci && npm run dev`. Vite가 HTTP와 WebSocket `/api`를 localhost:8000으로 전달한다.

### 모바일 라이브 화면

헤더와 메뉴의 높이를 줄이고, 모바일 상품 검색은 돋보기로 펼친다. 이전 상태는 수신율·유지율·접속 환경을 요약하며 상세 측정값은 펼쳐서 확인한다. 기준 저장은 메인 화면에 유지하고 채팅 봇 시작·정지와 봇 속도 입력, 주문 수동 정지는 LIVE 설정에서 표시한다.

실시간 WebSocket 메시지는 방송 화면 위에 최근 최대 9개만 표시한다. 새 메시지가 아래에서 등장하고 기존 메시지는 위로 밀리며 흐려진다. 로컬 수신 시각 기준 12초가 지나면 화면 효과에서 사라지며, 최근 채팅 기록과 수신율 집계에는 영향을 주지 않는다. 재접속으로 받은 과거 기록을 새 실시간 메시지처럼 재생하지 않는다. 채팅 전체 기록은 아래에서 펼칠 수 있으며 입력·전송 확인·재시도 기능을 유지한다. 동작 줄이기 설정에서는 이동과 블러를 적용하지 않는다. 방송 이미지 자체에는 블러를 적용하지 않는다.

## Redis 프록시를 통한 두 앱 실행

demo 옆에 redis-migrator checkout이 있어야 한다. Pub/Sub의 느린 구독자 처리와 명령 제한이 반영된 main `8a04c52` 이상을 권장한다. Compose의 `!override` 지원이 필요하다.

```sh
docker compose -p chiikawa-live -f docker-compose.yml -f compose.migration.yml up -d --build
# 새 환경에서만 seed. 기존 시연 데이터를 초기화한다.
curl -X POST 'http://localhost:18800/seed?close_in_s=86400'
docker compose -p chiikawa-live -f docker-compose.yml -f compose.migration.yml exec -T -e LIVE_URLS=http://app:8000,http://app-gcp:8000 app python -u scripts/check_live.py
docker compose -p chiikawa-live -f docker-compose.yml -f compose.migration.yml exec -T app python -u scripts/check_cutover.py
```

별도 checkout을 쓰려면 `REDIS_MIGRATOR_PATH` 환경변수를 지정한다. 이번 세션은 기존 redis-migrator의 미커밋 작업을 건드리지 않도록 `../.onboarding/redis-migrator` 사본의 main `8a04c52`로 검증했다.

전환·롤백 검사는 테스트 계정과 메시지를 생성한다. 실제 구매 경로 검사도 시험 주문 1건을 생성한다. 두 검사 모두 `/seed`를 호출하지 않는다. `check_cutover.py`는 실제 로컬 Redis의 활성 위치를 바꾸고 정상 롤백한다. 기존 마이그레이션 작업과 동시에 실행하면 안 된다.

관리 API는 로컬 loopback만 노출한다. 토큰 `local-live-admin`은 로컬 시연 전용이다.

```sh
# 정방향 동기화 시작
curl -H 'Authorization: Bearer local-live-admin' -H 'Content-Type: application/json' -d '{"target":"gcp","budget_ms":5000,"timeout_s":60}' http://localhost:18900/migrations
# ready=true 확인 후 전환
curl -H 'Authorization: Bearer local-live-admin' http://localhost:18900/migrations/current/ready
curl -H 'Authorization: Bearer local-live-admin' -H 'Content-Type: application/json' -d '{"budget_ms":5000}' http://localhost:18900/migrations/current/cutover
# 정상 롤백
curl -H 'Authorization: Bearer local-live-admin' -H 'Content-Type: application/json' -d '{"mode":"normal","budget_ms":5000}' http://localhost:18900/migrations/current/rollback
```

이 Compose는 Redis 전환을 시연한다. PostgreSQL은 단일 DB이고, 오브젝트 저장소도 S3Mock이다. DB·오브젝트·Cloudflare 이전을 통합 완료한 구성은 아니다. DB Operator를 연결할 때 `chat_messages`를 복제 registry에 등록해야 한다.

## 실제 검증 (2026-11-03)

- TypeScript 검사와 Vite production build 통과.
- 1440px·768px·390px 화면 점검. 가로 넘침 없음.
- 화면에서 채팅 입력·전송·수신 확인. 브라우저 콘솔 오류 없음.
- 다른 ASGI 프로세스 및 AWS/GCP 역할의 서로 다른 앱 컨테이너 사이 메시지 전달 확인.
- 재전송 시 DB 기록 1건, 재접속 시 history 복원, 빈 본문·잘못된 형식·유효하지 않은 세션 거부 확인.
- 로그인 세션을 지우면 이미 열린 WebSocket에서도 다음 전송이 4401로 종료됨을 확인.
- 공구 참여 → 동일 멱등 키 재시도 → worker 확정 → S3 영수증 조회 통과.
- 실제 Redis 컷오버·정상 롤백 동안 메시지 40개를 양쪽 앱에서 각각 40개 수신. 누락·중복 0, WebSocket 재접속 0.
- 이 로컬 실행의 Redis 쓰기 정지: 컷오버 약 36ms, 정상 롤백 약 37ms. 성능 보장 수치가 아니다.
- 프록시 통계: pubsub_moved=4, pubsub_dropped=0, pubsub_cut=0. 2개 구독을 정방향·역방향으로 이동했다.

## 메시지 계약과 한계

- 첫 프레임: `{"sid":"로그인 세션"}`. 세션은 URL에 넣지 않는다. 브라우저 Origin과 Host도 대조한다.
- 클라이언트 메시지: `{"id":"UUID","text":"1~300자"}`.
- 서버 이벤트: history, ready, message, ack, heartbeat, error. ready에는 served_by·pid·connection_id가 있다.
- 서버에서 메시지를 저장한 뒤 publish하고 ack한다. publish 결과가 불명일 때는 같은 ID로 수동 재시도한다. DB와 Redis 사이의 원자적 outbox는 구현하지 않았다.
- 재시도는 같은 ID를 다시 발행할 수 있으며 UI가 ID로 중복을 제거한다. ack는 서버의 발행 완료 확인이지 모든 수신자의 읽음 확인이 아니다.
- history는 영속 기록, message는 실시간 수신이다. Redis Pub/Sub 자체는 재생 로그가 아니고 장애 구간의 무손실을 보장하지 않는다.
- 원본 Redis 프로세스가 죽거나 프록시 자체가 재시작하는 장애와 앱 서버 종료는 정상 Redis 컷오버와 다르다. WebSocket이 끊기면 재접속 후 기록을 복원한다.
- 닉네임 로그인은 기존 데모 방식을 유지했다. 비밀번호 인증이나 실제 결제·배송은 없다.
- ‘좋아요’는 이 브라우저 화면의 토글이다. 집계된 가짜 시청자 수나 가짜 채팅은 넣지 않았다.

## 방송 이미지

내장 image_gen 도구로 만든 프로젝트용 데모 이미지: `web/public/live-studio.png`. 원본 생성물을 복사해 프로젝트 안에 보관했다.

춤추는 무대용 파생 이미지도 같은 내장 도구로 생성했다. `web/public/live-stage.png`는 원본에서 세 인형만 제거한 배경이고, `web/public/dancing-friends-clean.png`는 하치와레·치이카와·우사기를 각각 가로 3등분 칸에 배치한 투명 RGBA 이미지다. CSS가 각 칸을 별도로 표시하고 회전·이동·스케일을 적용한다. 채팅과 독립적인 시각 효과이며 영상 송출은 아니다. 원본 추출에서 남은 흰 매트는 같은 도구로 한 번 더 제거했고, 최종 alpha 범위 0~255와 칸 경계의 완전 투명을 확인했다.

파생 이미지의 최종 프롬프트:

```text
Empty stage: Edit target: the supplied Chiikawa plush studio photograph. Remove ALL THREE plush characters completely. Fill their former areas naturally with the same pink curtain, yellow display riser and cream tabletop behind them. Keep exactly the same camera, framing, proportions, soft lighting, pink curtain, hanging stars, vase and flowers left, strawberries left, gift box and daisies right, cream tabletop. Empty studio stage for animated characters to be composited later. Do not add new characters, faces, text, logos or graphics. Preserve the original warm pastel photographic style.

Sprites: Use case: background-extraction / sprite asset. Reference image: supplied Chiikawa plush photo. Produce a TRUE TRANSPARENT background PNG containing ONLY the three matching plush toys, fully visible, no stage, no floor, no props, no shadow outside the toys, no text. Wide horizontal composition divided into THREE EQUAL-WIDTH INVISIBLE CELLS: Hachiware blue-and-white cat centered in LEFT third, Chiikawa white bear-like plush centered in MIDDLE third, Usagi yellow bunny centered in RIGHT third. Each toy stands separately with arms slightly out like dancing. IMPORTANT no overlap: entire character including ears and feet fits inside its own equal third, with transparent gaps at each third boundary. Feet all on same baseline near bottom. Each character same apparent body size; bunny ears taller. Preserve original plush fur, face details, pastel colors and front-facing view. Transparent padding above bunny ears and below feet. These will be split into three CSS sprites and animated independently. No background, no checkerboard drawn in image.

Final alpha cleanup: Edit target: the supplied three plush character sprite image. Preserve exact canvas size, exact positions, equal thirds layout, character appearances, scale and framing. Fix transparency ONLY: remove ALL white rectangular matte backgrounds, all milky haze between/above/below characters, and all white glow outside fur silhouettes. The whole background must be fully transparent, including gaps between ears and under arms. Each plush must be a clean tight alpha cutout following its actual fur outline, with no floor, no rectangular panels, no backdrop, no shadow. Keep white fur itself opaque and intact. Do not redraw faces, move or resize the characters. This is an alpha background cleanup for compositing over a pink curtain.
```

최종 프롬프트:

> Use case: product-mockup. Create a beautiful wide landscape 16:9 studio photograph for a Chiikawa live shopping demo. Three adorable plush toys of Chiikawa (small round white bear-like creature with tiny round ears rosy cheeks), Hachiware (white cat with blue ears and blue head cap) and Usagi (pale yellow bunny with long ears) sitting together on a cream cotton-covered product display counter in a charming pastel pink live-shopping studio. Chiikawa plush centered slightly larger, Hachiware to left and Usagi right. Soft strawberry pink curtain backdrop with subtle vertical folds, a few small felt stars hanging, warm butter yellow circular stage platform, tiny gift box, plush textures, professional softbox lighting, clean tasteful Japanese character merchandise photography. Frame all three characters fully with generous cream floor at bottom. No people, no text, no lettering, no logos or watermark, no UI. Crisp material detail, gentle shadows, endearing simple facial features, soft pink cream pale blue yellow palette.
