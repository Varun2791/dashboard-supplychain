"""Dataframe-engine smoke test (ADR-026: pandas + pyarrow).

Reads a tiny invented fixture with pandas to prove the approved engine
resolves and parses tabular data. The fixture contains no real customer,
order, or product data and no personal information of any kind.
"""

from pathlib import Path

import pandas as pd


def test_pandas_reads_synthetic_fixture() -> None:
    """pandas loads the synthetic fixture with the expected shape."""
    fixture = Path(__file__).parent / "fixtures" / "synthetic_sample.csv"
    frame = pd.read_csv(fixture, dtype=str)
    assert list(frame.columns) == [
        "order_item_id",
        "order_id",
        "customer_id",
        "product_id",
        "quantity_units",
        "net_sales",
    ]
    assert len(frame) == 4
    assert frame["order_item_id"].is_unique
