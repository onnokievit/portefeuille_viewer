import pandas as pd

def coalesce_cols(df: pd.DataFrame, out_col: str, *cands: str):
    vals = None
    for c in cands:
        if c in df.columns:
            vals = df[c] if vals is None else vals.where(vals.notna(), df[c])
    df[out_col] = vals if vals is not None else pd.NA

def compute_equity_flows(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    df = raw[raw["asset_type"].str.lower() == "aandeel"].copy()
    if df.empty: return pd.DataFrame()

    is_buy  = df["transactie_type"].str.lower().eq("koop")
    is_sell = df["transactie_type"].str.lower().eq("verkoop")

    buy = df[is_buy].groupby("asset_rollup", as_index=False).agg(
        buy_qty=("aantal","sum"),
        buy_eur=("transactie_euro_totaal", lambda s: -s.sum()),
        fee_buy=("transactie_fee","sum")
    )
    sell = df[is_sell].groupby("asset_rollup", as_index=False).agg(
        sell_qty=("aantal","sum"),
        sell_eur=("transactie_euro_totaal","sum"),
        fee_sell=("transactie_fee","sum")
    )
    flows = pd.merge(buy, sell, on="asset_rollup", how="outer").fillna(0.0)
    flows["qty_eq"] = flows["buy_qty"] - flows["sell_qty"]
    flows["fee_eq"] = flows["fee_buy"] + flows["fee_sell"]
    return flows
