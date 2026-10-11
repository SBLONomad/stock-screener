"""지표 계산과 TOP5 필수조건 필터 (데이터 소스와 분리해서 테스트 가능하게 둠)."""
import math

import pandas as pd

# ---- 필수 조건 (리포트 기준과 동일) ----
MIN_MARCAP = 3_000e8          # 시가총액 3,000억원
MIN_AMOUNT20 = 50e8           # 20일 평균 거래대금 50억원
PULLBACK_MIN, PULLBACK_MAX = -0.20, -0.07   # 60일 고점 대비 하락률
MA20_BAND = 0.05              # 20일선 ±5%
RSI_MAX = 70
RET5_MAX = 0.15               # 5거래일 +15% 이상 급등 제외
MA20_GAP_MAX = 0.10           # 20일선 이격 +10% 이상 제외
MAX_STOP_PCT = 0.08           # 손절은 진입가 대비 -8% 이내
MIN_STOP_PCT = 0.03           # 손절폭 최소 3%
MIN_RR = 2.0                  # 손익비 2 이상


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, math.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def compute(df: pd.DataFrame) -> dict | None:
    """df: 일봉 (Open, High, Low, Close, Volume) — 최소 80봉. 마지막 봉 기준 지표 dict."""
    if df is None or len(df) < 80:
        return None
    df = df.dropna(subset=["Close"])
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    ma5, ma20, ma60 = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(60).mean()
    amount = c * v
    last = c.iloc[-1]
    high60 = h.iloc[-60:].max()
    out = {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": float(last),
        "chg_1d": float(last / c.iloc[-2] - 1),
        "ret_5d": float(last / c.iloc[-6] - 1),
        "ma5": float(ma5.iloc[-1]),
        "ma20": float(ma20.iloc[-1]),
        "ma60": float(ma60.iloc[-1]),
        "ma60_slope_20d": float(ma60.iloc[-1] / ma60.iloc[-21] - 1),
        "rsi14": float(rsi(c).iloc[-1]),
        "high60": float(high60),
        "low10": float(l.iloc[-10:].min()),
        "low20": float(l.iloc[-20:].min()),
        "from_high": float(last / high60 - 1),
        "ma20_gap": float(last / ma20.iloc[-1] - 1),
        "amount20": float(amount.iloc[-20:].mean()),
        "vol_ratio_5_20": float(v.iloc[-5:].mean() / max(v.iloc[-20:].mean(), 1)),
    }
    return {k: (round(x, 4) if isinstance(x, float) else x) for k, x in out.items()}


def plan(ind: dict) -> dict:
    """진입 범위·목표·손절·손익비·분류·기술 점수(70점 만점)."""
    close, ma20, ma60 = ind["close"], ind["ma20"], ind["ma60"]
    entry_lo = min(ma20, ind["low10"], close)
    entry_hi = max(min(ma20 * 1.02, close), entry_lo)
    entry = (entry_lo + entry_hi) / 2
    target = ind["high60"]
    # 손절: 진입 하단 아래에 있는 60일선·20일 저점 중 가까운 쪽을 2% 이탈
    supports = [s for s in (ma60, ind["low20"]) if s < entry_lo] or [min(ma60, ind["low20"])]
    stop = max(supports) * 0.98
    stop = min(stop, entry * (1 - MIN_STOP_PCT))   # 너무 촘촘한 손절로 손익비 부풀리기 방지
    stop = max(stop, entry * (1 - MAX_STOP_PCT))   # -8% 이내로 제한
    rr = (target - entry) / (entry - stop) if entry > stop else 0.0

    # 분류: 5일선 회복 + 전일 상승이면 지지 확인, 아니면 눌림 대기
    if close >= ind["ma5"] and ind["chg_1d"] > 0:
        label = "🟢 즉시 진입 관심"
    else:
        label = "🟡 눌림 대기"

    # 기술 점수 (모멘텀 30점은 리포트에서 뉴스로 채움)
    trend = 25 * min(1, max(0, (close / ma60 - 1) / 0.15)) * (1 if ind["ma60_slope_20d"] > 0 else 0.6)
    pull = 25 * max(0, 1 - abs(ind["from_high"] + 0.12) / 0.10) * max(0, 1 - abs(ind["ma20_gap"]) / MA20_BAND * 0.5)
    vol = 20 * min(1, max(0, (1.3 - ind["vol_ratio_5_20"]) / 0.6))
    return {
        "entry_low": round(entry_lo), "entry_high": round(entry_hi),
        "target": round(target), "stop": round(stop),
        "target_pct": round(target / entry - 1, 4), "stop_pct": round(stop / entry - 1, 4),
        "rr": round(rr, 2), "label": label,
        "tech_score": round(trend + pull + vol, 1),
        "score_parts": {"trend25": round(trend, 1), "pullback25": round(pull, 1), "volume20": round(vol, 1)},
    }


def passes(ind: dict, marcap: float | None) -> tuple[bool, str]:
    """필수 조건 통과 여부와 탈락 사유."""
    if marcap is not None and marcap < MIN_MARCAP:
        return False, "시총"
    if ind["amount20"] < MIN_AMOUNT20:
        return False, "거래대금"
    if ind["close"] <= ind["ma60"]:
        return False, "60일선 아래"
    if not (PULLBACK_MIN <= ind["from_high"] <= PULLBACK_MAX):
        return False, "눌림폭"
    if abs(ind["ma20_gap"]) > MA20_BAND:
        return False, "20일선 거리"
    if ind["rsi14"] >= RSI_MAX or ind["ret_5d"] >= RET5_MAX or ind["ma20_gap"] >= MA20_GAP_MAX:
        return False, "과열"
    return True, ""
