"""latest.json + 보유 정보(시크릿)로 숫자 리포트를 만들어 카카오톡(나에게 보내기)·이메일로 발송.

필요한 GitHub Secrets (없는 채널은 건너뜀)
- HOLDINGS_JSON        {"011930":{"name":"신성이엔지","avg":20105,"qty":544}, ...}  ← 평단·수량은 공개 저장소에 두지 않음
- KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN, (선택) KAKAO_CLIENT_SECRET
- GH_PAT               (선택) 카카오 refresh token이 갱신되면 시크릿을 자동 교체
- GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO
"""
import json
import os
import smtplib
import subprocess
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests

OUT = Path(__file__).parent / "data" / "latest.json"
WD = "월화수목금토일"


def pct(x, signed=True):
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def arrow(x):
    return "🔴" if x > 0 else "🔵" if x < 0 else "⚪"


def build(d: dict, hold_cfg: dict) -> list[str]:
    """섹션별 문자열 리스트 (카카오 1메시지 = 1섹션, 200자 내외)."""
    dt = datetime.strptime(d["data_date"], "%Y-%m-%d")
    head = f"📊 장마감 {dt.month}/{dt.day}({WD[dt.weekday()]}) · 기준 {d['generated_at']}"
    if d.get("stale"):
        head += "\n⚠️ 오늘 데이터 아님"

    # 보유
    lines = ["💼 보유"]
    for name, h in d["holdings"].items():
        if "close" not in h:
            lines.append(f"{name} 데이터 없음")
            continue
        cfg = hold_cfg.get(h["code"], {})
        usd = not h["code"].isdigit()
        px = f"${h['close']:,.2f}" if usd else f"{h['close']:,.0f}원"
        s = f"{name} {px} {arrow(h['chg_1d'])}{pct(h['chg_1d'])}"
        if cfg.get("avg"):
            pr = h["close"] / cfg["avg"] - 1
            pl = (h["close"] - cfg["avg"]) * cfg["qty"]
            s += f" | 평단 {pct(pr)} {('$' + format(pl, ',.0f')) if usd else format(pl, ',.0f') + '원'}"
        lines.append(s)
    sec_hold = "\n".join(lines)

    # 업종
    sec = d.get("sectors") or {}
    sec_lines = []
    if sec:
        k = sec["kospi"]
        sec_lines.append(f"🧭 코스피 1일 {pct(k['r1d'] / 100)} · 20일 {pct(k['r20d'] / 100)} · 60일 {pct(k['r60d'] / 100)}")
        for g, title in (("strong", "🔥 강세"), ("inline", "➖ 동행"), ("weak", "🧊 약세")):
            items = sec["groups"][g]
            items = items[:4] if g != "weak" else items[-4:][::-1]
            txt = ", ".join(f"{s['sector']}({s['excess']:+.0f})" for s in items) or "없음"
            sec_lines.append(f"{title}: {txt}")
    sec_sector = "\n".join(sec_lines)

    # 후보
    c_lines = ["🎯 눌림 후보(기술점수)"]
    for c in d["candidates"][:5]:
        c_lines.append(f"{c['name']} {c['close']:,.0f} · 진입 {c['entry_low']:,}~{c['entry_high']:,} · "
                       f"목표 {pct(c['target_pct'])} · 손절 {pct(c['stop_pct'])} · {c['tech_score']:.0f}점")
    sec_cand = "\n".join(c_lines)
    return [head + "\n\n" + sec_hold, sec_sector, sec_cand]


def kakao(parts: list[str]):
    key, rt = os.getenv("KAKAO_REST_KEY"), os.getenv("KAKAO_REFRESH_TOKEN")
    if not (key and rt):
        print("카카오 시크릿 없음 → 건너뜀")
        return
    data = {"grant_type": "refresh_token", "client_id": key, "refresh_token": rt}
    if os.getenv("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = os.getenv("KAKAO_CLIENT_SECRET")
    tok = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=15).json()
    if "access_token" not in tok:
        raise SystemExit(f"카카오 토큰 갱신 실패: {tok}")
    if tok.get("refresh_token") and os.getenv("GH_PAT"):   # 만료 1개월 전 새 토큰 발급 시 자동 교체
        subprocess.run(["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--body", tok["refresh_token"]],
                       env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]}, check=False)
        print("카카오 refresh token 갱신됨")
    elif tok.get("refresh_token"):
        print("⚠️ 카카오 refresh token이 새로 발급됨 — GH_PAT가 없어 자동 교체 못함, 수동 갱신 필요")
    link = {"web_url": "https://finance.naver.com", "mobile_web_url": "https://m.stock.naver.com"}
    for p in [x for x in parts if x]:
        for i in range(0, len(p), 195):    # 텍스트 템플릿은 200자 제한
            obj = {"object_type": "text", "text": p[i:i + 195], "link": link, "button_title": "증권 열기"}
            r = requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                              headers={"Authorization": f"Bearer {tok['access_token']}"},
                              data={"template_object": json.dumps(obj, ensure_ascii=False)}, timeout=15)
            print("카카오 전송", r.status_code, r.text[:80])


def email(parts: list[str]):
    user, pw, to = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD"), os.getenv("MAIL_TO")
    if not (user and pw and to):
        print("메일 시크릿 없음 → 건너뜀")
        return
    msg = MIMEText("\n\n".join(p for p in parts if p), "plain", "utf-8")
    msg["Subject"] = parts[0].splitlines()[0]
    msg["From"], msg["To"] = user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    print("메일 전송 완료")


def main():
    d = json.loads(OUT.read_text())
    hold_cfg = json.loads(os.getenv("HOLDINGS_JSON") or "{}")
    parts = build(d, hold_cfg)
    print("\n\n".join(parts))
    for fn in (kakao, email):
        try:
            fn(parts)
        except Exception as e:   # 한 채널 실패가 다른 채널을 막지 않게
            print(f"{fn.__name__} 실패: {e}")


if __name__ == "__main__":
    main()
