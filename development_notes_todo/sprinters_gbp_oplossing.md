# Sprinters GBP: Correctie pence-naar-pounds via valuta uit asset_rollup_data

## Aanleiding

Bij analyse van de historische sprinter-data is een structurele fout ontdekt in de
waardering van sprinters op GBP-genoteerde assets (London Stock Exchange).

IBKR en de LSE leveren koersen voor UK-aandelen in **pence**, niet in pounds. De
koershistorie in `hist_data_per_asset_symbol` voor assets met `ib_currency = 'GBP'`
is daardoor opgeslagen in pence (bijv. BATS: 2787.5p in plaats van £27.875).

De sprinter state engine (`open_sprinters_state_v2.py`) gebruikt deze ruwe koers
rechtstreeks in de waarderingsformule, zonder correctie voor de pence/pounds
verhouding. De `sprinter_funding` in `sprinters_referentie_data` is wél in pounds
opgeslagen, waardoor de formule intern inconsistent is:

```
sprinter_resultaat = (aantal × close_pence) / ratio
                   - (aantal × funding_pounds) / ratio
                   + transactie_euro_totaal
```

Dit levert een open-positiewaarde die ~100× te groot is voor het koersdeel.

### Vastgestelde impact

- Asset: **BATS** (BATS_SP_CR38Z), ratio=10, open jan–feb 2022
- Anomalie: open sprinter waarde van **€8.4M** in januari 2022 (correct zou ~€84k zijn)
- Oorzaak: 2787.5 pence wordt behandeld als £2787.50; met ratio=10 resteert factor 10 te groot
- `gesloten_sprinters` (gerealiseerde P&L op basis van kasstromen) is **niet** aangetast
- BATS was de enige GBP-sprinter ooit in de portefeuille

### Huidig veld `multiplier_close_price`

Het veld `multiplier_close_price` in `transacties_bron_data` was oorspronkelijk bedoeld
voor exacte dit soort koerscorrecties. Het is echter verouderd (deprecated) ten gunste
van de `stock_splits` tabel voor aandelen en opties. Alleen de sprinter state engine
gebruikt dit veld nog. Een handmatige fix per transactierecord is onwenselijk.

---

## Oplossing (high level)

Breid `compute_sprinter_values` in `open_sprinters_state_v2.py` uit met een automatische
koerscorrectie op basis van de `ib_currency` uit `asset_rollup_data`:

- Als `ib_currency = 'GBP'` → pas een `price_multiplier = 0.01` toe (pence → pounds)
- Voor alle andere valuta → `price_multiplier = 1.0` (geen correctie)

De gecorrigeerde koers wordt dan:

```
asset_close_effective = asset_close_raw × multiplier_close_price × price_multiplier
```

De `multiplier_close_price` uit de transactie blijft behouden voor eventuele andere
toekomstige correcties; de valutacorrectie wordt er bovenop toegepast.

Het resultaat van de sprinter staat daarmee in de **home currency** van het asset
(GBP voor BATS), wat aansluit op de bestaande architectuur waarbij de app-laag
verantwoordelijk is voor de uiteindelijke omrekening naar EUR.

---

## Technische uitwerking

### 1. Laad `ib_currency` uit `asset_rollup_data`

Voeg een nieuwe laadstap toe in `open_sprinters_state_v2.py`, analoog aan
`load_sprinter_reference`:

```python
def load_asset_currency(conn) -> pl.DataFrame:
    sql = """
        SELECT asset_rollup, ib_currency
        FROM asset_rollup_data
        WHERE asset_rollup IS NOT NULL
    """
    return (
        pl.read_database(sql, conn)
        .with_columns(
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase(),
            pl.col("ib_currency").cast(pl.Utf8).str.strip_chars().str.to_uppercase().fill_null(""),
        )
        .unique(subset=["asset_rollup"])
    )
```

### 2. Geef `df_currency` mee aan `compute_sprinter_values`

Pas de signatuur aan:

```python
def compute_sprinter_values(
    df_daily: pl.DataFrame,
    df_ref: pl.DataFrame,
    df_currency: pl.DataFrame,
) -> pl.DataFrame:
```

### 3. Join en bereken `price_multiplier` in `compute_sprinter_values`

Na de bestaande join met `df_ref`, voeg toe:

```python
.join(df_currency, on="asset_rollup", how="left")
.with_columns(
    pl.col("ib_currency").fill_null(""),
)
.with_columns(
    pl.when(pl.col("ib_currency") == "GBP")
    .then(pl.lit(0.01))
    .otherwise(pl.lit(1.0))
    .alias("price_multiplier")
)
.with_columns(
    (
        pl.col("asset_close_raw")
        * pl.col("multiplier_close_price")
        * pl.col("price_multiplier")
    ).alias("asset_close_effective")
)
```

De rest van de formule (`sprinter_resultaat`, `sprinter_aantal_bezit`) blijft ongewijzigd.

### 4. Aanroep in `main()` uitbreiden

```python
df_currency = load_asset_currency(conn)
# ...
df_final = compute_sprinter_values(df_final, df_ref, df_currency)
```

### 5. Rebuild uitvoeren

Na de codewijziging:

```bash
python open_sprinters_state_v2.py --mode full
python per_dag_asset_result_v2.py --mode full
```

---

## Aandachtspunten

- **Alleen open posities** zijn aangetast. Gesloten sprinters (kasstromen) zijn correct.
- **Alleen historisch**: BATS was de enige GBP-sprinter en is al jaren gesloten.
  De fix corrigeert de historische open-positie-waardering in jan–feb 2022.
- **Toekomstbestendig**: mochten er ooit weer GBP-sprinters worden ingenomen,
  werkt de correctie automatisch zonder verdere datawijzigingen.
- **Andere valuta**: controleer of er assets zijn met `ib_currency` anders dan EUR/GBP
  in `asset_rollup_data`. Indien aanwezig en ooit gebruikt als sprinter, geldt
  dezelfde analyse (bijv. JPY, USD kunnen ook afwijkende notaties hebben).
- **`price_multiplier` kolom**: hoeft niet te worden opgeslagen in
  `per_dag_open_sprinters_opgerold_v2` — het is een tussenberekening. Alleen
  `asset_close_effective` (het eindresultaat) wordt weggeschreven.
