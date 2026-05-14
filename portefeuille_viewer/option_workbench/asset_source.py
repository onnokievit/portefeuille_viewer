from __future__ import annotations

from pathlib import Path

import pyodbc

from .models import OptionScanAsset


TRUE_TEXT = {"1", "-1", "true", "yes", "ja", "j", "y", "on", "waar"}


def connect_access(db_path: str | Path):
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in TRUE_TEXT


def table_columns(cursor, table_name: str) -> set[str]:
    out: set[str] = set()
    try:
        for row in cursor.columns(table=table_name):
            out.add(str(row.column_name).lower())
    except Exception:
        return set()
    return out


def load_scan_assets(stock_db_path: str | Path, include_disabled: bool = False) -> list[OptionScanAsset]:
    with connect_access(stock_db_path) as conn:
        cur = conn.cursor()
        asset_cols = table_columns(cur, "asset_rollup_data")
        if not asset_cols:
            raise RuntimeError("Tabel asset_rollup_data niet gevonden of geen kolommen gevonden.")

        required = {"asset_rollup", "ib_symbol", "ib_currency"}
        missing = required - asset_cols
        if missing:
            raise RuntimeError(f"asset_rollup_data mist verplichte kolommen: {sorted(missing)}")

        has_incl = "optie_scanner_incl" in asset_cols
        has_type = "ib_asset_type" in asset_cols
        has_exchange = "exchange" in asset_cols
        select_cols = ["asset_rollup", "ib_symbol", "ib_currency"]
        if has_incl:
            select_cols.append("optie_scanner_incl")
        if has_type:
            select_cols.append("ib_asset_type")
        if has_exchange:
            select_cols.append("exchange")
        rows = cur.execute(f"SELECT {', '.join('[' + c + ']' for c in select_cols)} FROM asset_rollup_data").fetchall()
        idx = {name: pos for pos, name in enumerate(select_cols)}

        opt_ref = _load_option_reference(cur)

    assets: list[OptionScanAsset] = []
    for row in rows:
        enabled = truthy(row[idx["optie_scanner_incl"]]) if has_incl else False
        if not enabled and not include_disabled:
            continue
        asset_rollup = _clean(row[idx["asset_rollup"]]).upper()
        ib_symbol = _clean(row[idx["ib_symbol"]]).upper() or asset_rollup
        ib_currency = _clean(row[idx["ib_currency"]]).upper()
        ib_asset_type = _clean(row[idx["ib_asset_type"]]).upper() if has_type else "STK"
        if not ib_asset_type:
            ib_asset_type = "STK"
        asset_exchange = _clean(row[idx["exchange"]]).upper() if has_exchange else ""
        ref = opt_ref.get(asset_rollup, {})
        option_exchange = _clean(ref.get("opt_exchange")).upper() or _fallback_option_exchange(
            ib_currency=ib_currency,
            asset_exchange=asset_exchange,
        )
        assets.append(
            OptionScanAsset(
                asset_rollup=asset_rollup,
                ib_symbol=ib_symbol,
                ib_currency=ib_currency,
                ib_asset_type=ib_asset_type,
                option_exchange=option_exchange,
                opt_tradingclass=_clean(ref.get("opt_tradingclass")).upper(),
            )
        )
    return assets


def _load_option_reference(cursor) -> dict[str, dict]:
    cols = table_columns(cursor, "optie_referentie_data")
    if not cols or "asset_rollup" not in cols:
        return {}
    wanted = ["asset_rollup"]
    for col in ("opt_exchange", "opt_tradingclass", "opt_multiplier", "opt_week"):
        if col in cols:
            wanted.append(col)
    try:
        rows = cursor.execute(f"SELECT {', '.join('[' + c + ']' for c in wanted)} FROM optie_referentie_data").fetchall()
    except Exception:
        return {}
    idx = {name: pos for pos, name in enumerate(wanted)}
    out: dict[str, dict] = {}
    for row in rows:
        asset = _clean(row[idx["asset_rollup"]]).upper()
        if not asset:
            continue
        week = 0
        if "opt_week" in idx:
            try:
                week = int(row[idx["opt_week"]] or 0)
            except Exception:
                week = 0
        # Prefer generic week=0 mapping; otherwise keep first row for now.
        if asset not in out or week == 0:
            out[asset] = {name: row[pos] for name, pos in idx.items()}
    return out


def _fallback_option_exchange(ib_currency: str, asset_exchange: str) -> str:
    ex = asset_exchange.upper()
    if ex in {"FTA", "AEB", "ENEXT.BE", "SBF"}:
        return "FTA"
    if ex in {"IBIS", "EUREX", "FWB"}:
        return "EUREX"
    if ib_currency.upper() == "USD":
        return "SMART"
    if ib_currency.upper() == "EUR":
        return "SMART"
    return "SMART"


def _clean(value: object) -> str:
    return str(value or "").strip()
