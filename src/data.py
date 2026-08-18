"""
Fetch e caching delle serie storiche.

Tre fonti, tutte con degradazione controllata: FINRA (obbligatoria), S&P 500 (obbligatoria),
HY OAS da FRED (facoltativa, solo contesto). Se una fonte primaria non risponde si ricade
sullo snapshot committato nel repo: la dashboard deve sempre mostrare qualcosa, anche
quando il server di FINRA e' giu' — e succede.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import streamlit as st

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = (10, 30)          # (connect, read) — mai attese indefinite in una dashboard

FINRA_URLS = [
    "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
    "https://www.finra.org/sites/default/files/margin-statistics.xlsx",
]
SNAPSHOT_FINRA = Path(__file__).resolve().parent.parent / "data" / "snapshot_finra.csv"
SNAPSHOT_SPX = Path(__file__).resolve().parent.parent / "data" / "snapshot_spx.csv"

# pandas >= 2.2 usa 'ME' per la frequenza di fine mese
try:
    from pandas.tseries.frequencies import to_offset

    to_offset("ME")
    ME = "ME"
except Exception:  # pragma: no cover
    ME = "M"


def month_end(x):
    """Normalizza date all'ultimo giorno del mese. Accetta Series o indici."""
    dt = pd.to_datetime(x)
    if isinstance(dt, pd.Series):
        return dt.dt.to_period("M").dt.to_timestamp("M")
    return pd.DatetimeIndex(dt).to_period("M").to_timestamp("M")


# ----------------------------------------------------------------------------
# FINRA margin statistics
# ----------------------------------------------------------------------------
def _parse_period(v):
    """Il campo Month/Year arriva come datetime, 'Jan-97', 'January 2026'..."""
    if pd.isna(v):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime, np.datetime64)):
        return pd.Timestamp(v)
    s = str(v).strip()
    for fmt in ("%b-%y", "%b-%Y", "%B-%y", "%B-%Y", "%b %Y", "%B %Y", "%Y-%m", "%m/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except Exception:
            continue
    return pd.to_datetime(s, errors="coerce")


def _to_num(s: pd.Series) -> pd.Series:
    cleaned = (
        s.astype(str)
        .str.replace(" ", "", regex=False)
        .str.replace(r"[^0-9eE\.\-]", "", regex=True)
        .replace({"": np.nan, "-": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_finra_xlsx(content: bytes) -> pd.DataFrame:
    """
    Parser difensivo: individua la riga di header cercando 'debit' e mappa le colonne
    per contenuto semantico, non per posizione, cosi' regge una riorganizzazione del file.
    L'ordine dei test conta: la colonna dei debiti contiene anch'essa 'Securities Margin
    Accounts', quindi 'debit' va testato per primo.
    """
    xls = pd.ExcelFile(io.BytesIO(content))
    frames = []
    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        if raw.empty:
            continue
        hdr = None
        for i in range(min(20, len(raw))):
            if raw.iloc[i].astype(str).str.lower().str.contains("debit", na=False).any():
                hdr = i
                break
        if hdr is None:
            continue
        body = raw.iloc[hdr + 1:].copy()
        body.columns = raw.iloc[hdr].astype(str).str.strip()

        ren, period_col = {}, body.columns[0]
        for c in body.columns:
            lc = str(c).lower()
            if "debit" in lc:
                ren[c] = "md_debit"
            elif "free credit" in lc and "cash" in lc:
                ren[c] = "fc_cash"
            elif "free credit" in lc:
                ren[c] = "fc_margin"
        keep = [period_col] + list(ren.keys())
        sub = body.loc[:, keep].copy()
        sub.columns = ["period_raw"] + [ren[c] for c in keep[1:]]
        frames.append(sub)

    if not frames:
        raise ValueError("Nessun foglio riconoscibile nell'XLSX FINRA")

    df = pd.concat(frames, ignore_index=True)
    df["period"] = df["period_raw"].apply(_parse_period)
    for c in ("md_debit", "fc_cash", "fc_margin"):
        if c not in df.columns:
            df[c] = np.nan
        df[c] = _to_num(df[c])

    df = df.dropna(subset=["period"])
    df = df[df["md_debit"].notna()].copy()
    df["period"] = month_end(df["period"])
    df = (
        df.drop(columns=["period_raw"])
        .drop_duplicates(subset=["period"], keep="first")
        .sort_values("period")
        .set_index("period")
    )
    df.index.name = "ref_month"
    df["fc_total"] = df[["fc_cash", "fc_margin"]].sum(axis=1, min_count=1)
    df["net_credit"] = df["fc_total"] - df["md_debit"]
    return df[["md_debit", "fc_cash", "fc_margin", "fc_total", "net_credit"]]


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_finra() -> tuple[pd.DataFrame, str]:
    """Ritorna (dataframe, etichetta_fonte). FINRA aggiorna una volta al mese: cache 6h."""
    for url in FINRA_URLS:
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            if len(r.content) < 5000:
                raise ValueError("payload sospetto")
            return parse_finra_xlsx(r.content), "FINRA (live)"
        except Exception:
            continue
    if SNAPSHOT_FINRA.exists():
        df = pd.read_csv(SNAPSHOT_FINRA, index_col=0, parse_dates=True)
        df.index = month_end(df.index)
        df.index.name = "ref_month"
        return df, "snapshot locale (FINRA non raggiungibile)"
    raise RuntimeError("FINRA non raggiungibile e nessuno snapshot disponibile")


# ----------------------------------------------------------------------------
# S&P 500
# ----------------------------------------------------------------------------
EODHD_TICKER = "GSPC.INDX"      # S&P 500 spot su EODHD; i piani senza indici danno 403


def _secret(nome: str) -> str | None:
    """Legge un secret di Streamlit, con fallback su variabile d'ambiente."""
    try:
        v = st.secrets.get(nome)
        if v:
            return str(v)
    except Exception:
        pass
    import os

    return os.environ.get(nome)


def _spx_eodhd(key: str) -> pd.Series:
    """S&P 500 da EODHD. 'from' e' parola riservata in Python: va passato via dizionario."""
    r = requests.get(
        f"https://eodhd.com/api/eod/{EODHD_TICKER}",
        params={"from": "1990-01-01", "period": "d", "fmt": "json", "api_token": key},
        headers=UA,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or not payload:
        raise ValueError("risposta EODHD inattesa (piano senza indici?)")
    df = pd.DataFrame(payload)
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"])).sort_index()
    return s.dropna().astype(float)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_spx() -> tuple[pd.Series, str]:
    """
    Chiusure daily dell'S&P 500: EODHD -> Stooq -> yfinance -> snapshot.

    EODHD per primo quando la chiave c'e': e' l'unica fonte contrattualizzata delle quattro.
    Stooq e yfinance sono endpoint pubblici non garantiti e da IP condivisi come quelli di
    Streamlit Cloud capita che vengano limitati.
    """
    key = _secret("EODHD_API_KEY")
    if key:
        try:
            s = _spx_eodhd(key)
            if len(s) > 1000:
                return s, f"EODHD ({EODHD_TICKER})"
        except Exception:
            pass
    try:
        r = requests.get("https://stooq.com/q/d/l/?s=%5Espx&i=d", headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if "Close" in df.columns and len(df) > 1000:
            s = pd.Series(df["Close"].values, index=pd.to_datetime(df["Date"])).sort_index()
            return s.dropna(), "Stooq"
    except Exception:
        pass
    try:
        import yfinance as yf

        df = yf.download("^GSPC", start="1990-01-01", progress=False, auto_adjust=False)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        if len(close) > 1000:
            return close.dropna(), "yfinance"
    except Exception:
        pass
    if SNAPSHOT_SPX.exists():
        df = pd.read_csv(SNAPSHOT_SPX, index_col=0, parse_dates=True)
        return df.iloc[:, 0].dropna(), "snapshot locale"
    raise RuntimeError("Nessuna fonte disponibile per l'S&P 500")


# ----------------------------------------------------------------------------
# HY OAS — solo contesto, mai parte del segnale
# ----------------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_hy_oas() -> pd.Series | None:
    """Spread high yield ICE BofA. Facoltativo: se non arriva, la dashboard lo omette."""
    key = _secret("FRED_API_KEY")
    if key:
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params=dict(series_id="BAMLH0A0HYM2", api_key=key, file_type="json"),
                headers=UA,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            df = pd.DataFrame(r.json()["observations"])
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
            return df.dropna(subset=["date"]).set_index("date")["value"].dropna().sort_index()
        except Exception:
            pass
    try:
        r = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2",
            headers=UA,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"] + list(df.columns[2:])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(
            df["value"].astype(str).str.strip().replace(".", np.nan), errors="coerce"
        )
        return df.dropna(subset=["date"]).set_index("date")["value"].dropna().sort_index()
    except Exception:
        return None
