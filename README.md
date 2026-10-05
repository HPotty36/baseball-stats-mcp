# baseball-stats-mcp

MLB와 KBO 기록을 Claude가 직접 조회하고, 원본 사이트가 주지 않는 세이버메트릭스 지표(FIP, K-BB%, LOB%, ISO, BABIP, 피타고리안 승률 등)를 **서버에서 계산해서** 돌려주는 MCP 서버.

- **MLB**: 공식 MLB Stats API(statsapi.mlb.com)를 실시간 조회. API 키 불필요.
- **KBO**: 직접 내려받은 시즌 CSV를 읽음. (KBO 공식 기록실은 robots.txt로 자동 수집을 막고 있어서 스크래퍼를 넣지 않았다.)

두 리그 모두 같은 내부 표현(`BattingLine`, `PitchingLine`)으로 변환한 뒤 같은 지표 코드를 타기 때문에, "KBO 마무리와 MLB 마무리의 K-BB%" 같은 리그 간 비교도 같은 기준으로 나온다.

## 툴

| 툴 | 하는 일 |
|---|---|
| `baseball_player_stats` | 선수 시즌 기록 + 파생 지표 (타자: OPS/ISO/BABIP/BB%/K%, 투수: ERA/FIP/ERA-FIP/K-BB%/BABIP/LOB%) |
| `baseball_leaderboard` | 아무 지표로나 순위 (규정타석/이닝 필터, 팀 필터, 최소 PA/IP) |
| `baseball_pitcher_luck_check` | ERA vs FIP 괴리 → BABIP·LOB%를 리그 평균과 비교 → 운/실력 신호와 주의사항 |
| `mlb_search_players` | 영문 이름으로 MLB 선수 ID 찾기 |
| `mlb_standings` | 지구별 순위 + 득실차 + 피타고리안 기대 승수 + 운(실제 승 - 기대 승) |
| `kbo_data_status` | 불러온 KBO CSV 목록, 행 수, 컬럼 문제 진단 |

모든 툴은 읽기 전용이고, `format: "json"`을 주면 마크다운 대신 구조화된 JSON을 반환한다.

## 설치

[uv](https://docs.astral.sh/uv/)가 있으면:

```bash
cd baseball-stats-mcp
uv sync            # 의존성 + 개발용(pytest) 설치
uv run pytest      # 네트워크 없이 목업으로 동작
```

Python 3.10 이상, MCP Python SDK 2.x(`MCPServer`) 기준이다.

실제 MLB API로 확인하려면 `uv run python scripts/live_check.py` — 서버를 stdio로 띄워 툴을 하나씩 호출하고 결과를 출력한다.

## Claude에 연결

**Claude Code**

```bash
claude mcp add --env KBO_DATA_DIR=/절대경로/baseball-stats-mcp/data/kbo --transport stdio baseball-stats \
  -- uv --directory /절대경로/baseball-stats-mcp run baseball-stats-mcp
```

**Claude Desktop** — `claude_desktop_config.json`에 추가 (Windows 예시):

```json
{
  "mcpServers": {
    "baseball-stats": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\<you>\\baseball-stats-mcp", "run", "baseball-stats-mcp"],
      "env": { "KBO_DATA_DIR": "C:\\Users\\<you>\\baseball-stats-mcp\\data\\kbo" }
    }
  }
}
```

`KBO_DATA_DIR`를 생략하면 프로젝트의 `data/kbo/`를 쓴다. 저장 후 Claude Desktop을 재시작.

## KBO 데이터 넣기

`data/kbo/README.md` 참고. 요약:

- `data/kbo/hitters_2026.csv`, `data/kbo/pitchers_2026.csv` 형식으로 저장
- 헤더는 KBO 기록실 표기(`선수명, 팀명, PA, AB, H, 2B, ...`) 그대로 써도 되고 영문도 됨
- 엑셀에서 저장한 CP949 CSV도 읽음
- 리그 FIP 상수는 투수 파일 전체 합계로 계산하므로, **전 투수가 들어 있어야** 정확함. 일부만 있으면 `league_overrides.json`으로 상수를 직접 지정

## 이렇게 물어보면 된다

- "Chris Sale 2025 시즌 운 체크해줘"
- "2026 MLB 규정이닝 투수 K-BB% 상위 10명"
- "2026 내셔널리그 동부 피타고리안 승률이랑 실제 승수 차이 보여줘"
- "KBO 2026 삼성 타자 ISO 순위" (CSV 필요)

## 구조

```
src/baseball_stats_mcp/
  lines.py       리그 공통 기록 단위 (이닝은 아웃카운트로 저장해 .1=1/3 문제 방지)
  metrics.py     지표 계산, 리그 컨텍스트(cFIP 등), 운 체크, 피타고리안
  mlb.py         MLB Stats API 클라이언트 (10분 캐시, 트레이드 선수 합산, 동명이인 처리)
  kbo.py         KBO CSV 로더 (한/영 컬럼 별칭, CP949, '144 1/3' 이닝 파싱)
  formatting.py  마크다운/JSON 출력
  server.py      MCP 툴 정의
tests/           지표 공식, 소스 매핑, 실제 MCP 클라이언트로 툴 호출까지 검증
```

## 공식

- FIP = (13·HR + 3·(BB+HBP) − 2·K) / IP + cFIP, cFIP = 리그ERA − (13·lgHR + 3·(lgBB+lgHBP) − 2·lgK) / lgIP
- BABIP = (H − HR) / (AB − K − HR + SF). KBO CSV에 피타수가 없으면 상대타자 기반 근사치로 계산하고 결과에 표시
- LOB% = (H + BB + HBP − R) / (H + BB + HBP − 1.4·HR)
- 피타고리안 기대 승률 = RS^x / (RS^x + RA^x), 기본 x = 1.83

운 체크 기준(ERA-FIP ±0.75, BABIP ±.030, LOB% ±5%p)은 "어디를 더 볼지" 알려주는 신호일 뿐이다. 40이닝 미만이면 소표본 경고가 붙는다.

## 한계와 다음 단계

- Statcast(xERA, 배럴, 하드히트), WAR, 파크팩터, wOBA는 없다. wOBA는 리그·시즌별 가중치가 필요해서 근사치로 넣지 않았다.
- 다음에 붙이기 좋은 것: Baseball Savant CSV 로더(운 체크에 xERA 추가), 시즌 비교 툴, 경기 로그, KBO 연도별 추이
- MLB Stats API 데이터는 개인적·비상업적 용도로만 쓸 것

## 라이선스

MIT. 단, MLB Stats API로 가져온 데이터 자체는 MLB 저작권 고지를 따른다.
