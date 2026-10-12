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

## 업종 분석 (`sectors.py`)
- 코스피 시총 상위 100종목(우선주 제외)을 네이버 업종으로 묶어 업종 동일가중 수익률을 코스피 지수와 비교
- 초과수익 = 0.6×(20일 초과) + 0.4×(60일 초과), %p
  - 🔥 강세: +3%p 이상 & 20일선 위 종목 50% 이상 · 🧊 약세: -3%p 이하 · ➖ 동행: 나머지
- 60일 상관계수·베타도 함께 저장 (`latest.json` → `sectors`)

## 카카오톡·메일 발송 (`notify.py`)
GitHub → Settings → Secrets and variables → Actions → New repository secret. 없는 채널은 건너뜀.

| Secret | 값 |
|---|---|
| `HOLDINGS_JSON` | `{"011930":{"avg":20105,"qty":544},"042660":{"avg":107440,"qty":75},"IREN":{"avg":38.53,"qty":66}}` |
| `GMAIL_USER` / `MAIL_TO` | 보내는 Gmail / 받을 주소 |
| `GMAIL_APP_PASSWORD` | Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호(16자리) |
| `KAKAO_REST_KEY` | 카카오 디벨로퍼스 앱의 REST API 키 |
| `KAKAO_REFRESH_TOKEN` | 아래 1회 발급 절차로 받은 값 |
| `KAKAO_CLIENT_SECRET` | (앱에서 Client Secret을 켠 경우만) |
| `GH_PAT` | (선택) repo 권한 토큰 — 카카오 refresh token(2개월 만료)을 자동 갱신 |

카카오 refresh token 1회 발급
1. developers.kakao.com → 내 애플리케이션 → 앱 추가
2. 카카오 로그인 활성화, Redirect URI에 `https://localhost` 등록, 동의항목에서 `카카오톡 메시지 전송` 켜기
3. 브라우저로 `https://kauth.kakao.com/oauth/authorize?client_id=REST키&redirect_uri=https://localhost&response_type=code&scope=talk_message` 접속·동의 → 주소창 `code=` 뒤 값 복사
4. `curl -d grant_type=authorization_code -d client_id=REST키 -d redirect_uri=https://localhost -d code=복사한값 https://kauth.kakao.com/oauth/token` → `refresh_token` 값을 시크릿에 저장

## 실행
- 자동: 평일 17:37 KST + 백업 17:52 KST (오늘 데이터가 있으면 백업은 건너뜀). 실행 후 카톡·메일 발송
- Claude 리포트(뉴스 모멘텀 포함)는 18:04 KST에 이 파일을 읽어 작성
- 수동: GitHub → Actions → daily-screen → Run workflow
- 로컬: `pip install -r requirements.txt && python screener.py`
