"""corpCode.xml (ZIP) → 기업 목록."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class CorpCodeRow:
    corp_code: str
    corp_name: str
    stock_code: str | None
    modify_date: str


def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None else ""


def parse_corpcode_zip(raw: bytes, *, listed_only: bool = False) -> list[CorpCodeRow]:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        xml = z.read(name).decode("utf-8")

    root = ET.fromstring(xml)
    rows: list[CorpCodeRow] = []
    for node in root.findall("list"):
        stock = _text(node, "stock_code")
        row = CorpCodeRow(
            corp_code=_text(node, "corp_code"),
            corp_name=_text(node, "corp_name"),
            stock_code=stock or None,
            modify_date=_text(node, "modify_date"),
        )
        if listed_only and row.stock_code is None:
            continue
        rows.append(row)
    return rows
