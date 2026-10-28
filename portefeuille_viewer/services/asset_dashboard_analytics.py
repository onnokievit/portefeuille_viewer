"""Dashboard payoff and history, operating on immutable captured snapshots."""
from datetime import date, datetime
import math
from types import SimpleNamespace

import polars as pl

from portefeuille_viewer.services.asset_dashboard_data import json_safe
from portefeuille_viewer.services.asset_dashboard_logic import DashboardAssetLogic
from portefeuille_viewer.services.asset_dashboard_distribution import DashboardDistribution


ANALYTIC_SOURCES = (
    "repository_snapshot_load_open_opties", "repository_snapshot_gesloten_opties",
    "repository_snapshot_open_sprinters", "repository_snapshot_gesloten_sprinters",
    "repository_snapshot_aandelen", "repository_portfolio_dividend",
    "repository_snapshot_historical_ohlcv", "repository_snapshot_per_dag_asset_result_v2",
    "snapshot_portfolio_value_total_combined_put",
)
LABELS = ["Open aandelen", "Open sprinters", "Open opties", "Gesloten aandelen",
          "Gesloten sprinters", "Gesloten opties", "Dividend", "Totaal zonder fees", "Fees", "Totaal"]


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), pattern).date()
        except ValueError:
            pass
    return None


def capture_analytics(store):
    """Called on the UI thread. Polars clones share immutable/COW buffers."""
    frames = {key: getattr(store, key, None) for key in ANALYTIC_SOURCES}
    token = tuple((key, id(value)) for key, value in frames.items())
    frozen = SimpleNamespace(**{key: value.clone() if isinstance(value, pl.DataFrame) else None
                               for key, value in frames.items()})
    frozen._history_token = tuple((key, id(frames[key])) for key in (
        "repository_snapshot_historical_ohlcv", "repository_snapshot_per_dag_asset_result_v2"))
    return frozen, token


def calculate_analytics(store, payload, settings, history_cache=None, history_token=None):
    asset = payload["asset"]
    if not asset:
        return {"asset": "", "payoff": {}, "history": []}
    # Filter on the worker before date conversions and joins, not on the UI thread.
    filtered = SimpleNamespace(**{
        key: frame.filter(pl.col("asset_rollup") == asset)
        if isinstance(frame, pl.DataFrame) and "asset_rollup" in frame.columns else frame
        for key, frame in vars(store).items()
    })
    factor = number(settings.get("currency_factor")) or 1.0
    if factor <= 0:
        raise ValueError("Ongeldige valutafactor")
    logic = DashboardAssetLogic(filtered, asset, factor)
    if settings.get("test_orders_enabled"):
        logic._augment_with_test_orders(asset)
        logic.df_gesloten_aandelen = logic.df_aandelen
    start = parse_date(settings.get("start")) or date(1900, 1, 1)
    end = parse_date(settings.get("end")) or date.today()
    cache_key = (asset, getattr(store, "_history_token", history_token), start, end, factor)
    if history_cache is not None and history_cache.get("key") == cache_key:
        history = [dict(row) for row in history_cache["rows"]]
    else:
        joined = logic.load_asset_history(asset, start, end, market_days_only=True)
        history = []
        # Native OHLC lookup; missing candle bodies are kept missing.
        prices = getattr(filtered, "repository_snapshot_historical_ohlcv", None)
        ohlc = {}
        if isinstance(prices, pl.DataFrame):
            for row in prices.to_dicts():
                day = parse_date(row.get("datum"))
                if day is not None:
                    ohlc[day] = row
        for row in joined.to_dicts():
            day = parse_date(row["datum"])
            raw = ohlc.get(day, {})
            history.append({"date": day.isoformat(), "close": number(row.get("close_price")),
                            "open": number(raw.get("open_price")), "high": number(raw.get("high_price")),
                            "low": number(raw.get("low_price")), "result": number(row.get("totaal")) / factor,
                            "quantity": number(row.get("totaal_aantal_bezit")), "live": False})
        if history_cache is not None:
            history_cache.update(key=cache_key, rows=[dict(row) for row in history])

    summary = payload.get("summary", {})
    price = number(summary.get("koers"))
    price_source = "snapshot"
    if price is None and history:
        price = history[-1]["close"]
        price_source = "laatste historische slotkoers"
    # Legacy chart appends/replaces today's live result in display currency.
    # Never invent today's OHLC from a single quote.
    live_result = number(summary.get("totaal_inc_fee"))
    if start <= date.today() <= end and price_source == "snapshot" and price is not None and live_result is not None:
        quantity = None
        combined = getattr(filtered, "snapshot_portfolio_value_total_combined_put", None)
        if isinstance(combined, pl.DataFrame) and not combined.is_empty():
            r = combined.row(0, named=True)
            quantity = ((number(r.get("aand_aantal_bezit")) or 0)
                        + (number(r.get("aantal_sprinters")) or 0)
                        + abs(number(r.get("opt_aantal_ITM_put")) or 0)
                        + abs(number(r.get("opt_aantal_OTM_put")) or 0))
        today = date.today().isoformat()
        current = next((row for row in history if row["date"] == today), None)
        if current is None:
            current = {"date": today, "open": None, "high": None, "low": None}
            history.append(current)
        fallback_quantity = current.get("quantity")
        if fallback_quantity is None:
            fallback_quantity = history[-2].get("quantity") if len(history) > 1 else 0
        current.update(close=price, result=live_result, live=True,
                       quantity=quantity if quantity is not None else fallback_quantity)

    payoff = {}
    if price is not None and price != 0:
        step_pct = number(settings.get("step_pct"))
        step_pct = min(99.99,max(0.,step_pct if step_pct is not None else 2.))
        width = abs(price) * step_pct / 100
        if width<=0:
            width=max(abs(price)*.01,.01)
        shift = number(settings.get("shift")) or 0.
        decimals = max(0, min(6, int(settings.get("decimals", 2))))
        current_col = max(0, min(16, 8 + round(shift / width)))
        steps = [round(price + (i - current_col) * width, decimals) for i in range(17)]
        matrix = [
            [logic.payoff_open_aandelen(s) for s in steps],
            [logic.payoff_open_sprinters(s) for s in steps],
            [logic.payoff_open_opties(s) for s in steps],
            [logic.payoff_gesloten_aandelen() for _ in steps],
            [logic.payoff_gesloten_sprinters(s) for s in steps],
            [logic.payoff_gesloten_opties(s) for s in steps],
            [logic.get_dividend(asset) for _ in steps],
        ]
        matrix.append([sum(row[i] for row in matrix) for i in range(17)])
        matrix.append(logic.get_fees(steps))
        matrix.append([matrix[7][i] + matrix[8][i] for i in range(17)])
        payoff = {"steps": steps, "labels": LABELS,
                  "values": [[float(v) / factor for v in row] for row in matrix],
                  "price": price, "price_source": price_source, "current_col": current_col,
                  "currency": "EUR", "test_orders": bool(settings.get("test_orders_enabled")), "decimals": decimals,
                  "distribution": DashboardDistribution(filtered).calculate(asset, steps)}
    return json_safe({"asset": asset, "payoff": payoff, "history": history,
                      "currency": "EUR", "start": start, "end": end})
