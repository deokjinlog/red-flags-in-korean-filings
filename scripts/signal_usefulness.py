"""채택된 신호가 실제로 얼마나 쓸 만한가 — 정밀도·재현율·신뢰구간.

왜 따로 내나:
  "결손금 ×3.7 · p=0.0002" 를 "결손금 있으면 망한다" 로 읽으면 완전히 틀린다.
  배율은 기저율 위에서만 뜻이 있고, 기저율이 3% 면 ×3.7 은 6% 다.
  **걸린 기업의 94%는 2년 안에 아무 일도 없었다.**

  반대쪽도 봐야 한다 — 부실이 난 회사 중 이 신호가 몇 %를 잡았는지(재현율).
  절반을 놓치는 신호를 "부실을 잡아낸다" 고 말하면 안 된다.

사용:
    uv run python scripts/signal_usefulness.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import CensoredWindowError, events_after
from dartweave.signal.labels import is_distress
from dartweave.signal.usefulness import lift_ci, usefulness

SIGNALS = {
    "결손금": lambda a: float(a["이익잉여금"]) < 0,
    "영업손실": lambda a: a.get("영업이익") is not None and float(a["영업이익"]) < 0,
    "당기순손실": lambda a: (a.get("당기순이익(손실)") is not None
                        and float(a["당기순이익(손실)"]) < 0),
    "셋 중 하나라도": lambda a: any((
        float(a["이익잉여금"]) < 0,
        a.get("영업이익") is not None and float(a["영업이익"]) < 0,
        a.get("당기순이익(손실)") is not None and float(a["당기순이익(손실)"]) < 0,
    )),
    "셋 다": lambda a: all((
        float(a["이익잉여금"]) < 0,
        a.get("영업이익") is not None and float(a["영업이익"]) < 0,
        a.get("당기순이익(손실)") is not None and float(a["당기순이익(손실)"]) < 0,
    )),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20220630,20230630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--fin", default="data/fin_by_year.json")
    p.add_argument("--runs", type=int, default=2000)
    args = p.parse_args(argv)

    fin = json.loads(Path(args.fin).read_text(encoding="utf-8"))
    engine = create_engine(args.db)

    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        year = str(int(T[:4]) - 1)
        acc = fin.get(year, {})
        with Session(engine) as s:
            try:
                events = events_after(s, T, within_days=args.within_days)
            except CensoredWindowError as e:
                # 관측 창이 모자란 기준시점 하나 때문에 전체 실행을 죽이지 않는다.
                # 대신 **조용히 포함시키지도 않는다** — 그게 배율 비교를 어긋나게 한다.
                print(f"\n{'=' * 74}\nT={T} 건너뜀 — {e}")
                continue
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        # 재무 신호에 그래프 소속을 요구하지 않는다 — 요구하면 DART 타법인출자 API 의
        # 연도별 수록 편차가 표본을 좌우한다(2020 사업연도는 2021년의 3분의 1도 안 준다).
        pool = sorted(c for c in acc if "이익잉여금" in (acc.get(c) or {}))
        labels = [c in label for c in pool]

        print(f"\n{'=' * 76}\nT={T} · {year}년 재무 · {len(pool):,}사 · "
              f"이후 {args.within_days}일 부실 {sum(labels)}사 "
              f"(기저율 {sum(labels) / len(pool):.1%})\n")
        for name, rule in SIGNALS.items():
            flags = [rule(acc[c]) for c in pool]
            u = usefulness(flags, labels)
            ci = lift_ci(flags, labels, runs=args.runs)
            band = f" · 95% CI ×{ci[0]:.2f}~×{ci[1]:.2f}" if ci else ""
            print(f"  [{name}]")
            print(f"    {u.explain()}{band}")
    print("\n※ 여기 배율은 신호군 대 **전체**(통제 없음) 라 검정 쪽 ×3.70(신호군 대"
          "\n   비신호군 · 규모·업종 통제)보다 낮게 나온다. 분모가 다르다.")
    print("\n※ 배율이 크다고 '이 회사는 망한다' 가 아니다. 가장 강한 신호도 걸린 기업의"
          "\n   90% 이상은 2년 안에 아무 일도 없었다. 이 도구가 매수·매도를 말하지 않는"
          "\n   이유가 여기 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
