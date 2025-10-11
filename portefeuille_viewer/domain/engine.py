import polars as pl

# ------------------------------------------------------------
# engine.py:
# bevat algemene rekenhulpen — kleine, herbruikbare functies
# bijv. compute_equity_flows(), coalesce_cols(), compact_float64()
# ------------------------------------------------------------




# ------------------------------------------------------------
# float32 maken van polar dataframes om snelheid en geheugen te besparen
# ------------------------------------------------------------

def compact_float64(df: pl.DataFrame) -> pl.DataFrame:
    """
    Zet alle Float64 kolommen om naar Float32 om geheugen te besparen.
    """
    for c in df.columns:
        if df.schema[c] == pl.Float64:
            df = df.with_columns(pl.col(c).cast(pl.Float32))
    return df

# ------------------------------------------------------------
# einde float32 maken van polar dataframes om snelheid en geheugen te besparen
# ------------------------------------------------------------



def coalesce_cols(df: pl.DataFrame, out_col: str, *cands: str) -> pl.DataFrame:
    """
    Combineer meerdere kolommen in volgorde van prioriteit.
    De eerste niet-null waarde wordt gekozen.
    """
    if not cands:
        df = df.with_columns(pl.lit(None).alias(out_col))
        return df

    expr = pl.col(cands[0])
    for c in cands[1:]:
        expr = expr.fill_null(pl.col(c))
    return df.with_columns(expr.alias(out_col))


def compute_equity_flows(raw: pl.DataFrame) -> pl.DataFrame:
    """
    Bereken cumulatieve equity flows (aandelen).
    Output bevat buy/sell totals en netto positie.
    """
    if raw.is_empty():
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "qty_eq": pl.Float32})

    # Alleen aandelen
    df = raw.filter(pl.col("asset_type").str.to_lowercase() == "aandeel")
    if df.is_empty():
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8, "qty_eq": pl.Float32})

    # Koop/verkoop splitsen
    is_buy = df.filter(pl.col("transactie_type").str.to_lowercase() == "koop")
    is_sell = df.filter(pl.col("transactie_type").str.to_lowercase() == "verkoop")

    # Aggregaties
    buy = (
        is_buy
        .group_by("asset_rollup")
        .agg([
            pl.col("aantal").sum().alias("buy_qty"),
            (-pl.col("transactie_euro_totaal")).sum().alias("buy_eur"),
            pl.col("transactie_fee").sum().alias("fee_buy")
        ])
    )

    sell = (
        is_sell
        .group_by("asset_rollup")
        .agg([
            pl.col("aantal").sum().alias("sell_qty"),
            pl.col("transactie_euro_totaal").sum().alias("sell_eur"),
            pl.col("transactie_fee").sum().alias("fee_sell")
        ])
    )

    # Outer join met null-opvulling
    flows = (
        buy.join(sell, on="asset_rollup", how="outer")
        .fill_null(0.0)
        .with_columns([
            (pl.col("buy_qty") - pl.col("sell_qty")).cast(pl.Float32).alias("qty_eq"),
            (pl.col("fee_buy") + pl.col("fee_sell")).cast(pl.Float32).alias("fee_eq")
        ])
    )

    return flows

def print_snapshot_head(snapshot_name: str, snapshot: pl.DataFrame, n: int = 50):
    """
    Druk de eerste `n` records van een snapshot af.
    """
    if snapshot is None:
        print(f"Snapshot '{snapshot_name}' is None.")
        return

    if snapshot.is_empty():
        print(f"Snapshot '{snapshot_name}' is leeg.")
        return

    print(f"Snapshot: {snapshot_name} (eerste {n} records)")
    print(snapshot.head(n))
    print("\n")

def print_snapshot_columns(snapshot_name: str, snapshot: pl.DataFrame, log_file="snapshots.log"):
    """
    Druk de kolommen van een snapshot af in tabelvorm en log naar een bestand.
    """
    with open(log_file, "a") as f:
        if snapshot is None:
            f.write(f"Snapshot '{snapshot_name}' is None.\n")
            return

        if snapshot.is_empty():
            f.write(f"Snapshot '{snapshot_name}' is leeg.\n")
            return

        f.write(f"Snapshot: {snapshot_name}\n")
        f.write("Kolommen:\n")
        for col in snapshot.columns:
            f.write(f"- {col}\n")
        f.write("\n")