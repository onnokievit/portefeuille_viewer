import polars as pl

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
