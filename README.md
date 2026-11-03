![공구앱 메인화면](docs/home.png)

# 치이카와 LIVE 공구앱

이전 대상이 되는 데모앱입니다. 라이브 홈쇼핑 콘셉트의 화면, Redis Pub/Sub 기반 실시간 채팅, 로그인, 공구 목록, 참여 주문, 영수증 조회 기능이 있습니다. 방송 무대는 생성 이미지로 구성한 데모이며 실제 영상 스트리밍은 아닙니다.

## 라이브 채팅과 이전 시연

`/api/live/chat` WebSocket은 첫 프레임의 세션으로 인증합니다. 채팅은 PostgreSQL에 보관하고 Redis `live:chiikawa-live` 채널로 전달합니다. 각 브라우저는 별도 Redis 구독을 가지며 발행·인증에는 다른 연결을 사용합니다. 앱 인스턴스가 달라도 같은 방으로 전달됩니다. 최근 100개 대화 복원, 메시지 ID 중복 방지, 전송 확인·수동 재시도, 자동 재접속, 분당 60개 제한을 지원합니다.

Redis 프록시와 AWS/GCP 역할의 앱 두 대를 연결하는 실행법·검증 결과는 [docs/live.md](docs/live.md)에 있습니다. 화면 아래 ‘연결 정보’에서 앱·WebSocket 연결 ID·재접속 횟수·실시간 수신 수를 볼 수 있습니다.

- 백엔드: FastAPI, 큐 worker(Python)
- 화면: React, Vite
- 저장소: Redis(Valkey), PostgreSQL, S3

## 기능별 저장소

| 기능 | 위치 | Redis | PostgreSQL | S3 |
|---|---|---|---|---|
| 로그인·로그아웃 | `POST /api/login/{uid}`, `POST /api/logout` | `session:{sid}` 생성·삭제 | | |
| 로그인 확인 | 아래 API 중 worker를 뺀 사용자 API 전부 | `session:{sid}` 조회, TTL 연장 | | |
| 라이브 채팅 | `WS /api/live/chat` | 세션 확인, 요청 제한, Pub/Sub 구독·발행 | `chat_messages` 저장·최근 기록 조회 | |
| 공구 목록 | `GET /api/groupbuys` | | `groupbuys` 조회 | |
| 공구 상세 | `GET /api/groupbuys/{id}` | `cache:groupbuy:{id}` 조회, 없으면 저장 | 캐시에 없을 때 `groupbuys` 조회 | |
| 가격 변경 | `POST /groupbuys/{id}/price` | `cache:groupbuy:{id}` 삭제 | `groupbuys` 수정 | |
| 공구 참여 | `POST /api/groupbuys/{id}/join` | `rl:{uid}:{분}` 증가, `q:join`에 등록 | `join_requests` 저장 | |
| 주문 확정 | worker | `q:join` 소비, `q:notify`에 등록 | `join_requests`, `groupbuys` 재고, `orders` 수정 | `receipts/{request_id}.json` 저장 |
| 내 주문 | `GET /api/me/requests` | | `join_requests`, `groupbuys`, `orders` 조회 | |
| 영수증 조회 | `GET /api/me/receipts/{request_id}` | | `orders.receipt_key` 조회 | 기본 버킷에서 읽고, 없으면 다른 버킷에서 읽기 |
| 공구 마감 | worker | `q:delayed`에서 `q:notify`로 이동 | `groupbuys.closed_ms` 수정 | |
| 알림 기록 | worker | `q:notify` 소비 | `notifications` 저장 | |
| 누락 복구 | worker (`--reconciler`) | `q:join` 재등록, `q:delayed` 복원 | 오래 대기 중인 `join_requests`, 마감 전 `groupbuys` 조회 | 영수증이 없는 주문의 영수증 저장 |

알림은 DB에 기록만 하고 실제로 보내지 않습니다.

## 저장하는 데이터

**PostgreSQL** (원본 데이터, PgBouncer를 거쳐 접속)

| 테이블 | 내용 |
|---|---|
| `groupbuys` | 공구 상품, 가격, 재고, 마감 시각 |
| `join_requests` | 참여 요청과 처리 상태(`QUEUED`, `CONFIRMED`, `SOLD_OUT`), 멱등 키 |
| `orders` | 확정된 주문, 영수증 키 |
| `notifications` | 알림 기록 |
| `stats` | 재처리 횟수 같은 내부 집계 |
| `chat_messages` | 방송 채팅 ID·닉네임·본문·시각. seed 시 함께 초기화 |

**Redis**

| 키 | 종류 | 내용 | TTL |
|---|---|---|---|
| `session:{sid}` | String | 로그인 세션 | 30분 |
| `cache:groupbuy:{id}` | String | 공구 상세 캐시 | 5분 |
| `rl:{uid}:{분}` | String | 참여 요청 횟수 제한 | 1분 |
| `q:join`, `q:notify` | Stream | 주문 처리 큐, 알림 큐 (consumer group `workers`) | 없음 |
| `q:join:dead`, `q:notify:dead` | Stream | 반복 실패한 메시지 | 없음 |
| `q:delayed` | Sorted Set | 예약된 공구 마감 작업 | 없음 |

**S3**

| 키 | 내용 |
|---|---|
| `receipts/{request_id}.json` | 주문 영수증. 키는 바뀌지 않음 |

버킷 이름은 `S3_BUCKET`(기본 `receipts-aws`)과 `S3_FALLBACK_BUCKET`(기본 `receipts-gcp`)으로 정합니다.

## 시스템 아키텍처

회의에서 정한 구성입니다. Redis 프록시와 PgBouncer는 AWS 관리 VPC에 두고, 트래픽 비율은 오케스트레이터가 Cloudflare API로 바꿉니다. 앱은 Redis 프록시, PgBouncer, S3의 주소만 알고 뒤의 저장소가 바뀌어도 앱 설정은 그대로입니다.

```mermaid
flowchart LR
    U[사용자] --> E[Cloudflare Load Balancer]
    O[오케스트레이터] -. 가중치 API .-> E
    E -- Tunnel --> A1[유저 앱 AWS]
    E -- Tunnel --> A2[유저 앱 GCP]
    E -- Tunnel --> A3[유저 앱 온프레]
    A1 & A2 & A3 --> RP[Redis 프록시]
    A1 & A2 & A3 --> PB[PgBouncer]
    A1 & A2 & A3 --> S[S3 호환 스토리지]
    W[Queue worker] --> RP & PB & S
    subgraph M[AWS 관리 VPC]
        O
        RP
        PB
    end
    RP -- Tailscale --> R[(Redis / Valkey)]
    PB -- Tailscale --> P[(PostgreSQL)]
```

이 레포의 `docker-compose.yml`은 앱을 혼자 띄우기 위한 구성이라 다음이 다릅니다.

| 설계 | 로컬 |
|---|---|
| Cloudflare Load Balancer, Tunnel | 없음. 앱에 바로 접속 |
| Redis 프록시 | 없음. Valkey에 바로 접속 |
| RDS, Cloud SQL | PostgreSQL 컨테이너 1개 |
| S3, Cloud Storage | S3Mock 컨테이너 1개 |

주문 처리 순서:

1. 앱이 `join_requests`에 `QUEUED`로 저장하고 `q:join`에 등록한 뒤 응답합니다.
2. worker가 한 트랜잭션에서 재고를 줄이고 주문을 확정합니다.
3. worker가 S3에 영수증을 저장한 뒤 `orders.receipt_key`를 채웁니다.

## 트래픽 계층과의 계약

- `GET /readyz`: 저장소에 처음 연결되기 전과 종료 중에는 503, 그 외에는 200입니다.
- SIGTERM을 받으면 `/readyz`가 바로 503이 되고 6초 뒤(`DRAIN_S`) 서버가 종료를 시작합니다.
- `DRAIN_S`는 앱이 로드 밸런서에서 빠질 시간을 기다립니다. 종료 전에 오케스트레이터가 가중치를 0으로 내리면 기본값 그대로 쓸 수 있습니다. 상태 검사에만 맡기려면 Cloudflare 검사 주기(요금제별 최소 Pro 60초, Business 15초, Enterprise 10초)에 맞춰 `DRAIN_S`와 컨테이너 종료 유예를 늘려야 합니다.
- `/readyz`는 처음 연결된 뒤에는 저장소 장애를 반영하지 않습니다. 컷오버 중 정지로 앱이 빠지는 일을 막기 위해서이고, 실제 장애 판단은 오케스트레이터가 해야 합니다.
- 모든 응답에 `X-Served-By`(`SERVED_BY` 값)가 붙습니다.
- 화면은 `/api/...` 상대 경로로 호출합니다.
- `POST /api/groupbuys/{id}/join`에 `Idempotency-Key`를 보내면 같은 키의 재시도는 주문을 새로 만들지 않습니다.

## 실행

```bash
docker compose up -d --build
```

```bash
curl -X POST "http://localhost:8000/seed?close_in_s=1800"
```

http://localhost:8000 에 접속합니다. `/seed`는 DB를 비우고 상품을 다시 만듭니다.

화면만 고칠 때는 `web`에서 실행합니다. `vite.config.ts`의 `app` 주소를 `http://localhost:8000`으로 맞춰 둡니다.

```bash
npm install && npm run dev
```

## 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis 또는 Redis 프록시 주소 |
| `DATABASE_URL` | `postgresql://app:apppw@db-proxy.internal:6432/appdb` | PgBouncer 주소 |
| `S3_ENDPOINT` | 없음 | S3 호환 스토리지 주소. 없으면 AWS S3 |
| `S3_REGION` | `us-east-1` | S3 리전 |
| `S3_BUCKET`, `S3_FALLBACK_BUCKET` | `receipts-aws`, `receipts-gcp` | 영수증 버킷 |
| `SERVED_BY` | `local` | `X-Served-By` 값 |
| `DRAIN_S` | `6` | 종료 전 대기 시간(초) |

## 초안이라 없는 것

- 비밀번호 로그인. 이름만 입력하면 로그인됩니다.
- `/seed`, `/report`, `/cache-check`, 가격 변경 API의 인증.
- API(`:8000`)와 화면(`:3000`) 분리. 지금은 앱이 화면까지 함께 제공합니다.
- 실제 알림 전송.

`docker-compose.yml`과 `pgbouncer/userlist.txt`의 비밀번호는 로컬 전용 값입니다.
