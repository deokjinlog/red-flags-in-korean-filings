import csv
import io

from dartweave.graph.export import EXPORT_HEADER, degree_table, write_edge_list


ROWS = [
    {"start": "A", "end": "B", "type": "SUPPLIES_TO", "weight": 1.0, "fiscal_year": "2025"},
    {"start": "B", "end": "C", "type": "SUPPLIES_TO", "weight": 0.5, "fiscal_year": "2025"},
    {"start": "A", "end": "C", "type": "SUPPLIES_TO", "weight": 2.0, "fiscal_year": "2025"},
]


def test_header_matches_contract():
    assert EXPORT_HEADER == ["start", "end", "type", "weight", "fiscal_year"]


def test_writes_all_rows_with_header():
    buf = io.StringIO()
    write_edge_list(ROWS, buf)
    parsed = list(csv.reader(io.StringIO(buf.getvalue())))
    assert parsed[0] == EXPORT_HEADER
    assert len(parsed) == 4


def test_degree_table_preserves_direction():
    """차수 보존 셔플이 가능하려면 방향별 차수가 나와야 한다."""
    deg = degree_table(ROWS)
    assert deg["A"] == {"out": 2, "in": 0}
    assert deg["B"] == {"out": 1, "in": 1}
    assert deg["C"] == {"out": 0, "in": 2}


def test_degree_sum_is_conserved():
    deg = degree_table(ROWS)
    assert sum(d["out"] for d in deg.values()) == len(ROWS)
    assert sum(d["in"] for d in deg.values()) == len(ROWS)
