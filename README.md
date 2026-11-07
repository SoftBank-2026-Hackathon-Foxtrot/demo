![치이카와 공구앱 아키텍처](docs/architecture.png)

> 파란 선은 사용자 요청과 플랫폼 지시, 회색 선은 데이터 연결, 점선은 이전 중 복사입니다. 앱은 Redis 프록시, PgBouncer, 오브젝트 스토리지의 고정 주소만 알고, DB 전환 때는 control-plane의 지시로 업무를 멈춥니다.

![공구앱 메인화면](docs/home.png)

# 치이카와 LIVE 공구앱

이전 대상이 되는 데모앱입니다. 라이브 홈쇼핑 콘셉트의 화면, Redis Pub/Sub 기반 실시간 채팅, 로그인, 공구 목록, 참여 주문, 영수증 조회 기능이 있습니다. 방송 무대는 생성 이미지로 구성한 데모이며 실제 영상 스트리밍은 아닙니다.

## 라이브 채팅과 이전 시연

`/api/live/chat` WebSocket은 첫 프레임의 세션으로 인증합니다. 채팅은 PostgreSQL에 보관하고 Redis `live:chiikawa-live` 채널로 전달합니다. 각 브라우저는 별도 Redis 구독을 가지며 발행·인증에는 다른 연결을 사용합니다. 앱 인스턴스가 달라도 같은 방으로 전달됩니다. 최근 100개 대화 복원, 메시지 ID 중복 방지, 전송 확인·수동 재시도, 자동 재접속, 분당 60개 제한을 지원합니다.

Redis 프록시와 AWS/GCP 역할의 앱 두 대를 연결하는 실행법·검증 결과는 [docs/live.md](docs/live.md)에 있습니다. 화면 아래 ‘연결 정보’에서 앱·WebSocket 연결 ID·재접속 횟수·실시간 수신 수를 볼 수 있습니다.

채팅 위의 **채팅 봇 시작** 버튼으로 자동 메시지를 생성합니다. 옆 숫자 입력칸은 목표 **초당 메시지 수**이며 기본 10, 범위 1~1,000입니다. 실행 중 숫자를 바꾸면 바로 적용되고 **봇 정지**로 멈춥니다. 봇은 화면(WebSocket 연결)마다 하나씩 실행되므로 여러 화면에서 켜면 트래픽이 합산됩니다. 화면을 닫거나 연결이 끊기면 정지하며, 재접속 후에는 직접 다시 시작합니다. 정지 전에 처리 중이던 메시지 한 건은 도착할 수 있습니다.

봇 메시지도 PostgreSQL 저장 → Redis `live:chiikawa-live` 발행 → 각 브라우저 구독 경로를 거치고, DB 이전 시 업무 정지 지시를 따릅니다. 데모 부하 생성을 위해 봇에는 일반 채팅의 분당 60개 제한을 적용하지 않습니다. 설정값은 목표 속도로, DB·Redis 처리 시간에 따라 실제 속도는 낮아질 수 있으며 지연 후 몰아서 보내지 않습니다. WebSocket 제어 프레임은 `{"type":"bot","rate":10}`(시작/변경), `{"type":"bot","rate":0}`(정지)이고 서버는 `bot_state`로 적용 결과를 응답합니다.

### 화면에서 이전 상태 확인

라이브 화면의 모니터는 HTTP 측정 요청과 채팅 WebSocket을 처리한 환경을 각각 표시합니다. 배포할 때 `SERVED_BY=aws`, `gcp`, `onprem`으로 지정하세요. 로컬 실행은 `local`입니다. 이 표시는 앱 서버의 설정이며 DB·Redis의 실제 위치나 클라우드 트래픽 분배 비율을 의미하지 않습니다.

- **채팅 실시간 수신율:** 최초 채팅 연결 이후 PostgreSQL에 저장된 최근 최대 1,000개 메시지 ID 중 이 탭이 Pub/Sub으로 실시간 수신한 비율입니다. 최근 2초는 전달 유예로 제외하고 약 3초마다 갱신합니다. 재접속 기록은 수신으로 세지 않으며, 연결이 끊긴 동안의 누락을 포함합니다. 새로고침하면 채팅 측정이 다시 시작됩니다. 표본의 원본 DB 자체가 유실된 경우 이 수치만으로는 유실을 판단할 수 없습니다.
- **기준 데이터 유지율:** 이전 전에 **기준 저장**을 누르면 채팅·주문·참여 요청·상품의 ID를 종류별 최대 500건씩 읽어 브라우저 탭의 `sessionStorage`에 보관합니다. 이후 DB에서 여전히 조회 가능한 ID / 기준 ID를 표시합니다. ID 존재 여부를 검사하며 내용 일치·영수증 파일·Redis 세션 유지·전체 데이터 무손실을 검증하는 수치는 아닙니다. 기준은 새로고침 후에도 유지되고 탭을 닫으면 사라집니다.
- 기준·표본이 없으면 백분율을 표시하지 않습니다. 조회 실패 때도 마지막 수치를 현재 수치처럼 표시하지 않고 **갱신 실패**로 표시합니다.

로그인된 화면은 `GET /api/live/baseline`, `POST /api/live/metrics`로 읽기 전용 검사를 실행합니다. 원래 채팅 전달 경로에 별도 카운터 쓰기를 추가하지 않습니다.

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
| `OBJECT_MIGRATION_SERVER` | 없음 | object-migration 서버 주소. 있으면 영수증 버킷 이전을 따라감 (아래) |
| `OBJECT_MIGRATION_ID` 또는 `OBJECT_MIGRATION_ID_FILE` | 없음 | 따라갈 이전 ID. 파일은 1초마다 다시 읽음 |
| `STORAGE_<KIND>_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY`, `_ENDPOINT` | 없음 | 이전 경로의 버킷 종류(`S3`, `GCS`, `SEAWEEDFS`)별 앱 자격 증명과 주소. GCS는 S3 호환 API와 HMAC 키 |
| `CONTROL_PLANE_URL` | 없음 | 플랫폼(control-plane) 주소. 있으면 업무 정지 지시를 따름 (아래). 없으면 기존과 같이 동작 |
| `WORKLOAD_ACTOR` | 없음 | 이 프로세스의 역할. 플랫폼 시드의 `actors` 이름 (`goods-aws-api`, `goods-aws-worker` 등). `CONTROL_PLANE_URL`이 있으면 필수 |
| `WORKLOAD_TOKEN` | 없음 | 플랫폼의 heartbeat 토큰 |
| `WORKLOAD_SCOPE` | `scope:goods` | 플랫폼 시드의 `scope` |

### 영수증 버킷 이전 따라가기

[object-migration](https://github.com/SoftBank-2026-Hackathon-Foxtrot/object-migration)의 앱 저장소 모듈(`docs/app-storage.md`)을 `app/objroute.py`로 구현했습니다. 모든 프로세스(API worker, 큐 worker)가 1초마다 경로를 묻고, 쓰는 버킷과 읽는 순서를 그대로 따릅니다. 서버는 살아 있는 앱이 모두 새 경로를 적용해야 다음 단계로 넘어갑니다. 이전 중 경로를 5초 넘게 갱신하지 못하면 영수증 요청을 실패시킵니다. 이전 ID가 없으면 `S3_BUCKET`, `S3_FALLBACK_BUCKET`을 씁니다. 앱은 영수증을 지우지 않아 삭제 기록은 구현하지 않았습니다.

**전환 전에 앱이 이전 ID를 알고 있어야 합니다.** 서버는 한 번도 묻지 않은 앱을 기다리지 않습니다. 이전을 만든 직후 ID를 `OBJECT_MIGRATION_ID_FILE`에 쓰거나, 그 ID로 앱을 다시 배포합니다. `CONTROL_PLANE_URL`이 있으면 플랫폼이 heartbeat 응답으로 이전 ID를 알려 주고, 앱이 이 파일에 직접 씁니다.

검증: 실제 object-migration 서버(fake engine)와 s3mock으로 앱 프로세스 2개가 50ms마다 영수증을 쓰고 읽는 중에 freeze → switch → resume → finalize. 쓰기 760건, 읽기 760건 실패 0건. 전환 뒤 원본에 쓴 영수증 0건, 전환 전 대상에 쓴 영수증 0건.

### 플랫폼의 업무 정지 따르기

DB 전환에는 앱과 Worker의 실제 업무 정지가 필요합니다. [control-plane의 앱 연동 문서](https://github.com/SoftBank-2026-Hackathon-Foxtrot/control-plane/blob/main/docs/app-integration.md)대로 `app/workload.py`에 구현했습니다. `CONTROL_PLANE_URL`이 없으면 아무것도 하지 않습니다.

- **heartbeat:** API의 uvicorn worker와 큐 worker가 프로세스마다 따로 플랫폼에 상태를 보고하고 RUN/HOLD 지시를 받습니다. 간격은 응답의 `pollAfterMs`(평소 5초, 정지 중 200ms)를 따릅니다.
- **API:** HOLD 동안 새 HTTP 요청과 채팅 메시지 저장을 게이트에서 기다리게 합니다. 처리 중인 요청이 0이 되면 HELD를 보고합니다. 60초를 넘으면 `503`과 `Retry-After`를 반환합니다. `/readyz`는 게이트를 거치지 않습니다.
- **큐 worker:** HOLD 동안 새 배치를 가져가지 않고, 처리 중인 배치를 끝내면 HELD를 보고합니다.
- **시작과 단절:** 첫 지시를 받기 전까지 `/readyz`가 503이고 업무를 받지 않습니다. 플랫폼과 통신이 끊기면 마지막 지시를 유지합니다. HOLD는 스스로 풀지 않습니다.
- **오브젝트 이전 ID:** 응답의 `objectMigrationId`를 `OBJECT_MIGRATION_ID_FILE`에 씁니다.

검증(로컬): 실제 control-plane API와 코디네이터를 띄우고, 이 앱(uvicorn worker 4개, 큐 worker 2개)에 부하를 주는 중에 정지를 요청해 5초 유지한 뒤 풀었습니다.

- 6개 프로세스 모두 HELD를 보고했고, 해제 후 0.45초 안에 모두 RUNNING을 보고했습니다.
- 요청 277건이 모두 200이었습니다. 정지 중에 응답한 요청은 0건이고, 정지에 걸린 8건은 최대 6.47초 기다린 뒤 성공했습니다.
- 정지 중 DB 쓰기는 0건이었습니다(접수된 참여 요청 0건, 처리된 주문 0건).
- 오브젝트 이전 ID가 세 컨테이너 모두의 파일에 기록됐습니다.
- 확인하지 않은 것: 60초 초과 시 503, 정지 중 플랫폼 단절 시 HOLD 유지.

## 초안이라 없는 것

- 비밀번호 로그인. 이름만 입력하면 로그인됩니다.
- `/seed`, `/report`, `/cache-check`, 가격 변경 API의 인증.
- API(`:8000`)와 화면(`:3000`) 분리. 지금은 앱이 화면까지 함께 제공합니다.
- 실제 알림 전송.

`docker-compose.yml`과 `pgbouncer/userlist.txt`의 비밀번호는 로컬 전용 값입니다.
