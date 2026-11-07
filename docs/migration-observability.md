# 앱 OTEL 관측

`app/main.py`의 외부 HTTP middleware가 HOLD 대기를 포함한 요청 span을 만듭니다. `app/workload.py`는 API/worker 작업 span과 독립 5초 in-flight/WebSocket/Redis 잔존 연결 수치를 발행합니다. 업무 입력·SQL·Redis key·토큰은 기록하지 않습니다. CP의 probe 요청 context를 추출해 작업 추적을 연결합니다.

기존 workload heartbeat와 Redis route 지시는 제어에 사용하므로 유지합니다. CP는 actor 요약에 workflow ID를 붙여 OTEL snapshot으로 내보냅니다. heartbeat를 중단시키는 방식으로 telemetry를 끄면 안 됩니다.

`/api/migration-probe`는 무캐시 `{"ok":true}`와 X-Served-By를 반환하며 workload gate를 거칩니다. CP의 공용 URL·SERVED_BY 매핑을 설정합니다. /readyz는 HOLD 영향 측정용이 아닙니다. WebSocket 수와 DB 업무 in-flight는 별도입니다.

일반 사용자 요청의 trace 양을 제한하려면 앱에 `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1`을 설정합니다. 샘플된 CP 부모 trace는 이어집니다. 브라우저에 Collector 토큰을 전달하지 않습니다.

검사: `python -m unittest discover -s tests -v`.

## OTEL 실행 설정

공식 OpenTelemetry SDK가 OTLP HTTP/protobuf로 로그·메트릭·트레이스를 내보냅니다. 아래 값을 **프로세스 환경**에 주입합니다. endpoint가 없거나 `OTEL_SDK_DISABLED=true`이면 전송하지 않습니다. `.env` 파일을 만드는 것만으로 Python 프로세스 환경이 바뀌지는 않습니다.

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.internal:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<module-ingest-token>
```

Collector는 IaC의 `observability/compose.yaml`로 준비합니다. Collector → CP에는 별도 `OBSERVATION_TOKEN`을 씁니다. 모듈에 CP 수신 토큰을 주지 않습니다. 운영 주소는 사설망/VPN에서 접근하도록 구성하고, TLS를 사용하는 경우 SDK의 `OTEL_EXPORTER_OTLP_CERTIFICATE`와 HTTPS endpoint를 설정합니다. 앱 환경 값·DSN·Terraform output·원시 키·오류 원문은 전송하지 않습니다.

진행 상태는 OTEL 구조화 로그 → Collector → CP의 `OBS_LATEST`/24시간 이력, 수치는 Prometheus, 작업 span은 Tempo에 저장합니다. 플랫폼은 CP API만 조회합니다. 제어 명령·승인·멱등성·판정 근거는 기존 저장소가 원본이며 OTEL 전송 성공을 전환 조건으로 사용하지 않습니다. 관측이 끊겨도 이전 값을 0이나 성공으로 바꾸지 않습니다.

Python `telemetry.py`/`telemetry_contract.py`는 독립 이미지에 포함한 공통 계약 v1 사본입니다. 계약을 바꾸면 CP와 모든 Python 발행자의 사본 및 SDK 계약 테스트를 함께 갱신합니다. metric에는 operation/transition ID·키·URL을 label로 넣지 않으며, 값 캐시는 최대 2048 series/20초입니다. workflow ID는 마이그레이션별 화면 조회를 위한 제한된 차원입니다.

## 앱 시스템 지표

앱 시스템 지표는 새 이미지의 `app/system_metrics.py`가 발행합니다. `OTEL_SYSTEM_METRICS=container`, `OTEL_APPLICATION_ID`, `OTEL_OWNER_ID`, `OTEL_DEPLOYMENT_ID`, `SERVED_BY`와 OTLP endpoint/headers가 필요합니다. 소유자와 배포 ID는 플랫폼 배포 기록에서 주입하며 앱 이름만으로 합산하지 않습니다. API worker 여러 개 중 한 프로세스만 10초마다 발행하고 종료 시 다른 프로세스가 이어받습니다.

CPU 사용 시간·메모리·디스크 I/O는 현재 프로세스가 속한 컨테이너 cgroup을 읽습니다. CPU·메모리 제한이 없으면 사용량만 제공하고 비율은 비웁니다. 호스트 CPU/메모리 및 공유 디스크 용량은 수집하지 않습니다. Docker/온프렘의 네트워크는 분리된 컨테이너 namespace 기준입니다. Fargate/Cloud Run은 같은 앱 실행 묶음의 API·워커·터널이 네트워크를 공유하므로 `OTEL_NETWORK_SCOPE=app-instance`로 표시하고 API만 발행합니다. 지원하지 않는 커널 지표는 0 대신 누락으로 처리합니다.

기존 `compose.observability.yml` 호스트 에이전트는 제거했습니다. 이미 실행한 에이전트는 중단해야 합니다. 기존 호스트 지표는 새 조회 조건에 포함되지 않습니다. 로컬 예시는 `docker compose --env-file .env.otel up --build`이며 `.env.otel.example`을 참고합니다. 원격 배포는 새 이미지와 프로비저너 설정을 함께 적용해야 합니다.
