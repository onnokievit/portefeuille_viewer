from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import polars as pl

from portefeuille_viewer.data import repository
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_sprinters import LiveAggregatorSprinters
from portefeuille_viewer.projections.aandelen_projection_v2 import AandelenProjectionV2
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary


COMPARE_COLS = ["koers_prev", "koers", "net_change", "totaal_inc_fee", "totaal_fee"]
EPS = 1e-8
OUT_DIR = Path("logs")


def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def hydrate_snapshots():
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_gesloten_opties_no_broker()
    repository.load_open_sprinters_from_tx()
    repository.load_gesloten_sprinters_from_tx()
    repository.load_asset_rollup_data()
    repository.load_sprinter_referentie_data()
    repository.load_dividend_data()
    repository.load_historical_close_snapshot()
    repository.load_per_dag_asset_result_v2_snapshot()
    repository.load_optie_referentie_data()
    repository.build_repository_active_asset_rollup_data()
    LiveAggregatorAandelen().process_live_update()
    LiveAggregatorOpties().process_live_update()
    LiveAggregatorSprinters().process_live_update()
    repository.portfolio_value_asset_rollup_opties_put()
    repository.portfolio_value_asset_rollup_aandelen()
    repository.portfolio_value_asset_rollup_sprinters()
    repository.portfolio_value_asset_rollup_combined()


def main():
    hydrate_snapshots()
    classic = build_aandelen_tab_summary()
    proj = AandelenProjectionV2()
    proj.recompute(set())
    v2 = proj.snapshot()

    c_map = {str(r["asset_rollup"]): r for r in classic.select(["asset_rollup"] + COMPARE_COLS).to_dicts()}
    v_map = {str(r["asset_rollup"]): r for r in v2.select(["asset_rollup"] + COMPARE_COLS).to_dicts()}

    assets = sorted(set(c_map.keys()) | set(v_map.keys()))
    mismatch = []
    for a in assets:
        c = c_map.get(a)
        v = v_map.get(a)
        if c is None or v is None:
            mismatch.append((a, "missing_row", c is not None, v is not None))
            continue
        for col in COMPARE_COLS:
            cv = _safe_float(c.get(col))
            vv = _safe_float(v.get(col))
            if cv is None and vv is None:
                continue
            if cv is None or vv is None or abs(cv - vv) > EPS:
                mismatch.append((a, col, cv, vv))
        # Hard parity for nullability on price fields
        for col in ("koers", "koers_prev"):
            c_is_null = c.get(col) is None
            v_is_null = v.get(col) is None
            if c_is_null != v_is_null:
                mismatch.append((a, f"{col}_nullability", c_is_null, v_is_null))

    print(f"classic_rows={classic.height} v2_rows={v2.height} mismatches={len(mismatch)}")
    for row in mismatch[:100]:
        print(str(row).encode("ascii", "ignore").decode())
    if mismatch:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = OUT_DIR / f"aandelen_projection_v2_parity_mismatch_{stamp}.csv"
        out = pl.DataFrame(
            {
                "asset_rollup": [str(m[0]) for m in mismatch],
                "field": [str(m[1]) for m in mismatch],
                "classic": [str(m[2]) for m in mismatch],
                "projection_v2": [str(m[3]) for m in mismatch],
            }
        )
        out.write_csv(out_file)
        print(f"mismatch_export={out_file}")


if __name__ == "__main__":
    main()
