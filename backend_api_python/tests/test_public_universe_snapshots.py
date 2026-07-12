from scripts import refresh_public_universe_snapshots as snapshots
from scripts.refresh_public_universe_snapshots import _parse_hk_factsheet_text


class _RowsCursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, _sql, params=None):
        self.params = params

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _RowsConnection:
    def __init__(self, rows):
        self.cursor_obj = _RowsCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def test_hk_factsheet_parser_normalizes_codes_and_weights():
    text = """
    CONSTITUENTS
    Stock Code ISIN CODE Company Name Industry Classification Share Type Weighting (%)
    0700 KYG875721634 TENCENT Information Technology Other HK-listed Mainland Co. 8.30
    0939 CNE1000002H1 CCB Financials H Share 7.99
    Total 100.00
    """

    rows = _parse_hk_factsheet_text(text, "sample")

    assert [row["symbol"] for row in rows] == ["00700", "00939"]
    assert rows[0]["weight"] == 0.083
    assert rows[0]["metadata"]["industry"] == "Information Technology"
    assert rows[0]["metadata"]["share_type"] == "Other HK-listed Mainland Co."
    assert rows[1]["name"] == "CCB"


def test_etf_snapshot_loader_reads_hot_symbol_master_rows(monkeypatch):
    connection = _RowsConnection([
        {"market": "USStock", "symbol": "spy", "name": "SPDR S&P 500 ETF"},
        {"market": "USStock", "symbol": "qqq", "name": "Invesco QQQ"},
    ])
    monkeypatch.setattr(snapshots, "get_db_connection", lambda: connection)

    rows = snapshots.symbol_master_etfs("USStock")

    assert connection.cursor_obj.params == ("USStock",)
    assert [row["symbol"] for row in rows] == ["SPY", "QQQ"]
    assert rows[0]["rank"] == 1
    assert rows[0]["metadata"] == {"source": "symbol_master", "asset_class": "etf"}
    assert "hk_etf" in snapshots.LOADERS
    assert "us_etf" in snapshots.LOADERS
