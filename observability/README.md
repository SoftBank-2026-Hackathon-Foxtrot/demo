# 사용자 앱 서버의 시스템 메트릭

Linux 앱 서버마다 OTEL Collector agent 하나를 실행한다. **서버 전체 CPU·메모리·디스크·네트워크**를 수집한다. 컨테이너별 수치와 중앙 Collector 서버의 수치를 섞지 않는다. 이번 변경은 앱 요청·주문·채팅 계측을 추가하지 않는다.

## 실행

1. `.env.otel.example`을 `.env.otel`로 복사한다.
2. `OTEL_APPLICATION_ID`와 `SERVED_BY`를 control-plane에 등록한 앱 ID·환경 이름으로 맞춘다. 기본 seed는 `goods`, `aws`/`gcp`다.
3. `OTEL_HOST_NAME`에 서버별로 고유하고 유지되는 이름을 지정한다. 예: `goods-aws-01`.
4. `OTEL_EXPORTER_OTLP_ENDPOINT`에 중앙 Collector의 HTTP OTLP 주소, `OTEL_INGEST_TOKEN`에 수집 토큰을 넣는다. 실제 토큰은 버전 관리하지 않는다.
5. **앱이 실행되는 각 서버에서** 다음을 실행한다. 앱 Compose와 독립적으로 실행할 수 있다.

```sh
docker compose --env-file .env.otel -f compose.observability.yml up -d
```

플랫폼의 **모니터링 → 시스템**에서 앱·환경·서버와 CPU/메모리/디스크/네트워크를 선택한다. central Prometheus의 resource attribute 승격 설정과 control-plane의 system-metrics API도 함께 배포해야 한다. API 서버에는 기존 `CONTROL_PLANE_PROMETHEUS_URL`을 설정한다.

## 측정 기준

| 항목 | 기준 |
| --- | --- |
| CPU | 모든 코어의 busy 비율, 최근 2분 누적 CPU 시간 |
| 메모리 | MemTotal - MemAvailable 및 사용률; reclaim 가능한 cache는 사용 가능 메모리에 포함 |
| 디스크 | 루트 `/`의 사용률, 장치 read/write bytes/s; loop/ram/dm 장치 제외 |
| 네트워크 | 인터페이스 receive/transmit bytes/s; loopback/veth/Docker bridge 제외 |

10초마다 수집한다. 서버 이름은 환경 안에서 유일해야 하며 같은 서버에 같은 앱 ID의 agent를 중복 실행하지 않는다. 수집 중단 30초 뒤 현재값은 결측값이 된다. Prometheus가 최근 5분 내 본 서버가 선택 목록에 남는 동안 마지막 수집 시각과 중단 상태를 표시한다. CPU와 I/O는 rate 계산을 위해 최소 두 표본이 필요하다.

agent는 호스트 파일시스템을 `/hostfs`에 읽기 전용으로 마운트하고 host network를 사용한다. Docker socket, privileged, 추가 capability는 사용하지 않는다. 파일 내용·프로세스 명령행·환경 변수는 수집하지 않는다. 공유 서버라면 다른 프로세스의 자원 사용도 포함된다. 이 구성은 Linux용이다. Docker Desktop에서 실행하면 VM의 수치가 된다.

Collector 설정 검증:

```sh
docker compose --env-file .env.otel -f compose.observability.yml run --rm otel-system validate --config=/etc/otelcol/config.yaml
```

[공식 hostmetrics receiver 문서](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.147.0/receiver/hostmetricsreceiver).
