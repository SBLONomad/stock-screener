# stock-screener

평일 장마감 후 국장(코스피·코스닥) 종목의 일봉으로 지표를 계산해 `data/latest.json`에 저장합니다.
Claude 예약 리포트가 이 파일을 읽어 TOP5와 보유 종목 점검을 작성합니다.

## 필수 조건 (`indicators.py`)
| 항목 | 기준 |
|---|---|
| 유동성 | 시총 3,000억 이상, 20일 평균 거래대금 50억 이상 |
| 추세 | 종가 > 60일선 |
| 눌림 | 60일 고점 대비 -7% ~ -20%, 20일선 ±5% |
| 과열 제외 | RSI(14) ≥ 70, 5일 +15% 이상, 20일선 이격 +10% 이상 |
| 손익비 | (목표−진입)/(진입−손절) ≥ 2 |

- 목표 = 60일 고점, 손절 = 60일선·20일 저점 중 높은 쪽 이탈(진입가 대비 -8% 이내)
- `tech_score` 70점 = 추세 25 + 눌림 25 + 거래량(조정 중 감소) 20. 모멘텀 30점은 리포트에서 뉴스로 채점.

## 실행
- 자동: 평일 15:35 KST (`.github/workflows/screen.yml`)
- 수동: GitHub → Actions → daily-screen → Run workflow
- 로컬: `pip install -r requirements.txt && python screener.py`
