from datetime import date

import polars as pl

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


def _safe_df(df: pl.DataFrame | None) -> pl.DataFrame:
	if df is None:
		return pl.DataFrame()
	return df


def _apply_filters(df: pl.DataFrame, selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	if df.is_empty():
		return df
	if selected_brokers is not None and "broker" in df.columns:
		df = df.filter(pl.col("broker").is_in(list(selected_brokers)))
	if asset_rollup and "asset_rollup" in df.columns:
		df = df.filter(pl.col("asset_rollup") == asset_rollup)
	return df


def build_aandelen_tab_summary(selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	"""
	Build the same summary DataFrame as AandelenTab, optionally filtered to a single asset.
	Filtering happens as early as possible to keep it lightweight for single-asset use.
	"""
	########### import data ##################################
	df = _apply_filters(_safe_df(SNAPSHOT_STORE.aggregator_snapshot_aandelen_live), selected_brokers, asset_rollup)
	if not df.is_empty():
		df_aandelen_sum = df.group_by("asset_rollup", "koers", "regio", "sector", "value_grow").agg([
			pl.col("aantal_bezit").sum().alias("eq_aantal_bezit"),
			pl.col("aantal_koop").sum().alias("eq_aantal_koop"),
			pl.col("euro_koop").sum().alias("eq_euro_koop"),
			pl.col("aantal_verkoop").sum().alias("eq_aantal_verkoop"),
			pl.col("euro_verkoop").sum().alias("eq_euro_verkoop"),
			pl.col("total_result").sum().alias("eq_total_result"),
			pl.col("eq_total_fee").sum().alias("eq_total_fee"),
		])
	else:
		df_aandelen_sum = df

	df_gesloten_opties = _apply_filters(_safe_df(SNAPSHOT_STORE.repository_snapshot_gesloten_opties), selected_brokers, asset_rollup)
	if not df_gesloten_opties.is_empty():
		df_clos_opt_sum = df_gesloten_opties.group_by("asset_rollup").agg([
			pl.col("clos_opt_transactie_euro_totaal").sum(),
			pl.col("clos_opt_transactie_fee").sum(),
		])
	else:
		df_clos_opt_sum = df_gesloten_opties

	df_gesloten_sprinters = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_gesloten_sprinters_no_asset_detail),
		selected_brokers,
		asset_rollup,
	)
	if not df_gesloten_sprinters.is_empty():
		df_clos_sp_sum = df_gesloten_sprinters.group_by("asset_rollup").agg([
			pl.col("clos_sp_transactie_euro_totaal").sum(),
			pl.col("clos_sp_transactie_fee").sum(),
		])
	else:
		df_clos_sp_sum = df_gesloten_sprinters

	df_open_opties = _apply_filters(
		_safe_df(SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live),
		selected_brokers,
		asset_rollup,
	)
	if not df_open_opties.is_empty():
		df_open_opt_sum = df_open_opties.group_by("asset_rollup").agg([
			pl.col("opt_total_result").sum().alias("open_opt_total_result"),
			pl.col("SomVantransactie_fee").sum().alias("open_opt_transactie_fee"),
		])
	else:
		df_open_opt_sum = df_open_opties

	df_open_sprinters = _apply_filters(
		_safe_df(SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live),
		selected_brokers,
		asset_rollup,
	)
	if not df_open_sprinters.is_empty():
		df_open_sp_sum = df_open_sprinters.group_by("asset_rollup").agg([
			pl.col("sp_result").sum().alias("open_sp_result"),
			pl.col("SomVantransactie_fee").sum().alias("open_sp_transactie_fee"),
			pl.col("SomVantransactie_aantal").sum().alias("open_sp_aantal"),
		])
	else:
		df_open_sp_sum = df_open_sprinters if df_open_sprinters is not None else pl.DataFrame()

	# Optie live tijdswaarde (signed) per asset, omgerekend naar EUR.
	df_opt_time_live = _safe_df(SNAPSHOT_STORE.snapshot_optie_timevalue_live)
	if not df_opt_time_live.is_empty():
		if asset_rollup:
			df_opt_time_live = df_opt_time_live.filter(pl.col("asset") == asset_rollup)
		EURUSD = get_settings().get_eurusd()
		df_opt_time_sum = (
			df_opt_time_live
			.select([
				pl.col("asset").cast(pl.Utf8).alias("asset_rollup"),
				pl.col("ccy").cast(pl.Utf8).alias("ccy"),
				pl.col("time_total").cast(pl.Float64).alias("time_total"),
			])
			.filter(pl.col("time_total").is_not_null())
			.group_by(["asset_rollup", "ccy"])
			.agg(pl.col("time_total").sum().alias("time_total_signed"))
			.with_columns(
				pl.when(pl.col("ccy") == "USD")
				.then(pl.col("time_total_signed") / EURUSD)
				.otherwise(pl.col("time_total_signed"))
				.alias("time_total_signed_eur")
			)
			.group_by("asset_rollup")
			.agg(pl.col("time_total_signed_eur").sum().alias("optie_tijdswaarde_signed_eur"))
		)
	else:
		df_opt_time_sum = pl.DataFrame()

	df_dividend = _apply_filters(_safe_df(SNAPSHOT_STORE.repository_portfolio_dividend), selected_brokers, asset_rollup)
	if not df_dividend.is_empty():
		df_div_bel = df_dividend.group_by("asset_rollup").agg([
			pl.col("div_en_bel").sum().alias("div_en_bel"),
		])
	else:
		df_div_bel = df_dividend

	df_active_rollup = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_active_asset_rollup_data),
		None,
		asset_rollup,
	)

	df_portfolio_value_combined = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_portfolio_value_total_combined_put),
		None,
		asset_rollup,
	)

	df_asset_result = _safe_df(SNAPSHOT_STORE.repository_snapshot_per_dag_asset_result_v2)
	today = date.today()
	if not df_asset_result.is_empty():
		df_asset_result = df_asset_result.filter(pl.col("datum") < today)
		if df_asset_result["datum"].dtype == pl.String:
			df_asset_result = df_asset_result.with_columns(
				pl.col("datum").str.strptime(pl.Date, "%d/%m/%Y")
			)
		if "totaal_v2" in df_asset_result.columns:
			df_asset_result = df_asset_result.with_columns(
				pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("totaal")
			)
		if asset_rollup:
			df_asset_result = df_asset_result.filter(pl.col("asset_rollup") == asset_rollup)

	# Neem per asset de laatste v2-rij (referentie voor net_change).
	df_aset_result_latest = (
		df_asset_result
		.sort(["asset_rollup", "datum"])
		.group_by("asset_rollup")
		.agg([pl.col("totaal").last().alias("totaal")])
	) if not df_asset_result.is_empty() else pl.DataFrame()

	# Neem per asset de laatste rij met beschikbare close_price (< vandaag).
	# Zo voorkomen we lege koers_prev op niet-handelsdagen (weekend/feestdag).
	df_historical_close = _safe_df(SNAPSHOT_STORE.repository_snapshot_historical_close)
	if not df_historical_close.is_empty():
		if "datum" in df_historical_close.columns:
			df_historical_close = df_historical_close.with_columns(
				pl.coalesce(
					[
						pl.col("datum").cast(pl.Date, strict=False),
						pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False),
						pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%d/%m/%Y", strict=False),
					]
				).alias("datum")
			)
		df_historical_close = df_historical_close.filter(pl.col("datum") < today)
		if asset_rollup:
			df_historical_close = df_historical_close.filter(pl.col("asset_rollup") == asset_rollup)
	df_close_latest = (
		df_historical_close
		.filter(pl.col("close_price").is_not_null())
		.sort(["asset_rollup", "datum"])
		.group_by("asset_rollup")
		.agg([pl.col("close_price").last().alias("close_price")])
	) if not df_historical_close.is_empty() else pl.DataFrame()

	########### einde import data ##################################

	########### Joins ##################################
	df_aand_opt = df_aandelen_sum.join(df_clos_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_gesloten")
	if "asset_rollup_opt_gesloten" in df_aand_opt.columns:
		df_aand_opt = df_aand_opt.with_columns([
			pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_gesloten")]).alias("asset_rollup")
	])
	df_aand_opt_sp = df_aand_opt.join(df_clos_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_gesloten")
	if "asset_rollup_sp_gesloten" in df_aand_opt_sp.columns:
		df_aand_opt_sp = df_aand_opt_sp.with_columns([
			pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_gesloten")]).alias("asset_rollup")
	])
	df_aand_opt_sp_open_opt = df_aand_opt_sp.join(df_open_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_o_open")
	if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
		df_aand_opt_sp_open_opt = df_aand_opt_sp_open_opt.with_columns([
			pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_o_open")]).alias("asset_rollup")
	])
	df_open_sp_sum_join = df_aand_opt_sp_open_opt.join(df_open_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_open")
	if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
		df_open_sp_sum_join = df_open_sp_sum_join.with_columns([
			pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_open")]).alias("asset_rollup")
	])
	df_final = df_open_sp_sum_join.join(df_div_bel, on=["asset_rollup"], how="full", suffix="_div_bel")
	if "asset_rollup_div_bel" in df_open_sp_sum_join.columns:
		df_final = df_final.with_columns([
			pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_div_bel")]).alias("asset_rollup")
	])
	if not df_active_rollup.is_empty():
		df_final = df_final.join(df_active_rollup.select(["asset_rollup", "status"]), on=["asset_rollup"], how="left")
	if not df_portfolio_value_combined.is_empty():
		df_final = df_final.join(
			df_portfolio_value_combined.select([
				"asset_rollup",
				"portfolio_total_waarde_lineair_pct",
				"portfolio_total_waarde_delta_pct",
			]),
			on=["asset_rollup"],
			how="left",
		)
	if not df_aset_result_latest.is_empty():
		df_final = df_final.join(df_aset_result_latest.select(["asset_rollup", "totaal"]), on=["asset_rollup"], how="left")
	if not df_close_latest.is_empty():
		df_final = df_final.join(df_close_latest.select(["asset_rollup", "close_price"]), on=["asset_rollup"], how="left")
	if not df_opt_time_sum.is_empty():
		df_final = df_final.join(df_opt_time_sum, on=["asset_rollup"], how="left")

	required_columns = {
		"open_sp_aantal": 0,
		"open_sp_result": 0,
		"open_sp_transactie_fee": 0,
		"clos_sp_transactie_euro_totaal": 0,
		"clos_sp_transactie_fee": 0,
		"eq_aantal_bezit": 0,
		"eq_total_result": 0,
		"clos_opt_transactie_euro_totaal": 0,
		"clos_opt_transactie_fee": 0,
		"open_opt_total_result": 0,
		"open_opt_transactie_fee": 0,
		"div_en_bel": 0,
		"totaal_resultaat": 0,
		"totaal_fee": 0,
		"totaal": 0,
		"close_price": 0,
		"koers": 0,
		"status": "",
		"asset_rollup": "",
		"optie_tijdswaarde_signed_eur": 0,
	}
	for col, default in required_columns.items():
		if col not in df_final.columns:
			df_final = df_final.with_columns(pl.lit(default).alias(col))
	########### Einde Joins ##################################

	EURUSD = get_settings().get_eurusd()
	df_final = df_final.with_columns(
		(pl.col("eq_total_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("eq_total_result"),
		(pl.col("clos_opt_transactie_euro_totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_opt_transactie_euro_totaal"),
		(pl.col("clos_sp_transactie_euro_totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_sp_transactie_euro_totaal"),
		(pl.col("open_opt_total_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_opt_total_result"),
		(pl.col("open_sp_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_sp_result"),
		(pl.col("eq_total_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("eq_total_fee"),
		(pl.col("clos_opt_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_opt_transactie_fee"),
		(pl.col("clos_sp_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_sp_transactie_fee"),
		(pl.col("open_opt_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_opt_transactie_fee"),
		(pl.col("open_sp_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_sp_transactie_fee"),
		(pl.col("div_en_bel") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("div_en_bel"),
		(pl.col("totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("totaal"),
		pl.when(
			(pl.col("close_price").is_not_null()) & (pl.col("close_price") != 0)
		).then(
			(pl.col("koers") / pl.col("close_price")) - 1
		).otherwise(0).alias("pct_change")
	)
	########### Sum en berekende kolommen ###############
	if not df_final.is_empty():
		df_sum = df_final.group_by(
			"asset_rollup",
			"koers",
			"regio",
			"sector",
			"value_grow",
			"status",
			"portfolio_total_waarde_lineair_pct",
			"portfolio_total_waarde_delta_pct",
			"close_price",
			"pct_change",
		).agg([
			pl.col("eq_aantal_bezit").sum().alias("eq_aantal_bezit"),
			pl.col("open_sp_aantal").sum().alias("open_sp_aantal"),
			pl.col("eq_total_result").sum().alias("eq_total_result"),
			pl.col("clos_opt_transactie_euro_totaal").sum().alias("clos_opt_transactie_euro_totaal"),
			pl.col("clos_sp_transactie_euro_totaal").sum().alias("clos_sp_transactie_euro_totaal"),
			pl.col("open_opt_total_result").sum().alias("open_opt_total_result"),
			pl.col("open_sp_result").sum().alias("open_sp_result"),
			pl.col("eq_total_fee").sum().alias("eq_total_fee"),
			pl.col("clos_opt_transactie_fee").sum().alias("clos_opt_transactie_fee"),
			pl.col("clos_sp_transactie_fee").sum().alias("clos_sp_transactie_fee"),
			pl.col("open_opt_transactie_fee").sum().alias("open_opt_transactie_fee"),
			pl.col("open_sp_transactie_fee").sum().alias("open_sp_transactie_fee"),
			pl.col("div_en_bel").sum().alias("div_en_bel"),
			pl.col("totaal").sum().alias("totaal"),
			pl.col("optie_tijdswaarde_signed_eur").sum().alias("optie_tijdswaarde_signed_eur"),
		]).with_columns([
			(
				pl.col("eq_total_result")
				+ pl.col("clos_opt_transactie_euro_totaal")
				+ pl.col("clos_sp_transactie_euro_totaal")
				+ pl.col("open_opt_total_result")
				+ pl.col("open_sp_result")
				+ pl.col("div_en_bel")
			).alias("totaal_ex_fee"),
			(
				pl.col("eq_total_result")
				+ pl.col("clos_opt_transactie_euro_totaal")
				+ pl.col("clos_sp_transactie_euro_totaal")
				+ pl.col("open_opt_total_result")
				+ pl.col("open_sp_result")
				+ pl.col("div_en_bel")
				+ pl.col("eq_total_fee")
				+ pl.col("clos_opt_transactie_fee")
				+ pl.col("clos_sp_transactie_fee")
				+ pl.col("open_opt_transactie_fee")
				+ pl.col("open_sp_transactie_fee")
			).alias("totaal_inc_fee"),
			(
				pl.col("eq_total_fee")
				+ pl.col("clos_opt_transactie_fee")
				+ pl.col("clos_sp_transactie_fee")
				+ pl.col("open_opt_transactie_fee")
				+ pl.col("open_sp_transactie_fee")
			).alias("totaal_fee"),
		])
	else:
		df_sum = df

	df_sum = df_sum.with_columns((pl.col("totaal_inc_fee") - pl.col("totaal")).alias("net_change"))
	########### Kolom indeling ##################################
	df_sum = df_sum.select([
		"asset_rollup",
		pl.col("close_price").alias("koers_prev"),
		"koers",
		"pct_change",
		"eq_aantal_bezit",
		"open_sp_aantal",
		"eq_total_result",
		"clos_opt_transactie_euro_totaal",
		"clos_sp_transactie_euro_totaal",
		"open_opt_total_result",
		"open_sp_result",
		"div_en_bel",
		"totaal_ex_fee",
		"totaal_inc_fee",
		"net_change",
		"totaal_fee",
		"regio",
		"sector",
		"value_grow",
		"status",
		"portfolio_total_waarde_lineair_pct",
		"portfolio_total_waarde_delta_pct",
		"optie_tijdswaarde_signed_eur",
	])
	return df_sum
