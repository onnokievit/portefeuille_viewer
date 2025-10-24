import polars as pl

def bereken_open_aandelen_payoff(df_aandelen: pl.DataFrame, koers: float) -> float:
	"""
	Bereken de ongerealiseerde winst op open aandelen (nog in bezit).
	Verwacht kolommen: euro_koop, aantal_koop, euro_verkoop, aantal_verkoop
	"""
	if df_aandelen is None or df_aandelen.height == 0:
		return 0.0
	# Sommeer alle aankopen en verkopen
	euro_koop = float(df_aandelen['euro_koop'].sum()) if 'euro_koop' in df_aandelen.columns else 0.0
	aantal_koop = float(df_aandelen['aantal_koop'].sum()) if 'aantal_koop' in df_aandelen.columns else 0.0
	euro_verkoop = float(df_aandelen['euro_verkoop'].sum()) if 'euro_verkoop' in df_aandelen.columns else 0.0
	aantal_verkoop = float(df_aandelen['aantal_verkoop'].sum()) if 'aantal_verkoop' in df_aandelen.columns else 0.0
	avg_buy = euro_koop / aantal_koop if aantal_koop != 0 else 0.0
	aantal_bezit = aantal_koop + aantal_verkoop
	# Normale long-positie of geen positie
	if aantal_bezit >= 0:
		waarde_bezit = aantal_bezit * koers
		kostprijs_bezit = aantal_bezit * avg_buy
		winst_bezit = waarde_bezit + kostprijs_bezit
	else:
		# Short-only: winst = euro_verkoop + aantal_bezit * koers
		winst_bezit = euro_verkoop + aantal_bezit * koers
	return winst_bezit

def bereken_gesloten_aandelen_payoff(df_aandelen: pl.DataFrame) -> float:
	"""
	Bereken de gerealiseerde winst op gesloten aandelen (al verkocht).
	Verwacht kolommen: euro_koop, aantal_koop, euro_verkoop, aantal_verkoop
	"""
	if df_aandelen is None or df_aandelen.height == 0:
		return 0.0
	# Sommeer alle aankopen en verkopen
	asset_rollup = df_aandelen['asset_rollup'][0] if 'asset_rollup' in df_aandelen.columns else 'onbekend'
	euro_koop = float(df_aandelen['euro_koop'].sum()) if 'euro_koop' in df_aandelen.columns else 0.0
	aantal_koop = float(df_aandelen['aantal_koop'].sum()) if 'aantal_koop' in df_aandelen.columns else 0.0
	euro_verkoop = float(df_aandelen['euro_verkoop'].sum()) if 'euro_verkoop' in df_aandelen.columns else 0.0
	aantal_verkoop = float(df_aandelen['aantal_verkoop'].sum()) if 'aantal_verkoop' in df_aandelen.columns else 0.0
	avg_buy = euro_koop / aantal_koop if aantal_koop != 0 else 0.0
	
	winst_verkocht = euro_verkoop - (aantal_verkoop * avg_buy)
	print(f"DEBUG: Gesloten aandelen payoff berekend: asset= {asset_rollup}, euro_koop={euro_koop}, aantal_koop={aantal_koop}, euro_verkoop={euro_verkoop}, aantal_verkoop={aantal_verkoop}, avg_buy={avg_buy}, winst_verkocht={winst_verkocht}")
	return winst_verkocht


def bereken_open_sprinters_payoff(df_open_sprinters: pl.DataFrame, koers: float) -> float:
	"""
	Bereken de totale payoff van open sprinters bij een bepaalde koers.
	Verwacht kolommen: optie_strike, optie_call_put, SomVantransactie_aantal, SomVantransactie_euro_totaal
	"""
	if df_open_sprinters is None or df_open_sprinters.height == 0:
		return 0.0
	strikes = df_open_sprinters['optie_strike'].to_numpy()
	callputs = df_open_sprinters['optie_call_put'].to_numpy()
	aantallen = df_open_sprinters['SomVantransactie_aantal'].to_numpy()
	premies = df_open_sprinters['SomVantransactie_euro_totaal'].to_numpy() if 'SomVantransactie_euro_totaal' in df_open_sprinters.columns else [0.0] * len(strikes)
	payoff = 0.0
	for strike, cp, aantal, premie in zip(strikes, callputs, aantallen, premies):
		try:
			strike = float(strike)
			aantal = float(aantal)
			premie = float(premie)
			if isinstance(cp, str):
				cp = cp.lower()
			# Voor sprinters: payoff = (koers - strike) * aantal + premie (call), (strike - koers) * aantal + premie (put)
			if cp in ('call', 'c'):
				payoff += (koers - strike) * aantal + premie
			elif cp in ('put', 'p'):
				payoff += (strike - koers) * aantal + premie
		except Exception:
			continue
	return payoff


def bereken_open_opties_payoff(df_open_opties: pl.DataFrame, koers: float) -> float:
	"""
	Bereken de totale payoff van open opties bij een bepaalde koers.
	Verwacht kolommen: optie_strike, optie_call_put, SomVantransactie_aantal
	"""
	if df_open_opties is None or df_open_opties.height == 0:
		return 0.0
	strikes = df_open_opties['optie_strike'].to_numpy()
	callputs = df_open_opties['optie_call_put'].to_numpy()
	aantallen = df_open_opties['SomVantransactie_aantal'].to_numpy()
	premies = df_open_opties['SomVantransactie_euro_totaal'].to_numpy() if 'SomVantransactie_euro_totaal' in df_open_opties.columns else [0.0] * len(strikes)
	payoff = 0.0
	for strike, cp, aantal, premie in zip(strikes, callputs, aantallen, premies):
		try:
			strike = float(strike)
			aantal = float(aantal)
			premie = float(premie)
			if isinstance(cp, str):
				cp = cp.lower()
			if cp in ('call', 'c'):
				payoff += max(koers - strike, 0) * aantal + premie
			elif cp in ('put', 'p'):
				payoff += max(strike - koers, 0) * aantal + premie
		except Exception:
			continue
	return payoff
