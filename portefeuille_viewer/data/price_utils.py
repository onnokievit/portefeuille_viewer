import polars as pl


def build_prices_df(live_prices: dict | None, last_prices: dict | None) -> pl.DataFrame:
    """
    Combineer laatste bekende prijzen met live prijzen.

    - last_prices: basislaag (bijv. uit DB)
    - live_prices: overschrijft last_prices wanneer aanwezig en > 0
    """
    combined: dict[tuple[str, str], float] = {}

    if last_prices:
        for (sym, curr), price in last_prices.items():
            if sym and curr and price is not None:
                combined[(sym, curr)] = float(price)

    if live_prices:
        for key, price in live_prices.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            sym, curr = key
            if sym and curr and price not in (None, 0.0):
                combined[(sym, curr)] = float(price)

    if not combined:
        return pl.DataFrame(
            {"ib_symbol": pl.Series([], dtype=pl.Utf8), "ib_currency": pl.Series([], dtype=pl.Utf8), "price": pl.Series([], dtype=pl.Float64)}
        )

    ib_symbol, ib_currency, price = zip(*[(k[0], k[1], v) for k, v in combined.items()])
    return pl.DataFrame({"ib_symbol": ib_symbol, "ib_currency": ib_currency, "price": price})
