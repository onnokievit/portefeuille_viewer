from __future__ import annotations

import argparse
import csv
import html
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyodbc


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_databases, get_default_database, get_stockdata_db_path
from portefeuille_viewer.option_workbench.db_access import table_columns


DEFAULT_MULTIPLIER = 100.0
INTEGER_DTYPES = {
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.Int128,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
}


@dataclass(frozen=True)
class OpenOptionPosition:
    uniek_id: str
    broker: str
    asset_rollup: str
    exp_date: date
    strike: float
    right: str
    qty: float
    cashflow: float
    fees: float


@dataclass(frozen=True)
class OptionMarketQuote:
    price: float | None
    source: str
    bid: float | None = None
    ask: float | None = None
    update: Any = None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return default


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _connect_access_readonly(db_path: str | Path):
    return pyodbc.connect(
        rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};ReadOnly=1"
    )


def _table_exists(db_path: str | Path, table_name: str) -> bool:
    with _connect_access_readonly(db_path) as conn:
        cur = conn.cursor()
        return bool(table_columns(cur, table_name))


def _resolve_tx_table(db_path: str | Path, preferred: str | None = None) -> str:
    candidates = [preferred] if preferred else []
    candidates.extend(["transacties_bron_data", "transacties_bron_data_org"])
    seen: set[str] = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        if _table_exists(db_path, name):
            return name
    raise RuntimeError("Geen transactietabel gevonden: transacties_bron_data of transacties_bron_data_org")


def load_open_option_positions(db_path: str | Path, *, tx_table: str | None = None) -> list[OpenOptionPosition]:
    table_name = _resolve_tx_table(db_path, tx_table)
    sql = """
        SELECT
            uniek_id,
            broker,
            asset_rollup,
            asset_type,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            transactie_fee,
            transactie_euro_totaal,
            transactie_aantal
        FROM {table}
    """.format(table=f"[{table_name}]")
    today = date.today()
    grouped: dict[tuple[str, str, str, date, float, str], dict[str, float]] = {}

    with _connect_access_readonly(db_path) as conn:
        cur = conn.cursor()
        rows = cur.execute(sql).fetchall()

    for row in rows:
        asset_type = _clean(row.asset_type).lower()
        if asset_type != "optie":
            continue
        exp_date = _as_date(row.optie_exp_date)
        if exp_date is None or exp_date < today:
            continue
        strike = _to_float(row.optie_strike)
        right = _clean(row.optie_call_put).lower()
        if right in {"c", "call"}:
            right = "call"
        elif right in {"p", "put"}:
            right = "put"
        else:
            continue
        key = (
            _clean(row.uniek_id),
            _clean(row.broker),
            _clean(row.asset_rollup).upper(),
            exp_date,
            strike,
            right,
        )
        bucket = grouped.setdefault(key, {"qty": 0.0, "cashflow": 0.0, "fees": 0.0})
        bucket["qty"] += _to_float(row.transactie_aantal)
        bucket["cashflow"] += _to_float(row.transactie_euro_totaal)
        bucket["fees"] += _to_float(row.transactie_fee)

    positions: list[OpenOptionPosition] = []
    for (uniek_id, broker, asset_rollup, exp_date, strike, right), values in grouped.items():
        qty = values["qty"]
        if abs(qty) < 1e-9:
            continue
        positions.append(
            OpenOptionPosition(
                uniek_id=uniek_id,
                broker=broker,
                asset_rollup=asset_rollup,
                exp_date=exp_date,
                strike=strike,
                right=right,
                qty=qty,
                cashflow=values["cashflow"],
                fees=values["fees"],
            )
        )
    return sorted(positions, key=lambda p: (p.asset_rollup, p.exp_date, p.strike, p.right, p.broker))


def load_asset_map(db_path: str | Path) -> dict[str, dict[str, Any]]:
    with _connect_access_readonly(db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "asset_rollup_data")
        required = {"asset_rollup", "ib_symbol", "ib_currency"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"asset_rollup_data mist kolommen: {sorted(missing)}")
        wanted = ["asset_rollup", "ib_symbol", "ib_currency"]
        for col in ("ib_asset_type", "exchange"):
            if col in cols:
                wanted.append(col)
        rows = cur.execute(f"SELECT {', '.join('[' + col + ']' for col in wanted)} FROM asset_rollup_data").fetchall()
    idx = {name: pos for pos, name in enumerate(wanted)}
    assets: dict[str, dict[str, Any]] = {}
    for row in rows:
        asset_rollup = _clean(row[idx["asset_rollup"]]).upper()
        if not asset_rollup:
            continue
        assets[asset_rollup] = {
            "asset_rollup": asset_rollup,
            "ib_symbol": _clean(row[idx["ib_symbol"]]).upper() or asset_rollup,
            "ib_currency": _clean(row[idx["ib_currency"]]).upper(),
            "ib_asset_type": _clean(row[idx["ib_asset_type"]]).upper() if "ib_asset_type" in idx else "STK",
            "exchange": _clean(row[idx["exchange"]]).upper() if "exchange" in idx else "",
        }
    return assets


def load_spot_quotes(db_path: str | Path, asset_map: dict[str, dict[str, Any]]) -> dict[str, tuple[float | None, str]]:
    with _connect_access_readonly(db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "asset_last_prices")
        required = {"ib_symbol", "ib_currency", "price", "last_update"}
        if not required.issubset(cols):
            return {asset: (None, "asset_last_prices: tabel/kolommen ontbreken") for asset in asset_map}
        rows = cur.execute(
            """
            SELECT [ib_symbol], [ib_currency], [price], [last_update]
            FROM asset_last_prices
            WHERE [price] IS NOT NULL
            """
        ).fetchall()

    by_key: dict[tuple[str, str], list[tuple[float, Any, str]]] = {}
    for row in rows:
        symbol = _clean(row[0]).upper()
        currency = _clean(row[1]).upper()
        price = _to_float(row[2], default=-1.0)
        if not symbol or not currency or price <= 0:
            continue
        by_key.setdefault((symbol, currency), []).append((price, row[3], f"{row[0]}/{row[1]} {row[3]}"))

    out: dict[str, tuple[float | None, str]] = {}
    for asset_rollup, asset in asset_map.items():
        symbol = _clean(asset.get("ib_symbol") or asset_rollup).upper()
        currency = _clean(asset.get("ib_currency")).upper()
        candidates = _asset_last_price_candidates(asset_rollup, symbol, currency)
        best: tuple[int, Any, float, str] | None = None
        for priority, candidate in enumerate(candidates):
            for price, last_update, detail in by_key.get((candidate, currency), []):
                row_best = (priority, last_update or "", price, detail)
                if best is None or row_best[0] < best[0] or (row_best[0] == best[0] and str(row_best[1]) > str(best[1])):
                    best = row_best
        if best is None:
            out[asset_rollup] = (None, f"asset_last_prices: geen prijs voor {symbol}/{currency}")
        else:
            out[asset_rollup] = (best[2], f"asset_last_prices: {best[3]}")
    return out


def load_option_market_quotes(db_path: str | Path) -> dict[tuple[str, str, date, float], OptionMarketQuote]:
    with _connect_access_readonly(db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "option_last_prices")
        if not cols:
            return {}
        try:
            cur.execute("SELECT * FROM option_last_prices")
        except Exception:
            return {}
        col_list = [str(desc[0]).strip().lower() for desc in (cur.description or [])]
        rows = cur.fetchall()

    quotes: dict[tuple[str, str, date, float], tuple[Any, OptionMarketQuote]] = {}
    for row in rows:
        rec = {col_list[i]: row[i] for i in range(len(col_list))}
        asset = _clean(rec.get("asset_rollup") or rec.get("asset")).upper()
        right = _normalize_right(rec.get("optie_call_put") or rec.get("c_p") or rec.get("right"))
        exp = _as_date(rec.get("optie_exp_date") or rec.get("expiry") or rec.get("exp_date") or rec.get("exp"))
        strike = _to_float(rec.get("optie_strike") or rec.get("strike"), default=-1.0)
        if not asset or right not in {"call", "put"} or exp is None or strike <= 0:
            continue
        price, source = _pick_option_market_price(rec)
        if price is None:
            continue
        update = rec.get("last_update") or rec.get("ts")
        quote = OptionMarketQuote(
            price=price,
            source=source,
            bid=_positive_float_or_none(rec.get("bid")),
            ask=_positive_float_or_none(rec.get("ask")),
            update=update,
        )
        key = (asset, right, exp, round(strike, 6))
        prev = quotes.get(key)
        if prev is None or str(update or "") > str(prev[0] or ""):
            quotes[key] = (update, quote)
    return {key: item[1] for key, item in quotes.items()}


def _normalize_right(value: Any) -> str:
    right = _clean(value).lower()
    if right in {"c", "call"}:
        return "call"
    if right in {"p", "put"}:
        return "put"
    return right


def _positive_float_or_none(value: Any) -> float | None:
    out = _to_float(value, default=-1.0)
    return out if out > 0 else None


def _pick_option_market_price(rec: dict[str, Any]) -> tuple[float | None, str]:
    bid = _positive_float_or_none(rec.get("bid"))
    ask = _positive_float_or_none(rec.get("ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0, "bid_ask_mid"
    if bid is not None:
        return bid, "bid_only"
    if ask is not None:
        return 0.0, "ask_only_ignored"
    for key in ("mid_price", "last_px", "last_price", "model_price", "close"):
        value = _positive_float_or_none(rec.get(key))
        if value is not None:
            px_source = _clean(rec.get("px_source"))
            return value, px_source or key
    return None, ""


def _asset_last_price_candidates(asset_rollup: str, symbol: str, currency: str) -> list[str]:
    raw = [symbol, asset_rollup, f"{symbol}.{currency}", f"{symbol}{currency}"]
    out: list[str] = []
    for value in raw:
        clean = _clean(value).upper()
        if clean and clean not in out:
            out.append(clean)
    return out


def _option_intrinsic(right: str, strike: float, spot: float) -> float:
    if right == "put":
        return max(strike - spot, 0.0)
    if right == "call":
        return max(spot - strike, 0.0)
    return 0.0


def _margin_estimate_per_share(right: str, strike: float, spot: float, option_value_proxy: float) -> float:
    if right == "put":
        otm = max(spot - strike, 0.0)
        return option_value_proxy + max(0.20 * spot - otm, 0.10 * strike)
    if right == "call":
        otm = max(strike - spot, 0.0)
        return option_value_proxy + max(0.20 * spot - otm, 0.10 * spot)
    return 0.0


def build_margin_efficiency_report(
    portfolio_db_path: str | Path,
    *,
    stock_db_path: str | Path | None = None,
    tx_table: str | None = None,
    asset_filter: str | None = None,
    multiplier: float = DEFAULT_MULTIPLIER,
) -> pl.DataFrame:
    stock_db_path = stock_db_path or portfolio_db_path
    positions = load_open_option_positions(portfolio_db_path, tx_table=tx_table)
    if asset_filter:
        wanted = asset_filter.upper()
        positions = [pos for pos in positions if pos.asset_rollup.upper() == wanted]
    asset_map = load_asset_map(stock_db_path)
    spot_quotes = load_spot_quotes(stock_db_path, asset_map)
    option_quotes = load_option_market_quotes(stock_db_path)
    today = date.today()
    rows: list[dict[str, Any]] = []

    for pos in positions:
        spot, spot_source = spot_quotes.get(pos.asset_rollup, (None, "asset_rollup_data: asset niet gevonden"))
        option_quote = option_quotes.get((pos.asset_rollup, pos.right, pos.exp_date, round(pos.strike, 6)))
        option_px = option_quote.price if option_quote else None
        option_px_source = option_quote.source if option_quote else ""
        option_px_update = option_quote.update if option_quote else None
        option_bid = option_quote.bid if option_quote else None
        option_ask = option_quote.ask if option_quote else None
        if spot is None or spot <= 0:
            margin_used = None
            intrinsic_value = None
            result_proxy = None
            premium_per_margin = None
            result_per_margin = None
            ann_premium_per_margin = None
            extrinsic_per_share = None
            remaining_extrinsic = None
            entry_cashflow_per_margin = None
            ann_entry_cashflow_per_margin = None
            stress_10_result = None
            stress_20_result = None
        else:
            abs_underlying_qty = abs(pos.qty)
            intrinsic_per_share = _option_intrinsic(pos.right, pos.strike, spot)
            intrinsic_value = intrinsic_per_share * abs_underlying_qty
            option_value_proxy = option_px if option_px is not None and option_px > 0 else intrinsic_per_share
            extrinsic_per_share = max(float(option_value_proxy) - intrinsic_per_share, 0.0)
            remaining_extrinsic = extrinsic_per_share * abs_underlying_qty
            if pos.qty > 0:
                remaining_extrinsic *= -1.0
            regt_margin = _margin_estimate_per_share(pos.right, pos.strike, spot, option_value_proxy) * abs_underlying_qty
            cash_secured = pos.strike * abs_underlying_qty if pos.right == "put" and pos.qty < 0 else None
            margin_used = min(regt_margin, cash_secured) if cash_secured else regt_margin

            if pos.qty < 0:
                result_proxy = pos.cashflow - intrinsic_value
                entry_premium_received = max(pos.cashflow, abs(pos.cashflow))
            else:
                result_proxy = pos.cashflow + intrinsic_value
                entry_premium_received = 0.0

            premium_per_margin = remaining_extrinsic / margin_used if margin_used else None
            result_per_margin = result_proxy / margin_used if margin_used else None
            dte = max((pos.exp_date - today).days, 1)
            ann_premium_per_margin = premium_per_margin * 365.0 / dte if premium_per_margin is not None else None
            entry_cashflow_per_margin = entry_premium_received / margin_used if margin_used else None
            ann_entry_cashflow_per_margin = entry_cashflow_per_margin * 365.0 / dte if entry_cashflow_per_margin is not None else None

            if pos.right == "put":
                stress_10 = spot * 0.90
                stress_20 = spot * 0.80
            else:
                stress_10 = spot * 1.10
                stress_20 = spot * 1.20
            stress_10_intrinsic = _option_intrinsic(pos.right, pos.strike, stress_10) * abs_underlying_qty
            stress_20_intrinsic = _option_intrinsic(pos.right, pos.strike, stress_20) * abs_underlying_qty
            stress_10_result = pos.cashflow - stress_10_intrinsic if pos.qty < 0 else pos.cashflow + stress_10_intrinsic
            stress_20_result = pos.cashflow - stress_20_intrinsic if pos.qty < 0 else pos.cashflow + stress_20_intrinsic

        abs_underlying_qty = abs(pos.qty)
        rows.append(
            {
                "asset": pos.asset_rollup,
                "broker": pos.broker,
                "right": pos.right,
                "side": "short" if pos.qty < 0 else "long",
                "exp_date": pos.exp_date.isoformat(),
                "dte": (pos.exp_date - today).days,
                "strike": pos.strike,
                "qty_underlying": pos.qty,
                "contracts_est": abs_underlying_qty / multiplier,
                "cashflow": pos.cashflow,
                "fees": pos.fees,
                "spot": spot,
                "spot_source": spot_source,
                "option_px": option_px,
                "option_px_source": option_px_source,
                "option_px_update": option_px_update,
                "option_bid": option_bid,
                "option_ask": option_ask,
                "intrinsic_proxy": intrinsic_value,
                "extrinsic_per_share": extrinsic_per_share,
                "remaining_extrinsic": remaining_extrinsic,
                "result_proxy": result_proxy,
                "regt_margin_est": None if spot is None else _margin_estimate_per_share(
                    pos.right,
                    pos.strike,
                    spot,
                    option_px if option_px is not None and option_px > 0 else _option_intrinsic(pos.right, pos.strike, spot),
                )
                * abs_underlying_qty,
                "cash_secured_margin": None if spot is None or pos.right != "put" or pos.qty >= 0 else pos.strike * abs_underlying_qty,
                "margin_used": margin_used,
                "premium_per_margin": premium_per_margin,
                "entry_cashflow_per_margin": entry_cashflow_per_margin,
                "result_per_margin": result_per_margin,
                "ann_premium_per_margin": ann_premium_per_margin,
                "ann_entry_cashflow_per_margin": ann_entry_cashflow_per_margin,
                "stress_10_result": stress_10_result,
                "stress_20_result": stress_20_result,
                "uniek_id": pos.uniek_id,
            }
        )

    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).sort(["asset", "exp_date", "strike", "right", "broker"])


def _write_outputs(df: pl.DataFrame, output: Path) -> Path:
    formatted_rows = _format_rows_for_export(df)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".html":
        csv_output = _write_csv_rows_with_fallback(output.with_suffix(".csv"), df.columns, formatted_rows)
        headers = "".join(f"<th>{html.escape(col)}</th>" for col in df.columns)
        body = []
        for row in formatted_rows:
            cells = "".join(f"<td>{html.escape(row.get(col, ''))}</td>" for col in df.columns)
            body.append(f"<tr>{cells}</tr>")
        html_output = _write_text_with_fallback(
            output,
            (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<style>body{font-family:Segoe UI,Arial,sans-serif;font-size:13px}"
                "table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 6px;text-align:right}"
                "td:first-child,th:first-child{text-align:left}th{position:sticky;top:0;background:#f3f3f3}</style>"
                "</head><body><table><thead><tr>"
                + headers
                + "</tr></thead><tbody>"
                + "".join(body)
                + "</tbody></table></body></html>"
            ),
        )
        return html_output
    else:
        return _write_csv_rows_with_fallback(output, df.columns, formatted_rows)


def _write_csv_rows_with_fallback(output: Path, columns: list[str], rows: list[dict[str, str]]) -> Path:
    try:
        _write_csv_rows(output, columns, rows)
        return output
    except PermissionError:
        fallback = _timestamped_output(output)
        _write_csv_rows(fallback, columns, rows)
        print(f"[margin] output gelocked, geschreven naar {fallback}")
        return fallback


def _write_csv_rows(output: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _write_text_with_fallback(output: Path, text: str) -> Path:
    try:
        output.write_text(text, encoding="utf-8")
        return output
    except PermissionError:
        fallback = _timestamped_output(output)
        fallback.write_text(text, encoding="utf-8")
        print(f"[margin] output gelocked, geschreven naar {fallback}")
        return fallback


def _timestamped_output(output: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output.with_name(f"{output.stem}_{stamp}{output.suffix}")


def _format_rows_for_export(df: pl.DataFrame) -> list[dict[str, str]]:
    int_cols = {name for name, dtype in df.schema.items() if dtype in INTEGER_DTYPES}
    out: list[dict[str, str]] = []
    for row in df.iter_rows(named=True):
        out.append({col: _format_nl(value, decimals=0 if col in int_cols else 3) for col, value in row.items()})
    return out


def _format_nl(value: Any, *, decimals: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        formatted = f"{value:,.{decimals}f}"
        return formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return str(value)


def _default_portfolio_db_path() -> str:
    default_name = get_default_database()
    databases = get_databases()
    if default_name and default_name in databases:
        return databases[default_name]["path"]
    if databases:
        return next(iter(databases.values()))["path"]
    return get_stockdata_db_path()


def main() -> int:
    default_portfolio_db = _default_portfolio_db_path()
    parser = argparse.ArgumentParser(
        description="Standalone POC: margin-efficiency voor open optieposities uit de portefeuille DB."
    )
    parser.add_argument("--db", help="Alias voor --portfolio-db")
    parser.add_argument("--portfolio-db", default=default_portfolio_db, help="Pad naar portefeuille/transactie DB")
    parser.add_argument("--stock-db", default=get_stockdata_db_path(), help="Pad naar STOCKDATA DB voor spot/asset metadata")
    parser.add_argument("--asset", help="Filter op asset_rollup, bv APP of PL")
    parser.add_argument("--tx-table", help="Transactietabel, default auto: transacties_bron_data of transacties_bron_data_org")
    parser.add_argument("--output", default=str(ROOT / "margin_efficiency_report.csv"), help="Output .csv of .html")
    parser.add_argument("--limit", type=int, default=80, help="Aantal regels tonen in de CLI")
    parser.add_argument("--multiplier", type=float, default=DEFAULT_MULTIPLIER, help="Optie multiplier, standaard 100")
    args = parser.parse_args()

    portfolio_db_path = Path(args.db or args.portfolio_db)
    stock_db_path = Path(args.stock_db)
    if not portfolio_db_path.exists():
        print(f"Portfolio DB niet gevonden: {portfolio_db_path}", file=sys.stderr)
        return 2
    if not stock_db_path.exists():
        print(f"Stock DB niet gevonden: {stock_db_path}", file=sys.stderr)
        return 2

    print(f"[margin] portfolio_db={portfolio_db_path}")
    print(f"[margin] stock_db={stock_db_path}")
    try:
        df = build_margin_efficiency_report(
            portfolio_db_path,
            stock_db_path=stock_db_path,
            tx_table=args.tx_table,
            asset_filter=args.asset,
            multiplier=args.multiplier,
        )
    except Exception as exc:
        print(f"[margin] fout bij lezen/berekenen: {exc}", file=sys.stderr)
        return 1
    if df.is_empty():
        print("[margin] geen open optieposities gevonden")
        return 0

    out = Path(args.output)
    written = _write_outputs(df, out)
    print(f"[margin] rows={df.height} output={written}")
    print("[margin] let op: margin is Reg-T/proxy, geen exacte IBKR portfolio-margin what-if.")

    display_cols = [
        "asset",
        "side",
        "right",
        "exp_date",
        "dte",
        "strike",
        "spot",
        "option_px",
        "remaining_extrinsic",
        "cashflow",
        "margin_used",
        "premium_per_margin",
        "ann_premium_per_margin",
        "entry_cashflow_per_margin",
    ]
    display_df = pl.DataFrame(_format_rows_for_export(df.select(display_cols)))
    with pl.Config(tbl_rows=args.limit, tbl_cols=len(display_cols), tbl_formatting="ASCII_FULL"):
        print(display_df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
