"""대규모기업집단 소속 여부 수집.

`대규모기업집단현황공시` 는 공정위 지정 대기업집단 소속회사만 제출한다. 따라서
**제출자 목록 = 소속회사 목록**이다.

⚠️ 한계: DART 는 '소속 여부' 는 주지만 **'어느 집단인지' 는 안 준다.** list API 에
집단명 필드가 없다. 집단 식별은 공정거래위원회 기업집단포털이 필요하고, 그래서
`check_company.py` 의 계열 라벨은 아직 손으로 넣은 20개다.

그래도 소속 여부만으로 쓸모가 있다 — 대기업집단 소속이면 내부거래·상호출자 규제를
받고, 공시 의무도 다르다.

⚠️ 부분 수집본을 "소속 명단" 으로 쓰면 **나머지 전부가 '미소속' 으로 잘못 분류된다.**
   모르는 걸 아니라고 세는 오류다. 그래서 500사 미만이면 경고를 띄우고,
   `--max-pages` 를 충분히 올려 전수를 떠야 한다(분기당 8,000건 = 80페이지).

집단명은 못 얻는다 — list API 에 없고 `flr_nm` 도 회사명과 같다(실측 확인).
그래도 **소속 여부**만으로 검정 가능한 신호가 된다.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify

OUT = Path("data/conglomerate_members.json")
KEY = "대규모기업집단현황공시"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2024")
    p.add_argument("--max-pages", type=int, default=100,
                   help="분기당 페이지 상한. 낮으면 부분 수집이 되어 쓸 수 없다")
    args = p.parse_args(argv)
    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr); return 2

    c = DartClient(api_key=s.dart_api_key)
    members: dict[str, str] = {}
    try:
        # 3개월 제한이 있어 분기로 끊는다
        for bgn, end in [(f"{args.year}0101", f"{args.year}0331"),
                         (f"{args.year}0401", f"{args.year}0630"),
                         (f"{args.year}0701", f"{args.year}0930"),
                         (f"{args.year}1001", f"{args.year}1231")]:
            page = 1
            while page <= args.max_pages:
                r = c.get_json("list.json", {"bgn_de": bgn, "end_de": end,
                                             "pblntf_ty": "J", "page_no": str(page),
                                             "page_count": "100"})
                if classify(str(r.get("status", ""))) is not Action.OK:
                    break
                for it in (r.get("list") or []):
                    if KEY in it.get("report_nm", ""):
                        members[it["corp_code"]] = it.get("corp_name", "")
                if page >= int(r.get("total_page", 1)):
                    break
                page += 1
            print(f"  {bgn[:6]} 누적 {len(members)}사")
    finally:
        c.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"year": args.year, "members": members},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n대규모기업집단 소속 {len(members):,}사 ({args.year})")
    print("예:", ", ".join(list(members.values())[:8]))
    print(f"→ {OUT}")
    if len(members) < 500:
        print(f"\n⚠️ {len(members)}사는 전수가 아니다 — --max-pages 를 올려 다시 뜰 것. "
              "부분 목록을 소속 명단으로 쓰면 나머지가 '미소속' 으로 잘못 분류된다.")
    print("\n⚠️ 집단명은 DART 에 없다 — 어느 집단인지는 공정위 포털이 필요하다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
