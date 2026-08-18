"""
Margin Debt Monitor — Kriterion Quant

Dashboard di monitoraggio di una singola condizione di rischio, derivata dallo studio sul
margin debt FINRA. Il criterio di progettazione e' che la risposta stia nella prima
schermata: tutto il resto e' contesto per chi vuole verificarla.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src import charts, signal
from src.data import ME, load_finra, load_hy_oas, load_spx

st.set_page_config(page_title="Margin Debt Monitor | Kriterion Quant",
                   page_icon="📉", layout="wide", initial_sidebar_state="expanded")

# I nomi dei mesi vanno scritti a mano: il locale del server e' inglese e non e'
# configurabile su Streamlit Cloud.
MESI = {1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
        7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre",
        12: "dicembre"}


def mese_anno(ts) -> str:
    return f"{MESI[ts.month]} {ts.year}"


def data_lunga(ts) -> str:
    return f"{ts.day} {MESI[ts.month]} {ts.year}"

BADGE = {
    "ATTIVA": ("#F44336", "CONDIZIONE ATTIVA",
               "La leva in eccesso e' nel quartile superiore mentre il mercato sale."),
    "COPERTURA IN CORSO": ("#FF9800", "FINESTRA DI 12 MESI ANCORA APERTA",
                           "La condizione si e' spenta, ma la finestra di rischio "
                           "aperta dall'ultima accensione non e' scaduta."),
    "INATTIVA": ("#4CAF50", "CONDIZIONE INATTIVA",
                 "Nessuna accensione nei 12 mesi precedenti."),
}

# ----------------------------------------------------------------------------
# Caricamento dati
# ----------------------------------------------------------------------------
with st.spinner("Caricamento serie storiche..."):
    try:
        finra, fonte_finra = load_finra()
        spx_daily, fonte_spx = load_spx()
    except Exception as e:
        st.error(f"Impossibile caricare i dati: {e}")
        st.info("FINRA pubblica un solo file XLSX e ogni tanto non risponde. "
                "Riprova fra qualche minuto oppure ricarica lo snapshot nel repo.")
        st.stop()

    d = signal.build(finra, spx_daily)
    stato = signal.stato_corrente(d)
    att = signal.attivazioni(d, spx_daily)
    stats = signal.statistiche_storiche(d, spx_daily)

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Specifica")
    st.markdown(
        f"""
**Segnale**
`YoY log(margin debt) − YoY log(SPX)`

**Stato acceso quando**
- percentile su {signal.RANK_WINDOW} mesi **> {signal.THRESHOLD:.0%}**
- momentum SPX 12 mesi **> 0**

**Finestra di rischio**
{signal.LATCH_MONTHS} mesi dall'accensione

**Ritardo di pubblicazione**
{signal.LAG_MONTHS} mese (FINRA pubblica nella terza settimana del mese successivo)
        """
    )
    st.divider()
    st.caption(f"Margin debt: {fonte_finra}")
    st.caption(f"S&P 500: {fonte_spx}")
    st.caption(f"Ultimo mese FINRA: {mese_anno(stato['ref_month'])}"
               if pd.notna(stato["ref_month"]) else "Ultimo mese FINRA: n/d")
    if stato["prossimo_ref_month"] is not None:
        pubb = stato["prossimo_ref_month"] + pd.DateOffset(months=1)
        st.caption(f"Prossimo dato ({mese_anno(stato['prossimo_ref_month'])}): "
                   f"atteso terza settimana di {mese_anno(pubb)}")
    st.divider()
    if st.button("Forza aggiornamento dati", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ----------------------------------------------------------------------------
# Riga 1 — la risposta
# ----------------------------------------------------------------------------
st.title("Margin Debt Monitor")
st.caption("Una sola condizione, monitorata mensilmente: la leva a margine sta crescendo "
           "molto piu' del mercato mentre il mercato sale?")

colore, titolo, spiega = BADGE[stato["stato"]]
riga_extra = ""
if stato["scadenza_copertura"] is not None:
    riga_extra = (f"<div style='font-size:15px;opacity:.9;margin-top:6px'>"
                  f"Finestra aperta fino a <b>{mese_anno(stato['scadenza_copertura'])}</b></div>")

st.markdown(
    f"""
<div style="background:{colore}1F;border-left:6px solid {colore};
            border-radius:8px;padding:18px 22px;margin:6px 0 18px 0">
  <div style="font-size:13px;letter-spacing:.13em;color:{colore};font-weight:700">
    STATO AL {data_lunga(stato['data']).upper()}
  </div>
  <div style="font-size:30px;font-weight:800;line-height:1.25;margin-top:2px">{titolo}</div>
  <div style="font-size:15px;opacity:.9;margin-top:6px">{spiega}</div>
  {riga_extra}
</div>
""",
    unsafe_allow_html=True,
)

c = st.columns(5)
c[0].metric("Percentile leva in eccesso", f"{stato['rank']:.0%}" if pd.notna(stato["rank"]) else "n/d",
            f"soglia {signal.THRESHOLD:.0%}", delta_color="off")
c[1].metric("Margin debt, var. annua",
            f"{np.expm1(stato['yoy_md']):+.1%}" if pd.notna(stato["yoy_md"]) else "n/d")
c[2].metric("S&P 500, var. annua",
            f"{np.expm1(stato['yoy_spx']):+.1%}" if pd.notna(stato["yoy_spx"]) else "n/d")
c[3].metric("Margin debt", f"{stato['md_debit']/1000:,.0f} mld $"
            if pd.notna(stato["md_debit"]) else "n/d",
            f"dato di {mese_anno(stato['ref_month'])}"
            if pd.notna(stato["ref_month"]) else "",
            delta_color="off")
c[4].metric("S&P 500 dal massimo", f"{stato['dd_from_ath']:.1%}"
            if pd.notna(stato["dd_from_ath"]) else "n/d")

# ----------------------------------------------------------------------------
# Riga 2 — cosa vuol dire, in numeri
# ----------------------------------------------------------------------------
st.subheader("Cosa cambia quando la condizione e' attiva")
st.markdown(
    "Distribuzione dei rendimenti dell'S&P 500 nei dodici mesi successivi, calcolata su "
    f"tutto lo storico dal {d.index.min():%Y} a oggi. Sono i numeri che danno significato "
    "al riquadro qui sopra."
)
k = st.columns(4)
k[0].metric("Rendimento medio a 12 mesi — attiva", f"{stats['ret_on']:+.1%}",
            f"{stats['n_on']} mesi", delta_color="off")
k[1].metric("Rendimento medio a 12 mesi — spenta", f"{stats['ret_off']:+.1%}",
            f"{stats['n_off']} mesi", delta_color="off")
k[2].metric("Anni positivi — attiva", f"{stats['pos_on']:.0%}")
k[3].metric("Anni positivi — spenta", f"{stats['pos_off']:.0%}")

st.plotly_chart(charts.grafico_distribuzione(stats["serie_ret"], d["condizione"]),
                use_container_width=True)

# ----------------------------------------------------------------------------
# Riga 3 — la storia
# ----------------------------------------------------------------------------
st.subheader("Storico")
t1, t2, t3 = st.tabs(["Segnale e mercato", "Le due componenti", "Accensioni passate"])

with t1:
    st.plotly_chart(charts.grafico_principale(d, signal.THRESHOLD), use_container_width=True)

with t2:
    st.markdown("Il segnale e' la differenza fra le due linee: conta di quanto la leva "
                "cresce **piu'** del mercato, non quanto cresce in assoluto.")
    st.plotly_chart(charts.grafico_componenti(d), use_container_width=True)

with t3:
    st.markdown("Esito misurato **al mese di accensione**, non sul mese migliore del "
                "grappolo: e' cosa sarebbe successo a chi avesse agito quel giorno.")
    if att.empty:
        st.info("Nessuna accensione nello storico disponibile.")
    else:
        # I formattatori di st.column_config sono printf: non riscalano da decimale a
        # percentuale, quindi la conversione va fatta qui.
        vis = att.copy()
        vis["accensione"] = vis["accensione"].map(mese_anno)
        vis["fine_copertura"] = vis["fine_copertura"].map(mese_anno)
        for col in ("rank", "min_12m", "ret_12m"):
            vis[col] = vis[col] * 100.0
        st.dataframe(
            vis.rename(columns={
                "accensione": "Accensione", "fine_copertura": "Fine finestra",
                "rank": "Percentile", "spx": "S&P 500", "min_12m": "Minimo a 12m",
                "ret_12m": "Rendimento a 12m", "esito": "Esito"}),
            use_container_width=True, hide_index=True,
            column_config={
                "Percentile": st.column_config.NumberColumn(format="%.0f%%"),
                "S&P 500": st.column_config.NumberColumn(format="%.0f"),
                "Minimo a 12m": st.column_config.NumberColumn(format="%.1f%%"),
                "Rendimento a 12m": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption("Percentuali gia' espresse in punti: -25.0 significa -25%.")

# ----------------------------------------------------------------------------
# Riga 4 — contesto credito (facoltativo)
# ----------------------------------------------------------------------------
hy = load_hy_oas()
if hy is not None and len(hy) > 60:
    hy_m = hy.resample(ME).last().dropna()
    z = ((hy_m - hy_m.expanding(min_periods=60).mean())
         / hy_m.expanding(min_periods=60).std()).dropna()
    st.subheader("Contesto: stress creditizio")
    cc = st.columns(3)
    cc[0].metric("HY OAS", f"{hy.iloc[-1]:.2f}%", f"al {data_lunga(hy.index[-1])}",
                 delta_color="off")
    cc[1].metric("Z-score storico", f"{z.iloc[-1]:+.2f}" if len(z) else "n/d")
    cc[2].metric("Percentile a 5 anni",
                 f"{hy_m.tail(60).rank(pct=True).iloc[-1]:.0%}")
    st.caption("Lo spread high yield **non** fa parte del segnale: e' il principale "
               "indicatore concorrente e serve come contesto indipendente.")

# ----------------------------------------------------------------------------
# Riga 5 — i limiti, in chiaro
# ----------------------------------------------------------------------------
st.subheader("Cosa questa condizione dice, e cosa non dice")
a, b = st.columns(2)
with a:
    st.success(
        "**Dice**\n\n"
        "- Che il rischio di coda a dodici mesi e' elevato rispetto alla norma\n"
        "- Che la distribuzione dei rendimenti a un anno si sposta in modo netto\n"
        "- Che la condizione non e' replicabile con le sole variabili di prezzo: "
        "lo stato di prezzo da solo sta **sotto** la frequenza media di drawdown\n"
        "- Che ha preceduto tutti e tre gli episodi anticipabili del campione "
        "(2000, 2007, 2021)"
    )
with b:
    st.warning(
        "**Non dice**\n\n"
        "- Quando. Ha preceduto i massimi di otto e dieci mesi\n"
        "- Che ci sara' un drawdown: circa **due accensioni su tre** non sono seguite "
        "da un calo oltre il 20%\n"
        "- Niente sul rendimento del mese successivo: a breve termine il contenuto "
        "direzionale misurato e' nullo\n"
        "- Non e' una raccomandazione di investimento"
    )

with st.expander("Metodo, validazione e limiti statistici"):
    st.markdown(
        f"""
**Costruzione.** Il margin debt e' in larga parte un derivato meccanico del prezzo: sale
perche' sale il collaterale. Applicare oscillatori alla serie grezza produce segnali
coincidenti travestiti da anticipatori — sullo storico completo un RSI a 3 mesi sui livelli
sta sopra 50 nel 65% dei mesi, con mediana 69,6, quindi la soglia canonica di ipercomprato
non discrimina nulla. Il segnale usa quindi il **differenziale di crescita annua** fra
margin debt e indice, che risulta l'unica trasformazione stazionaria fra quelle testate
(ADF p = 0,0003).

**Perche' non il residuo di cointegrazione.** L'impostazione standard — regredire
log(margin debt) su log(SPX) e usare il residuo come "leva eccedente il collaterale" — non
ha fondamento su questi dati: il test di Engle-Granger non rifiuta in **nessuno** dei due
regimi (p = 0,92 prima del 2010, p = 0,62 dopo). Senza cointegrazione non esiste un
equilibrio a cui la serie torni.

**Nessun look-ahead.** FINRA pubblica nella terza settimana del mese successivo a quello di
riferimento: a fine mese *t* la dashboard usa esclusivamente il dato del mese *t−1*. La
distanza fra mese di riferimento e data di decisione e' verificata meccanicamente, non a vista.

**Finestra di {signal.LATCH_MONTHS} mesi, non "finche' e' attiva".** La condizione richiede
momentum positivo, quindi si spegne appena il ribasso comincia. Restare esposti solo mentre
e' accesa significa rientrare al 100% dentro il crollo. I {signal.LATCH_MONTHS} mesi
coincidono con l'orizzonte su cui il segnale era stato definito prima di ogni simulazione.

**Limiti, dichiarati.** L'evidenza poggia su **tre episodi indipendenti** — non su 350 mesi,
che sono fortemente autocorrelati. Test di permutazione circolare su formulazioni diverse:
p ≈ 0,07, mai sotto lo 0,05 su una singola statistica pre-specificata, mai vicino
all'irrilevanza. La valutazione e' in-sample: i parametri del segnale sono stati scelti sullo
stesso campione. Il dato FINRA non ha vintage — l'XLSX incorpora revisioni retroattive,
quindi anche gestendo il ritardo di pubblicazione la storia e' costruita su dati rivisti.
Break di perimetro a febbraio 2010 (FINRA Rule 4521, +12/18% di livello) e deriva di
misurazione dichiarata da FINRA dopo la FAQ dell'aprile 2021.

**Il 2020 non e' anticipabile** da questo impianto e non lo e' mai stato: massimo il 19
febbraio, minimo il 23 marzo. Con dato mensile e un mese di ritardo di pubblicazione non
esiste alcuna configurazione che possa segnalarlo.
        """
    )

st.divider()
st.caption(
    "Fonti: FINRA Margin Statistics (mensile, milioni di USD) · S&P 500 spot · "
    "ICE BofA US High Yield OAS via FRED. "
    "Materiale di ricerca a fini informativi, non consulenza finanziaria."
)
