from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_market_symbol_seed_has_no_known_mojibake() -> None:
    sql = (MIGRATIONS / "init.sql").read_text(encoding="utf-8")
    corrupted_fragments = (
        "璐靛窞鑼呭彴",
        "鎷涘晢閾惰",
        "涓浗骞冲畨",
        "鑵捐鎺ц偂",
        "小斜械褉斜邪薪泻",
    )

    assert not any(fragment in sql for fragment in corrupted_fragments)


def test_a_share_hot_seed_uses_canonical_exchange() -> None:
    sql = (MIGRATIONS / "init.sql").read_text(encoding="utf-8")
    hot_symbols = (
        "600519",
        "600036",
        "601318",
        "600900",
        "601899",
        "000858",
        "000333",
        "002594",
        "300750",
        "000001",
    )

    for symbol in hot_symbols:
        rows = [line for line in sql.splitlines() if line.startswith(f"('CNStock', '{symbol}',")]
        assert rows
        assert all(", 'CN', 'CNY'," in row for row in rows)

    assert "legacy.exchange IN ('SSE', 'SZSE')" in sql
    assert "canonical.exchange = 'CN'" in sql
