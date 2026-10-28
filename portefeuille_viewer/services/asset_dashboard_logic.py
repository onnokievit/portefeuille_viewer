"""Private dashboard copy of legacy payoff/history glue (27 October 2026).

The shared payoff calculators remain imported from their original service.
Only UI-private orchestration is copied so the old page stays independent.
Inputs are frozen snapshot references; this class never opens a database.
"""
import contextlib
import polars as pl
from portefeuille_viewer.data.repository import build_uniek_id
from portefeuille_viewer.services.single_asset_scenario_analyse import (
    bereken_open_opties_payoff, bereken_open_sprinters_payoff,
    bereken_gesloten_aandelen_payoff, bereken_open_aandelen_payoff,
)

class DashboardAssetLogic:
    def __init__(self, store, asset, currency_factor, load_payoff=True):
        self.store = store
        self.currency_factor = currency_factor
        if not load_payoff:
            return
        for attribute, key in (
            ('df_open_opties', 'repository_snapshot_load_open_opties'),
            ('df_gesloten_opties', 'repository_snapshot_gesloten_opties'),
            ('df_open_sprinters', 'repository_snapshot_open_sprinters'),
            ('df_gesloten_sprinters', 'repository_snapshot_gesloten_sprinters'),
            ('df_aandelen', 'repository_snapshot_aandelen'),
        ):
            frame = getattr(store, key, None)
            if isinstance(frame, pl.DataFrame) and 'asset_rollup' in frame.columns:
                frame = frame.filter(pl.col('asset_rollup') == asset)
            else:
                frame = None
            setattr(self, attribute, frame)
        self.df_gesloten_aandelen = self.df_aandelen

    def _filter_broker_snapshot(self, frame):
        return frame  # Current dashboard scope is all brokers, no test orders.

    def payoff_open_opties(self, koers):
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import self.store # sourcery skip
        # self.store.test_repository_load_input_test_dataframe = self.df_open_opties  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        return bereken_open_opties_payoff(self.df_open_opties, koers)

    def payoff_gesloten_opties(self, koers):
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0:
            if "clos_opt_transactie_euro_totaal" in self.df_gesloten_opties.columns:
                return float(self.df_gesloten_opties["clos_opt_transactie_euro_totaal"].sum())
        return 0.0

    def payoff_open_sprinters(self, koers):
        return bereken_open_sprinters_payoff(self.df_open_sprinters, koers)

    def payoff_gesloten_sprinters(self, koers):
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0:
            if "clos_sp_transactie_euro_totaal" in self.df_gesloten_sprinters.columns:
                return float(self.df_gesloten_sprinters["clos_sp_transactie_euro_totaal"].sum())
        return 0.0

    def payoff_open_aandelen(self, koers):
        return bereken_open_aandelen_payoff(self.df_aandelen, koers)

    def payoff_gesloten_aandelen(self):
        if self.df_gesloten_aandelen is not None:
            return bereken_gesloten_aandelen_payoff(self.df_gesloten_aandelen)
        return 0.0

    def get_dividend(self, asset_rollup):
        df_div = getattr(self.store, "repository_portfolio_dividend", None)
        df_div = self._filter_broker_snapshot(df_div)
        dividend_val = 0.0
        if df_div is not None and hasattr(df_div, "filter"):
            with contextlib.suppress(Exception):
                rows = df_div.filter(pl.col("asset_rollup") == asset_rollup)
                if rows.height > 0 and "div_en_bel" in rows.columns:
                    dividend_val = float(rows["div_en_bel"].sum())
        return dividend_val

    def get_fees(self, steps):
        fee_aandelen = 0.0
        if self.df_aandelen is not None and self.df_aandelen.height > 0:
            if "fee_koop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_koop"].sum())
            if "fee_verkoop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_verkoop"].sum())

        fee_open_opties = [0.0 for _ in steps]
        if self.df_open_opties is not None and self.df_open_opties.height > 0 and "SomVantransactie_fee" in self.df_open_opties.columns:
            fee_val = float(self.df_open_opties["SomVantransactie_fee"].sum())
            fee_open_opties = [fee_val for _ in steps]

        fee_gesloten_opties = 0.0
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0 and "clos_opt_transactie_fee" in self.df_gesloten_opties.columns:
            fee_gesloten_opties = float(self.df_gesloten_opties["clos_opt_transactie_fee"].sum())

        fee_open_sprinters = [0.0 for _ in steps]
        if self.df_open_sprinters is not None and self.df_open_sprinters.height > 0 and "SomVantransactie_fee" in self.df_open_sprinters.columns:
            fee_val = float(self.df_open_sprinters["SomVantransactie_fee"].sum())
            fee_open_sprinters = [fee_val for _ in steps]

        fee_gesloten_sprinters = 0.0
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0 and "clos_sp_transactie_fee" in self.df_gesloten_sprinters.columns:
            fee_gesloten_sprinters = float(self.df_gesloten_sprinters["clos_sp_transactie_fee"].sum())

        return [
            fee_open_opties[i]
            + fee_gesloten_opties
            + fee_open_sprinters[i]
            + fee_gesloten_sprinters
            + fee_aandelen
            for i in range(len(steps))
        ]

    def load_asset_history(self, asset, start_date, end_date, market_days_only: bool = True):
        if not asset:
            return pl.DataFrame({})

        # Convert QDate to Python date when needed.
        if hasattr(start_date, "toPython"):
            start_date = start_date.toPython()
        elif hasattr(start_date, "toPyDate"):
            start_date = start_date.toPyDate()
        if hasattr(end_date, "toPython"):
            end_date = end_date.toPython()
        elif hasattr(end_date, "toPyDate"):
            end_date = end_date.toPyDate()
        if start_date is None or end_date is None or start_date > end_date:
            return pl.DataFrame({})

        # Prices (calendar source for market days)
        df_prices = getattr(self.store, "repository_snapshot_historical_ohlcv", None)
        if df_prices is None or df_prices.height == 0:
            return pl.DataFrame({})

        df_prices = (
            df_prices.with_columns(
                [
                    pl.coalesce(
                        [
                            pl.col("datum").cast(pl.Date, strict=False),
                            pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False),
                            pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%d/%m/%Y", strict=False),
                        ]
                    ).alias("datum"),
                    pl.col("close_price").cast(pl.Float64, strict=False).alias("close_price"),
                ]
            )
            .filter(
                (pl.col("asset_rollup") == asset)
                & (pl.col("datum") >= start_date)
                & (pl.col("datum") <= end_date)
            )
            .select(["datum", "asset_rollup", "close_price"])
            .sort("datum")
        )
        if df_prices.is_empty():
            return pl.DataFrame({})

        # v2 result data
        df_v2 = getattr(self.store, "repository_snapshot_per_dag_asset_result_v2", None)
        if df_v2 is None:
            df_v2 = pl.DataFrame({})
        if df_v2.height > 0:
            df_v2 = (
                df_v2.with_columns(
                    [
                        pl.coalesce(
                            [
                                pl.col("datum").cast(pl.Date, strict=False),
                                pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False),
                                pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%d/%m/%Y", strict=False),
                            ]
                        ).alias("datum"),
                        pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("totaal"),
                        pl.col("totaal_aantal_bezit_v2").cast(pl.Float64, strict=False).alias("totaal_aantal_bezit"),
                    ]
                )
                .filter(
                    (pl.col("asset_rollup") == asset)
                    & (pl.col("datum") >= start_date)
                    & (pl.col("datum") <= end_date)
                )
                .select(["datum", "asset_rollup", "totaal", "totaal_aantal_bezit"])
                .sort("datum")
            )
        else:
            df_v2 = pl.DataFrame(
                schema={
                    "datum": pl.Date,
                    "asset_rollup": df_prices.schema["asset_rollup"],
                    "totaal": pl.Float64,
                    "totaal_aantal_bezit": pl.Float64,
                }
            )

        # Market-days base join
        df_joined = df_prices.join(df_v2, on=["datum", "asset_rollup"], how="left").with_columns(
            [
                pl.col("totaal").fill_null(strategy="forward").fill_null(0.0),
                pl.col("totaal_aantal_bezit").fill_null(strategy="forward").fill_null(0.0),
            ]
        )

        if market_days_only:
            return df_joined.sort("datum")

        # All days: dense calendar + forward fill from latest market day values.
        cal = pl.DataFrame({"datum": pl.date_range(start=start_date, end=end_date, interval="1d", eager=True)})
        cal = cal.with_columns(pl.lit(asset).alias("asset_rollup"))
        dense = cal.join(df_joined, on=["datum", "asset_rollup"], how="left").sort("datum")
        dense = dense.with_columns(
            [
                pl.col("close_price").fill_null(strategy="forward"),
                pl.col("totaal").fill_null(strategy="forward").fill_null(0.0),
                pl.col("totaal_aantal_bezit").fill_null(strategy="forward").fill_null(0.0),
            ]
        )
        return dense


    def load_option_open_data(self):
        # print("Load open opties data for single asset analyse aangeroepen")
        empty_result = pl.DataFrame(
            schema={
                "itm": pl.Utf8,
                "broker": pl.Utf8,
                "asset_rollup": pl.Utf8,
                "optie_call_put": pl.Utf8,
                "optie_exp_date": pl.Utf8,
                "optie_strike": pl.Float64,
                "Koers": pl.Float64,
                "afwijking_pct": pl.Float64,
                "aantal_bezit": pl.Float64,
                "premie": pl.Float64,
                "totaal_resultaat_optie": pl.Float64,
                "totaal_fees": pl.Float64,
                "itm_otm": pl.Float64,
                "time_per_unit": pl.Float64,
                "time_value": pl.Float64,
                "uniek_id": pl.Utf8,
                "optie_comment": pl.Utf8,
                "optie_comment_color": pl.Utf8,
                "optie_comment_textcolor": pl.Utf8,
                "optie_comment_updated_at": pl.Datetime,
            }
        )
        df = self.store.aggregator_snapshot_load_open_opties_from_tx_live
        if df is None:
            return empty_result
        df = self._filter_broker_snapshot(df)
        required_cols = {
            "broker",
            "asset_rollup",
            "optie_call_put",
            "optie_exp_date",
            "optie_strike",
            "Koers",
            "SomVantransactie_aantal",
            "SomVantransactie_euro_totaal",
            "opt_total_result",
            "SomVantransactie_fee",
            "ITM_OTM",
        }
        if not required_cols.issubset(set(df.columns)):
            return empty_result
        if "ITM_OTM" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("ITM_OTM") != 0)
                    .then(pl.lit("ITM"))
                    .otherwise(pl.lit("OTM"))
                    .alias("itm")
            )
        # Voeg berekende kolom toe: % afwijking koers t.o.v. strike (absoluut)
        if "Koers" in df.columns and "optie_strike" in df.columns:
            df = df.with_columns(
            ( (pl.col("Koers") - pl.col("optie_strike")) / pl.col("optie_strike") * 100 ).alias("afwijking_pct")
            )

        df = df.select([
            pl.col("itm").alias("itm"),

            "broker",
            "asset_rollup",
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("optie_strike").alias("optie_strike"),
            "Koers",
            "afwijking_pct",
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
            pl.col("opt_total_result").alias("totaal_resultaat_optie"),
            pl.col("SomVantransactie_fee").alias("totaal_fees"),
            pl.col("ITM_OTM").alias("itm_otm"),


        ])


        # Koppel timevalue live data op serie-identiteit voor time_per_unit en signed time_value.
        # Gebruik genormaliseerde lookup (robuust tegen datum-/typeverschillen).
        try:
            tv = self.store.snapshot_optie_timevalue_live
            tv_lookup = {}
            if tv is not None and not tv.is_empty():
                for tr in tv.to_dicts():
                    try:
                        broker_k = str(tr.get("broker") or "").strip().lower()
                        asset_k = str(tr.get("asset") or "").strip().upper()
                        cp_k = str(tr.get("c_p") or "").strip().lower()
                        strike_k = round(float(tr.get("strike") or 0.0), 6)
                        exp_raw = tr.get("exp")
                        if hasattr(exp_raw, "isoformat"):
                            exp_k = str(exp_raw.isoformat())[:10]
                        else:
                            exp_s = str(exp_raw or "").strip()
                            if len(exp_s) >= 10 and exp_s[4] == "-" and exp_s[7] == "-":
                                exp_k = exp_s[:10]
                            elif len(exp_s) >= 10 and exp_s[2] == "-" and exp_s[5] == "-":
                                exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                            elif len(exp_s) >= 10 and exp_s[2] == "/" and exp_s[5] == "/":
                                exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                            else:
                                exp_k = exp_s[:10]
                        key = (broker_k, asset_k, exp_k, cp_k, strike_k)
                        tpu = float(tr.get("time_per_unit") or 0.0)
                        tval = float(tr.get("time_total") or 0.0)
                        tv_lookup[key] = (tpu, tval)
                    except Exception:
                        continue

            def _lookup_tpu(s):
                try:
                    exp_raw = s.get("optie_exp_date")
                    if hasattr(exp_raw, "isoformat"):
                        exp_k = str(exp_raw.isoformat())[:10]
                    else:
                        exp_s = str(exp_raw or "").strip()
                        if len(exp_s) >= 10 and exp_s[4] == "-" and exp_s[7] == "-":
                            exp_k = exp_s[:10]
                        elif len(exp_s) >= 10 and exp_s[2] == "-" and exp_s[5] == "-":
                            exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                        elif len(exp_s) >= 10 and exp_s[2] == "/" and exp_s[5] == "/":
                            exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                        else:
                            exp_k = exp_s[:10]
                    key = (
                        str(s.get("broker") or "").strip().lower(),
                        str(s.get("asset_rollup") or "").strip().upper(),
                        exp_k,
                        str(s.get("optie_call_put") or "").strip().lower(),
                        round(float(s.get("optie_strike") or 0.0), 6),
                    )
                    return float(tv_lookup.get(key, (None, None))[0]) if key in tv_lookup else None
                except Exception:
                    return None

            def _lookup_tval(s):
                try:
                    exp_raw = s.get("optie_exp_date")
                    if hasattr(exp_raw, "isoformat"):
                        exp_k = str(exp_raw.isoformat())[:10]
                    else:
                        exp_s = str(exp_raw or "").strip()
                        if len(exp_s) >= 10 and exp_s[4] == "-" and exp_s[7] == "-":
                            exp_k = exp_s[:10]
                        elif len(exp_s) >= 10 and exp_s[2] == "-" and exp_s[5] == "-":
                            exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                        elif len(exp_s) >= 10 and exp_s[2] == "/" and exp_s[5] == "/":
                            exp_k = f"{exp_s[6:10]}-{exp_s[3:5]}-{exp_s[0:2]}"
                        else:
                            exp_k = exp_s[:10]
                    key = (
                        str(s.get("broker") or "").strip().lower(),
                        str(s.get("asset_rollup") or "").strip().upper(),
                        exp_k,
                        str(s.get("optie_call_put") or "").strip().lower(),
                        round(float(s.get("optie_strike") or 0.0), 6),
                    )
                    return float(tv_lookup.get(key, (None, None))[1]) if key in tv_lookup else None
                except Exception:
                    return None

            df = df.with_columns([
                pl.struct(["broker", "asset_rollup", "optie_exp_date", "optie_call_put", "optie_strike"])
                .map_elements(_lookup_tpu, return_dtype=pl.Float64)
                .alias("time_per_unit"),
                pl.struct(["broker", "asset_rollup", "optie_exp_date", "optie_call_put", "optie_strike"])
                .map_elements(_lookup_tval, return_dtype=pl.Float64)
                .alias("time_value"),
            ])
        except Exception:
            df = df.with_columns([
                pl.lit(None).cast(pl.Float64).alias("time_per_unit"),
                pl.lit(None).cast(pl.Float64).alias("time_value"),
            ])

        if df is None or df.is_empty():
            return empty_result

        if not df.is_empty():
            # Voeg uniek_id toe op basis van optiekenmerken (hidden kolom in de tabel)
            df = df.with_columns([
                pl.struct([
                    "broker",
                    "asset_rollup",
                    "optie_exp_date",
                    "optie_call_put",
                    "optie_strike",
                ]).map_elements(
                    lambda s: build_uniek_id({**s, "asset_type": "optie"}),
                    return_dtype=pl.Utf8,
                ).alias("uniek_id"),
            ])
            # Standaard lege comment kolommen, worden gevuld vanuit DB in update_opties_open_table
            df = df.with_columns([
                pl.lit("").alias("optie_comment"),
                pl.lit("").alias("optie_comment_color"),
                pl.lit("").alias("optie_comment_textcolor"),
                pl.lit(None).alias("optie_comment_updated_at"),
            ])

        return df

    def _augment_with_test_orders(self, asset_rollup: str):
        df_test = getattr(self.store, "dashboard_test_orders", None)
        if df_test is None or df_test.is_empty():
            return
        df_test = self._filter_broker_snapshot(df_test)
        if df_test is None or df_test.is_empty():
            return
        if "include" in df_test.columns:
            df_test = df_test.filter(pl.col("include") == 1)

        # Opties
        df_test_opties = df_test.filter(pl.col("asset_type") == "optie")
        if df_test_opties.height > 0:
            df_opt = (
                df_test_opties
                .with_columns([
                    pl.when(pl.col("transactie_type") == "verkoop")
                    .then(-pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(pl.col("transactie_aantal").cast(pl.Float64))
                    .alias("SomVantransactie_aantal"),
                ])

                .with_columns([
                    (-1* pl.col("SomVantransactie_aantal") * pl.col("transactie_prijs").cast(pl.Float64) )
                        .alias("SomVantransactie_euro_totaal"),
                    pl.lit(0.0).alias("SomVantransactie_fee"),
                    (pl.col("optie_strike").cast(pl.Float64) * pl.col("SomVantransactie_aantal")).alias("optie_waarde"),
                    pl.lit(None).alias("uniek_id"),
                ])
                .select([
                    "uniek_id",
                    "broker",
                    "asset_rollup",
                    "asset_type",
                    "optie_exp_date",
                    "optie_strike",
                    "optie_call_put",
                    "SomVantransactie_fee",
                    "SomVantransactie_euro_totaal",
                    "SomVantransactie_aantal",
                    "optie_waarde",
                ])
            )
            base_opt = self.df_open_opties if self.df_open_opties is not None else pl.DataFrame()
            self.df_open_opties = pl.concat([base_opt, df_opt], how="diagonal_relaxed")

        # Aandelen
        # Aandelen – zelfde structuur als df_aandelen, geen koers/waarde_bezit
        df_test_eq = df_test.filter(pl.col("asset_type") == "aandeel")
        if df_test_eq.height > 0:
            df_eq = (
                df_test_eq
                .with_columns([
                    pl.lit("aandeel").alias("asset_type"),
                    pl.when(pl.col("transactie_type") == "koop")
                    .then(pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("aantal_koop"),
                    pl.when(pl.col("transactie_type") == "koop")
                      .then(-pl.col("transactie_aantal").cast(pl.Float64) * pl.col("transactie_prijs").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("euro_koop"),
                    pl.lit(0.0).alias("fee_koop"),
                    pl.when(pl.col("transactie_type") == "verkoop")
                    .then(-pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("aantal_verkoop"),
                    pl.when(pl.col("transactie_type") == "verkoop")
                      .then(pl.col("transactie_aantal").cast(pl.Float64) * pl.col("transactie_prijs").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("euro_verkoop"),
                    pl.lit(0.0).alias("fee_verkoop"),
                ])
                .group_by(["broker", "asset_rollup", "asset_type"])
                .agg([
                    pl.sum("aantal_koop"),
                    pl.sum("euro_koop"),
                    pl.sum("fee_koop"),
                    pl.sum("aantal_verkoop"),
                    pl.sum("euro_verkoop"),
                    pl.sum("fee_verkoop"),
                ])
                .with_columns([
                    (pl.col("aantal_koop") + pl.col("aantal_verkoop")).alias("aantal_bezit"),
                    (pl.col("fee_koop") + pl.col("fee_verkoop")).alias("eq_total_fee"),
                ])
                .select([
                    "broker", "asset_rollup", "asset_type",
                    "aantal_koop", "euro_koop", "fee_koop",
                    "aantal_verkoop", "euro_verkoop", "fee_verkoop",
                    "aantal_bezit", "eq_total_fee",
                ])
            )
            base_eq = self.df_aandelen if self.df_aandelen is not None else pl.DataFrame()
            self.df_aandelen = pl.concat([base_eq, df_eq], how="diagonal_relaxed")
