# Margin Debt Monitor

Dashboard Streamlit che monitora una singola condizione di rischio derivata dal margin debt
FINRA: **la leva a margine sta crescendo molto più del mercato mentre il mercato sale?**

La condizione si aggiorna una volta al mese, quando FINRA pubblica le Margin Statistics
(terza settimana del mese successivo a quello di riferimento).

## La specifica

```
EL2        = YoY log(margin debt) − YoY log(S&P 500)
percentile = rank rolling di EL2 su 120 mesi, burn-in 24
CONDIZIONE = percentile > 0,75  E  momentum S&P 500 a 12 mesi > 0
FINESTRA   = 12 mesi dall'accensione, anche se la condizione si spegne prima
```

L'ultimo punto è quello che si sbaglia in modo naturale: la condizione richiede momentum
positivo, quindi si spegne appena il ribasso comincia. Restare in allerta solo mentre è
attiva significa uscire dall'allerta proprio all'inizio del crollo.

Il dato FINRA viene usato con un mese di ritardo, sempre: a fine mese *t* la dashboard vede
solo il mese *t−1*. Nessuna eccezione, nessun look-ahead.

## Deploy su Streamlit Cloud

1. Crea un repository su GitHub e carica questi file mantenendo la struttura.
2. Vai su [share.streamlit.io](https://share.streamlit.io), collega il repo e indica
   `app.py` come entry point.
3. In *Settings → Secrets* aggiungi le chiavi che hai:

   ```toml
   EODHD_API_KEY = "la_tua_chiave"
   FRED_API_KEY  = "la_tua_chiave"
   ```

Entrambe sono facoltative ma consigliate.

- **`EODHD_API_KEY`** — diventa la fonte primaria dell'S&P 500 (`GSPC.INDX`). È l'unica
  fonte contrattualizzata delle quattro: Stooq e yfinance sono endpoint pubblici non
  garantiti e da IP condivisi come quelli di Streamlit Cloud capita che vengano limitati.
  Se il tuo piano EODHD non include gli indici la chiamata restituisce 403 e la dashboard
  passa automaticamente a Stooq, dichiarandolo nella barra laterale. In quel caso puoi
  cambiare `EODHD_TICKER` in `src/data.py`.
- **`FRED_API_KEY`** — serve solo alla sezione sullo spread high yield. Senza chiave la
  dashboard prova comunque l'endpoint CSV pubblico di FRED e, se non risponde, omette
  quella sezione.

Il margin debt arriva sempre direttamente da FINRA: non esiste alcuna alternativa, FINRA
dichiara esplicitamente che il dato non è disponibile via data feed.

La barra laterale mostra sempre **quale fonte è stata effettivamente usata**, così un
downgrade silenzioso non passa inosservato.

## Esecuzione in locale

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

## Snapshot di riserva (consigliato)

FINRA pubblica un solo file XLSX su un unico host, e capita che non risponda per ore. Per
non avere mai una dashboard vuota, committa uno snapshot in `data/`:

```python
finra[['md_debit', 'fc_cash', 'fc_margin']].to_csv('data/snapshot_finra.csv')
```

Il file va prodotto dal notebook di ricerca (`01_finra_margin_debt_dataset.ipynb`, variabile
`finra`) e aggiornato ogni tanto. Stessa cosa per l'S&P 500 in `data/snapshot_spx.csv`, con
una sola colonna di chiusure e l'indice di date.

Quando la fonte live non risponde, la dashboard usa lo snapshot e lo dichiara nella barra
laterale.

## Struttura

```
margin-debt-monitor/
├── app.py                  # layout e testi
├── requirements.txt
├── .streamlit/config.toml  # tema scuro
├── data/                   # snapshot di riserva (facoltativi)
└── src/
    ├── data.py             # fetch FINRA / S&P 500 / HY OAS, cache 6h, fallback
    ├── signal.py           # costruzione del segnale, stato corrente, storico accensioni
    └── charts.py           # grafici Plotly
```

## Limiti

L'evidenza a supporto della condizione poggia su **tre episodi indipendenti** (2000, 2007,
2021), non sui circa 350 mesi del campione, che sono fortemente autocorrelati. Test di
permutazione su formulazioni diverse danno p ≈ 0,07: mai sotto lo 0,05 su una singola
statistica pre-specificata, mai vicino all'irrilevanza. La valutazione è in-sample.

Il dato FINRA non ha vintage: l'XLSX incorpora revisioni retroattive, quindi anche gestendo
correttamente il ritardo di pubblicazione la storia è ricostruita su dati rivisti. Esiste un
break di perimetro a febbraio 2010 (FINRA Rule 4521) e FINRA stessa segnala una deriva di
misurazione dopo la FAQ dell'aprile 2021.

Il crollo del 2020 non è anticipabile da questo impianto e non lo è mai stato: massimo il
19 febbraio, minimo il 23 marzo. Con dato mensile e un mese di ritardo di pubblicazione non
esiste configurazione che possa segnalarlo.

Materiale di ricerca a fini informativi. Non è consulenza finanziaria.
