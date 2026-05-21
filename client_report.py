"""Generación de mensajes de seguimiento semanal por cliente (cuenta).

Toma los KPIs de los últimos 7 días vs los 7 anteriores, top términos de
búsqueda y sugerencias de optimización, los clasifica en un tono
(positivo/mixto/mejora) y arma un mensaje en lenguaje natural listo para enviar.

Diseño determinístico (sin LLM): los templates están en este módulo. Si se
quiere editar el copy hay que tocar este archivo.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional

import analyzer


PERIODO_DIAS = 7


# Diagnósticos técnicos → frase amable orientada al cliente.
# El objetivo es nunca exponer jerga interna (CPA, Lost IS, ranking, etc.) en
# el mensaje al cliente; cada categoría se reescribe a una promesa de acción.
CATEGORIA_A_FRASE_CLIENTE = {
    "Presupuesto (subir)": "explorar oportunidades de crecimiento ampliando el alcance de las campañas",
    "Presupuesto (reducir)": "reasignar inversión hacia las campañas con mejor rendimiento",
    "Ranking": "mejorar el posicionamiento de tus anuncios en las búsquedas",
    "Puja": "afinar la estrategia de pujas para optimizar el costo por resultado",
    "Anuncios": "renovar los textos de los anuncios para conectar mejor con tu audiencia",
    "Landing": "revisar la experiencia de la página de destino para aumentar conversiones",
    "Rentabilidad": "optimizar las campañas para mejorar el retorno de inversión",
    "Calidad": "aplicar recomendaciones de calidad para potenciar el rendimiento",
}


def _safe_div(a: float, b: float) -> Optional[float]:
    if b is None or b == 0 or pd.isna(b):
        return None
    return a / b


def _pct_change(actual: float, anterior: float) -> Optional[float]:
    if anterior is None or anterior == 0 or pd.isna(anterior):
        return None
    return (actual - anterior) / anterior * 100


def aggregate_account_period(df: pd.DataFrame, fechas: list) -> dict:
    """Suma KPIs por cuenta en el rango de fechas dado.

    Devuelve dict {cuenta: {clics, coste, conversiones, ctr, tasa_conv, cpa,
    campanas_activas}}.
    """
    if not fechas:
        return {}

    periodo = df[df["Día"].isin(fechas)].copy()
    if periodo.empty:
        return {}

    out = {}
    for cuenta, grupo in periodo.groupby("Cuenta"):
        clics = float(grupo["Clics"].sum()) if "Clics" in grupo.columns else 0.0
        coste = float(grupo["Coste"].sum()) if "Coste" in grupo.columns else 0.0
        conv = float(grupo["Conversiones"].sum()) if "Conversiones" in grupo.columns else 0.0

        impr_col = "Impresiones" if "Impresiones" in grupo.columns else (
            "_impresiones" if "_impresiones" in grupo.columns else None
        )
        impresiones = float(grupo[impr_col].sum()) if impr_col else 0.0

        ctr = _safe_div(clics, impresiones)
        tasa_conv = _safe_div(conv, clics)
        cpa = _safe_div(coste, conv)

        campanas_activas = int(
            grupo[grupo.get("_activa", False)]["Campaña"].nunique()
        ) if "Campaña" in grupo.columns else 0

        out[cuenta] = {
            "clics": clics,
            "coste": coste,
            "conversiones": conv,
            "impresiones": impresiones,
            "ctr": ctr * 100 if ctr is not None else None,
            "tasa_conv": tasa_conv * 100 if tasa_conv is not None else None,
            "cpa": cpa,
            "campanas_activas": campanas_activas,
        }
    return out


def _top_campanas(df: pd.DataFrame, cuenta: str, fechas: list, n: int = 3) -> list:
    """Top N campañas de la cuenta por clics en el período."""
    periodo = df[(df["Cuenta"] == cuenta) & (df["Día"].isin(fechas))]
    if periodo.empty or "Campaña" not in periodo.columns:
        return []
    agg = (
        periodo.groupby("Campaña")
        .agg(clics=("Clics", "sum"), conv=("Conversiones", "sum"))
        .sort_values("clics", ascending=False)
        .head(n)
    )
    return [
        {"campana": idx, "clics": int(row["clics"]), "conv": float(row["conv"])}
        for idx, row in agg.iterrows()
        if row["clics"] > 0
    ]


def _top_terminos(search_terms_df: Optional[pd.DataFrame], cuenta: str, n: int = 5) -> list:
    """Top N términos de búsqueda por clics para la cuenta."""
    if search_terms_df is None or search_terms_df.empty:
        return []
    if "Cuenta" not in search_terms_df.columns or "Término de búsqueda" not in search_terms_df.columns:
        return []
    sub = search_terms_df[search_terms_df["Cuenta"] == cuenta].copy()
    if sub.empty or "Clics" not in sub.columns:
        return []
    sub = sub[sub["Clics"].fillna(0) > 0]
    if sub.empty:
        return []
    agg = (
        sub.groupby("Término de búsqueda")
        .agg(clics=("Clics", "sum"))
        .sort_values("clics", ascending=False)
        .head(n)
    )
    return [
        {"termino": idx, "clics": int(row["clics"])}
        for idx, row in agg.iterrows()
    ]


def _score_terminos_cuenta(search_terms_agg: Optional[pd.DataFrame], cuenta: str) -> Optional[float]:
    if search_terms_agg is None or search_terms_agg.empty:
        return None
    row = search_terms_agg[search_terms_agg["Cuenta"] == cuenta]
    if row.empty:
        return None
    val = row.iloc[0].get("score_promedio")
    if val is None or pd.isna(val):
        return None
    return float(val)


def _top_sugerencias(suggestions_df: Optional[pd.DataFrame], cuenta: str, n: int = 3) -> list:
    """Top N sugerencias de optimización para la cuenta, ordenadas por impacto."""
    if suggestions_df is None or suggestions_df.empty:
        return []
    sub = suggestions_df[suggestions_df["Cuenta"] == cuenta].copy()
    if sub.empty:
        return []
    sub = sub.sort_values("Impacto", ascending=False).head(n)
    out = []
    for _, row in sub.iterrows():
        categoria = row.get("Categoría", "")
        frase = CATEGORIA_A_FRASE_CLIENTE.get(categoria, categoria.lower())
        out.append({
            "categoria": categoria,
            "frase_cliente": frase,
            "impacto": int(row.get("Impacto", 0)),
        })
    # Deduplicar por frase (varias campañas pueden disparar la misma categoría)
    vistos = set()
    unicas = []
    for s in out:
        if s["frase_cliente"] in vistos:
            continue
        vistos.add(s["frase_cliente"])
        unicas.append(s)
    return unicas


def classify_tone(actual: dict, deltas: dict, score_terminos: Optional[float]) -> str:
    """Reglas de clasificación de tono.

    - mejora: 0 conversiones, o conv cayó >=20%
    - positivo: conversiones subieron (o se mantuvieron) Y (CPA no empeoró >5%
      O hay buena calidad de términos)
    - mixto: cualquier otra cosa
    """
    conv = actual.get("conversiones", 0) or 0
    conv_delta = deltas.get("conv_pct")
    cpa_delta = deltas.get("cpa_pct")

    if conv == 0:
        return "mejora"
    if conv_delta is not None and conv_delta <= -20:
        return "mejora"

    conv_sube = conv_delta is None or conv_delta >= 0
    cpa_no_empeora = cpa_delta is None or cpa_delta <= 5
    terminos_buenos = score_terminos is not None and score_terminos >= 70

    if conv_sube and (cpa_no_empeora or terminos_buenos):
        return "positivo"

    return "mixto"


def compute_account_summary(
    df: pd.DataFrame,
    search_terms_df: Optional[pd.DataFrame] = None,
    search_terms_agg: Optional[pd.DataFrame] = None,
    suggestions_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """Calcula el summary para cada cuenta presente en df.

    Devuelve lista de dicts con todo lo necesario para renderizar el mensaje.
    """
    if df.empty:
        return []

    fechas_orden = sorted(df["Día"].dropna().unique(), reverse=True)
    if not fechas_orden:
        return []

    fechas_actual = [pd.Timestamp(d) for d in fechas_orden[:PERIODO_DIAS]]
    fechas_anterior = [pd.Timestamp(d) for d in fechas_orden[PERIODO_DIAS:PERIODO_DIAS * 2]]

    kpis_actual = aggregate_account_period(df, fechas_actual)
    kpis_anterior = aggregate_account_period(df, fechas_anterior) if fechas_anterior else {}

    summaries = []
    for cuenta, actual in kpis_actual.items():
        anterior = kpis_anterior.get(cuenta) if kpis_anterior else None

        deltas = {}
        if anterior:
            deltas = {
                "clics_pct": _pct_change(actual["clics"], anterior["clics"]),
                "conv_pct": _pct_change(actual["conversiones"], anterior["conversiones"]),
                "cpa_pct": _pct_change(actual["cpa"] or 0, anterior["cpa"] or 0)
                    if actual["cpa"] is not None and anterior["cpa"] is not None else None,
                "ctr_pct": _pct_change(actual["ctr"] or 0, anterior["ctr"] or 0)
                    if actual["ctr"] is not None and anterior["ctr"] is not None else None,
            }

        score = _score_terminos_cuenta(search_terms_agg, cuenta)
        top_camp = _top_campanas(df, cuenta, fechas_actual)
        top_term = _top_terminos(search_terms_df, cuenta)
        top_sug = _top_sugerencias(suggestions_df, cuenta)

        tono = classify_tone(actual, deltas, score)

        summaries.append({
            "cuenta": cuenta,
            "periodo_actual": actual,
            "periodo_anterior": anterior,
            "deltas": deltas,
            "top_campanas": top_camp,
            "top_terminos": top_term,
            "score_terminos": score,
            "sugerencias_top": top_sug,
            "tono": tono,
            "fecha_inicio": min(fechas_actual),
            "fecha_fin": max(fechas_actual),
            "tiene_periodo_anterior": bool(anterior),
        })

    return summaries


# ─── Templates ────────────────────────────────────────────────────────────────

def _fmt_num(n: float) -> str:
    if n is None or pd.isna(n):
        return "—"
    if n >= 1000:
        return f"{n:,.0f}".replace(",", ".")
    # Trata como entero si está a menos de 0.05 de un entero (evita "77.0" por floats)
    if abs(n - round(n)) < 0.05:
        return f"{int(round(n))}"
    return f"{n:,.1f}".replace(",", ".")


def _fmt_money(n: Optional[float]) -> str:
    if n is None or pd.isna(n):
        return "—"
    return f"${n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(n: Optional[float]) -> str:
    if n is None or pd.isna(n):
        return "—"
    return f"{n:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_delta(pct: Optional[float], invertido: bool = False) -> str:
    """Formatea un delta porcentual con flecha. invertido=True para CPA (bajar = bueno)."""
    if pct is None:
        return ""
    abs_pct = abs(pct)
    if abs_pct < 1:
        return "se mantuvo estable"
    if pct > 0:
        flecha = "↑"
        bueno = not invertido
    else:
        flecha = "↓"
        bueno = invertido
    adjetivo = "más" if pct > 0 else "menos"
    return f"{flecha} {abs_pct:.0f}% {adjetivo}"


def _frase_comparativa(actual: dict, anterior: dict, deltas: dict) -> str:
    """Genera la frase comparativa vs semana anterior. Vacía si no hay datos."""
    if not anterior:
        return ""
    conv_pct = deltas.get("conv_pct")
    if conv_pct is None:
        return ""
    if conv_pct >= 10:
        return f", un {conv_pct:.0f}% más que la semana anterior"
    if conv_pct >= 1:
        return f", ligeramente por encima de la semana anterior (+{conv_pct:.0f}%)"
    if conv_pct >= -1:
        return ", manteniendo el ritmo de la semana anterior"
    if conv_pct >= -10:
        return f", levemente por debajo de la semana anterior ({conv_pct:.0f}%)"
    return f", {abs(conv_pct):.0f}% menos que la semana anterior"


def _frase_terminos(top_terminos: list, score: Optional[float]) -> str:
    if not top_terminos:
        return ""
    nombres = [t["termino"] for t in top_terminos[:4]]
    listado = ", ".join(f"\"{n}\"" for n in nombres)
    if score is not None and score >= 70:
        return (
            f"Los términos por los que más te están encontrando son {listado}, "
            f"todos muy alineados con tu negocio (calidad de {score:.0f}/100). "
        )
    if score is not None and score >= 50:
        return (
            f"Los términos con más tracción esta semana fueron {listado}. "
            f"La calidad de búsqueda está en {score:.0f}/100, con margen de mejora. "
        )
    if score is not None:
        return (
            f"Los términos que generaron más clics fueron {listado}. "
            f"Estamos trabajando en refinar las palabras clave para que el tráfico sea aún más relevante. "
        )
    return f"Los términos con más tracción esta semana fueron {listado}. "


def _frase_top_campana(top_campanas: list) -> str:
    if not top_campanas:
        return ""
    primera = top_campanas[0]
    return (
        f"La campaña que más volumen movió fue \"{primera['campana']}\" "
        f"con {_fmt_num(primera['clics'])} clics"
        + (f" y {_fmt_num(primera['conv'])} conversiones." if primera['conv'] > 0 else ".")
        + " "
    )


def _bullets_sugerencias(sugerencias: list, n: int = 3) -> str:
    if not sugerencias:
        return ""
    items = [f"• {s['frase_cliente'].capitalize()}." for s in sugerencias[:n]]
    return "\n".join(items)


def _template_positivo(s: dict) -> str:
    act = s["periodo_actual"]
    comparativa = _frase_comparativa(act, s["periodo_anterior"], s["deltas"])
    terminos = _frase_terminos(s["top_terminos"], s["score_terminos"])
    top_camp = _frase_top_campana(s["top_campanas"])

    cierre_cpa = ""
    cpa_delta = s["deltas"].get("cpa_pct")
    if cpa_delta is not None and cpa_delta <= -5:
        cierre_cpa = f"Además, el costo por conversión mejoró un {abs(cpa_delta):.0f}% frente a la semana anterior. "

    return (
        f"Hola,\n\n"
        f"Te compartimos el resumen semanal de tu cuenta {s['cuenta']}.\n\n"
        f"Esta semana generamos un total de {_fmt_num(act['clics'])} clics y "
        f"{_fmt_num(act['conversiones'])} conversiones{comparativa}, "
        f"con una tasa de conversión del {_fmt_pct(act['tasa_conv'])} — un resultado muy positivo. "
        f"{cierre_cpa}"
        f"{top_camp}"
        f"{terminos}\n"
        f"Seguimos optimizando día a día para sostener este desempeño y buscar nuevas oportunidades de crecimiento.\n\n"
        f"Cualquier consulta quedamos atentos."
    )


def _template_mixto(s: dict) -> str:
    act = s["periodo_actual"]
    comparativa = _frase_comparativa(act, s["periodo_anterior"], s["deltas"])
    terminos = _frase_terminos(s["top_terminos"], s["score_terminos"])
    bullets = _bullets_sugerencias(s["sugerencias_top"], n=2)

    # Resalta lo bueno si hay algo
    destaca = ""
    if s["deltas"].get("ctr_pct") and s["deltas"]["ctr_pct"] > 5:
        destaca = f"Un dato positivo: el CTR mejoró un {s['deltas']['ctr_pct']:.0f}% respecto a la semana anterior, lo que indica que los anuncios están conectando mejor. "
    elif act["tasa_conv"] and act["tasa_conv"] >= 5:
        destaca = f"La tasa de conversión se mantiene en {_fmt_pct(act['tasa_conv'])}, en un rango saludable. "

    bloque_sug = ""
    if bullets:
        bloque_sug = (
            f"\nHemos identificado algunas oportunidades en las que ya estamos trabajando:\n\n"
            f"{bullets}\n"
        )

    return (
        f"Hola,\n\n"
        f"Te compartimos el resumen semanal de tu cuenta {s['cuenta']}.\n\n"
        f"Esta semana generamos {_fmt_num(act['clics'])} clics y "
        f"{_fmt_num(act['conversiones'])} conversiones{comparativa}. "
        f"{destaca}"
        f"{terminos}"
        f"{bloque_sug}\n"
        f"Esperamos reflejar el impacto de estos ajustes en los próximos días.\n\n"
        f"Cualquier consulta quedamos atentos."
    )


def _template_mejora(s: dict) -> str:
    act = s["periodo_actual"]
    comparativa = _frase_comparativa(act, s["periodo_anterior"], s["deltas"])
    bullets = _bullets_sugerencias(s["sugerencias_top"], n=3)

    intro_conv = ""
    if act["conversiones"] == 0:
        intro_conv = (
            f"Esta semana la campaña generó {_fmt_num(act['clics'])} clics pero aún no concretamos conversiones"
            f"{comparativa}. "
        )
    else:
        intro_conv = (
            f"Esta semana generamos {_fmt_num(act['clics'])} clics y "
            f"{_fmt_num(act['conversiones'])} conversiones{comparativa}. "
        )

    bloque_sug = (
        f"Por eso revisamos a fondo el rendimiento e identificamos oportunidades concretas en las que ya estamos trabajando:\n\n"
        f"{bullets}\n"
        if bullets
        else "Estamos revisando a fondo la cuenta para identificar las palancas que más rápido pueden mover los resultados.\n"
    )

    return (
        f"Hola,\n\n"
        f"Te compartimos el resumen semanal de tu cuenta {s['cuenta']}.\n\n"
        f"{intro_conv}\n"
        f"{bloque_sug}\n"
        f"Esperamos ver el impacto positivo en los próximos 7 días. Te mantendremos al tanto del progreso.\n\n"
        f"Cualquier consulta quedamos atentos."
    )


def build_message(summary: dict) -> str:
    """Genera el mensaje narrativo según el tono clasificado."""
    tono = summary.get("tono", "mixto")
    if tono == "positivo":
        return _template_positivo(summary)
    if tono == "mejora":
        return _template_mejora(summary)
    return _template_mixto(summary)
