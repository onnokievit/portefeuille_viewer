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

---

## 39. Integratieplan in `portefeuille_viewer_1.2`

### 39.1 Hoofdkeuze: bouwen als service, niet als losse indicator-tab

De analyse-tool moet in `portefeuille_viewer_1.2` als centrale service draaien:

```text
AssetIndicatorService
```

Deze service moet:

1. bestaande snapshots lezen;
2. per asset scores en adviesregels berekenen;
3. actuele resultaten naar `SNAPSHOT_STORE` schrijven;
4. periodiek resultaten persistent wegschrijven;
5. snapshot-events publiceren zodat andere onderdelen de output kunnen gebruiken;
6. later uitbreidbaar zijn naar backtest, alerts en ML.

Belangrijk:

```text
De indicator-service is een beslislaag bovenop bestaande data.
De indicator-service wordt niet de nieuwe brondata-laag.
```

Dus:

- geen tweede eigen prijsfeed;
- geen dubbele optiechain-loader;
- geen eigen positie-import naast de bestaande aggregators;
- geen directe UI-logica in de service;
- geen transactie-injectiepad.

De service hoort dezelfde ontwerpfilosofie te volgen als de rest van de app:

- snapshots als centrale runtime-datalaag;
- additieve database-uitbreidingen;
- heavy compute buiten directe UI-interactie;
- signalen alleen gericht publiceren;
- eerst parallel bouwen, pas later UI-cutover of bredere afhankelijkheden.

---

### 39.2 Plaats in de bestaande architectuur

Voorgestelde bestanden:

```text
portefeuille_viewer/services/asset_indicator_service.py
portefeuille_viewer/services/asset_indicator_rules.py
portefeuille_viewer/services/asset_indicator_models.py
portefeuille_viewer/data/asset_indicator_repository.py
```

Later, wanneer een aparte moderne view zinvol wordt:

```text
portefeuille_viewer/projections/asset_indicator_projection_v2.py
portefeuille_viewer/ui_logica/asset_indicator_web_pilot_tab.py
```

Voor de eerste iteratie is een aparte tab niet nodig. De eerste zichtbare integratie hoort in:

```text
Single Asset Analyse
```

Daar moet bovenin de balk per geselecteerd asset een compacte adviesregel komen:

```text
ASML | Bullish accumulation | Long houden | Geen call dichtbij | Put schrijven alleen bij pullback
```

Of korter:

```text
Advies: schrijf puts / long houden / niets doen / covered calls ver OTM / risico verlagen
```

---

### 39.3 Runtime dataflow

Gewenste dataflow:

```text
Repository / PriceFeed / Aggregators / StateEngine
        ↓
SNAPSHOT_STORE bron-snapshots
        ↓
AssetIndicatorService
        ↓
SNAPSHOT_STORE indicator-snapshots
        ↓
Single Asset Analyse / Aandelen / Alerts / toekomstige advisor
        ↓
optioneel: persistente signal history
```

De service gebruikt dus bestaande snapshots als input en publiceert nieuwe snapshots als output.

Minimale output-snapshots:

```text
snapshot_asset_indicator_live
snapshot_asset_indicator_summary
snapshot_asset_indicator_meta
```

Betekenis:

| Snapshot | Inhoud | Consumer |
|---|---|---|
| `snapshot_asset_indicator_live` | rij per asset met scores, regime, advies, reasons | Single Asset Analyse, toekomstige tab |
| `snapshot_asset_indicator_summary` | samenvatting/toplijsten per adviescategorie | dashboard, alerts, scans |
| `snapshot_asset_indicator_meta` | run-id, timestamp, input snapshot versions, status, fouten | debugging, observability |

Voorbeeldrij in `snapshot_asset_indicator_live`:

```text
asset_rollup
asset_name
asset_type
risk_class
as_of
direction_score
theta_score
volume_score
vulnerability_score
liquidity_score
confidence_score
asset_mode
primary_action
secondary_action
covered_call_delta_min
covered_call_delta_max
short_put_delta_min
short_put_delta_max
max_exposure_pct
current_exposure_pct
assignment_exposure_pct
reason_1
reason_2
reason_3
data_quality
```

Voorbeeld:

```text
asset_rollup: MSFT
direction_score: 72
theta_score: 48
volume_score: 63
vulnerability_score: 31
liquidity_score: 92
asset_mode: bullish_accumulation
primary_action: long_houden
secondary_action: covered_calls_alleen_ver_otm
covered_call_delta_min: 0.05
covered_call_delta_max: 0.15
short_put_delta_min: 0.15
short_put_delta_max: 0.25
reason_1: koers boven SMA20/50/200
reason_2: volume bevestigt stijging
reason_3: IV/theta niet hoog genoeg om upside agressief weg te schrijven
```

---

### 39.4 Persistente opslag

De actuele service-output moet in memory beschikbaar zijn via snapshots, maar periodiek ook persistent worden opgeslagen.

Doel van persistentie:

- historie van signalen opbouwen;
- later backtesten of signalen nuttig waren;
- regimewissels reconstrueren;
- toekomstige ML-dataset voorbereiden;
- app na restart snel laatste advies kunnen tonen, ook voordat alle bronnen opnieuw zijn opgebouwd.

Voorgestelde nieuwe tabel:

```text
asset_indicator_signal_history
```

Locatie:

```text
STOCKDATA database
```

Reden:

- signalen zijn markt-/asset-gerelateerd;
- signalen zijn niet puur persoonlijke transactiedata;
- dezelfde asset-signalen kunnen voor meerdere user databases bruikbaar zijn.

Velden:

```text
id
run_id
created_at
as_of
asset_rollup
asset_name
asset_type
risk_class
direction_score
theta_score
volume_score
vulnerability_score
liquidity_score
confidence_score
asset_mode
primary_action
secondary_action
covered_call_delta_min
covered_call_delta_max
short_put_delta_min
short_put_delta_max
max_exposure_pct
current_exposure_pct
assignment_exposure_pct
data_quality
reason_1
reason_2
reason_3
input_hash
service_version
```

Unieke index of dedupe-logica:

```text
asset_rollup + as_of + service_version
```

Voor persoonlijke portefeuille-afhankelijke scores is er een nuance:

- `direction_score`, `volume_score`, `theta_score`, `liquidity_score` zijn grotendeels asset-/marktdata;
- `vulnerability_score`, `current_exposure_pct`, `assignment_exposure_pct` zijn portfolio-afhankelijk.

Daarom zijn er twee opties:

1. v1: alles in user database opslaan, omdat het advies direct portefeuille-afhankelijk is;
2. v2: splitsen in:

```text
STOCKDATA.asset_indicator_market_signal_history
USERDB.asset_indicator_portfolio_signal_history
```

Pragmatische keuze voor eerste implementatie:

```text
Schrijf v1 naar de actieve user database.
```

Reden:

- de eerste adviezen zijn portefeuille-afhankelijk;
- max exposure en assignment exposure horen bij de gebruiker;
- multi-user/multi-db gedrag blijft eenvoudiger te begrijpen;
- later kan marktdeel alsnog naar STOCKDATA worden afgesplitst.

---

### 39.5 Input-snapshots voor v1

De service moet in v1 alleen bestaande bronnen gebruiken.

#### Marktdata

```text
repository_snapshot_historical_ohlcv
repository_snapshot_historical_close
repository_snapshot_historical_close_latest
live_prices
```

Gebruik:

- close/open/high/low/volume;
- moving averages;
- 52-week high/low;
- ATR%;
- recent volume;
- latest close/live price.

#### Asset metadata

```text
repository_snapshot_asset_rollup_data
repository_snapshot_active_asset_rollup_data
```

Gebruik:

- asset naam;
- ticker/IB symbol;
- valuta;
- sector/regio;
- asset type;
- risk class;
- optionable;
- eventueel max exposure.

#### Positie- en exposuredata

```text
aggregator_snapshot_aandelen_live
aggregator_snapshot_load_open_opties_from_tx_live
aggregator_snapshot_open_sprinters_live
repository_snapshot_portfolio_value_total_combined_put
```

Gebruik:

- huidige aandelenwaarde;
- open optieposities;
- open sprinterposities;
- totale portefeuillewaarde;
- asset exposure;
- assignment exposure bij geschreven puts;
- short call risico;
- leverage/knockout risico.

#### Optie- en theta-data

```text
snapshot_optie_timevalue_live
snapshot_optie_timevalue_summary
aggregator_snapshot_load_open_opties_from_tx_live
```

Gebruik:

- time value;
- DTE;
- moneyness;
- optieprijs;
- eventueel IV/Greeks als beschikbaar;
- open option liquidity als deze later beschikbaar komt.

#### Eventdata

```text
repository_snapshot_asset_dividend_calendar
```

Gebruik:

- ex-dividend waarschuwing;
- dividend assignment risk bij calls.

Earnings en macro-events zijn voor v1 optioneel. Deze kunnen later als aparte event-snapshot of tabel worden toegevoegd.

---

### 39.6 Servicegedrag en updatefrequentie

De service moet zowel event-driven als periodiek kunnen draaien.

#### Triggers

Rebuild-trigger bij relevante snapshotupdates:

```text
repository_snapshot_historical_ohlcv
repository_snapshot_historical_close_latest
repository_snapshot_asset_rollup_data
repository_snapshot_active_asset_rollup_data
aggregator_snapshot_aandelen_live
aggregator_snapshot_load_open_opties_from_tx_live
aggregator_snapshot_open_sprinters_live
snapshot_optie_timevalue_live
repository_snapshot_asset_dividend_calendar
repository_snapshot_portfolio_value_total_combined_put
```

Maar:

```text
Niet elke live tick mag direct een volledige indicator-run veroorzaken.
```

Daarom:

- snapshot-events zetten alleen een dirty flag;
- een `QTimer` coalescet updates;
- volledige rebuild maximaal eens per ingestelde interval;
- lichte live refresh mag vaker, maar alleen voor prijzen/exposure.

#### Voorgestelde timers

```text
startup run: 5-10 seconden na app-start
normal market run: elke 5 minuten
live dirty debounce: 30-60 seconden
end-of-day run: na historische update/catchup
persistent write: elke 15 minuten of bij regimewijziging
```

Voor v1:

```text
Elke 5 minuten live berekenen.
Elke 15 minuten wegschrijven.
Bij assetselectie in Single Asset Analyse alleen snapshot lezen, niet zelf rekenen.
```

Voor dagopties/intraday kan later een kortere `intraday_signal` laag komen, maar die hoort niet in v1.

---

### 39.7 Dirty flags en compute-modi

De service moet onderscheid maken tussen drie compute-modi:

#### 1. Full rebuild

Wanneer:

- startup;
- databasewissel;
- historische OHLCV refresh;
- asset metadata gewijzigd;
- handmatige force-refresh.

Doet:

- alle assets opnieuw berekenen;
- alle indicator-snapshots vervangen;
- optioneel persistent wegschrijven.

#### 2. Incremental portfolio refresh

Wanneer:

- open posities wijzigen;
- opties/sprinters/aandelen live aggregators wijzigen;
- scenario later eventueel actief wordt.

Doet:

- alleen exposure/vulnerability en actieadvies herberekenen;
- technische direction/volume-features hergebruiken.

#### 3. Lightweight publish

Wanneer:

- live price verandert;
- UI-consumer actuele stand nodig heeft.

Doet:

- geen zware moving averages;
- alleen laatste prijs, afstand tot levels, exposure en timestamp bijwerken;
- publiceert alleen als relevante waarden echt veranderen.

---

### 39.8 Interne modules

Voorgestelde scheiding:

```text
asset_indicator_service.py
```

Orkestratie:

- QObject-service;
- timers;
- snapshot listeners;
- dirty flags;
- run scheduling;
- schrijft output naar snapshot store;
- roept repository aan voor persistente writes.

```text
asset_indicator_rules.py
```

Pure beslislogica:

- scoreberekeningen;
- regimeclassificatie;
- actie-mapping;
- delta-band mapping;
- reason generation.

Deze module moet zoveel mogelijk zonder Qt en zonder database kunnen draaien.

```text
asset_indicator_models.py
```

Dataclasses of simpele typed payloads:

- `AssetIndicatorInput`
- `AssetIndicatorScores`
- `AssetIndicatorDecision`
- `AssetIndicatorRunMeta`

```text
asset_indicator_repository.py
```

Database-laag:

- tabel aanmaken/migreren;
- laatste signalen laden;
- signal history upserten;
- oude signalen eventueel opschonen.

---

### 39.9 Beslis-output standaardiseren

De service moet geen lange vrije tekst als primaire output gebruiken. Vrije tekst is nuttig voor de UI, maar andere onderdelen moeten op stabiele codes kunnen filteren.

Gebruik daarom vaste codes.

#### Asset modes

```text
bullish_accumulation
bullish_trend
range_theta
bottoming
overextended
bearish_distribution
high_risk_avoid
insufficient_data
```

#### Primary actions

```text
long_houden
long_uitbreiden_voorzichtig
schrijf_puts
covered_calls_ver_otm
theta_harvest
defensieve_covered_call
alleen_spreads
risico_verlagen
niets_doen
geen_advies_onvoldoende_data
```

#### Secondary actions

```text
geen_call_dichtbij
puts_alleen_bij_pullback
geen_naked_puts
geen_extra_leverage
assignment_risico_controleren
ex_dividend_controleren
roll_candidate_zoeken
wachten_op_stabilisatie
```

Single Asset Analyse kan deze codes vertalen naar korte Nederlandse labels:

```text
schrijf_puts -> Schrijf puts
niets_doen -> Niets doen
covered_calls_ver_otm -> Calls ver OTM
risico_verlagen -> Risico verlagen
```

---

### 39.10 Scoring v1

V1 moet bewust beperkt blijven.

#### Direction score v1

Input:

- close versus SMA20/50/200;
- helling SMA50;
- 20d/60d momentum;
- afstand tot 52w high;
- drawdown vanaf 52w high.

Output:

```text
-100 tot +100
```

V1-regels:

```text
close > SMA20 > SMA50 > SMA200              -> positief
SMA50 stijgt                               -> positief
20d momentum positief                      -> positief
close < SMA50 < SMA200                     -> negatief
drawdown groot en geen stabilisatie        -> negatief
drawdown groot maar momentum draait        -> bottoming-kandidaat
```

Belangrijke verbetering:

Een enkele `direction_score` is te eendimensionaal. Voor assetadvies moet direction worden opgesplitst in minimaal:

```text
long_term_direction_score
short_term_direction_score
range_position_score
trend_phase
```

Doel:

- long-term trend apart houden van korte-termijn retrace;
- onderscheid maken tussen structureel bullish, pullback binnen uptrend, range, bodemzone en bearish distributie;
- voorkomen dat een asset met sterke lange trend maar korte pullback verkeerd als `niets_doen` of generiek bearish wordt gezien;
- herkennen of de koers onderin, middenin of bovenin de actuele range zit.

Voorbeelden van `trend_phase`:

```text
long_term_bull_short_term_bull
long_term_bull_retrace
long_term_bull_bottom_10pct_range
long_term_bull_top_10pct_range
range_lower_band
range_mid
range_upper_band
long_term_bear_relief_rally
bearish_distribution
insufficient_data
```

Voorbeeldinterpretatie:

```text
AHOLD:
long_term_direction_score: hoog
short_term_direction_score: neutraal/positief
range_position_score: niet extreem
trend_phase: long_term_bull_short_term_bull
advies: long houden / puts schrijven toegestaan

VFC:
long_term_direction_score: positief/herstellend
short_term_direction_score: pullback
range_position_score: richting onderkant kanaal
trend_phase: long_term_bull_retrace
advies: reduced sizing / deeper OTM puts / calls blijven beheren
```

Deze velden moeten later naast de bestaande `direction_score` in `snapshot_asset_indicator_live` komen. De bestaande `direction_score` mag dan een samenvattende score blijven voor sortering, maar mag niet meer de enige input zijn voor `asset_mode` en `primary_action`.

#### Volume score v1

Input:

- relative volume 20d;
- 3-daagse price-volume score;
- volume-weighted price change.

Output:

```text
-100 tot +100
```

V1-regels:

```text
stijging + hoog volume       -> accumulatie
stijging + laag volume       -> zwakker bullish
daling + hoog volume         -> distributie/panic
daling + laag volume         -> normale pullback
zijwaarts + normaal volume   -> theta-regime
```

#### Theta score v1

Input:

- open optie timevalue;
- DTE;
- premium yield;
- option mid/last indien beschikbaar;
- IV/Greeks alleen gebruiken als betrouwbaar aanwezig.

Output:

```text
0 tot 100
```

V1-regels:

```text
veel timevalue per dag       -> positief
zeer korte DTE + hoge gamma   -> vulnerability omhoog
lage premie                  -> calls/puts minder aantrekkelijk
slechte prijsdata            -> theta confidence omlaag
```

Belangrijke nuance:

De huidige `theta_score` is in eerste instantie een score op bestaande open optieposities en hun timevalue. Dat is nuttig om lopende posities te beoordelen, maar onvoldoende om nieuwe theta-kansen te vinden op assets waar nog geen optiepositie open staat.

Toekomstige uitbreiding:

```text
OptionOpportunityService
```

Idee:

- neem per asset een representatieve subset uit de beschikbare toekomstige optie-series;
- selecteer meerdere looptijden, bijvoorbeeld 1 week, 2 weken, 4 weken en eventueel maandexpiraties;
- neem per looptijd meerdere strikes rond de koers:
  - licht ITM;
  - ATM;
  - licht OTM;
  - verder OTM;
- bereken per optie de relevante timevalue/extrinsic value;
- koppel dit aan DTE om premie per dag of premie per week te krijgen;
- koppel dit aan delta als ruwe kansschatter;
- gebruik eventueel IV, spread en open interest/volume als kwaliteits- en liquiditeitsfilter;
- vergelijk call- en putzijde apart, omdat een asset tegelijk goede covered-call-premie en slechte put-risk/reward kan hebben, of andersom.

Doel stap 1:

```text
Optiedata gebruiken om het assetadvies te verfijnen.
```

Deze eerste stap hoeft nog geen concreet orderadvies per optiecontract te geven. De vraag is eerst:

```text
Moet ik in deze asset zitten, reduced zitten, bullish blijven,
range/theta traden, of de asset links laten liggen?
```

Optiedata is daarbij niet alleen een losse "is opties interessant?" score, maar een extra lens op de asset zelf:

- hoge premie + stabiele/range koers kan `range_theta` versterken;
- hoge premie + bullish pullback kan short puts interessanter maken;
- lage premie + chaotische koers kan juist betekenen dat risico niet betaald wordt;
- brede spreads of dunne chains verlagen de bruikbaarheid van opties, ook als direction positief is;
- lage theta op een asset met veel koersruis kan leiden tot `links_laten_liggen` of `reduced_position`;
- hoge theta op een zwakke/bearish asset is geen automatisch koopsignaal, maar kan alleen met kleinere sizing/deeper OTM zinvol zijn.

Pas in een latere stap komt de tweede vraag:

```text
Waar zou ik nu nieuwe opties kunnen schrijven, en tegen welke strike/looptijd?
```

Doel latere stap:

```text
Niet alleen meten hoeveel theta er nu in bestaande posities zit,
maar inschatten of een asset momenteel een aantrekkelijke theta-markt heeft.
```

Richting expected value:

```text
candidate_score =
    premium_yield_per_day
  * liquidity_factor
  * direction_fit
  * role_fit
  * risk_penalty
```

Waarbij:

- `premium_yield_per_day`: premie of extrinsic value gedeeld door onderliggende waarde/strike en DTE;
- `liquidity_factor`: spread, volume, open interest en aantal beschikbare strikes;
- `direction_fit`: short puts scoren beter bij bullish trend/pullback; calls beter bij range of overextended;
- `role_fit`: `dividend_low_beta_anchor`, `medium_value_theta`, `high_beta_speculative`, enz. wegen theta verschillend;
- `risk_penalty`: assignment exposure, gamma-risico, drawdown, earnings/dividend en te korte looptijd.

Delta wordt hierbij niet als perfecte kans gezien, maar als bruikbare marktproxy. Delta helpt om een ruwe kansinschatting te maken, maar mag niet los worden gebruikt als "kans op winst". De indicator moet daarom niet alleen zeggen "theta hoog", maar specifieker:

```text
theta aantrekkelijk voor covered calls
theta aantrekkelijk voor short puts
theta alleen aantrekkelijk met deeper OTM strikes
theta te duur qua assignment/downside risico
theta niet aantrekkelijk door lage premie of slechte spread
```

Deze uitbreiding hoort bij de optiechain-/advisorlaag en niet bij de eerste snapshot-only service. De eerste service mag wel alvast aparte velden voorbereiden:

```text
current_theta_score
theta_market_score
theta_opportunity_score
theta_call_opportunity_score
theta_put_opportunity_score
theta_risk_score
theta_ev_proxy
theta_data_quality
```

De optiechain-/advisorlaag moet daarnaast per asset een compacte surface summary kunnen publiceren, zodat de Asset Indicator niet zelf de volledige optiechain hoeft te doorrekenen:

```text
best_put_1w
best_put_2w
best_put_4w
best_call_1w
best_call_2w
best_call_4w
avg_spread_quality
available_strike_count
theta_curve_slope
```

Belangrijk ontwerpprincipe:

```text
De Asset Indicator leest de samenvatting van OptionOpportunityService.
De Asset Indicator scant niet zelf de volledige option chain.
```

Nog te bouwen:

```text
OptionOpportunityService bestaat nog niet.
```

Deze bouwfase moet expliciet toevoegen:

- optiechain/universe ophalen per asset via de bestaande broker-/IBKR-koppeling;
- expiraties selecteren rond bijvoorbeeld 1 week, 2 weken, 4 weken en maandexpiratie;
- strikes selecteren rond ATM, licht OTM, verder OTM en eventueel licht ITM;
- calls en puts apart ophalen en beoordelen;
- bid/ask/last/mid, DTE, delta, theta, IV, volume en open interest vastleggen waar beschikbaar;
- spreadkwaliteit en liquiditeit berekenen;
- per asset bepalen of de optiemarkt interessant genoeg is om actief te volgen;
- ruwe expected-value proxy per kandidaatoptie berekenen;
- kandidaatopties publiceren naar een candidate snapshot;
- per asset een compacte summary publiceren die de Asset Indicator kan lezen.

Voorgestelde snapshots:

```text
snapshot_option_opportunity_candidates
snapshot_option_opportunity_summary
snapshot_option_opportunity_meta
```

Minimale output voor stap 1:

```text
asset_rollup
option_market_score
option_premium_score
option_liquidity_score
option_spread_score
option_chain_depth_score
call_market_score
put_market_score
option_market_status
option_asset_bias
option_positioning_hint
option_regime_hint
reason_1
reason_2
reason_3
```

Voorbeelden van `option_market_status`:

```text
interesting_for_options
usable_but_selective
only_existing_positions
not_interesting_for_options
insufficient_option_data
```

Daarmee kan de Asset Indicator eerst onderscheid maken tussen:

- assets waar opties structureel nuttig zijn;
- assets waar alleen bestaande posities beheerd moeten worden;
- assets waar opties eigenlijk weinig toevoegen;
- assets waar data ontbreekt.

Voorbeelden van assetgerichte hints:

```text
option_asset_bias:
  supports_bullish
  supports_range_theta
  supports_reduced_position
  warns_unpaid_volatility
  warns_bad_liquidity
  no_useful_option_signal

option_positioning_hint:
  normal_position_allowed
  reduced_position_sizing
  only_existing_position_management
  avoid_new_exposure
  avoid_asset_for_now

option_regime_hint:
  bullish_with_put_premium
  range_theta_candidate
  noisy_low_theta
  premium_rich_but_direction_weak
  liquid_but_low_premium
  illiquid_options
```

Deze hints worden later gecombineerd met `direction_score`, `volume_score`, `vulnerability_score` en `indicator_role`. Het eindadvies blijft assetgericht, bijvoorbeeld:

```text
long_houden
schrijf_puts
range_theta
reduced_position
alleen_bestaande_posities_beheren
links_laten_liggen
risico_verlagen
```

Eerste versie bij voorkeur handmatig starten, niet automatisch periodiek:

- optiechain ophalen is traag;
- IBKR-requests kunnen rate-limited zijn;
- de scan moet eerst controleerbaar en reproduceerbaar zijn;
- pas later eventueel periodiek draaien met throttling/cache.

Voorbeeldinterpretatie:

```text
BAYER:
put opportunity: hoog bij 4w 20-30 delta
call opportunity: matig
liquiditeit: ok
risico: verhoogd door zwakke direction_score
advies: alleen deeper OTM puts / ladder klein houden
```

#### Vulnerability score v1

Input:

- current exposure pct;
- assignment exposure pct;
- sprinter/hefboom aanwezigheid;
- short option count;
- asset risk class;
- event flags zoals dividend.

Output:

```text
0 tot 100
```

V1-regels:

```text
asset exposure > max         -> vulnerability omhoog
short puts + assignment > max -> vulnerability omhoog
sprinters dicht bij knockout -> vulnerability sterk omhoog
ex-dividend + short ITM call -> vulnerability omhoog
high beta/speculatief        -> max exposure lager
```

#### Liquidity score v1

Input:

- dollar volume uit OHLCV;
- optie open interest/volume alleen als beschikbaar;
- bid/ask spread later toevoegen.

Output:

```text
0 tot 100
```

V1 mag liquidity nog simpel houden. Als data ontbreekt:

```text
liquidity_score = null
data_quality = partial
```

---

### 39.11 Actie-mapping v1

De belangrijkste mapping:

```text
if data_quality == "insufficient":
    primary_action = "geen_advies_onvoldoende_data"

elif vulnerability_score >= 80:
    primary_action = "risico_verlagen"
    secondary_action = "geen_naked_puts"

elif direction_score >= 60 and volume_score >= 40:
    primary_action = "long_houden"
    secondary_action = "geen_call_dichtbij"
    covered_call_delta = 0.05-0.15

elif direction_score >= 30 and theta_score >= 60:
    primary_action = "covered_calls_ver_otm"
    secondary_action = "puts_alleen_bij_pullback"
    covered_call_delta = 0.15-0.25

elif -25 <= direction_score <= 25 and theta_score >= 60 and vulnerability_score < 60:
    primary_action = "theta_harvest"
    secondary_action = "covered_calls_en_puts_toegestaan"
    covered_call_delta = 0.25-0.40
    short_put_delta = 0.20-0.30

elif direction_score <= -40 and volume_score <= -40:
    primary_action = "risico_verlagen"
    secondary_action = "geen_naked_puts"

elif direction_score >= 10 and volume_score <= -30:
    primary_action = "niets_doen"
    secondary_action = "volume_waarschuwt"

else:
    primary_action = "niets_doen"
```

Belangrijk:

```text
De service geeft een adviesrichting, geen automatische order.
```

Een latere roll-advisor kan op basis van deze output concrete option candidates rangschikken.

---

### 39.12 Integratie met Single Asset Analyse

Eerste UI-consumer:

```text
single_asset_analyse_tab_logica.py
```

Gewenst gedrag:

1. Bij assetselectie leest de tab `snapshot_asset_indicator_live`.
2. De tab filtert op `asset_rollup`.
3. Bovenin de bestaande balk of header komt een compacte adviesstrip.
4. De tab rekent het advies niet zelf uit.
5. Bij `snapshotUpdated("snapshot_asset_indicator_live")` vernieuwt alleen deze strip en eventueel een klein detailblok.

Voorbeeld compacte strip:

```text
Advies: Long houden | Calls: 0.05-0.15 delta | Puts: alleen bij pullback | Risico: normaal
```

Voorbeeld kleurcodering:

| Primary action | Kleur |
|---|---|
| `long_houden` | groen |
| `schrijf_puts` | blauw/groen |
| `theta_harvest` | blauw |
| `covered_calls_ver_otm` | groen/blauw |
| `niets_doen` | grijs |
| `risico_verlagen` | rood/oranje |
| `alleen_spreads` | oranje |
| `geen_advies_onvoldoende_data` | grijs |

Detailpopup of tooltip:

```text
Direction +72
Theta 48
Volume +63
Vulnerability 31
Reden:
1. Koers boven SMA20/50/200
2. Volume bevestigt stijging
3. Premie niet hoog genoeg om upside agressief weg te schrijven
```

De strip moet stabiel blijven bij live ticks:

- geen tabel rebuild;
- geen asset reload;
- alleen label/score update;
- update throttlen als de service snel publiceert.

---

### 39.13 Integratie met andere onderdelen

#### Aandelen-tab

Later kan `snapshot_asset_indicator_live` worden gejoined op `asset_rollup`.

Mogelijke extra kolommen:

```text
asset_mode
primary_action
direction_score
theta_score
vulnerability_score
```

Gebruik:

- snel zien welke assets calls vermijden;
- welke assets put-write candidates zijn;
- welke assets te veel vulnerability hebben.

#### Open Opties

Gebruik:

- short calls markeren wanneer `secondary_action = geen_call_dichtbij`;
- roll candidate markeren als short call delta te hoog wordt;
- short puts markeren wanneer volume/distributie waarschuwt.

#### Optie Tijdswaarde

Gebruik:

- timevalue niet los beoordelen, maar combineren met direction;
- hoge timevalue op bullish accumulation betekent niet automatisch call schrijven;
- hoge timevalue in range_theta krijgt prioriteit.

#### Alerts

Later kunnen alerts direct op de indicator-output draaien:

```text
asset_mode veranderd
primary_action veranderd
vulnerability_score boven 80
theta_score boven 70
volume_score draait van positief naar sterk negatief
assignment_exposure_pct boven limiet
```

---

### 39.14 Scenario-integratie

Voor v1 moet de indicator-service standaard op live/base portefeuille draaien.

Scenario-integratie komt later en moet aansluiten op de bestaande overlay-architectuur.

Niet doen:

```text
scenario-orders in de indicator-service als transacties injecteren
```

Wel doen:

```text
scenario-aware indicator-run als aparte context
```

Voorbeeld latere snapshots:

```text
snapshot_asset_indicator_live
snapshot_asset_indicator_scenario
snapshot_asset_indicator_scenario_meta
```

Gebruik:

- wat verandert er aan vulnerability als een scenario actief is;
- welke assets worden na scenario boven max exposure geduwd;
- verandert het advies na generated option actions.

Voor v1:

```text
geen scenario-integratie, alleen architectuur voorbereiden.
```

---

### 39.15 Database-migratie en compatibiliteit

Schemawijzigingen moeten via `DbMigrationService`.

Regels:

- alleen nieuwe tabellen;
- geen breaking changes op bestaande tabellen;
- nullable/default kolommen;
- meerdere user databases ondersteunen;
- migratie idempotent maken.

V1-tabellen in user database:

```text
asset_indicator_signal_history
asset_indicator_service_runs
```

`asset_indicator_service_runs`:

```text
run_id
started_at
finished_at
status
assets_total
assets_scored
assets_insufficient_data
error_message
service_version
input_summary
```

Deze run-tabel is nuttig om te zien of de service betrouwbaar draait.

---

### 39.16 Configuratie en feature flags

Nieuwe settings:

```text
ENABLE_ASSET_INDICATOR_SERVICE=true/false
ASSET_INDICATOR_RUN_INTERVAL_SECONDS=300
ASSET_INDICATOR_PERSIST_INTERVAL_SECONDS=900
ASSET_INDICATOR_STARTUP_DELAY_SECONDS=10
ASSET_INDICATOR_ENABLE_SINGLE_ASSET_STRIP=true/false
ASSET_INDICATOR_ENABLE_HISTORY_WRITE=true/false
```

Reden:

- service veilig parallel kunnen bouwen;
- UI-strip apart kunnen aanzetten;
- persistent schrijven apart kunnen testen;
- snel rollback mogelijk houden.

---

### 39.17 Observability

De service moet per run minimaal loggen:

```text
run_id
mode
duration_ms
assets_total
assets_scored
assets_skipped
snapshot_rows_written
history_rows_written
trigger_reason
```

In `snapshot_asset_indicator_meta`:

```text
last_run_id
last_run_at
last_success_at
last_duration_ms
last_status
last_error
assets_scored
assets_insufficient_data
service_version
```

Belangrijk voor performance:

- geen volledige rebuild bij elke live tick;
- geen publish als output identiek is;
- hash of rowcount/timestamp gebruiken om onnodige UI-updates te vermijden.

---

### 39.18 Teststrategie

#### Unit tests

Voor `asset_indicator_rules.py`:

- bullish accumulation;
- range theta;
- bearish distribution;
- high vulnerability;
- insufficient data;
- covered-call penalty;
- put-writing filter.

#### Service tests

Met kleine Polars testframes:

- service leest bron-snapshots;
- service schrijft `snapshot_asset_indicator_live`;
- ontbrekende OHLCV geeft `insufficient_data`;
- ontbrekende optiegegevens breekt run niet;
- exposure boven limiet verhoogt vulnerability;
- same-output publish wordt overgeslagen of beperkt.

#### Integratietests

- app start met service uit;
- app start met service aan;
- databasewissel forceert full rebuild;
- Single Asset Analyse toont strip voor geselecteerd asset;
- bij ontbrekend advies toont UI neutrale tekst.

#### Handmatige smoke test

1. Start app.
2. Controleer dat indicator-service na startup één run doet.
3. Open Single Asset Analyse.
4. Kies asset met voldoende historie.
5. Controleer adviesstrip.
6. Kies asset zonder voldoende historie.
7. Controleer `geen advies / onvoldoende data`.
8. Wacht op volgende timer-run.
9. Controleer dat tab niet flikkert of volledig herlaadt.
10. Controleer history-tabel op nieuwe signalen als persistentie aan staat.

---

### 39.19 Gefaseerde implementatie

#### Fase 0: datacontract vastleggen

Doel:

- outputkolommen vastleggen;
- action codes vastleggen;
- snapshot keys toevoegen aan `SnapshotStore`;
- feature flags toevoegen;
- geen UI-gedrag wijzigen.

Resultaat:

```text
Leeg maar stabiel contract voor indicator-output.
```

#### Fase 1: pure rules-engine

Doel:

- `asset_indicator_rules.py` bouwen;
- Direction v1;
- Volume v1;
- simpele action mapping;
- unit tests.

Nog geen timers, geen database.

Resultaat:

```text
Los testbare score- en advieslogica.
```

#### Fase 2: service met snapshot-output

Doel:

- `AssetIndicatorService` bouwen;
- bestaande snapshots lezen;
- `snapshot_asset_indicator_live` publiceren;
- `snapshot_asset_indicator_meta` publiceren;
- startup run en handmatige schedule.

Resultaat:

```text
Andere app-onderdelen kunnen indicator-output lezen uit SNAPSHOT_STORE.
```

#### Fase 3: Single Asset Analyse strip

Doel:

- bovenin `Single Asset Analyse` advies tonen;
- alleen lezen uit `snapshot_asset_indicator_live`;
- reageren op `snapshotUpdated("snapshot_asset_indicator_live")`;
- geen zware herberekening in UI.

Resultaat:

```text
Per asset zichtbaar: schrijf puts / niets doen / long houden / calls ver OTM / risico verlagen.
```

#### Fase 4: persistentie

Doel:

- repository bouwen;
- migratie voor history/run-tabellen;
- periodieke writes;
- laatste advies kunnen laden na restart.

Resultaat:

```text
Historische signalen worden opgebouwd.
```

#### Fase 5: portfolio-aware scores

Doel:

- aandelen, opties en sprinters combineren;
- current exposure pct;
- assignment exposure pct;
- vulnerability score;
- max exposure regels per risk class.

Resultaat:

```text
Advies houdt rekening met bestaande portefeuillepositie.
```

#### Fase 6: theta-aware uitbreiding

Doel:

- koppelen aan `snapshot_optie_timevalue_live`;
- theta score;
- DTE/gamma-risk;
- call/put delta-band output;
- roll-candidate basis voorbereiden.

Resultaat:

```text
Advies ondersteunt theta harvesting zonder blind upside weg te schrijven.
```

#### Fase 7: scans en alerts

Doel:

- summary snapshot gebruiken;
- assets groeperen per actie;
- alertregels toevoegen.

Voorbeelden:

```text
toon assets waar ik geen calls moet schrijven
toon put-write candidates
toon assets met vulnerability > 80
toon range-theta assets
```

#### Fase 8: backtest en ML-voorbereiding

Doel:

- signal history combineren met latere returns;
- meten of regimes zinvol waren;
- roll-beslissingen evalueren;
- feature dataset opbouwen.

Resultaat:

```text
De indicator wordt meetbaar en kan later ML voeden.
```

---

### 39.20 Eerste concrete bouwsnede

De kleinste zinvolle eerste bouwsnede is:

```text
1. Snapshot contract toevoegen
2. asset_indicator_rules.py met Direction + Volume + action mapping
3. AssetIndicatorService met 5-minuten timer
4. snapshot_asset_indicator_live publiceren
5. Single Asset Analyse adviesstrip lezen uit snapshot
```

Nog niet in eerste bouwsnede:

- persistent history;
- volledige optiechain/Greeks;
- IV Rank;
- scenario-integratie;
- aparte WebEngine-tab;
- ML;
- automatische order-candidates.

Deze volgorde houdt de feature klein genoeg om veilig in de bestaande app te integreren, maar legt wel direct het juiste fundament:

```text
service -> snapshot -> consumers -> history -> advisor
```

---

### 39.21 Asset role naast `waarde_groei`

`asset_rollup_data.value_grow` / `waarde_groei` blijft bestaan en behoudt zijn huidige betekenis.

Voor de indicator is later een aparte interpretatiekolom nodig, omdat waarde/groei niet hetzelfde is als de rol die een asset in de strategie speelt.

Extra kolom in `asset_rollup_data`:

```text
indicator_rol
```

Let op: de huidige fysieke kolomnaam is `indicator_rol`. In de code worden daarnaast de aliases `indicator_role` en de oude typo `indicatorl_rol` ondersteund.

Vaste rollen:

```text
dividend_low_beta_anchor
dividend_value
medium_value_theta
high_beta_value
high_beta_speculative
early_investor
volatility_products
ignore
```

Gebruik:

- `dividend_low_beta_anchor`: stabiele dividend-/allocatiepositie met lage beta. Lagere groei en lage theta zijn acceptabel; advies moet minder snel dwingen tot actie. Covered calls alleen voorzichtig en niet te dicht bij de koers.
- `dividend_value`: waarde/dividendpositie waar trend en dividend belangrijk zijn, maar waar optiepremie wel als extra rendement mag meetellen.
- `medium_value_theta`: tussen waarde en groei in, vaak met hogere volatiliteit en bruikbare theta. Voorbeelden zoals Bayer kunnen hier vallen: richting mag wisselend zijn, maar de asset kan interessant blijven voor ladders met puts/calls mits position sizing klopt.
- `high_beta_value`: grote kwaliteitsbedrijven of big tech met hogere beta, maar ook echte omzet/winst. Upside niet te snel wegschrijven; drawdowns zijn normaaler dan bij dividend anchors.
- `high_beta_speculative`: speculatieve/high beta assets. Strengere exposurelimieten, kleinere posities, meer nadruk op downside en assignment-risico.
- `early_investor`: kleine vroege posities waarvan de thesis vooral groei is. Mag dalen zonder direct exit-signaal; calls kunnen later helpen om costbase te verlagen, maar niet agressief zolang de positie klein en thesisgedreven is.
- `volatility_products`: producten zoals UVXY die per case een andere interpretatie nodig hebben. Voor UVXY is de lange termijn bijvoorbeeld structurele daling en kan short calls schrijven logisch zijn, terwijl korte termijn stress juist hard tegen de positie kan bewegen.
- `ignore`: asset niet meer scoren of tonen in indicator-output.

`turnaround_theta` is geen vaste rol. Dat moet later een dynamische suggestie/regime worden die de indicator kan voorstellen en die daarna eventueel door de gebruiker geaccepteerd kan worden.

Implementatie v1.3:

- `indicator_rol` wordt ingelezen uit `asset_rollup_data`.
- `indicator_role` wordt gepubliceerd in `snapshot_asset_indicator_live`.
- Assets met rol `ignore` worden niet gescoord en niet getoond in de indicator-output.
- De Asset Indicator-tab krijgt een rolkolom en rolfilter.
- De rol weegt nu nog niet inhoudelijk mee in de action mapping; dat is de volgende laag nadat de rollen in de data gevuld zijn.

---

### 39.22 Status implementatie in `portefeuille_viewer_1.3`

De eerste werkende implementatie is inmiddels verder dan de oorspronkelijke minimale bouwsnede.

Gerealiseerd:

- `SnapshotStore` bevat indicator-snapshots:
  - `snapshot_asset_indicator_live`;
  - `snapshot_asset_indicator_summary`;
  - `snapshot_asset_indicator_meta`.
- `asset_indicator_contract.py` bevat het gedeelde outputcontract, vaste action/mode codes en schema's.
- `asset_indicator_rules.py` bevat pure score- en beslislogica.
- `asset_indicator_service.py` bouwt de indicator-output vanuit bestaande snapshots.
- `devtools/run_asset_indicator_once.py` kan de indicator buiten de app handmatig draaien.
- `asset_indicator_web_tab.py` toont de indicator-output in de app als aparte tab.
- `main_window_logica.py` voegt de tab `Asset Indicator` toe.

Huidige inputdata:

- `repository_snapshot_asset_rollup_data`;
- `repository_snapshot_historical_ohlcv`;
- `snapshot_optie_timevalue_live`, alleen wanneer deze in de app al gevuld is;
- `indicator_rol` uit `asset_rollup_data`.

Nog niet gebruikt:

- volledige optiechain;
- option opportunity scan;
- portfolio exposure;
- assignment exposure;
- sprinters/leverage;
- dividend/earnings events in de decision mapping;
- persistente signal history.

Huidige outputvelden in `snapshot_asset_indicator_live`:

```text
asset_rollup
asset_name
asset_type
risk_class
indicator_role
as_of
direction_score
long_term_direction_score
short_term_direction_score
range_position_pct
trend_phase
theta_score
volume_score
vulnerability_score
liquidity_score
confidence_score
asset_mode
primary_action
secondary_action
covered_call_delta_min
covered_call_delta_max
short_put_delta_min
short_put_delta_max
max_exposure_pct
current_exposure_pct
assignment_exposure_pct
reason_1
reason_2
reason_3
data_quality
```

Direction is nu meer-dimensionaal:

- `direction_score`: samengestelde score voor sortering en compacte weergave;
- `long_term_direction_score`: structurele trend;
- `short_term_direction_score`: tactische trend/retrace;
- `range_position_pct`: positie in recente range, 0 is onderkant en 100 is bovenkant;
- `trend_phase`: niet-lineair regime-label.

Huidige `trend_phase` waarden:

```text
long_term_bull_short_term_bull
long_term_bull_retrace
long_term_bull_bottom_10pct_range
long_term_bull_top_10pct_range
range_lower_band
range_mid
range_upper_band
long_term_bear_relief_rally
bearish_distribution
insufficient_data
```

Belangrijke ontwerpkeuze:

```text
trend_phase is geen scoreladder.
```

Het label zegt welk soort situatie het is. `range_lower_band` is bijvoorbeeld niet per se slechter dan `range_upper_band`; het vraagt een ander advies.

Huidige theta:

- `theta_score` is voorlopig een ruwe score op bestaande open optieposities;
- de score komt uit `snapshot_optie_timevalue_live`;
- deze score zegt nog niet of een asset zonder open opties aantrekkelijk is voor opties;
- hiervoor is later `OptionOpportunityService` nodig.

Huidige rolstatus:

- `indicator_rol` wordt gelezen;
- `ignore` werkt al als filter;
- rollen verschijnen in de Asset Indicator-tab;
- rollen wegen nog niet inhoudelijk mee in adviesregels.

Bekende beperkingen:

- `asset_mode` en `primary_action` zijn nog te generiek per rol;
- `bearish_distribution` kan voor assets als `medium_value_theta` te hard uitpakken;
- `long_term_bull_top_10pct_range` leidt nu nog niet altijd tot een aangepast call-/putadvies;
- `theta_score = null` betekent vaak alleen dat er geen open optie-timevalue beschikbaar is, niet dat theta onaantrekkelijk is;
- `vulnerability_score`, exposure en assignment-risk zijn nog niet aangesloten;
- option-market suitability is nog niet gebouwd.

Laatste technische validatie:

```text
python -m py_compile portefeuille_viewer\services\asset_indicator_contract.py portefeuille_viewer\services\asset_indicator_rules.py portefeuille_viewer\services\asset_indicator_service.py portefeuille_viewer\ui_logica\asset_indicator_web_tab.py devtools\run_asset_indicator_once.py
python devtools\run_asset_indicator_once.py --limit 20 --sort asset --no-html
```

Beide checks draaiden succesvol na toevoeging van de meer-dimensionale direction-laag.

---

### 39.23 Juiste vervolgstappen vanaf huidige status

De volgende stappen moeten niet meteen naar optiechain/EV springen. Eerst moet de huidige assetindicator beter worden gekalibreerd met de nieuwe dimensies en rollen.

#### Stap 1: role-aware action mapping

Doel:

```text
indicator_rol + trend_phase + range_position_pct gebruiken om het assetadvies te verfijnen.
```

Waarom:

- de rollen zijn nu gevuld en zichtbaar;
- zonder rolweging blijven AHOLD, O, BAYER, APPLOVIN, VFC en UVXY te generiek;
- dit is de kleinste stap met direct betere adviezen.

Voorbeelden:

- `dividend_low_beta_anchor`:
  - stabiele long-term trend minder snel afstraffen;
  - lagere theta accepteren;
  - covered calls voorzichtig en niet agressief;
  - vaker `long_houden` of `schrijf_puts` bij gezonde trend.
- `dividend_value`:
  - trend en dividend blijven leidend;
  - puts mogen bij bullish trend/pullback;
  - bovenin range eerder calls beheren of afwachten.
- `medium_value_theta`:
  - range/pullback mag interessanter zijn als theta of optie-markt later goed is;
  - niet automatisch `niets_doen` bij rommelige direction;
  - wel reduced sizing bij zwakke trend.
- `high_beta_value`:
  - upside niet snel wegschrijven;
  - pullbacks kunnen put-kansen zijn;
  - top van range betekent eerder voorzichtigheid dan automatisch meer puts.
- `high_beta_speculative`:
  - strenger op drawdown, volume en range chaos;
  - kleinere sizing;
  - vaker `avoid_new_exposure` of `reduced_position_sizing`.
- `early_investor`:
  - upside beschermen;
  - calls pas later/voorzichtig om costbase te verlagen;
  - kleine positie kan blijven bestaan ondanks slechte korte termijn.
- `volatility_products`:
  - niet generiek behandelen;
  - per product een aparte strategie-notitie of config nodig.

Concrete codewijziging:

- `ActionInput` uitbreiden met `indicator_role`;
- `map_scores_to_action()` role-aware maken;
- reason-teksten expliciet noemen wanneer rol het advies beïnvloedt;
- nieuwe action/secondary codes toevoegen als nodig:
  - `reduced_position`;
  - `alleen_bestaande_posities_beheren`;
  - `links_laten_liggen`;
  - `avoid_new_exposure`.

#### Stap 2: calibratie van `trend_phase`

Doel:

```text
thresholds controleren op bekende assets.
```

Reviewset:

```text
AHOLD
O
BAYER
APPLOVIN
VFC
ASMLAEB
ASMI
AMD
NVIDIA
UVXY
JNJ
KO
BATS
BTI
BMW
ARCHER
JOBY
ASTS
```

Te controleren per asset:

- klopt long-term score met de grafiek;
- klopt short-term score met recente beweging;
- klopt range position;
- is `trend_phase` logisch;
- is `asset_mode` logisch;
- is `primary_action` bruikbaar.

Uitkomst:

- thresholds aanpassen;
- eventueel nieuwe trend phases toevoegen;
- te harde labels zoals `bearish_distribution` nuanceren.

#### Stap 3: huidige theta hernoemen/splitsen

Doel:

```text
voorkomen dat huidige theta wordt verward met opportunity-theta.
```

Aanpassing:

- huidig `theta_score` inhoudelijk behandelen als `current_theta_score`;
- eventueel output uitbreiden met beide namen:
  - `current_theta_score`;
  - `theta_opportunity_score`;
- `theta_opportunity_score` voorlopig `null` houden tot OptionOpportunityService bestaat.

Waarom:

- huidige score komt alleen uit bestaande open opties;
- lege theta betekent nu vaak "geen open optiepositie", niet "geen theta-kans";
- de UI moet dit onderscheid duidelijk maken.

#### Stap 4: portfolio-aware vulnerability aansluiten

Doel:

```text
advies laten afhangen van bestaande exposure.
```

Input:

- open aandelen;
- open opties;
- open sprinters;
- portfolio value;
- assignment exposure;
- short call exposure;
- eventuele max exposure per rol.

Output:

- `current_exposure_pct`;
- `assignment_exposure_pct`;
- `vulnerability_score`;
- role-aware max exposure;
- reasons wanneer exposure het advies beperkt.

Voorbeeld:

```text
VFC bullish retrace, maar positie al groot:
primary_action: covered calls beheren / reduced sizing
secondary_action: geen extra assignment exposure
```

#### Stap 5: Option market suitability bouwen

Doel stap 5 is nog niet concrete optie-orders kiezen, maar assetadvies verbeteren met optiemarktdata:

```text
Is deze asset qua optiemarkt geschikt om met opties te werken?
```

Te bouwen service:

```text
OptionOpportunityService
```

Eerste output:

```text
option_market_score
option_premium_score
option_liquidity_score
option_spread_score
option_chain_depth_score
call_market_score
put_market_score
option_market_status
option_asset_bias
option_positioning_hint
option_regime_hint
```

Deze service moet eerst handmatig draaien, omdat optiechain ophalen via IBKR traag en rate-limited kan zijn.

#### Stap 6: concrete option opportunities

Pas na stap 5:

- strikes/expiraties rangschikken;
- call/put candidates tonen;
- EV-proxy per kandidaat;
- delta/DTE/spread/liquiditeit meewegen;
- roll-advisor voorbereiden.

#### Stap 7: persistentie en history

Doel:

- signalen bewaren;
- regimewissels volgen;
- later backtesten;
- kunnen zien of adviezen over tijd verbeteren.

Tabellen:

```text
asset_indicator_signal_history
asset_indicator_service_runs
```

#### Stap 8: integratie in Single Asset Analyse

Doel:

- compacte adviesstrip bovenin de bestaande assetanalyse;
- detail/tooltip met long-term, short-term, range, rol, theta en vulnerability;
- geen herberekening in de UI;
- alleen lezen uit `snapshot_asset_indicator_live`.

Aanpak:

- pas doen nadat stap 1 en 2 acceptabele adviezen geven;
- anders wordt een te vroeg advies te prominent in de dagelijkse workflow.
