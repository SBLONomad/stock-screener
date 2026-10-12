"""평일 장마감 후 실행: 국장 전 종목 일봉으로 지표 계산 → 후보·보유종목을 data/latest.json에 저장."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import FinanceDataReader as fdr

from indicators import MIN_MARCAP, MIN_RR, compute, passes, plan
from sectors import analyze as analyze_sectors

KST = timezone(timedelta(hours=9))
HOLDINGS = {"011930": "신성이엔지", "042660": "한화오션", "IREN": "IREN"}
TOP_N = 20
OUT = Path(__file__).parent / "data" / "latest.json"


def load_universe():
    lst = fdr.StockListing("KRX")
    lst = lst[lst["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
    lst = lst[~lst["Name"].str.contains("스팩|리츠|우$|우B$|우C$", regex=True)]
    lst = lst[lst["Marcap"] >= MIN_MARCAP]
    try:  # 업종 정보 (없어도 진행)
        desc = fdr.StockListing("KRX-DESC")[["Code", "Sector"]]
        lst = lst.merge(desc, on="Code", how="left")
    except Exception:
        lst["Sector"] = None
    return lst


def fetch(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None


def main():
    today = datetime.now(KST)
    # 예약 실행이 두 번(본 실행+백업) 걸려 있어서, 오늘 데이터가 이미 있으면 건너뜀
    if os.getenv("GITHUB_EVENT_NAME") == "schedule" and OUT.exists():
        prev = json.loads(OUT.read_text())
        if prev.get("data_date") == today.strftime("%Y-%m-%d"):
            print("오늘 데이터 이미 있음 → 건너뜀")
            Path(os.getenv("GITHUB_OUTPUT", os.devnull)).open("a").write("skip=true\n")
            return
    start = (today - timedelta(days=170)).strftime("%Y-%m-%d")
    uni = load_universe()
    rows = uni.to_dict("records")

    with ThreadPoolExecutor(max_workers=8) as ex:
        dfs = list(ex.map(lambda r: fetch(r["Code"], start), rows))

    cands, reasons, scanned, data_date = [], {}, 0, None
    for r, df in zip(rows, dfs):
        ind = compute(df)
        if not ind:
            continue
        scanned += 1
        data_date = max(data_date or ind["date"], ind["date"])
        ok, why = passes(ind, r["Marcap"])
        if not ok:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        p = plan(ind)
        if p["rr"] < MIN_RR:
            reasons["손익비"] = reasons.get("손익비", 0) + 1
            continue
        cands.append({"code": r["Code"], "name": r["Name"], "market": r["Market"],
                      "sector": r.get("Sector"), "marcap_eok": round(r["Marcap"] / 1e8),
                      **ind, **p})

    cands.sort(key=lambda x: x["tech_score"], reverse=True)

    # 코스피 시총 상위 100 업종 분석 (이미 받은 일봉 재사용)
    sectors = {}
    try:
        closes = {r["Code"]: df["Close"] for r, df in zip(rows, dfs) if df is not None and len(df)}
        top = uni[uni["Market"] == "KOSPI"].nlargest(100, "Marcap")
        sectors = analyze_sectors(top, closes, fdr.DataReader("KS11", start)["Close"])
    except Exception as e:
        print("업종 분석 실패:", e)

    holdings = {}
    for code, name in HOLDINGS.items():
        ind = compute(fetch(code, start))
        holdings[name] = ({"code": code, **ind} if ind else {"code": code, "error": "데이터 없음"})

    result = {
        "generated_at": today.strftime("%Y-%m-%d %H:%M KST"),
        "data_date": data_date,
        "stale": data_date != today.strftime("%Y-%m-%d"),
        "stats": {"universe": len(rows), "scanned": scanned, "passed": len(cands), "rejected": reasons},
        "note": "tech_score는 70점 만점(추세25+눌림25+거래량20). 모멘텀 30점은 리포트에서 뉴스로 판단.",
        "holdings": holdings,
        "candidates": cands[:TOP_N],
        "sectors": sectors,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"scanned={scanned} passed={len(cands)} date={data_date}")
    if scanned == 0:
        sys.exit("데이터를 하나도 받지 못함")


if __name__ == "__main__":
    main()
