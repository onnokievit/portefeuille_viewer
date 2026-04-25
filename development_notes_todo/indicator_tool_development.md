# Analyse Tool Development

## Context

Deze notitie bundelt de volledige inhoud van de conversatie over het ontwerpen van een Python-app/indicator voor een actieve buy-and-hold aandelenstrategie met opties, sprinters, futures, leverage, theta harvesting, volume-analyse en regime-detectie.

---

## 1. Strategieomschrijving

De strategie bestaat uit buy-and-hold, maar met actief bezit van assets via:

- aandelen;
- opties;
- sprinters/turbo’s;
- futures;
- soms andere instrumenten met leverage.

Er wordt actief in- en uitgeschaald afhankelijk van de fase waarin een aandeel of asset zit.

De inkomstenbronnen zijn:

- koersstijging;
- dividend;
- theta harvesting via geschreven opties.

Belangrijke kenmerken:

- Soms dalen aandelen licht, maar kan er toch rendement worden gemaakt via opties.
- Covered calls beperken soms de waardestijging.
- Choppy/zijwaartse markten zijn aantrekkelijk, omdat daar goed opties geschreven kunnen worden.
- Hoge volatiliteit is aantrekkelijk vanwege hogere premie.
- Opties worden in principe doorgerold om wekelijks theta te oogsten.
- Assets zitten in verschillende sectoren, risicoklassen en regio’s.
- Er wordt geprobeerd om een asset niet meer dan circa 5% van de blootstelling te laten zijn.
- Er worden dagopties, weekopties en maandopties gebruikt.
- Assets omvatten waarde, groei, zilver, bitcoin, UVXY, olie enzovoort.

De gewenste indicator moet per asset aangeven:

- hoe je op dit moment in het asset moet zitten;
- hoe kritisch het signaal is;
- of het bijvoorbeeld bullish, bearish, range-bound, high-volatility of bottoming is;
- of covered calls, geschreven puts, long exposure, spreads of geen positie passend zijn.

---

## 2. Eerste concept: Asset Positioning Matrix

De indicator is niet één klassieke indicator, maar een positie-regime-indicator.

De indicator moet per asset beoordelen:

- trendfase;
- volatiliteit;
- optie-premie;
- dividend;
- leverage- en exposure-risico.

### 2.1 Trendfase

Gebruik bijvoorbeeld:

- koers boven/onder 20-, 50- en 200-daags gemiddelde;
- helling van 50- en 200-daags gemiddelde;
- higher highs / higher lows;
- afstand tot 52-week high/low;
- relatieve sterkte versus index/sector.

Voorbeeldclassificatie:

| Fase | Betekenis | Voorkeurspositie |
|---|---|---|
| Capitulation / bottoming | Hard gedaald, stabilisatie begint | Put schrijven, kleine long, geen agressieve covered call |
| Early bullish turn | Draait omhoog vanaf bodem | Long delta, calls niet te dicht schrijven |
| Bull trend | Sterke trend omhoog | Aandelen / synthetisch long / sprinter, covered calls ver OTM |
| Choppy range | Zijwaarts met premie | Covered calls, puts schrijven, iron condor-achtig |
| Late-cycle / overextended | Sterk gestegen, risico op terugval | Covered calls dichterbij, deel winst afromen |
| Bear trend | Lagere toppen/bodems | Geen naked long, eventueel put spreads of alleen defensieve premie |

Belangrijk onderscheid:

- **early bullish:** upside niet te veel wegschrijven;
- **range/chop:** theta oogsten.

---

## 3. Volatiliteit en premie

Gebruik liever IV Rank / IV Percentile dan alleen absolute implied volatility.

### 3.1 Volatiliteit-score

Gebruik:

- IV Rank of IV Percentile;
- implied volatility versus realized volatility;
- ATR als percentage van koers;
- earnings/event risk;
- skew: zijn puts veel duurder dan calls?

| IV-regime | Interpretatie | Actie |
|---|---|---|
| Lage IV | Premie goedkoop | Minder calls schrijven, liever long exposure houden |
| Normale IV | Neutraal | Standaard wheel/covered call/put write |
| Hoge IV | Premie aantrekkelijk | Theta harvest, maar strike verder kiezen |
| Extreme IV | Vaak event/risk priced in | Positie kleiner, spreads i.p.v. naked short premium |

Belangrijk:

> Bij hoge volatiliteit niet automatisch dichter op de strike schrijven. Vaak juist verder OTM, zodat dezelfde premie wordt ontvangen met minder assignment-/gamma-risico.

---

## 4. Strike-keuze

### 4.1 Calls die je schrijft

| Regime | Call-delta | Betekenis |
|---|---:|---|
| Sterk bullish / net gebodemd | 0.10–0.20 | Upside ruimte houden |
| Bullish maar overbought | 0.20–0.30 | Premie pakken, maar niet te krap |
| Range / choppy | 0.25–0.40 | Theta maximaliseren |
| Bearish / distributie | 0.35–0.50 | Meer defensief, hogere kans op assignment |

### 4.2 Puts die je schrijft

| Regime | Put-delta | Betekenis |
|---|---:|---|
| Asset wil je graag kopen | 0.25–0.40 | Agressiever instappen via premie |
| Asset oké, maar onzeker | 0.15–0.25 | Voorzichtiger |
| Hoge IV / event risk | 0.10–0.20 of put spread | Risico begrenzen |
| Bear trend | Liever geen naked put | Wachten of spread gebruiken |

### 4.3 Call-writing penalty

De indicator moet ook bepalen hoeveel waardestijging je waarschijnlijk misloopt als je covered calls schrijft.

Voorbeelden:

- Momentum sterk + koers boven 20/50/200 MA + relatieve sterkte hoog = geen of lage call-delta.
- Zijwaarts + IV hoog + RSI neutraal = covered call dichterbij.
- Overextended + IV hoog = covered call dichterbij of collar.

---

## 5. Exposure en leverage

Omdat de strategie werkt met aandelen, opties, futures, sprinters en leveraged producten, moet gestuurd worden op effectieve blootstelling, niet op nominale positie.

### 5.1 Effective delta exposure

Meet per asset:

- aandelen: aantal × koers;
- opties: aantal × contractgrootte × koers × delta;
- futures: contractwaarde × delta;
- sprinters: financieringsniveau/hefboom meenemen;
- short opties: assignment-scenario meenemen.

Formule:

```text
Asset exposure % = effectieve blootstelling asset / totale portefeuille-blootstelling
```

### 5.2 Risicolimieten

| Risico | Max |
|---|---:|
| Normale aandelen/ETF’s | 5% netto delta |
| Hoge beta/groei | 3–4% |
| Crypto, UVXY, olie, single-name high IV | 1–3% |
| Futures/sprinters | op stress loss, niet nominale waarde |
| Short premium rond earnings | aparte limiet |

---

## 6. Asset Mode Score

De indicator kan bestaan uit:

- Directional score;
- Volatility score;
- Criticality score.

### 6.1 Directional score

```text
Directional Score =
30% trend
+ 20% momentum
+ 20% relatieve sterkte
+ 15% mean reversion / oversold-overbought
+ 15% fundamentele of carry-factor
```

| Score | Regime |
|---:|---|
| +60 tot +100 | Strong bullish |
| +25 tot +60 | Bullish |
| -25 tot +25 | Range / theta |
| -60 tot -25 | Bearish |
| -100 tot -60 | Avoid / short-biased |

### 6.2 Volatility score

```text
Vol Score =
IV Rank
+ IV minus realized volatility
+ event risk
+ ATR%
```

| Score | Betekenis |
|---:|---|
| 0–30 | Premie onaantrekkelijk |
| 30–60 | Normaal |
| 60–80 | Goed voor optie schrijven |
| 80–100 | Alleen met kleinere size / spreads |

### 6.3 Criticality score

```text
Criticality =
leverage
+ asset beta
+ liquidity risk
+ gap risk
+ earnings/event risk
+ short option gamma risk
+ concentration
```

| Score | Actie |
|---:|---|
| 0–30 | Normale sizing |
| 30–60 | Minder leverage, normale opties |
| 60–80 | Alleen kleine size, strikes verder weg |
| 80–100 | Geen naked short premium; alleen spreads of geen positie |

---

## 7. DTV-model

Het model werd samengevat als:

```text
DTV = Direction, Theta, Vulnerability
```

| Component | Vraag | Output |
|---|---|---|
| Direction | Wil ik long, neutraal of defensief zijn? | Long / neutral / avoid |
| Theta | Is premie aantrekkelijk genoeg? | Schrijf opties / niet schrijven |
| Vulnerability | Hoe hard kan dit fout gaan? | Size, leverage, spread/naked |

### 7.1 DTV-matrix

| Direction | Theta | Vulnerability | Positie |
|---|---|---|---|
| Bullish | Laag | Laag | Aandelen / synthetisch long, geen calls |
| Bullish | Hoog | Laag | Long + covered call ver OTM |
| Bullish | Hoog | Hoog | Put spread of kleine covered call |
| Neutral | Hoog | Laag | Covered call / cash-secured put |
| Neutral | Hoog | Hoog | Iron condor / spreads, kleine size |
| Bearish | Hoog | Laag | Geen long, eventueel call credit spread |
| Bearish | Hoog | Hoog | Vermijden |
| Bottoming | Hoog | Middel | Put schrijven of kleine long, calls vermijden |
| Overextended | Hoog | Middel | Covered call dichterbij, winst afromen |

Belangrijkste regel:

> Eerst bepalen of je upside wilt bezitten. Pas daarna bepalen of je theta wilt verkopen.

---

## 8. Volume toevoegen

Volume hoort als vierde kernblok in het model.

Nieuw model:

```text
DTVV = Direction, Theta, Vulnerability, Volume
```

Volume bepaalt vooral hoeveel vertrouwen er is in het regime.

---

## 9. Volume-regime

Gebruik niet alleen absoluut volume, maar volume relatief aan normaal volume.

```text
Relative Volume = huidig volume / gemiddeld volume over 20 dagen
```

| Relative volume | Betekenis |
|---:|---|
| < 0,7 | weinig interesse / zwak signaal |
| 0,7–1,2 | normaal |
| 1,2–2,0 | verhoogde aandacht |
| > 2,0 | institutionele/event-achtige activiteit |

Een stijging op laag volume is minder betrouwbaar.  
Een stijging op hoog volume is vaak sterker.  
Een daling op hoog volume kan distributie of capitulatie zijn.  
Een daling op laag volume kan ruis zijn.

---

## 10. Price-volume matrix

| Prijs | Volume | Interpretatie | Implicatie |
|---|---|---|---|
| Omhoog | Hoog | Accumulatie / breakout | Calls verder OTM of niet schrijven |
| Omhoog | Laag | Zwakke stijging | Covered calls toegestaan |
| Omlaag | Hoog | Distributie of capitulatie | Oppassen met naked puts |
| Omlaag | Laag | Gezonde pullback | Put schrijven interessanter |
| Zijwaarts | Hoog | Absorptie / strijd | Theta aantrekkelijk, maar voorzichtig |
| Zijwaarts | Laag | Rustige range | Ideaal voor covered calls / theta |

Belangrijke regel:

> Als prijs stijgt op hoog volume, wil je minder snel covered calls schrijven.

---

## 11. 3-daagse price-volume score

Per dag:

```text
+2 = koers omhoog + volume boven 20-daags gemiddelde
+1 = koers omhoog + volume normaal/laag
0 = zijwaarts
-1 = koers omlaag + volume laag
-2 = koers omlaag + volume hoog
```

| 3-daagse score | Interpretatie | Positie-aanpassing |
|---:|---|---|
| +4 tot +6 | Sterke accumulatie | Geen/diepe covered calls |
| +1 tot +3 | Licht bullish | Long houden, calls ver OTM |
| -1 tot +1 | Neutraal/chop | Theta harvest |
| -2 tot -4 | Verzwakking | Calls dichterbij, puts voorzichtiger |
| -5 tot -6 | Distributie/panic | Positie verkleinen of alleen spreads |

Voorbeeld:

```text
Dag 1: +1,8% op 1,6x volume = +2
Dag 2: +0,5% op 1,1x volume = +1
Dag 3: +2,3% op 2,2x volume = +2

3-daagse volume-score = +5
Regime: sterke accumulatie
Actie: geen covered call dichtbij schrijven
```

---

## 12. Volume-indicatoren

### 12.1 Relative Volume

```text
Vandaag volume / 20-daags gemiddeld volume
```

### 12.2 Volume-Weighted Price Change

```text
prijsverandering × relative volume
```

### 12.3 On-Balance Volume

OBV is nuttig voor divergenties:

- koers maakt lagere bodem, OBV maakt hogere bodem = mogelijke accumulatie;
- koers maakt hogere top, OBV maakt lagere top = mogelijke distributie.

### 12.4 VWAP

Voor dagopties en korte weekopties:

| Situatie | Interpretatie |
|---|---|
| koers boven VWAP + hoog volume | intraday bullish |
| koers onder VWAP + hoog volume | intraday bearish |
| koers rond VWAP | chop / mean reversion |
| herhaald afketsen op VWAP | weerstand/steun |

---

## 13. Verschil per looptijd

| Horizon | Belangrijkste volume-signaal |
|---|---|
| Dagopties | intraday volume, VWAP, orderflow, 1–3 dagen |
| Weekopties | 3-daagse price-volume, 5-daagse trend, IV Rank |
| Maandopties | 20-daags volume, OBV, trendfase, earnings/dividend |
| Aandelen buy-and-hold | 50/200-daags volumeprofiel, accumulatie/distributie |

Voorgestelde weging:

```text
Dagopties: 40% volume / 40% prijsactie / 20% IV
Weekopties: 25% volume / 35% trend / 40% IV-theta
Maandopties: 15% volume / 45% trend / 40% valuation/theta
```

---

## 14. Covered call filter met volume

Geen covered call dichtbij schrijven als:

```text
prijs stijgt
EN relative volume > 1,5
EN koers breekt boven weerstand
EN trend-score positief draait
```

Wel covered call schrijven als:

```text
prijs stijgt
MAAR relative volume < 1,0
EN koers nadert weerstand
EN momentum verzwakt
```

---

## 15. Put-writing filter met volume

Interessant:

```text
prijs daalt licht
EN volume is laag
EN lange trend is nog intact
EN IV is verhoogd
```

Gevaarlijk:

```text
prijs daalt hard
EN volume > 1,5–2,0
EN steun breekt
```

Dan liever:

- wachten;
- kleinere size;
- put credit spread;
- lagere strike;
- pas schrijven na stabilisatie.

---

## 16. Nieuwe eindscore

```text
Asset Position Score =
35% Direction
25% Theta
20% Volume Confirmation
20% Vulnerability inverse
```

Volume werkt vooral als confirmation modifier:

```text
Als Direction bullish is en Volume bullish:
    verhoog long-conviction

Als Direction bullish is maar Volume bearish:
    verlaag long-conviction

Als Direction neutraal is en Volume neutraal:
    theta-regime bevestigd

Als Direction bearish is en Volume bearish:
    geen naked short premium
```

---

## 17. Data nodig voor Python-app

De app heeft data nodig in 6 lagen:

```text
1. Marktdata
2. Volume-data
3. Optiedata
4. Portfolio-/positie-data
5. Asset-specifieke risico-data
6. Regime-/beslisregels
```

De app moet per asset output kunnen geven zoals:

```text
ASSET: AAPL
Regime: bullish accumulation
Beste houding: long houden, covered calls alleen ver OTM
Theta-kans: redelijk
Risico: normaal
Actie: schrijf geen call dichter dan 0.15 delta
Max exposure: 5%
```

---

## 18. Marktdata per asset

Minimaal:

| Data | Waarom nodig |
|---|---|
| Open | dagstructuur |
| High | volatiliteit / range |
| Low | volatiliteit / steun |
| Close | trend, momentum |
| Adjusted close | correct voor dividend/splits |
| Daily volume | volume-analyse |
| Intraday prijsdata | nodig voor dagopties / korte signalen |

Timeframes:

| Timeframe | Nodig voor |
|---|---|
| 1 minuut of 5 minuten | dagopties, VWAP, intraday momentum |
| 1 uur | weekopties, korte trend |
| dagelijks | hoofdmodel |
| wekelijks | lange trend / regime |

---

## 19. Volume-data

Nodig:

| Data | Berekening |
|---|---|
| Dagvolume | huidig volume |
| 3-daags gemiddeld volume | korte marktinteresse |
| 5-daags gemiddeld volume | korte swing |
| 20-daags gemiddeld volume | normaalvolume |
| 50-daags gemiddeld volume | middellange interesse |
| Relative volume | volume vandaag / 20-daags volume |
| Volume trend | stijgt of daalt volume over tijd |
| Dollar volume | koers × volume |

Berekeningen:

```python
relative_volume = volume_today / average_volume_20d
dollar_volume = close * volume
volume_weighted_move = price_change_pct * relative_volume
```

Velden:

```text
volume_today
volume_avg_3d
volume_avg_5d
volume_avg_20d
volume_avg_50d
relative_volume_20d
relative_volume_50d
dollar_volume
volume_weighted_price_change
```

---

## 20. Price-volume data

Nodig:

```text
close_today
close_1d_ago
close_3d_ago
close_5d_ago
volume_today
volume_avg_20d
```

Berekeningen:

```python
price_change_1d = close_today / close_1d_ago - 1
price_change_3d = close_today / close_3d_ago - 1
price_change_5d = close_today / close_5d_ago - 1
relative_volume = volume_today / volume_avg_20d
```

3-daagse score:

```python
def price_volume_day_score(price_change, relative_volume):
    if price_change > 0.005 and relative_volume > 1.2:
        return 2
    elif price_change > 0.005:
        return 1
    elif price_change < -0.005 and relative_volume > 1.2:
        return -2
    elif price_change < -0.005:
        return -1
    else:
        return 0
```

---

## 21. Trend- en momentumdata

Indicatoren:

| Indicator | Waarom |
|---|---|
| SMA 20 | korte trend |
| SMA 50 | middellange trend |
| SMA 100 | optioneel |
| SMA 200 | lange trend |
| EMA 8/21 | korte draai |
| RSI 14 | overbought/oversold |
| MACD | momentumdraai |
| ATR 14 | gerealiseerde beweeglijkheid |
| 52-week high/low | positie in cyclus |
| drawdown vanaf high | risicofase |
| distance to moving average | overextended of niet |

Velden:

```text
sma_20
sma_50
sma_200
ema_8
ema_21
rsi_14
atr_14
atr_pct
high_52w
low_52w
distance_from_52w_high
distance_from_sma_50
distance_from_sma_200
```

Voorbeeldlogica:

```python
trend_bullish = close > sma_50 > sma_200
early_bullish_turn = close > sma_20 and sma_20_slope > 0 and close < sma_200
bearish = close < sma_50 < sma_200
```

---

## 22. Optiedata

Per optiecontract:

| Data | Waarom |
|---|---|
| expiration date | looptijd |
| strike | bepalen welke strike aantrekkelijk is |
| call/put | strategie |
| bid | verkoopprijs |
| ask | liquiditeit/spread |
| mid | theoretische uitvoerbare prijs |
| last | minder belangrijk |
| volume | liquiditeit |
| open interest | liquiditeit |
| implied volatility | premiehoogte |
| delta | strike-keuze |
| gamma | risico bij korte looptijd |
| theta | verwachte tijdswaarde |
| vega | gevoeligheid voor IV |
| intrinsic value | ITM/OTM |
| extrinsic value | echte theta-premie |

Belangrijkste velden:

```text
option_delta
option_theta
option_gamma
option_iv
option_bid
option_ask
option_mid
option_volume
option_open_interest
days_to_expiration
extrinsic_value
```

Berekeningen:

```python
premium_yield = option_mid / stock_price
annualized_premium_yield = premium_yield * (365 / days_to_expiration)
theta_per_day_yield = option_theta / stock_price
bid_ask_spread_pct = (ask - bid) / mid
```

---

## 23. IV-data en volatiliteit

Nodig:

| Data | Waarom |
|---|---|
| current IV | huidige optiepremie |
| IV Rank | hoe hoog versus eigen historie |
| IV Percentile | hoe vaak IV lager was |
| historical volatility 10d | korte gerealiseerde vola |
| historical volatility 20d | normale gerealiseerde vola |
| historical volatility 60d | middellange gerealiseerde vola |
| IV minus HV | is premie relatief duur? |
| ATR percentage | praktische beweeglijkheid |

Berekeningen:

```python
iv_rank = (current_iv - iv_low_52w) / (iv_high_52w - iv_low_52w)
iv_hv_spread = current_iv - historical_volatility_20d
```

---

## 24. Event-data

Nodig:

| Event | Waarom |
|---|---|
| Earnings date | enorme IV/gap-risk |
| Ex-dividend date | assignment risk bij calls |
| Dividend amount | early assignment / yield |
| Fed/ECB-events | index, goud, zilver, crypto, olie |
| CPI / macrodata | brede marktrisico’s |
| Product-specific events | biotech, crypto ETF, olie-inventories |

Velden:

```text
next_earnings_date
days_to_earnings
next_ex_dividend_date
days_to_ex_dividend
dividend_amount
macro_event_flag
event_risk_score
```

---

## 25. Portfolio- en positie-data

Per positie:

| Data | Waarom |
|---|---|
| asset ticker | identificatie |
| aantal aandelen | delta exposure |
| gemiddelde aankoopprijs | P/L |
| huidige koers | actuele waarde |
| optieposities | totale delta/theta/gamma |
| futures/sprinters | leverage exposure |
| margin requirement | risico |
| stop-loss / knock-out niveau | sprinterrisico |
| currency | FX-risico |
| sector | spreiding |
| regio | spreiding |
| asset class | spreiding |
| beta | portefeuillerisico |

Voor opties:

```text
underlying
expiration
strike
call_put
long_short
quantity
entry_price
current_price
delta
gamma
theta
vega
iv
```

Voor sprinters/turbo’s:

```text
underlying
quantity
financing_level
knockout_level
leverage
current_price
issuer
distance_to_knockout
```

Voor futures:

```text
contract
multiplier
quantity
notional_value
initial_margin
maintenance_margin
expiry
```

---

## 26. Exposure-data

Nodig:

```text
gross_exposure
net_delta_exposure
asset_exposure_pct
sector_exposure_pct
region_exposure_pct
currency_exposure_pct
margin_used
cash_available
portfolio_value
```

Berekening:

```python
stock_delta_exposure = shares * stock_price

option_delta_exposure = (
    option_quantity 
    * contract_multiplier 
    * stock_price 
    * option_delta
)

total_asset_delta_exposure = stock_delta_exposure + option_delta_exposure
asset_exposure_pct = total_asset_delta_exposure / portfolio_value
```

Voor short puts:

```python
assignment_exposure = strike * contract_multiplier * contracts
```

Voorbeeld:

```text
Huidige delta exposure: 3,2%
Assignment exposure bij geschreven puts: +4,8%
Totaal potentieel asset risico: 8,0%
Conclusie: geen extra puts schrijven.
```

---

## 27. Liquiditeitsdata

Nodig:

| Data | Waarom |
|---|---|
| bid-ask spread aandeel | handelskosten |
| bid-ask spread optie | uitvoerbaarheid |
| option volume | liquiditeit |
| open interest | liquiditeit |
| dollar volume | asset liquiditeit |
| slippage estimate | realistische opbrengst |

Regels:

```text
option_bid_ask_spread_pct < 10% = goed
10–20% = matig
>20% = slecht
```

En:

```text
open_interest > 500 = voorkeur
option_volume > 50 = oké
```

---

## 28. Fundamentele / carry-data

Voor aandelen:

```text
dividend_yield
payout_ratio
earnings_growth
revenue_growth
free_cashflow_yield
debt_to_equity
valuation multiples
analyst estimates eventueel
```

Voor ETF’s:

```text
expense_ratio
distribution_yield
holdings concentration
tracking error
```

Voor commodities:

```text
futures curve
contango/backwardation
roll yield
inventory data indien beschikbaar
```

Voor bitcoin/crypto:

```text
spot price
volatility
funding rates indien futures/perps
ETF flows eventueel
correlation with Nasdaq/liquidity
```

Voor UVXY/VIX-producten:

```text
VIX futures curve
contango/backwardation
roll decay
term structure
```

---

## 29. Databronnen / minimale app-versie

### Minimum viable version

```text
OHLCV data
option chain
dividends
earnings dates
portfolio positions
```

### Betere versie

```text
intraday OHLCV
full Greeks
IV Rank
open interest
corporate actions
macro calendar
sector/regio-classificatie
```

### Professionele versie

```text
real-time quotes
order book / bid-ask depth
historische optie-IV
realized volatility curves
VIX term structure
futures curves
broker margin data
portfolio Greeks
```

---

## 30. Minimale database-structuur

### assets

```text
ticker
name
asset_type
sector
region
currency
risk_class
optionable
max_exposure_pct
```

### prices_daily

```text
date
ticker
open
high
low
close
adjusted_close
volume
```

### prices_intraday

```text
datetime
ticker
interval
open
high
low
close
volume
vwap
```

### options_chain

```text
datetime
underlying
expiration
strike
option_type
bid
ask
mid
last
volume
open_interest
iv
delta
gamma
theta
vega
```

### positions

```text
asset
instrument_type
quantity
entry_price
current_price
delta
theta
gamma
vega
notional_value
margin_required
expiry
strike
option_type
```

### events

```text
ticker
event_type
event_date
event_importance
description
```

### signals

```text
datetime
ticker
direction_score
theta_score
volume_score
vulnerability_score
asset_mode
recommended_action
confidence_score
```

---

## 31. Scores die de app moet berekenen

Hoofdscores:

```text
Direction Score
Theta Score
Volume Score
Vulnerability Score
Liquidity Score
```

### Direction Score

Gebaseerd op:

```text
trend
momentum
relative strength
position versus moving averages
distance from 52-week high/low
```

Output:

```text
-100 = sterk bearish
0 = neutraal
+100 = sterk bullish
```

### Theta Score

Gebaseerd op:

```text
IV Rank
IV minus HV
premium yield
days to expiration
option liquidity
```

Output:

```text
0 = geen aantrekkelijke premie
100 = zeer aantrekkelijk voor optie schrijven
```

### Volume Score

Gebaseerd op:

```text
relative volume
3-day price-volume score
OBV trend
VWAP-position
volume-weighted price move
```

Output:

```text
-100 = distributie
0 = neutraal
+100 = accumulatie
```

### Vulnerability Score

Gebaseerd op:

```text
leverage
gamma risk
event risk
gap risk
asset volatility
concentration
distance to knockout
assignment exposure
```

Output:

```text
0 = laag risico
100 = extreem kwetsbaar
```

### Liquidity Score

Gebaseerd op:

```text
bid-ask spread
option volume
open interest
dollar volume
slippage estimate
```

Output:

```text
0 = niet handelen
100 = zeer liquide
```

---

## 32. Beslislogica

Voorbeeld:

```python
if vulnerability_score > 80:
    action = "Alleen spreads of positie verkleinen"

elif direction_score > 60 and volume_score > 40:
    action = "Long houden; covered calls vermijden of zeer ver OTM"

elif direction_score > 30 and theta_score > 60:
    action = "Long houden; covered calls ver OTM"

elif -25 <= direction_score <= 25 and theta_score > 60:
    action = "Theta harvest: covered calls en/of puts schrijven"

elif direction_score < -40 and volume_score < -40:
    action = "Geen naked puts; reduceer leverage; eventueel covered calls defensief"

elif direction_score > 20 and volume_score < -30:
    action = "Bullish trend maar volume waarschuwt; geen leverage verhogen"

else:
    action = "Hold / wachten op beter signaal"
```

Strike-keuze:

```python
if asset_mode == "bullish_accumulation":
    covered_call_delta = "0.05-0.15"
elif asset_mode == "bullish":
    covered_call_delta = "0.15-0.25"
elif asset_mode == "range_theta":
    covered_call_delta = "0.25-0.40"
elif asset_mode == "overextended":
    covered_call_delta = "0.35-0.50"
else:
    covered_call_delta = "geen standaard covered call"
```

---

## 33. Output per asset

Voorbeeld:

```text
ASSET: MSFT

Regime:
Bullish accumulation

Scores:
Direction: +72
Theta: 48
Volume: +63
Vulnerability: 31
Liquidity: 92

Advies:
Long exposure behouden.
Geen covered call dichtbij schrijven.
Als je toch premie wilt: call maximaal 0.10–0.15 delta.
Put schrijven alleen bij pullback, rond 0.20 delta.
Geen extra leverage nodig.

Reden:
Koers boven 20/50/200 MA.
3-daagse price-volume score positief.
Volume bevestigt stijging.
IV is niet hoog genoeg om veel upside weg te schrijven.
```

Voor theta-regime:

```text
ASSET: SLV

Regime:
High-premium range

Scores:
Direction: +8
Theta: 76
Volume: +4
Vulnerability: 42
Liquidity: 78

Advies:
Theta harvesting toegestaan.
Covered calls rond 0.25–0.35 delta.
Short puts rond 0.20–0.30 delta als extra positie gewenst is.
Rollen bij 70–80% winst of bij delta boven 0.45.
```

Voor risico-regime:

```text
ASSET: UVXY

Regime:
High-risk volatility product

Scores:
Direction: -15
Theta: 84
Volume: -22
Vulnerability: 96
Liquidity: 81

Advies:
Geen naked short premium.
Geen buy-and-hold.
Alleen kleine defined-risk spreads.
Max exposure 1%.
```

---

## 34. Vast interval of op aanvraag

### Op aanvraag

Voorbeelden:

```text
analyseer AAPL nu
analyseer mijn portefeuille
toon assets met beste theta-score
toon assets waar ik geen calls moet schrijven
toon assets met distributierisico
```

### Vast interval

| Interval | Wat controleren |
|---|---|
| Elke 5 minuten | dagopties, VWAP, volume spike |
| Elk uur | weekopties, trend/volume shifts |
| Einde handelsdag | hoofdscore updaten |
| Voor opening | earnings/events/risico |
| Vrijdagmiddag | expiratie/roll-kandidaten |
| Maandag pre-market | nieuwe theta-kansen |

Minimaal:

```text
pre-market scan
midday update
laatste handelsuur update
einde-dag update
```

---

## 35. Alerts

Goede alerts:

```text
Asset breekt uit op >1.5x volume: schrijf geen call dichtbij.
Short call delta > 0.45: overweeg rollen.
Short put delta > 0.35 en volume bearish: risico stijgt.
Asset exposure boven 5%.
Assignment exposure boven limiet.
Earnings binnen 5 dagen.
Ex-dividend binnen 3 dagen en call is ITM.
IV Rank boven 70: theta-kans.
IV Rank onder 20: calls schrijven minder aantrekkelijk.
Sprinter binnen 10% van knockout.
```

---

## 36. Implementatiefases

### Fase 1 — basis analyzer

```text
OHLCV ophalen
moving averages berekenen
relative volume berekenen
3-daagse price-volume score maken
trendfase bepalen
```

### Fase 2 — optie-analyzer

```text
option chain ophalen
Greeks verwerken
IV Rank berekenen
beste call/put strikes selecteren
premium yield berekenen
```

### Fase 3 — portfolio-aware

```text
eigen posities importeren
delta exposure berekenen
assignment exposure berekenen
5%-limiet controleren
sector/regio-risico tonen
```

### Fase 4 — alerts

```text
vast interval draaien
regimewijzigingen detecteren
roll-alerts geven
earnings/dividend waarschuwingen
```

### Fase 5 — optimalisatie

```text
backtest
scorewegingen aanpassen
per assetclass andere regels
performance per regime meten
```

---

## 37. Brondata die uit IBKR gedownload moet worden

Kort en bondig:

1. **Accountwaarde**
   - Net liquidation value
   - Cash
   - Margin available
   - Buying power

2. **Huidige posities**
   - Aandelen
   - Opties
   - Futures
   - ETF’s/ETP’s
   - Sprinters/turbo’s indien beschikbaar

3. **Positie-details**
   - Aantal
   - Gemiddelde aankoopprijs
   - Huidige koers
   - Marktwaarde
   - Unrealized P/L
   - Realized P/L

4. **OHLCV-prijsdata**
   - Open
   - High
   - Low
   - Close
   - Volume
   - Adjusted close indien beschikbaar

5. **Intraday data**
   - 1-min / 5-min candles
   - Intraday volume
   - VWAP indien beschikbaar

6. **Realtime quotes**
   - Bid
   - Ask
   - Last
   - Bid size
   - Ask size
   - Volume

7. **Optieketens**
   - Expiratiedatum
   - Strike
   - Call/put
   - Bid
   - Ask
   - Last
   - Volume
   - Open interest

8. **Optie-Greeks**
   - Delta
   - Gamma
   - Theta
   - Vega
   - Implied volatility

9. **Contractinformatie**
   - Contract ID
   - Multiplier
   - Valuta
   - Beurs
   - Trading hours
   - Expiry
   - Settlement type

10. **Dividenddata**
    - Ex-dividenddatum
    - Dividendbedrag
    - Betaaldatum

11. **Corporate actions**
    - Splits
    - Special dividends
    - Mergers/spinoffs

12. **Margin-data**
    - Initial margin
    - Maintenance margin
    - Margin impact per positie
    - Portfolio margin impact

13. **Orders en trades**
    - Open orders
    - Uitgevoerde trades
    - Commissies
    - Fill price
    - Order status

14. **FX-data**
    - Valutakoersen
    - Cash per valuta
    - FX exposure

15. **Historische optieprijzen**
    - Historische bid/ask/last
    - Historische IV
    - Historische Greeks indien beschikbaar

---

## 38. Kernsamenvatting

De Python-app moet per asset bepalen:

```text
Direction: wat is de fase?
Theta: is premie aantrekkelijk?
Volume: bevestigt marktgedrag deze fase?
Vulnerability: hoe gevaarlijk is de positie?
Liquidity: is het uitvoerbaar?
```

En dit vertalen naar een Asset Mode:

```text
Long houden
Long zonder calls
Covered calls ver OTM
Theta harvest
Put-write entry
Defensieve covered call
Alleen spreads
Vermijden / reduceren
```

De belangrijkste regel van het model:

> Eerst bepalen of je upside wilt bezitten. Pas daarna bepalen of je theta wilt verkopen.

