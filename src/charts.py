"""Grafici Plotly, tema scuro coerente con Kriterion Quant."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

COLORS = {
    "primary": "#2196F3",
    "secondary": "#FF9800",
    "positive": "#4CAF50",
    "negative": "#F44336",
    "neutral": "#9E9E9E",
    "background": "#1E1E2E",
    "surface": "#2A2A3E",
    "text": "#E0E0E0",
    "accent": "#AB47BC",
}


def layout(title: str = "", xaxis_title: str = "", yaxis_title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(size=15, color=COLORS["text"])),
        paper_bgcolor=COLORS["background"],
        plot_bgcolor=COLORS["surface"],
        font=dict(color=COLORS["text"], family="Inter, Arial, sans-serif"),
        xaxis=dict(title=xaxis_title, showgrid=True, gridcolor="#333355",
                   zeroline=False, color=COLORS["text"]),
        yaxis=dict(title=yaxis_title, showgrid=True, gridcolor="#333355",
                   zeroline=False, color=COLORS["text"]),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#444466", orientation="h",
                    yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        margin=dict(l=60, r=25, t=55, b=45),
    )


def _spans(mask: pd.Series) -> list[tuple]:
    """Estrae gli intervalli contigui in cui la maschera e' vera."""
    b = mask.fillna(False).to_numpy()
    idx = mask.index
    out, i = [], 0
    while i < len(b):
        if b[i]:
            j = i
            while j + 1 < len(b) and b[j + 1]:
                j += 1
            out.append((idx[i], idx[j]))
            i = j + 1
        else:
            i += 1
    return out


def _ombreggia(fig, mask: pd.Series, colore: str, opacita: float, row=None, col=None):
    for a, b in _spans(mask):
        kw = dict(x0=a, x1=b, fillcolor=colore, opacity=opacita, line_width=0, layer="below")
        if row is not None:
            fig.add_vrect(row=row, col=col, **kw)
        else:
            fig.add_vrect(**kw)
    return fig


def grafico_principale(d: pd.DataFrame, soglia: float) -> go.Figure:
    """Percentile della leva in eccesso sopra, S&P 500 sotto, fasi di copertura ombreggiate."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.42, 0.58],
        subplot_titles=("Leva in eccesso — percentile sui 120 mesi precedenti",
                        "S&P 500 (scala logaritmica)"),
    )
    fig.add_trace(
        go.Scatter(x=d.index, y=d["rank"], name="percentile leva in eccesso",
                   line=dict(color=COLORS["accent"], width=2)),
        row=1, col=1,
    )
    fig.add_hline(y=soglia, line=dict(color=COLORS["secondary"], width=1.5, dash="dash"),
                  opacity=0.9, row=1, col=1)
    fig.add_trace(
        go.Scatter(x=d.index, y=d["spx"], name="S&P 500",
                   line=dict(color=COLORS["primary"], width=1.8)),
        row=2, col=1,
    )
    _ombreggia(fig, d["copertura"], COLORS["negative"], 0.14, row=1, col=1)
    _ombreggia(fig, d["copertura"], COLORS["negative"], 0.14, row=2, col=1)

    fig.update_layout(**layout())
    fig.update_layout(height=560, showlegend=False)
    fig.update_yaxes(range=[0, 1], tickformat=".0%", row=1, col=1,
                     gridcolor="#333355", color=COLORS["text"])
    fig.update_yaxes(type="log", row=2, col=1, gridcolor="#333355", color=COLORS["text"])
    fig.update_xaxes(gridcolor="#333355", color=COLORS["text"])
    fig.add_annotation(
        x=0.005, y=1.0, xref="paper", yref="paper", showarrow=False, align="left",
        font=dict(size=11, color=COLORS["neutral"]),
        text="Le fasce rosse sono i 12 mesi successivi a ogni accensione",
    )
    return fig


def grafico_distribuzione(serie_ret: pd.Series, condizione: pd.Series) -> go.Figure:
    """Distribuzione del rendimento S&P 500 a 12 mesi, condizione accesa vs spenta."""
    ok = serie_ret.notna()
    on = serie_ret[condizione & ok]
    off = serie_ret[(~condizione) & ok]

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=off, name=f"condizione spenta (n={len(off)})",
                               marker_color=COLORS["primary"], opacity=0.65,
                               histnorm="probability", xbins=dict(size=0.05)))
    fig.add_trace(go.Histogram(x=on, name=f"condizione attiva (n={len(on)})",
                               marker_color=COLORS["negative"], opacity=0.75,
                               histnorm="probability", xbins=dict(size=0.05)))
    for val, col, txt in ((off.mean(), COLORS["primary"], "media spenta"),
                          (on.mean(), COLORS["negative"], "media attiva")):
        if np.isfinite(val):
            fig.add_vline(x=val, line=dict(color=col, width=2, dash="dash"),
                          annotation_text=f"{txt}: {val:+.1%}",
                          annotation_font=dict(size=11, color=col))
    fig.add_vline(x=0, line=dict(color=COLORS["text"], width=1), opacity=0.5)
    fig.update_layout(**layout("", "Rendimento S&P 500 nei 12 mesi successivi",
                               "frequenza"))
    fig.update_layout(barmode="overlay", height=380)
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(tickformat=".0%")
    return fig


def grafico_componenti(d: pd.DataFrame, mesi: int = 84) -> go.Figure:
    """Le due crescite annue che compongono il segnale, negli ultimi anni."""
    s = d.tail(mesi)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.index, y=s["yoy_md"], name="margin debt, variazione annua",
                             line=dict(color=COLORS["secondary"], width=2)))
    fig.add_trace(go.Scatter(x=s.index, y=s["yoy_spx"], name="S&P 500, variazione annua",
                             line=dict(color=COLORS["primary"], width=2)))
    fig.add_trace(go.Bar(x=s.index, y=s["el2"], name="differenziale (il segnale)",
                         marker_color=COLORS["accent"], opacity=0.45))
    fig.add_hline(y=0, line=dict(color=COLORS["text"], width=1), opacity=0.5)
    fig.update_layout(**layout("", "", "variazione annua (log)"))
    fig.update_layout(height=360)
    fig.update_yaxes(tickformat=".0%")
    return fig
