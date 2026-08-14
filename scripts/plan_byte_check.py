"""구현계획서의 `**수정 후**` 블록이 실제 파일과 byte-equal 인지 검증한다.

왜 필요한가:
  구현을 서브에이전트에 맡기면 한국어 docstring 이 슬쩍 재서술될 수 있다. 테스트는
  통과하는데 주석의 근거 문장만 바뀌는 식이라 테스트로는 안 잡힌다. LLM 리뷰어에게
  "글자 단위로 대조하라" 고 시키는 것보다 기계 대조가 확실하다.

사용:
    uv run python scripts/plan_byte_check.py <plan.md>
    uv run python scripts/plan_byte_check.py <plan.md> --only src/dartweave/structure/lens.py

blocks 는 다음 형태만 인식한다:

    **수정 후** (new file: `path/to/file.py`):
    ```python
    ...
    ```
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# `**수정 후** (new file: `path`):` 다음 줄부터 펜스 블록.
_HEADER = re.compile(r"^\*\*수정 후\*\*\s*\(new file:\s*`([^`]+)`\)\s*:\s*$")
_FENCE = re.compile(r"^```(\w*)\s*$")


@dataclass(frozen=True)
class Block:
    path: str
    lang: str
    content: str
    plan_line: int


@dataclass(frozen=True)
class Mismatch:
    path: str
    plan_line: int
    reason: str
    detail: str


def extract_blocks(plan_text: str) -> list[Block]:
    lines = plan_text.splitlines()
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        m = _HEADER.match(lines[i])
        if not m:
            i += 1
            continue
        path = m.group(1)
        # 헤더 다음의 첫 펜스를 연다. 사이에 빈 줄이 있을 수 있다.
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        fence = _FENCE.match(lines[j]) if j < len(lines) else None
        if not fence:
            i += 1
            continue
        lang = fence.group(1)
        body: list[str] = []
        k = j + 1
        while k < len(lines) and lines[k] != "```":
            body.append(lines[k])
            k += 1
        # 빈 파일(예: tests/structure/__init__.py)은 body 가 비어 content 도 빈 문자열.
        content = ("\n".join(body) + "\n") if body else ""
        blocks.append(Block(path=path, lang=lang, content=content, plan_line=i + 1))
        i = k + 1
    return blocks


# 메인 에이전트가 사후에 붙이는 거버넌스 주석. `# ⚠️ RISK(` 로 시작해서
# 다음 비-주석 줄 직전까지가 한 덩어리다 (`# — by main(...)` 꼬리 포함).
_RISK_START = re.compile(r"^\s*#\s*⚠️\s*RISK\(")


def strip_risk_comments(text: str) -> str:
    """RISK 주석 블록을 지운 사본. 계획서에는 없고 코드에만 있는 게 정상이다."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if _RISK_START.match(line):
            skipping = True
            continue
        if skipping:
            if line.lstrip().startswith("#"):
                continue
            skipping = False
        out.append(line)
    return ("\n".join(out) + "\n") if out else ""


def verify(
    plan_path: Path,
    root: Path,
    only: str | None = None,
    *,
    ignore_risk: bool = False,
    skip_missing: bool = False,
) -> list[Mismatch]:
    blocks = extract_blocks(plan_path.read_text(encoding="utf-8"))
    out: list[Mismatch] = []
    for b in blocks:
        if only and b.path != only:
            continue
        target = root / b.path
        if not target.exists():
            if not skip_missing:
                out.append(Mismatch(b.path, b.plan_line, "파일 없음", str(target)))
            continue
        actual = target.read_text(encoding="utf-8")
        if actual == b.content:
            continue
        if ignore_risk and strip_risk_comments(actual) == b.content:
            continue
        expected = b.content
        if ignore_risk:
            actual = strip_risk_comments(actual)
        out.append(Mismatch(b.path, b.plan_line, "내용 불일치", _first_diff(expected, actual)))
    return out


def _first_diff(expected: str, actual: str) -> str:
    """첫 어긋난 줄만 보여준다 — 전체 diff 는 눈이 미끄러진다."""
    exp, act = expected.splitlines(), actual.splitlines()
    for n, (e, a) in enumerate(zip(exp, act), start=1):
        if e != a:
            return f"line {n}\n  계획: {e!r}\n  실제: {a!r}"
    if len(exp) != len(act):
        longer, who = (act, "실제") if len(act) > len(exp) else (exp, "계획")
        extra = longer[min(len(exp), len(act)) :][:3]
        return f"줄 수 다름 (계획 {len(exp)} vs 실제 {len(act)}) — {who} 쪽 여분: {extra!r}"
    return "말미 개행 차이"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("plan", type=Path)
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--only", default=None, help="이 경로 하나만 검사")
    p.add_argument(
        "--ignore-risk",
        action="store_true",
        help="메인이 사후에 붙인 `# ⚠️ RISK(...)` 주석은 차이로 치지 않는다",
    )
    p.add_argument(
        "--skip-missing",
        action="store_true",
        help="아직 안 만든 파일은 건너뛴다 (진행 중인 wave 검사용)",
    )
    args = p.parse_args(argv)

    if not args.plan.exists():
        print(f"계획서를 찾을 수 없습니다: {args.plan}", file=sys.stderr)
        return 2

    blocks = extract_blocks(args.plan.read_text(encoding="utf-8"))
    checked = [
        b
        for b in blocks
        if (not args.only or b.path == args.only)
        and (not args.skip_missing or (args.root / b.path).exists())
    ]
    mismatches = verify(
        args.plan,
        args.root,
        args.only,
        ignore_risk=args.ignore_risk,
        skip_missing=args.skip_missing,
    )

    for m in mismatches:
        print(f"MISMATCH {m.path} (plan:{m.plan_line}) — {m.reason}")
        print(f"  {m.detail}")
    if mismatches:
        print(f"\n{len(mismatches)}/{len(checked)} 블록 불일치")
        return 1
    print(f"plan_byte_check ✅ {len(checked)} 블록 전부 byte-equal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
