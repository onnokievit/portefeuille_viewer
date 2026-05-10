# Stock Analyzer Framework Skills - bevindingen en bouwplan

Datum: 2026-05-08

## Aanleiding

In `c:\python_coding\stock_analyzer_framework` staan meerdere trading-analysis skills, waaronder:

- `trade-technical`
- `trade-risk`
- `trade-analyze`
- `trade-quick`
- `trade-options`
- `trade-fundamental`
- `trade-sentiment`

De vraag was of de technische en risico-analyse uit deze skills echt door AI/websearch moet worden gedaan, of dat een groot deel goedkoper, betrouwbaarder en reproduceerbaarder met Python uit de bestaande portefeuille database kan worden berekend.

## Bevinding: huidige framework is vooral skill/prompt, geen Python analyse-engine

De map `stock_analyzer_framework` bevat vooral `SKILL.md` bestanden. Dit zijn instructies aan een AI-agent. Er is nauwelijks uitvoerende Python-code aanwezig. De enige duidelijke Python-code is `trade/scripts/generate_trade_pdf.py`, maar die maakt alleen een PDF op basis van al bestaande rapportdata. Die haalt geen marktdata op en berekent geen indicatoren.

De huidige `trade-technical` en `trade-risk` flows gebruiken in de instructies vooral `WebSearch`. De AI moet daarna gevonden data interpreteren, aanvullen, scoren en als markdown rapport uitschrijven. Dat werkt als onderzoeksprototype, maar heeft nadelen:

- veel tokengebruik;
- afhankelijk van willekeurige webbronnen;
- geen harde audit trail per getal;
- risico op oude, geschatte of tegenstrijdige data;
- indicatorwaarden zijn niet reproduceerbaar;
- moeilijker te integreren met de lokale portefeuille-data.

## Bevinding: technical analysis kan grotendeels lokaal

Het voorbeeldrapport `TRADE-TECHNICAL-ALAB.md` bevat onder meer:

- current price;
- dagrange;
- 20/50/200 moving averages;
- golden cross;
- 52-week high/low;
- RSI;
- MACD;
- Stochastic;
- volume versus gemiddelde volume;
- Bollinger Bands;
- support/resistance;
- Fibonacci levels;
- relative strength versus SPY;
- technische score.

In de portefeuille-app 1.4 wordt `historical_data_correct` al als OHLCV geladen via `portefeuille_viewer/data/repository.py`. Beschikbare velden:

- `datum`
- `asset_rollup`
- `open`
- `high`
- `low`
- `close`
- `volume`

Optioneel worden ook deze kolommen meegenomen als ze bestaan:

- `historical_volatility`
- `implied_volatility`

Daarmee kunnen de meeste technische indicatoren volledig lokaal worden berekend:

- SMA/EMA 20/50/100/200;
- RSI 14;
- MACD 12/26/9;
- Stochastic;
- Bollinger Bands;
- ATR;
- OBV;
- volume-spikes;
- 52-week high/low;
- drawdown;
- trend-classificatie;
- support/resistance via swing highs/lows;
- Fibonacci vanaf recente swing high/low;
- relative strength versus lokaal beschikbare indexen of ETF's.

Er bestaat al een begin van deze logica in `portefeuille_viewer/services/asset_indicator_service.py`. Die service berekent nu al onder meer SMA's, EMA's, 52-week high/low, volume-score, realized volatility, ATR en direction-score. Voor een volledige technical replacement ontbreken vooral RSI, MACD, Bollinger Bands, Stochastic, OBV, support/resistance, Fibonacci en benchmark-relative-strength scoring.

## Bevinding: risk analysis is ook grotendeels lokaal te bouwen

Het voorbeeldrapport `TRADE-RISK-ALAB.md` bevat onder meer:

- beta;
- realized volatility;
- ATR;
- max drawdown;
- drawdown scenarios;
- correlation matrix;
- liquidity metrics;
- position sizing;
- VaR/CVaR;
- risk/reward;
- risk score.

De kwantitatieve kern hiervan kan goed uit lokale data worden berekend:

- beta versus SPY/AEX/QQQ/sector ETF;
- correlatie met indexen en sector ETF's;
- 20/30/60/252-daagse realized volatility;
- ATR;
- average daily move;
- max drawdown;
- recovery time na drawdowns;
- VaR en CVaR;
- stress scenarios op basis van beta;
- position sizing;
- stop-loss op basis van ATR;
- liquidity op basis van volume en dollar volume;
- 52-week range;
- risk/reward op basis van berekende support/resistance.

Niet alles zit al lokaal. Voor een volledig risk-rapport blijven externe bronnen nodig voor:

- market cap;
- shares outstanding / float;
- short interest;
- days to cover;
- insider transactions;
- institutional ownership;
- debt/equity;
- cash position;
- free cash flow;
- revenue concentration;
- customer concentration;
- litigation/regulatory risk;
- earnings date;
- options IV rank en options liquidity.

Sommige van deze velden kunnen mogelijk via IBKR fundamental data of Wall Street Horizon worden opgehaald, afhankelijk van subscriptions. Andere velden vragen waarschijnlijk om scraping of een externe API.

## Analyst target clusters

Met analyst target clusters wordt bedoeld: prijszones waar meerdere analistenkoersdoelen bij elkaar liggen. Bijvoorbeeld meerdere targets rond 200-210, met een gemiddelde target van 205 en een hoogste target van 260. Dit kan als zachte weerstand of marktpsychologisch niveau worden gezien, maar het is geen zuivere technische indicator.

IBKR/TWS kan analyst-rating velden tonen, zoals average price target, average rating, number of analyst ratings en number of targets. Volgens IBKR documentatie is dit afhankelijk van Thomson Reuters data/subscription. Dit moet apart getest worden voordat het als betrouwbare bron in de tool wordt gebruikt.

Advies: analyst targets niet opnemen in de harde technische score. Alleen als losse context tonen, met bron en timestamp.

## Earnings en catalysts

Earnings-event context is geen technische indicator, maar wel belangrijk voor risico en volatiliteit. Mogelijke bronnen:

- IBKR Wall Street Horizon API, indien beschikbaar via subscription;
- scraping/API van earnings calendars;
- handmatige of periodieke externe import;
- AI/websearch als fallback.

Advies: earnings en catalysts horen in een aparte event/catalyst laag, niet in de pure technical engine. De technical/risk engines kunnen wel een event-risk flag krijgen als er een earnings event binnen bijvoorbeeld 14 dagen valt.

## Sector outperformance

Omdat de portefeuille-app ook indexen kan opslaan, kan sector outperformance lokaal worden berekend. Daarnaast kunnen sector ETF's als benchmark dienen, bijvoorbeeld:

- `XLB` Materials
- `XLC` Communication Services
- `XLE` Energy
- `XLF` Financials
- `XLI` Industrials
- `XLK` Technology
- `XLP` Consumer Staples
- `XLRE` Real Estate
- `XLU` Utilities
- `XLV` Health Care
- `XLY` Consumer Discretionary

Voor Europa kunnen eigen indexen of sector proxies worden gebruikt. Hiervoor moet per asset een benchmark of sector-ETF mapping beschikbaar zijn in `asset_rollup_data` of een aparte mappingtabel.

## Intraday data

`historical_data_correct` is vooral geschikt voor dagdata. Voor actuele intraday prijs kan de bestaande tickerdata uit de app worden gebruikt. Advies:

- intraday ticks niet direct in `historical_data_correct` schrijven;
- aparte tabel gebruiken, bijvoorbeeld `intraday_price_ticks`;
- velden: `asset_rollup`, `timestamp`, `last`, `bid`, `ask`, `volume`, `source`, `market_data_type`;
- einde dag eventueel aggregeren naar daily OHLCV;
- reports kunnen kiezen tussen daily close t/m gisteren of live laatste koers.

## Nieuws en catalyst context

Nieuws/catalyst context is het minst geschikt voor pure Python. Een goede hybride aanpak:

1. Python haalt nieuws op via RSS/API/scraping.
2. Python dedupt en filtert op ticker, datum en bron.
3. Python bewaart bron, titel, url, timestamp en korte snippet.
4. AI krijgt alleen de relevante headlines/snippets.
5. AI maakt een compacte samenvatting en classificatie.

De AI moet dus niet het hele web afzoeken en indicatorwaarden raden. De AI moet een beperkte set bronregels interpreteren.

## Gewenste doelarchitectuur

Splits de toekomstige analyzer in lagen.

### 1. Data layer

Bronnen:

- `historical_data_correct` voor OHLCV;
- `asset_rollup_data` voor asset metadata;
- index/ETF history uit dezelfde historical tabel;
- optie-parquet of optie-snapshot data voor IV/options liquidity;
- eventuele externe tabellen voor fundamentals/events/news.

Output:

- genormaliseerde pandas/polars DataFrames;
- per asset voldoende historie en datakwaliteit-checks.

### 2. Python technical engine

Nieuwe module, bijvoorbeeld:

- `stock_analyzer_framework/python_engines/technical_engine.py`

Of binnen portefeuille-app:

- `portefeuille_viewer/services/technical_analysis_service.py`

Taken:

- indicatoren berekenen;
- technische score berekenen;
- support/resistance bepalen;
- relative strength berekenen;
- compact technical snapshot opleveren.

Voorbeeld output:

```json
{
  "asset_rollup": "ALAB",
  "as_of": "2026-05-08",
  "price": 195.4,
  "technical_score": 72,
  "trend_score": 16,
  "momentum_score": 14,
  "volume_score": 11,
  "pattern_score": 12,
  "relative_strength_score": 15,
  "rsi_14": 69.1,
  "macd_signal": "bullish",
  "atr_pct": 6.3,
  "trend": "uptrend",
  "support": [187.0, 175.0, 166.0],
  "resistance": [214.0, 229.0, 262.9],
  "data_quality": "ok"
}
```

### 3. Python risk engine

Nieuwe module, bijvoorbeeld:

- `stock_analyzer_framework/python_engines/risk_engine.py`

Of binnen portefeuille-app:

- `portefeuille_viewer/services/risk_analysis_service.py`

Taken:

- beta en correlaties berekenen;
- drawdowns en recovery berekenen;
- realized volatility, ATR en VaR/CVaR berekenen;
- liquidity score op volume/dollar volume berekenen;
- position sizing tabellen maken;
- risk score opbouwen.

Voorbeeld componenten:

- `volatility_score`
- `drawdown_score`
- `liquidity_score`
- `correlation_score`
- `event_risk_score`
- `financial_health_score`
- `composite_risk_score`

### 4. Context/fundamental/event layer

Losse modules voor niet-OHLCV data:

- earnings calendar;
- dividend/event calendar;
- market cap / float / short interest;
- analyst targets;
- insider/institutional data;
- news/catalyst feed.

Elke externe datapunt moet een bron en timestamp hebben.

### 5. Report generator

Een markdown generator kan de Python snapshots omzetten naar rapporten:

- `TRADE-TECHNICAL-<ASSET>.md`
- `TRADE-RISK-<ASSET>.md`
- later eventueel PDF via bestaande `generate_trade_pdf.py`.

Belangrijk: het markdown rapport moet traceerbaar zijn naar Python-output. AI mag tekst verfijnen, maar niet zelf cijfers verzinnen.

## Rol van AI in de toekomstige opzet

AI blijft nuttig voor:

- narratieve samenvatting;
- bull/bear scenario's;
- catalyst/news duiding;
- uitleg van conflicterende signalen;
- leesbaar maken van rapporten.

AI moet niet meer gebruikt worden voor:

- RSI/MACD/EMA berekenen;
- beta/correlatie/volatiliteit berekenen;
- VaR/position sizing berekenen;
- drawdown meten;
- volume-score bepalen;
- indicatorwaarden uit webpagina's overtypen.

## Faseplan

### Fase 1 - Audit en data contract

- Vastleggen welke tabellen als bron dienen.
- Controleren of `historical_data_correct` voor alle assets OHLCV en volume bevat.
- Benchmark mapping ontwerpen: per asset default benchmark/index/ETF.
- Vastleggen minimale datakwaliteit: bijvoorbeeld minimaal 252 handelsdagen voor volledige score, minimaal 60 voor beperkte score.

### Fase 2 - Technical engine MVP

- Pure Python/Polars module bouwen.
- Input: asset + OHLCV + benchmark OHLCV.
- Output: technical snapshot dict/DataFrame.
- Indicatoren: SMA/EMA, RSI, MACD, Bollinger, ATR, 52w high/low, volume ratios, relative strength.
- Scoremodel afleiden uit huidige `trade-technical` skill.
- CLI/devtool maken voor 1 asset, bijvoorbeeld `python run_technical_snapshot.py --asset ALAB`.

### Fase 3 - Risk engine MVP

- Pure Python/Polars module bouwen.
- Input: asset + OHLCV + benchmark OHLCV.
- Output: risk snapshot dict/DataFrame.
- Metrics: beta, correlation, realized volatility, ATR, drawdown, VaR/CVaR, liquidity, position sizing.
- Scoremodel afleiden uit huidige `trade-risk` skill.
- CLI/devtool maken voor 1 asset.

### Fase 4 - Persist snapshots

- Resultaten opslaan in Access of Parquet.
- Mogelijke tabellen:
  - `asset_technical_snapshot_current`
  - `asset_technical_snapshot_history`
  - `asset_risk_snapshot_current`
  - `asset_risk_snapshot_history`
- Current tabel voor snelle UI.
- History tabel voor trend in scores.

### Fase 5 - Rapport generator

- Markdown generator bouwen die zonder AI een volledig rapport kan maken.
- AI optioneel toevoegen als "narrative enhancer".
- Rapport altijd voorzien van:
  - data timestamp;
  - bronvermelding per externe datapunt;
  - datakwaliteit;
  - ontbrekende data.

### Fase 6 - Integratie met portefeuille-app

- Tab of dialoog toevoegen voor technical/risk per asset.
- Later batch-run over alle assets.
- Mogelijk hergebruik in Single Asset Analyse, Asset Indicator en optie/theta scanner.

## Open ontwerpkeuzes

- Moeten engines in `stock_analyzer_framework` wonen of direct in `portefeuille_viewer_1.4`?
- Worden snapshots in Access opgeslagen of in Parquet?
- Welke benchmark mapping wordt gebruikt voor US/EU/NL assets?
- Welke externe bron wordt gekozen voor fundamentals/events/news?
- Wordt AI alleen handmatig gestart of automatisch na Python snapshot?

## Voorlopige aanbeveling

Bouw eerst een Python-first `technical_analysis_service` en `risk_analysis_service` binnen `portefeuille_viewer_1.4`, omdat daar de database, settings en snapshots al bestaan. Gebruik `stock_analyzer_framework` daarna als rapport-/skill-laag die deze lokale snapshots consumeert. Zo blijven de berekeningen dicht bij de brondata en blijft AI beperkt tot interpretatie en rapportage.
