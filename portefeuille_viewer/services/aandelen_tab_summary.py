from collections import OrderedDict

import polars as pl

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE
from portefeuille_viewer.data.price_utils import build_prices_df
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


_STATIC_CACHE_LIMIT = 32
_STATIC_SNAPSHOT_KEYS = (
	"repository_snapshot_gesloten_opties",
	"repository_snapshot_gesloten_sprinters_no_asset_detail",
	"repository_portfolio_dividend",
	"repository_snapshot_active_asset_rollup_data",
	"repository_snapshot_portfolio_value_total_combined_put",
	"repository_snapshot_per_dag_asset_result_v2_latest",
	"repository_snapshot_historical_ohlcv_latest",
)
_STATIC_SUMMARY_CACHE: OrderedDict[tuple, pl.DataFrame] = OrderedDict()


def _safe_df(df: pl.DataFrame | None) -> pl.DataFrame:
	if df is None:
		return pl.DataFrame()
	return df


def _empty_df(schema: dict[str, pl.DataType]) -> pl.DataFrame:
	return pl.DataFrame(schema=schema)


def _coalesce_asset_rollup(df: pl.DataFrame, fallback_col: str) -> pl.DataFrame:
	if fallback_col in df.columns:
		return df.with_columns(
			pl.coalesce([pl.col("asset_rollup"), pl.col(fallback_col)]).alias("asset_rollup")
		)
	return df


def _normalize_asset_rollup(df: pl.DataFrame, col: str = "asset_rollup") -> pl.DataFrame:
	if col not in df.columns:
		return df
	return df.with_columns(
		pl.col(col)
		.cast(pl.Utf8, strict=False)
		.str.strip_chars()
		.str.to_uppercase()
		.alias(col)
	)


def _apply_filters(df: pl.DataFrame, selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	if df.is_empty():
		return df
	if selected_brokers is not None and "broker" in df.columns:
		df = df.filter(pl.col("broker").is_in(list(selected_brokers)))
	if asset_rollup and "asset_rollup" in df.columns:
		df = _normalize_asset_rollup(df, "asset_rollup")
		df = df.filter(pl.col("asset_rollup") == str(asset_rollup).strip().upper())
	return df


def _brokers_key(selected_brokers) -> tuple | None:
	if selected_brokers is None:
		return None
	return tuple(sorted(str(b) for b in selected_brokers))


def _snapshot_token() -> tuple:
	last_update = getattr(SNAPSHOT_STORE, "_last_update_ts", {}) or {}
	token_parts = []
	for key in _STATIC_SNAPSHOT_KEYS:
		df = _safe_df(getattr(SNAPSHOT_STORE, key, None))
		token_parts.append((key, last_update.get(key), df.height, df.width, id(df)))
	return tuple(token_parts)


def _static_cache_key(selected_brokers, asset_rollup: str | None) -> tuple:
	return (_brokers_key(selected_brokers), asset_rollup or "", _snapshot_token())


def _cached_static_summary(selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	key = _static_cache_key(selected_brokers, asset_rollup)
	cached = _STATIC_SUMMARY_CACHE.get(key)
	if cached is not None:
		_STATIC_SUMMARY_CACHE.move_to_end(key)
		return cached

	static_df = _build_static_summary(selected_brokers, asset_rollup)
	_STATIC_SUMMARY_CACHE[key] = static_df
	_STATIC_SUMMARY_CACHE.move_to_end(key)
	while len(_STATIC_SUMMARY_CACHE) > _STATIC_CACHE_LIMIT:
		_STATIC_SUMMARY_CACHE.popitem(last=False)
	return static_df


def _build_static_summary(selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	df_gesloten_opties = _apply_filters(_safe_df(SNAPSHOT_STORE.repository_snapshot_gesloten_opties), selected_brokers, asset_rollup)
	if not df_gesloten_opties.is_empty():
		df_clos_opt_sum = df_gesloten_opties.group_by("asset_rollup").agg([
			pl.col("clos_opt_transactie_euro_totaal").sum(),
			pl.col("clos_opt_transactie_fee").sum(),
		])
		df_clos_opt_sum = _normalize_asset_rollup(df_clos_opt_sum)
	else:
		df_clos_opt_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"clos_opt_transactie_euro_totaal": pl.Float64,
			"clos_opt_transactie_fee": pl.Float64,
		})

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
		df_clos_sp_sum = _normalize_asset_rollup(df_clos_sp_sum)
	else:
		df_clos_sp_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"clos_sp_transactie_euro_totaal": pl.Float64,
			"clos_sp_transactie_fee": pl.Float64,
		})

	df_dividend = _apply_filters(_safe_df(SNAPSHOT_STORE.repository_portfolio_dividend), selected_brokers, asset_rollup)
	if not df_dividend.is_empty():
		df_div_bel = df_dividend.group_by("asset_rollup").agg([
			pl.col("div_en_bel").sum().alias("div_en_bel"),
		])
		df_div_bel = _normalize_asset_rollup(df_div_bel)
	else:
		df_div_bel = _empty_df({
			"asset_rollup": pl.Utf8,
			"div_en_bel": pl.Float64,
		})

	df_active_rollup = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_active_asset_rollup_data),
		None,
		asset_rollup,
	)
	if not df_active_rollup.is_empty():
		df_active_rollup = df_active_rollup.select(["asset_rollup", "status"])
		df_active_rollup = _normalize_asset_rollup(df_active_rollup)
	else:
		df_active_rollup = _empty_df({"asset_rollup": pl.Utf8, "status": pl.Utf8})

	df_portfolio_value_combined = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_portfolio_value_total_combined_put),
		None,
		asset_rollup,
	)
	if not df_portfolio_value_combined.is_empty():
		df_portfolio_value_combined = df_portfolio_value_combined.select([
			"asset_rollup",
			"portfolio_total_waarde_lineair_pct",
			"portfolio_total_waarde_delta_pct",
		])
		df_portfolio_value_combined = _normalize_asset_rollup(df_portfolio_value_combined)
	else:
		df_portfolio_value_combined = _empty_df({
			"asset_rollup": pl.Utf8,
			"portfolio_total_waarde_lineair_pct": pl.Float64,
			"portfolio_total_waarde_delta_pct": pl.Float64,
		})

	df_asset_result_latest = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_per_dag_asset_result_v2_latest),
		None,
		asset_rollup,
	)
	if df_asset_result_latest.is_empty():
		df_asset_result_latest = _empty_df({"asset_rollup": pl.Utf8, "totaal": pl.Float64})
	else:
		df_asset_result_latest = _normalize_asset_rollup(df_asset_result_latest)

	df_close_latest = _apply_filters(
		_safe_df(SNAPSHOT_STORE.repository_snapshot_historical_ohlcv_latest),
		None,
		asset_rollup,
	)
	if df_close_latest.is_empty():
		df_close_latest = _empty_df({"asset_rollup": pl.Utf8, "close_price": pl.Float64})
	else:
		df_close_latest = _normalize_asset_rollup(df_close_latest)

	df_static = df_clos_opt_sum.join(df_clos_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_gesloten")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_sp_gesloten")
	df_static = df_static.join(df_div_bel, on=["asset_rollup"], how="full", suffix="_div")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_div")
	df_static = df_static.join(df_active_rollup, on=["asset_rollup"], how="full", suffix="_active")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_active")
	df_static = df_static.join(df_portfolio_value_combined, on=["asset_rollup"], how="full", suffix="_port")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_port")
	df_static = df_static.join(df_asset_result_latest, on=["asset_rollup"], how="full", suffix="_pdag")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_pdag")
	df_static = df_static.join(df_close_latest, on=["asset_rollup"], how="full", suffix="_close")
	df_static = _coalesce_asset_rollup(df_static, "asset_rollup_close")
	return df_static


def _get_last_prices_cached() -> dict[tuple[str, str], float]:
	return ASSET_LAST_PRICE_STORE.get_snapshot()


def _asset_price_fallback_df(asset_rollup: str | None = None) -> pl.DataFrame:
	df_assets = _safe_df(SNAPSHOT_STORE.repository_snapshot_asset_rollup_data)
	if df_assets.is_empty():
		return _empty_df({"asset_rollup": pl.Utf8, "koers_fallback": pl.Float64})
	if "asset_rollup" not in df_assets.columns or "ib_symbol" not in df_assets.columns or "ib_currency" not in df_assets.columns:
		return _empty_df({"asset_rollup": pl.Utf8, "koers_fallback": pl.Float64})
	if asset_rollup:
		df_assets = _normalize_asset_rollup(df_assets)
		df_assets = df_assets.filter(pl.col("asset_rollup") == str(asset_rollup).strip().upper())
	prices_df = build_prices_df(SNAPSHOT_STORE.get_live_prices_snapshot(), _get_last_prices_cached())
	if prices_df.is_empty():
		return _empty_df({"asset_rollup": pl.Utf8, "koers_fallback": pl.Float64})
	return (
		df_assets
		.select(["asset_rollup", "ib_symbol", "ib_currency"])
		.join(prices_df, on=["ib_symbol", "ib_currency"], how="left")
		.select(
			[
				pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
				pl.col("price").cast(pl.Float64, strict=False).alias("koers_fallback"),
			]
		)
		.group_by("asset_rollup")
		.agg(pl.col("koers_fallback").max().alias("koers_fallback"))
	)


def _broker_scope_assets(selected_brokers, asset_rollup: str | None = None) -> set[str]:
	if selected_brokers is None:
		return set()
	frames = [
		_apply_filters(_safe_df(SNAPSHOT_STORE.aggregator_snapshot_aandelen_live), selected_brokers, asset_rollup),
		_apply_filters(_safe_df(SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live), selected_brokers, asset_rollup),
		_apply_filters(_safe_df(SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live), selected_brokers, asset_rollup),
		_apply_filters(_safe_df(SNAPSHOT_STORE.repository_snapshot_gesloten_opties), selected_brokers, asset_rollup),
		_apply_filters(_safe_df(SNAPSHOT_STORE.repository_snapshot_gesloten_sprinters_no_asset_detail), selected_brokers, asset_rollup),
		_apply_filters(_safe_df(SNAPSHOT_STORE.repository_portfolio_dividend), selected_brokers, asset_rollup),
	]
	assets: set[str] = set()
	for df in frames:
		if df is None or df.is_empty() or "asset_rollup" not in df.columns:
			continue
		for a in df["asset_rollup"].to_list():
			if a is None:
				continue
			s = str(a).strip().upper()
			if s:
				assets.add(s)
	return assets


def build_aandelen_tab_summary(selected_brokers=None, asset_rollup: str | None = None) -> pl.DataFrame:
	"""
	Build the same summary DataFrame as AandelenTab, optionally filtered to a single asset.
	Static components are cached and reused across live refreshes.
	"""
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
		df_aandelen_sum = _normalize_asset_rollup(df_aandelen_sum)
	else:
		df_aandelen_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"koers": pl.Float64,
			"regio": pl.Utf8,
			"sector": pl.Utf8,
			"value_grow": pl.Utf8,
			"eq_aantal_bezit": pl.Float64,
			"eq_aantal_koop": pl.Float64,
			"eq_euro_koop": pl.Float64,
			"eq_aantal_verkoop": pl.Float64,
			"eq_euro_verkoop": pl.Float64,
			"eq_total_result": pl.Float64,
			"eq_total_fee": pl.Float64,
		})

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
		df_open_opt_sum = _normalize_asset_rollup(df_open_opt_sum)
	else:
		df_open_opt_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"open_opt_total_result": pl.Float64,
			"open_opt_transactie_fee": pl.Float64,
		})

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
		df_open_sp_sum = _normalize_asset_rollup(df_open_sp_sum)
	else:
		df_open_sp_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"open_sp_result": pl.Float64,
			"open_sp_transactie_fee": pl.Float64,
			"open_sp_aantal": pl.Float64,
		})

	df_opt_time_live = _safe_df(SNAPSHOT_STORE.snapshot_optie_timevalue_live)
	if not df_opt_time_live.is_empty():
		if selected_brokers is not None and "broker" in df_opt_time_live.columns:
			df_opt_time_live = df_opt_time_live.filter(
				pl.col("broker").cast(pl.Utf8).str.to_lowercase().is_in([str(b).strip().lower() for b in selected_brokers])
			)
		if asset_rollup:
			df_opt_time_live = df_opt_time_live.filter(
				pl.col("asset").cast(pl.Utf8).str.strip_chars().str.to_uppercase() == str(asset_rollup).strip().upper()
			)
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
		df_opt_time_sum = _normalize_asset_rollup(df_opt_time_sum)
	else:
		df_opt_time_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"optie_tijdswaarde_signed_eur": pl.Float64,
		})

	df_live = df_aandelen_sum.join(df_open_opt_sum, on=["asset_rollup"], how="full", suffix="_open_opt")
	df_live = _coalesce_asset_rollup(df_live, "asset_rollup_open_opt")
	df_live = df_live.join(df_open_sp_sum, on=["asset_rollup"], how="full", suffix="_open_sp")
	df_live = _coalesce_asset_rollup(df_live, "asset_rollup_open_sp")
	df_live = df_live.join(df_opt_time_sum, on=["asset_rollup"], how="full", suffix="_tv")
	df_live = _coalesce_asset_rollup(df_live, "asset_rollup_tv")

	df_static = _cached_static_summary(selected_brokers=selected_brokers, asset_rollup=asset_rollup)
	df_final = df_live.join(df_static, on=["asset_rollup"], how="full", suffix="_static")
	df_final = _coalesce_asset_rollup(df_final, "asset_rollup_static")
	if selected_brokers is not None and "asset_rollup" in df_final.columns:
		scope_assets = _broker_scope_assets(selected_brokers, asset_rollup)
		if scope_assets:
			df_final = _normalize_asset_rollup(df_final)
			df_final = df_final.filter(pl.col("asset_rollup").is_in(list(scope_assets)))
		else:
			df_final = _empty_df({"asset_rollup": pl.Utf8})
	df_price_fallback = _asset_price_fallback_df(asset_rollup=asset_rollup)
	if not df_price_fallback.is_empty():
		df_final = df_final.join(df_price_fallback, on=["asset_rollup"], how="left")

	required_columns = {
		"open_sp_aantal": 0,
		"open_sp_result": 0,
		"open_sp_transactie_fee": 0,
		"clos_sp_transactie_euro_totaal": 0,
		"clos_sp_transactie_fee": 0,
		"eq_aantal_bezit": 0,
		"eq_total_result": 0,
		"eq_total_fee": 0,
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
		"regio": "",
		"sector": "",
		"value_grow": "",
		"portfolio_total_waarde_lineair_pct": 0,
		"portfolio_total_waarde_delta_pct": 0,
		"optie_tijdswaarde_signed_eur": 0,
	}
	for col, default in required_columns.items():
		if col not in df_final.columns:
			df_final = df_final.with_columns(pl.lit(default).alias(col))

	if "koers_fallback" in df_final.columns:
		df_final = df_final.with_columns(
			pl.when(pl.col("koers").is_null() | (pl.col("koers") <= 0))
			.then(pl.col("koers_fallback"))
			.otherwise(pl.col("koers"))
			.alias("koers")
		)

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
		df_sum = _empty_df({
			"asset_rollup": pl.Utf8,
			"close_price": pl.Float64,
			"koers": pl.Float64,
			"pct_change": pl.Float64,
			"eq_aantal_bezit": pl.Float64,
			"open_sp_aantal": pl.Float64,
			"eq_total_result": pl.Float64,
			"clos_opt_transactie_euro_totaal": pl.Float64,
			"clos_sp_transactie_euro_totaal": pl.Float64,
			"open_opt_total_result": pl.Float64,
			"open_sp_result": pl.Float64,
			"div_en_bel": pl.Float64,
			"totaal_ex_fee": pl.Float64,
			"totaal_inc_fee": pl.Float64,
			"totaal_fee": pl.Float64,
			"totaal": pl.Float64,
			"regio": pl.Utf8,
			"sector": pl.Utf8,
			"value_grow": pl.Utf8,
			"status": pl.Utf8,
			"portfolio_total_waarde_lineair_pct": pl.Float64,
			"portfolio_total_waarde_delta_pct": pl.Float64,
			"optie_tijdswaarde_signed_eur": pl.Float64,
		})

	df_sum = df_sum.with_columns((pl.col("totaal_inc_fee") - pl.col("totaal")).alias("net_change"))
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
