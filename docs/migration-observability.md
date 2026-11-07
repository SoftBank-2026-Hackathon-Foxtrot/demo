# 마이그레이션 관측

앱을 재배포하면 `GET /api/migration-probe`가 HTTP 200, {"ok":true}, Cache-Control:no-store와 기존 X-Served-By를 반환합니다. 일반 workload gate를 거치므로 HOLD 중 대기도 관측됩니다. DB·Redis·객체 업무 검증은 컨트롤 플레인의 기존 BusinessProbe가 담당합니다.

각 인스턴스의 SERVED_BY를 컨트롤 플레인의 PUBLIC_PROBE_SERVED_BY 매핑에 등록하고 Cloudflare 공용 URL을 PUBLIC_PROBE_URL에 설정합니다. 캐시 규칙에서도 이 경로를 캐시하지 않습니다. /readyz는 HOLD 영향 측정에 사용하지 않습니다.

기존 heartbeat에 activeWebSockets를 추가했습니다. 연결은 시작/종료에서 집계하며 DB 업무 정지용 inFlight와 합치지 않습니다. 기존 CONTROL_PLANE_URL, WORKLOAD_TOKEN, WORKLOAD_ACTOR를 사용합니다. token이 없는 공개 probe는 읽기 전용이며 데이터 저장소를 조회하지 않습니다.

검사: requirements.txt와 httpx를 설치한 환경에서 `python -m unittest discover -s tests -v`.
