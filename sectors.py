"""코스피 시총 상위 100종목을 업종별로 묶어 코스피 지수 대비 강세·동행·약세로 분류."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MAP_CACHE = Path(__file__).parent / "data" / "sector_map.json"
UA = {"User-Agent": "Mozilla/5.0"}
NAVER = "https://finance.naver.com"

# 분류 기준: 초과수익 E = 0.6×(20일 초과) + 0.4×(60일 초과), %p
STRONG_E, WEAK_E = 3.0, -3.0


def naver_sector_map() -> dict:
    """네이버 업종 분류(약 80개) → {종목코드: 업종명}. 실패하면 캐시 사용."""
    try:
        html = requests.get(f"{NAVER}/sise/sise_group.naver?type=upjong", headers=UA, timeout=15)
        html.encoding = "euc-kr"
        groups = re.findall(r'sise_group_detail\.naver\?type=upjong&(?:amp;)?no=(\d+)"[^>]*>([^<]+)</a>', html.text)
        m = {}
        for no, name in groups:
            r = requests.get(f"{NAVER}/sise/sise_group_detail.naver?type=upjong&no={no}", headers=UA, timeout=15)
            r.encoding = "euc-kr"
            for code in re.findall(r'/item/main\.naver\?code=(\d{6})', r.text):
                m.setdefault(code, name.strip())
        if len(m) > 500:   # 정상 수집일 때만 캐시 갱신
            MAP_CACHE.parent.mkdir(exist_ok=True)
            MAP_CACHE.write_text(json.dumps(m, ensure_ascii=False))
        if m:
            return m
    except Exception as e:
        print("업종 분류 수집 실패, 캐시 사용:", e)
    return json.loads(MAP_CACHE.read_text()) if MAP_CACHE.exists() else {}


def _ret(c: pd.Series, n: int) -> float:
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else float("nan")


def analyze(top: pd.DataFrame, closes: dict, kospi: pd.Series) -> dict:
    """top: Code·Name 컬럼(시총 상위 100), closes: {code: 종가 Series}, kospi: 코스피 종가 Series."""
    smap = naver_sector_map()
    k = kospi.dropna()
    kr = {"r1d": _ret(k, 1), "r5d": _ret(k, 5), "r20d": _ret(k, 20), "r60d": _ret(k, 60)}
    k_daily = k.pct_change().iloc[-60:]

    rows = []
    for code, name in zip(top["Code"], top["Name"]):
        c = closes.get(code)
        if c is None or len(c) < 70:
            continue
        c = c.dropna()
        rows.append({"code": code, "name": name, "sector": smap.get(code, "기타"),
                     "r1d": _ret(c, 1), "r5d": _ret(c, 5), "r20d": _ret(c, 20), "r60d": _ret(c, 60),
                     "above20": float(c.iloc[-1] > c.iloc[-20:].mean()),
                     "daily": c.pct_change().iloc[-60:]})
    if not rows:
        return {}
    df = pd.DataFrame(rows)

    out = []
    for sec, g in df.groupby("sector"):
        daily = pd.concat(list(g["daily"]), axis=1).mean(axis=1)            # 업종 동일가중 일간수익률
        both = pd.concat([daily, k_daily], axis=1).dropna()
        corr = float(both.iloc[:, 0].corr(both.iloc[:, 1])) if len(both) > 20 else float("nan")
        beta = float(np.cov(both.iloc[:, 0], both.iloc[:, 1])[0, 1] / both.iloc[:, 1].var()) if len(both) > 20 else float("nan")
        s = {"sector": sec, "n": len(g),
             **{f: float(g[f].mean()) for f in ("r1d", "r5d", "r20d", "r60d")},
             "above_ma20": float(g["above20"].mean()), "corr": corr, "beta": beta,
             "leaders": list(g.sort_values("r20d", ascending=False)["name"].head(3))}
        s["ex20"], s["ex60"] = s["r20d"] - kr["r20d"], s["r60d"] - kr["r60d"]
        s["excess"] = 0.6 * s["ex20"] + 0.4 * s["ex60"]
        if s["excess"] >= STRONG_E and s["above_ma20"] >= 0.5:
            s["group"] = "strong"
        elif s["excess"] <= WEAK_E:
            s["group"] = "weak"
        else:
            s["group"] = "inline"
        out.append({x: ((None if np.isnan(v) else round(v, 2)) if isinstance(v, float) else v) for x, v in s.items()})

    out.sort(key=lambda s: s["excess"], reverse=True)
    return {"kospi": {x: round(v, 2) for x, v in kr.items()},
            "rule": f"초과수익=0.6×20일+0.4×60일(%p). 강세≥+{STRONG_E}&20일선위 50%↑, 약세≤{WEAK_E}, 나머지 동행",
            "groups": {g: [s for s in out if s["group"] == g] for g in ("strong", "inline", "weak")}}
