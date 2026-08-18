"""
Costruzione della condizione e del suo stato corrente.

La specifica e' quella validata nello studio e NON va toccata senza rifare l'analisi:

    EL2  = YoY log(margin debt) - YoY log(SPX)          (unica serie risultata stazionaria)
    rank = percentile rolling di EL2 su 120 mesi, burn-in 24
    CONDIZIONE = rank > 0.75  E  momentum SPX a 12 mesi > 0
    COPERTURA  = 12 mesi dall'accensione, indipendentemente dal fatto che la condizione duri

L'ultimo punto e' quello che si sbaglia in modo naturale. La condizione richiede momentum
positivo, quindi si spegne appena il ribasso comincia: restare coperti solo finche' e' attiva
significa rientrare long dentro il crollo. Il segnale parla dei 12 mesi SUCCESSIVI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import ME, month_end

# --- Parametri della specifica validata ---
RANK_WINDOW = 120     # finestra della rank percentile, in mesi
RANK_MIN = 24         # burn-in: 24 copre il picco del marzo 2000, 36 lo escluderebbe
THRESHOLD = 0.75      # quartile superiore
LATCH_MONTHS = 12     # orizzonte su cui il segnale e' stato definito e validato
LAG_MONTHS = 1        # FINRA pubblica nella terza settimana del mese successivo


def build(finra: pd.DataFrame, spx_daily: pd.Series) -> pd.DataFrame:
    """
    Costruisce il frame decisionale.

    Distinzione da tenere ferma: le feature si calcolano accoppiando margin debt e SPX
    dello STESSO mese di riferimento; il lag di pubblicazione si applica DOPO, spostando
    in blocco la serie dalla data di riferimento alla data in cui il dato e' pubblico.
    """
    spx_m = spx_daily.resample(ME).last()
    spx_m.index = month_end(spx_m.index)

    # Griglia mensile senza buchi: tutto il calcolo shifta di una riga, e un mese mancante
    # trasformerebbe silenziosamente il lag di pubblicazione in due mesi.
    grid = month_end(pd.date_range(finra.index.min(), finra.index.max(), freq=ME))
    ref = finra.reindex(grid)
    ref.index.name = "ref_month"
    ref["spx"] = spx_m.reindex(ref.index)

    ref["yoy_md"] = np.log(ref["md_debit"]).diff(12)
    ref["yoy_spx"] = np.log(ref["spx"]).diff(12)
    ref["el2"] = ref["yoy_md"] - ref["yoy_spx"]
    ref["rank"] = ref["el2"].rolling(RANK_WINDOW, min_periods=RANK_MIN).rank(pct=True)

    # Indice esteso di LAG mesi prima dello shift: senza, l'osservazione piu' recente —
    # quella operativamente utile — non trova una riga su cui atterrare e sparisce.
    ext = month_end(
        pd.date_range(ref.index.min(), ref.index.max() + pd.DateOffset(months=LAG_MONTHS), freq=ME)
    )

    d = pd.DataFrame(index=spx_m.index)
    d["spx"] = spx_m
    d["ref_month"] = pd.Series(ext, index=ext).shift(LAG_MONTHS).reindex(d.index)
    for col in ("md_debit", "el2", "rank", "yoy_md", "yoy_spx"):
        d[col] = ref[col].reindex(ext).shift(LAG_MONTHS).reindex(d.index)

    lspx = np.log(d["spx"])
    d["mom_12m"] = lspx.diff(12)
    d["dd_from_ath"] = d["spx"] / d["spx"].cummax() - 1.0

    d["condizione"] = ((d["rank"] > THRESHOLD) & (d["mom_12m"] > 0)).fillna(False)
    d["copertura"] = _latch(d["condizione"], LATCH_MONTHS)
    return d.loc[d["ref_month"].first_valid_index():]


def _latch(cond: pd.Series, k: int) -> pd.Series:
    """True per k mesi da ogni accensione; un'accensione successiva fa ripartire il conto."""
    out = np.zeros(len(cond), dtype=bool)
    for i in np.flatnonzero(cond.values):
        out[i: i + k] = True
    return pd.Series(out, index=cond.index)


def stato_corrente(d: pd.DataFrame) -> dict:
    """Stato alla data piu' recente disponibile, con la scadenza della copertura."""
    ultima = d.index[-1]
    riga = d.loc[ultima]
    accensioni = d.index[d["condizione"] & ~d["condizione"].shift(fill_value=False)]
    ultima_accensione = accensioni[-1] if len(accensioni) else None

    scadenza = None
    if ultima_accensione is not None:
        # La copertura decorre dall'ULTIMA accensione, non dalla prima del grappolo.
        ultimo_mese_attivo = d.index[d["condizione"]][-1]
        scadenza = month_end(
            pd.DatetimeIndex([ultimo_mese_attivo + pd.DateOffset(months=LATCH_MONTHS - 1)])
        )[0]

    if bool(riga["condizione"]):
        stato = "ATTIVA"
    elif bool(riga["copertura"]):
        stato = "COPERTURA IN CORSO"
    else:
        stato = "INATTIVA"

    ref_m = riga["ref_month"]
    prossimo = (
        month_end(pd.DatetimeIndex([ref_m + pd.DateOffset(months=1)]))[0]
        if pd.notna(ref_m) else None
    )
    return dict(
        stato=stato,
        data=ultima,
        rank=riga["rank"],
        el2=riga["el2"],
        yoy_md=riga["yoy_md"],
        yoy_spx=riga["yoy_spx"],
        mom_12m=riga["mom_12m"],
        dd_from_ath=riga["dd_from_ath"],
        spx=riga["spx"],
        md_debit=riga["md_debit"],
        ref_month=ref_m,
        prossimo_ref_month=prossimo,
        ultima_accensione=ultima_accensione,
        scadenza_copertura=scadenza if stato != "INATTIVA" else None,
    )


def attivazioni(d: pd.DataFrame, spx_daily: pd.Series) -> pd.DataFrame:
    """
    Storico delle accensioni con l'esito misurato AL MESE DI ACCENSIONE.

    Scelta deliberata: misurare l'esito sul mese migliore del grappolo darebbe numeri
    piu' belli e privi di significato operativo. Quello che conta e' cosa sarebbe successo
    a chi avesse agito il giorno dell'accensione.
    """
    cond = d["condizione"]
    inizi = d.index[cond & ~cond.shift(fill_value=False)]
    fine_dati = spx_daily.index.max()

    righe = []
    for t0 in inizi:
        base = spx_daily.asof(t0)
        fine = t0 + pd.DateOffset(months=LATCH_MONTHS)
        finestra = spx_daily.loc[(spx_daily.index > t0) & (spx_daily.index <= fine)]
        completo = fine <= fine_dati

        min_12m = finestra.min() / base - 1.0 if len(finestra) and np.isfinite(base) else np.nan
        ret_12m = (
            spx_daily.asof(fine) / base - 1.0 if completo and np.isfinite(base) else np.nan
        )
        if not completo:
            esito = "in corso"
        elif min_12m <= -0.20:
            esito = "drawdown oltre 20%"
        elif min_12m <= -0.10:
            esito = "drawdown 10-20%"
        else:
            esito = "nessun drawdown rilevante"

        righe.append(
            dict(
                accensione=t0,
                fine_copertura=month_end(pd.DatetimeIndex([fine]))[0],
                rank=d.loc[t0, "rank"],
                spx=base,
                min_12m=min_12m,
                ret_12m=ret_12m,
                esito=esito,
            )
        )
    return pd.DataFrame(righe)


def statistiche_storiche(d: pd.DataFrame, spx_daily: pd.Series) -> dict:
    """Distribuzione dei rendimenti forward a 12 mesi, condizionata e non."""
    fine_dati = spx_daily.index.max()
    ret, mini = {}, {}
    for t in d.index:
        fine = t + pd.DateOffset(months=12)
        if fine > fine_dati:
            ret[t], mini[t] = np.nan, np.nan
            continue
        base = spx_daily.asof(t)
        fin = spx_daily.loc[(spx_daily.index > t) & (spx_daily.index <= fine)]
        ret[t] = spx_daily.asof(fine) / base - 1.0 if np.isfinite(base) else np.nan
        mini[t] = fin.min() / base - 1.0 if len(fin) and np.isfinite(base) else np.nan

    r = pd.Series(ret)
    m = pd.Series(mini)
    ok = r.notna()
    on = d["condizione"] & ok
    off = (~d["condizione"]) & ok
    return dict(
        n_on=int(on.sum()),
        n_off=int(off.sum()),
        ret_on=r[on].mean(),
        ret_off=r[off].mean(),
        pos_on=(r[on] > 0).mean(),
        pos_off=(r[off] > 0).mean(),
        min_on=m[on].median(),
        min_off=m[off].median(),
        serie_ret=r,
        serie_min=m,
    )
