# KBO 데이터 폴더

이 폴더에 시즌별 CSV를 넣으면 서버가 읽는다. (`.gitignore`로 CSV는 커밋되지 않게 해 두었다.)

## 파일 이름

```
hitters_2026.csv      타자
pitchers_2026.csv     투수
league_overrides.json (선택)
```

## 필수 컬럼

| 파일 | 필수 | 있으면 좋은 것 |
|---|---|---|
| 타자 | 선수명, AB, H, HR, BB, SO | 팀명, G, PA, 2B, 3B, HBP, SF, SAC, SB, CS, IBB, RBI, GDP |
| 투수 | 선수명, IP, H, HR, BB, SO, ER | 팀명, G, GS, W, L, SV, HLD, TBF, HBP, R, AB(피타수) |

헤더는 한글/영문 모두 인식한다. 예: `볼넷`=`BB`, `삼진`/`탈삼진`=`SO`, `사구`=`HBP`, `희비`=`SF`, `희타`=`SAC`, `TBF`=상대타자. 전체 목록은 `src/baseball_stats_mcp/kbo.py`의 `COLUMN_ALIASES`.

## 만드는 법

KBO 기록실 화면의 표를 직접 복사해 엑셀/구글 시트에 붙여넣고 CSV로 저장하면 된다. 기록실은 컬럼이 여러 탭(기본기록 1, 2 등)에 나뉘어 있으니 **선수별로 한 행이 되도록 합쳐서** 한 파일로 만든다.

- 이닝은 `144 1/3`, `144.1`, `144⅓` 모두 인식
- 엑셀 기본 저장(CP949)과 UTF-8 모두 인식
- 2B가 없으면 장타율·ISO가 과소 계산되니 가능하면 포함

## league_overrides.json

리그 FIP 상수는 투수 파일 전체를 더해서 계산한다. 파일에 일부 투수만 있으면 상수가 틀어지므로, 알고 있는 값으로 덮어쓸 수 있다.

```json
{
  "2026": { "fip_constant": 4.21, "team_games": 144 }
}
```

`team_games`는 규정타석·규정이닝 계산에 쓰인다. 없으면 타자 파일의 최다 경기 수로 추정한다.

문제가 있으면 Claude에게 "KBO 데이터 상태 확인해줘"라고 하면 `kbo_data_status`가 어떤 파일이 읽혔고 어떤 컬럼이 빠졌는지 알려준다.
