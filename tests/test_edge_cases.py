"""
Edge-case hardening — the pipeline must degrade gracefully, never crash.
Run from project root:  python tests/test_edge_cases.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ["SAPIENOIDS_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_tmp_home")

import numpy as np
import pandas as pd

from core.ingest import load_bytes
from core.presets import build_bundle
from core.reports.analyst_report import (build_analyst_report, markdown_to_doc,
                                         render_markdown, render_pdf)
from tests.test_presets import make_retail

PASS, FAIL = 0, 0


def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✅ {name}")
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name} → {type(e).__name__}: {e}")


def main():
    print("=" * 60)
    print("  EDGE CASE TEST")
    print("=" * 60)

    print("\n[1] Degenerate dataframes never crash the pipeline")
    cases = {
        "empty df": pd.DataFrame(),
        "one row": pd.DataFrame({"Revenue": [10.0], "Date": ["2024-01-01"]}),
        "one column": pd.DataFrame({"Amount": np.arange(50.0)}),
        "all nulls": pd.DataFrame({"a": [None] * 20, "b": [None] * 20}),
        "no dates": pd.DataFrame({"Product": ["a", "b"] * 25,
                                  "Sales": np.random.rand(50)}),
        "all text": pd.DataFrame({"Notes": ["hello world"] * 30,
                                  "Comment": ["x" * 80] * 30}),
        "single category": pd.DataFrame({"Store": ["S1"] * 40,
                                         "Amount": np.random.rand(40)}),
        "mixed junk": pd.DataFrame({"c1": [1, "x", None, 3.5] * 10,
                                    "c2": pd.date_range("2024-01-01",
                                                        periods=40)}),
    }
    for name, df in cases.items():
        check(f"build_bundle({name})", lambda d=df: build_bundle(d))

    print("\n[2] Report on minimal preset data")
    tiny = make_retail(25)
    b = build_bundle(tiny)

    def _tiny_report():
        assert b.preset is not None
        doc = build_analyst_report(tiny, b, b.kpis, b.cards)
        assert len(doc.sections) >= 4
        assert len(render_pdf(doc)) > 1000
    check("25-row retail report builds", _tiny_report)

    print("\n[3] Ingest pathological files")
    check("empty csv", lambda: load_bytes("x.csv", b""))
    check("header only", lambda: load_bytes("x.csv", b"a,b,c\n"))
    check("one cell", lambda: load_bytes("x.csv", b"hello"))
    check("unicode junk", lambda: load_bytes(
        "x.csv", "名前,金額\nテスト,¥1000\n".encode("utf-8")))
    check("semicolon delimited", lambda: (
        (lambda r: [None for _ in [0]] and None)(None)
        if load_bytes("x.csv", b"a;b;c\n1;2;3\n4;5;6\n").df.shape[1] == 3
        else (_ for _ in ()).throw(AssertionError("delimiter not sniffed"))))

    print("\n[4] markdown_to_doc robustness")
    check("empty text", lambda: markdown_to_doc(""))
    check("garbage text", lambda: markdown_to_doc("hello\n| broken | table"))
    check("orphan exhibit ref", lambda: markdown_to_doc(
        "## 1. X\n*[Exhibit 99 - gone - see PDF for the chart]*", {}))

    def _roundtrip_stability():
        doc = build_analyst_report(make_retail(200), b, b.kpis, b.cards)
        md = render_markdown(doc, embed_images=False)
        doc2 = markdown_to_doc(md, doc.exhibit_bank())
        md2 = render_markdown(doc2, embed_images=False)
        doc3 = markdown_to_doc(md2, doc.exhibit_bank())
        # double roundtrip: same section count, same table count
        n_tables = lambda d: sum(1 for s in d.sections   # noqa: E731
                                 for blk in s.blocks if blk[0] == "table")
        assert len(doc2.sections) == len(doc3.sections)
        assert n_tables(doc2) == n_tables(doc3), \
            f"{n_tables(doc2)} vs {n_tables(doc3)}"
    check("double roundtrip is stable", _roundtrip_stability)

    print("\n[5] PDF title emoji stripped cleanly (DejaVu)")

    def _emoji_pdf():
        doc = build_analyst_report(make_retail(60), b, b.kpis, b.cards)
        assert "🛒" in doc.title          # kept in markdown/UI
        pdf = render_pdf(doc)             # stripped in PDF, no crash
        assert bytes(pdf[:4]) == b"%PDF"
    check("emoji title renders", _emoji_pdf)

    print("\n" + "=" * 60)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
