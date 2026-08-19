from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import timedelta


NUMERIC_COLS = [
    "Presupuesto", "Coste", "Coste (moneda convertida)",
    "Clics", "Conversiones", "CPC medio",
    "CPC medio (moneda convertida)", "Coste/conv.",
    "Coste (moneda convertida)/conv.", "Consumo L-V",
    "Impresiones", "Impr.", "Valor de conv.", "Valor de conversión",
    "CPA objetivo", "ROAS objetivo",
]

PERCENT_COLS = [
    "CTR", "CTR visible",
    "Tasa de conv.", "Porcentaje de conversiones",
    # Lost IS por presupuesto
    "% impr. perdidas de búsq. (presup.)",
    "Cuota impr. perdidas de parte sup. de búsqueda (presupuesto)",
    "Cuota impr. perdidas de parte sup. abs. de búsqueda (presupuesto)",
    "Porcentaje de impresiones de búsqueda perdidas (presupuesto)",
    # Lost IS por ranking
    "Cuota impr. perd. de búsq. (ranking)",
    "Cuota impr. perdidas de parte sup. de búsqueda (ranking)",
    "Cuota impr. perdidas de parte sup. abs. de búsqueda (ranking)",
    "Porcentaje de impresiones de búsqueda perdidas (rank)",
    "Porcentaje de impresiones de búsqueda perdidas (ranking)",
    # Cuotas de búsqueda
    "Cuota de impr. de búsqueda",
    "Cuota impr. de parte sup. de búsqueda",
    "Cuota impr. parte sup. absoluta de Búsqueda",
    "Cuota de impresiones de búsqueda",
    "Cuota de impresiones de búsqueda (parte superior abs.)",
    "Cuota de impr. superior abs. de búsqueda",
    # Opt Score
    "Nivel de optimización", "Optimization score", "Optimization Score",
]

# Alias → nombre canónico interno. Si varias columnas mapean al mismo alias,
# la primera presente gana (las siguientes se ignoran porque el alias ya existe).
# Orden importante: poner primero los nombres reales del export Google Ads en español.
COLUMN_ALIASES = {
    "CTR": "_ctr",
    "Impr.": "_impresiones",
    "Impresiones": "_impresiones",
    "Tasa de conv.": "_tasa_conv",
    "Porcentaje de conversiones": "_tasa_conv",
    "Valor de conv.": "_valor_conv",
    "Valor de conversión": "_valor_conv",
    "Valor conv./coste": "_roas",
    # Estrategia de puja: priorizar "Tipo de estrategia de puja" (texto real
    # como "Maximizar conversiones (CPA objetivo)"). La col "Estrategia de puja"
    # del export suele venir como etiqueta '--'.
    "Tipo de estrategia de puja": "_estrategia_puja",
    "Estrategia de puja": "_estrategia_puja",
    "CPA objetivo": "_tcpa",
    "ROAS objetivo": "_troas",
    # Lost IS — nombres reales del export español primero
    "% impr. perdidas de búsq. (presup.)": "_lost_is_budget",
    "Porcentaje de impresiones de búsqueda perdidas (presupuesto)": "_lost_is_budget",
    "Cuota impr. perd. de búsq. (ranking)": "_lost_is_rank",
    "Porcentaje de impresiones de búsqueda perdidas (rank)": "_lost_is_rank",
    "Porcentaje de impresiones de búsqueda perdidas (ranking)": "_lost_is_rank",
    "Cuota de impr. de búsqueda": "_search_is",
    "Cuota de impresiones de búsqueda": "_search_is",
    "Cuota impr. parte sup. absoluta de Búsqueda": "_top_abs_is",
    "Cuota de impresiones de búsqueda (parte superior abs.)": "_top_abs_is",
    "Cuota de impr. superior abs. de búsqueda": "_top_abs_is",
    "Eficacia del anuncio": "_ad_strength",
    "Detalles de la eficacia de los anuncios": "_ad_strength",
    "Nivel de optimización": "_opt_score",
    "Optimization score": "_opt_score",
    "Optimization Score": "_opt_score",
    "Tipo de campaña": "_tipo_campana",
    "Subtipo de campaña": "_subtipo_campana",
}

ACTIVE_STATUSES = {"Habilitada", "Enabled", "Active", "Activa"}


def _parse_number(val):
    """Convierte strings con formato español (1.234,56) a float.
    Convención Google Ads ES: ',' decimal, '.' separador de miles."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "--", "—"):
        return np.nan
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        # Solo '.' → separador de miles en formato español
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _parse_percent(val):
    """Convierte '23,45%', '23,45', '< 10%' a float (0–100). NaN si no parseable."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "--", "—"):
        return np.nan
    s = s.lstrip("<>").replace("%", "")
    return _parse_number(s)


def load_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Normalizar nombre de la columna de fecha
    date_col = next((c for c in df.columns if c.strip().lower() in ("día", "dia", "date", "fecha")), None)
    if date_col is None:
        raise ValueError("No se encontró la columna de fecha (Día / Date / Fecha).")
    df.rename(columns={date_col: "Día"}, inplace=True)

    # Parsear fecha: detectar ISO (YYYY-MM-DD) vs formato día-primero (DD/MM/YYYY)
    sample = df["Día"].dropna().astype(str).iloc[0] if not df["Día"].dropna().empty else ""
    is_iso = bool(sample) and len(sample) >= 10 and sample[4] == "-"
    df["Día"] = pd.to_datetime(df["Día"], dayfirst=not is_iso, errors="coerce")
    if df["Día"].isna().all():
        raise ValueError("No se pudo parsear la columna de fecha. Verifica el formato.")

    # Limpiar columnas numéricas
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_number)

    # Limpiar columnas de porcentaje
    for col in PERCENT_COLS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_percent)

    # Crear alias internos canónicos para acceso uniforme
    for original, alias in COLUMN_ALIASES.items():
        if original in df.columns and alias not in df.columns:
            df[alias] = df[original]

    # Asegurar columna Cuenta
    if "Cuenta" not in df.columns:
        df["Cuenta"] = "Sin cuenta"

    # Columna de estado normalizada
    status_col = "Estado de la campaña" if "Estado de la campaña" in df.columns else "Estado"
    df["_estado"] = df[status_col].astype(str).str.strip() if status_col in df.columns else "Desconocido"

    df["_activa"] = df["_estado"].isin(ACTIVE_STATUSES)

    return df.sort_values("Día")


def get_date_range(df: pd.DataFrame):
    return df["Día"].min(), df["Día"].max()


def _latest_n_dates(df: pd.DataFrame, n: int):
    dates = sorted(df["Día"].dropna().unique(), reverse=True)
    return dates[:n]


# ─── Anomalía 1 & 2: Campañas sin movimiento ─────────────────────────────────

def campaigns_not_moving(df: pd.DataFrame, target_date) -> pd.DataFrame:
    """
    Campañas activas que no tuvieron clics ni coste en target_date.
    """
    day_df = df[df["Día"] == pd.Timestamp(target_date)].copy()
    if day_df.empty:
        return pd.DataFrame()

    active = day_df[day_df["_activa"]].copy()
    no_move = active[
        (active.get("Clics", pd.Series(0, index=active.index)).fillna(0) == 0) &
        (active.get("Coste", pd.Series(0, index=active.index)).fillna(0) == 0)
    ]

    cols = ["Cuenta", "Campaña", "_estado", "Clics", "Coste", "Conversiones"]
    cols = [c for c in cols if c in no_move.columns]
    return no_move[cols].rename(columns={"_estado": "Estado"}).reset_index(drop=True)


# ─── Anomalía 3: Cuentas sin conversiones en últimos N días ──────────────────

def accounts_no_conversions(df: pd.DataFrame, days: int = 3) -> pd.DataFrame:
    """
    Cuentas que no registraron conversiones en los últimos `days` días con datos.
    """
    recent_dates = _latest_n_dates(df, days)
    if not recent_dates:
        return pd.DataFrame()

    recent = df[df["Día"].isin(recent_dates)].copy()
    if "Conversiones" not in recent.columns:
        return pd.DataFrame()

    summary = (
        recent.groupby("Cuenta")
        .agg(
            Conversiones=("Conversiones", "sum"),
            Campañas=("Campaña", "nunique"),
            Coste=("Coste", "sum"),
        )
        .reset_index()
    )
    no_conv = summary[summary["Conversiones"].fillna(0) == 0].copy()
    no_conv["Días analizados"] = len(recent_dates)
    return no_conv.reset_index(drop=True)


# ─── Anomalía 4: Campañas sin consumir 100% del presupuesto en últimos N días ─

def campaigns_underbudget(df: pd.DataFrame, days: int = 7, threshold: float = 1.0) -> pd.DataFrame:
    """
    Campañas activas que en NINGUNO de los últimos `days` días consumieron
    >= threshold * Presupuesto.
    """
    recent_dates = _latest_n_dates(df, days)
    if not recent_dates:
        return pd.DataFrame()

    if "Presupuesto" not in df.columns or "Coste" not in df.columns:
        return pd.DataFrame()

    recent = df[df["Día"].isin(recent_dates) & df["_activa"]].copy()
    recent = recent[recent["Presupuesto"].fillna(0) > 0].copy()

    recent["_pct_consumo"] = recent["Coste"].fillna(0) / recent["Presupuesto"]
    recent["_full_budget"] = recent["_pct_consumo"] >= threshold

    # Agrupar por cuenta + campaña
    summary = (
        recent.groupby(["Cuenta", "Campaña"])
        .agg(
            Días_con_datos=("Día", "count"),
            Días_presupuesto_completo=("_full_budget", "sum"),
            Coste_total=("Coste", "sum"),
            Presupuesto_promedio=("Presupuesto", "mean"),
            Pct_consumo_promedio=("_pct_consumo", "mean"),
        )
        .reset_index()
    )

    # Solo las que NUNCA llegaron al 100%
    never_full = summary[summary["Días_presupuesto_completo"] == 0].copy()
    never_full["Consumo promedio (%)"] = (never_full["Pct_consumo_promedio"] * 100).round(1)
    never_full["Presupuesto diario prom."] = never_full["Presupuesto_promedio"].round(2)

    cols = ["Cuenta", "Campaña", "Días_con_datos", "Coste_total",
            "Presupuesto diario prom.", "Consumo promedio (%)"]
    return never_full[cols].sort_values("Consumo promedio (%)").reset_index(drop=True)


# ─── Ranking de campañas ──────────────────────────────────────────────────────

def rank_campaigns(df: pd.DataFrame, period_days: int = 30) -> pd.DataFrame:
    """
    Ranking de campañas agregado por los últimos `period_days` días disponibles.
    """
    recent_dates = _latest_n_dates(df, period_days)
    recent = df[df["Día"].isin(recent_dates)].copy()

    agg = {}
    for col in ("Clics", "Coste", "Conversiones"):
        if col in recent.columns:
            agg[col] = (col, "sum")
    if not agg:
        return pd.DataFrame()

    summary = recent.groupby(["Cuenta", "Campaña"]).agg(**agg).reset_index()

    if "Coste" in summary.columns and "Conversiones" in summary.columns:
        summary["CPA"] = (summary["Coste"] / summary["Conversiones"].replace(0, np.nan)).round(2)

    if "Coste" in summary.columns and "Clics" in summary.columns:
        summary["CPC"] = (summary["Coste"] / summary["Clics"].replace(0, np.nan)).round(2)

    if "Conversiones" in summary.columns:
        summary = summary.sort_values("Conversiones", ascending=False)

    summary["Rank"] = range(1, len(summary) + 1)
    return summary.reset_index(drop=True)


# ─── Auditoría diaria: tabla consolidada con score ──────────────────────────

RULE_WEIGHTS = {
    "sin_mov_hoy": 50,
    "sin_mov_ayer": 40,
    "sin_conv": 35,
    "tasa_conv_baja": 20,
    "consumo_bajo": 11,
}


def compute_anomaly_table(
    df: pd.DataFrame,
    conv_rate_threshold: float = 0.10,
    budget_threshold: float = 0.80,
    conv_days: int = 3,
    budget_days: int = 7,
) -> pd.DataFrame:
    """
    Tabla consolidada de auditoría diaria. Una fila por campaña que dispare
    al menos una regla, con score, reglas activas y métricas clave.
    """
    if df.empty:
        return pd.DataFrame()

    dates_sorted = sorted(df["Día"].dropna().unique(), reverse=True)
    if not dates_sorted:
        return pd.DataFrame()

    latest = pd.Timestamp(dates_sorted[0])
    yday = pd.Timestamp(dates_sorted[1]) if len(dates_sorted) > 1 else None
    last_7 = [pd.Timestamp(d) for d in dates_sorted[:budget_days]]
    last_3 = [pd.Timestamp(d) for d in dates_sorted[:conv_days]]

    df_today = df[df["Día"] == latest]
    df_yday = df[df["Día"] == yday] if yday is not None else df.iloc[0:0]
    df_7d = df[df["Día"].isin(last_7)]
    df_3d = df[df["Día"].isin(last_3)]

    def _sum(d, cuenta, camp, col):
        s = d[(d["Cuenta"] == cuenta) & (d["Campaña"] == camp)]
        return float(s[col].sum()) if col in s.columns else 0.0

    rows = []
    for (cuenta, camp), group in df.groupby(["Cuenta", "Campaña"]):
        if not group["_activa"].any():
            continue

        clicks_today = _sum(df_today, cuenta, camp, "Clics")
        clicks_yday = _sum(df_yday, cuenta, camp, "Clics") if yday is not None else 0
        cost_today = _sum(df_today, cuenta, camp, "Coste")
        clicks_7d = _sum(df_7d, cuenta, camp, "Clics")
        conv_7d = _sum(df_7d, cuenta, camp, "Conversiones")
        cost_7d = _sum(df_7d, cuenta, camp, "Coste")
        budget_7d = _sum(df_7d, cuenta, camp, "Presupuesto")
        conv_3d = _sum(df_3d, cuenta, camp, "Conversiones")

        conv_rate_7d = conv_7d / clicks_7d if clicks_7d > 0 else 0.0
        budget_consumption_7d = cost_7d / budget_7d if budget_7d > 0 else 0.0

        reglas = []
        score = 0

        if clicks_today == 0 and cost_today == 0:
            reglas.append("Sin movimiento hoy (Clicks=0)")
            score += RULE_WEIGHTS["sin_mov_hoy"]
        if yday is not None and clicks_yday == 0:
            reglas.append("Sin movimiento ayer (Clicks=0)")
            score += RULE_WEIGHTS["sin_mov_ayer"]
        if conv_3d == 0:
            reglas.append(f"Sin conversiones en {conv_days} días")
            score += RULE_WEIGHTS["sin_conv"]
        if clicks_7d > 0 and conv_rate_7d < conv_rate_threshold:
            reglas.append(f"Tasa de conversión 7d < {int(conv_rate_threshold*100)}%")
            score += RULE_WEIGHTS["tasa_conv_baja"]
        if budget_7d > 0 and budget_consumption_7d < budget_threshold:
            reglas.append(f"Consumo presupuesto 7d < {int(budget_threshold*100)}%")
            score += RULE_WEIGHTS["consumo_bajo"]

        if not reglas:
            continue

        # Estado más reciente de la campaña
        latest_row = group.sort_values("Día").iloc[-1]
        estado_val = latest_row.get("Estado", "")
        motivo_val = latest_row.get("Motivos del estado", "")
        estado = "" if pd.isna(estado_val) else str(estado_val)
        motivo = "" if pd.isna(motivo_val) else str(motivo_val)

        rows.append({
            "Cuenta": cuenta,
            "Campaña": camp,
            "Score": score,
            "Reglas activas": " | ".join(reglas),
            "Clicks hoy": int(clicks_today),
            "Clicks ayer": int(clicks_yday),
            "Tasa conv. 7d": round(conv_rate_7d * 100, 1),
            "Consumo presupuesto 7d": round(budget_consumption_7d * 100, 1),
            "Estado": estado,
            "Motivo del estado": motivo,
        })

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values("Score", ascending=False)
        .reset_index(drop=True)
    )


# ─── Resumen general ─────────────────────────────────────────────────────────

def general_summary(df: pd.DataFrame) -> dict:
    latest = _latest_n_dates(df, 1)
    today_date = latest[0] if latest else None

    total_accounts = df["Cuenta"].nunique()
    total_campaigns = df["Campaña"].nunique() if "Campaña" in df.columns else 0
    total_cost = df["Coste"].sum() if "Coste" in df.columns else 0
    total_conversions = df["Conversiones"].sum() if "Conversiones" in df.columns else 0

    return {
        "total_accounts": total_accounts,
        "total_campaigns": total_campaigns,
        "total_cost": total_cost,
        "total_conversions": total_conversions,
        "latest_date": today_date,
        "date_range": get_date_range(df),
    }


# ─── Sugerencias de optimización ─────────────────────────────────────────────

DEFAULT_OPT_THRESHOLDS = {
    "lost_is_budget_high": 20.0,       # % impr. perdidas por presupuesto
    "lost_is_rank_high": 30.0,         # % impr. perdidas por ranking
    "min_clicks_no_conv": 30,          # clicks sin conv. para sugerir pausa
    "tcpa_overshoot": 1.3,             # CPA real / tCPA > 1.3 → recalibrar
    "ctr_min_search": 3.0,             # CTR mínimo Search (%)
    "ctr_min_other": 1.0,              # CTR mínimo otros tipos (%)
    "conv_rate_min": 5.0,              # Tasa conv. mínima cuando CTR es ok (%)
    "roas_min": 1.5,                   # ROAS mínimo cuando hay valor configurado
    "opt_score_min": 70.0,             # Optimization score mínimo (%)
}


def _has(df: pd.DataFrame, *cols) -> bool:
    return all(c in df.columns for c in cols)


def _severity(impact: int) -> str:
    if impact >= 70:
        return "Alta"
    if impact >= 40:
        return "Media"
    return "Baja"


def compute_optimization_suggestions(
    df: pd.DataFrame,
    thresholds: dict | None = None,
    window_days: int = 7,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Sugerencias de optimización por campaña en una ventana de N días.
    Tolera columnas faltantes: cada regla se evalúa solo si tiene los datos necesarios.

    Returns:
        (suggestions_df, disabled_rules) — la segunda lista contiene reglas que
        no pudieron evaluarse por falta de columnas, para mostrar al usuario.
    """
    t = {**DEFAULT_OPT_THRESHOLDS, **(thresholds or {})}
    disabled = []

    if df.empty:
        return pd.DataFrame(), disabled

    recent_dates = _latest_n_dates(df, window_days)
    if not recent_dates:
        return pd.DataFrame(), disabled

    recent = df[df["Día"].isin(recent_dates) & df["_activa"]].copy()
    if recent.empty:
        return pd.DataFrame(), disabled

    # Agregaciones base por campaña
    agg = {}
    for src, name in [
        ("Clics", "clics"), ("Coste", "coste"), ("Conversiones", "conv"),
        ("Impresiones", "impr"), ("_impresiones", "impr"),
        ("_valor_conv", "valor_conv"),
    ]:
        if src in recent.columns and name not in agg:
            agg[name] = (src, "sum")

    if not agg:
        return pd.DataFrame(), disabled

    base = recent.groupby(["Cuenta", "Campaña"]).agg(**agg).reset_index()

    # Métricas calculadas
    base["cpa"] = base["coste"] / base["conv"].replace(0, np.nan) if "conv" in base.columns else np.nan
    if "impr" in base.columns and "clics" in base.columns:
        base["ctr"] = (base["clics"] / base["impr"].replace(0, np.nan)) * 100
    if "valor_conv" in base.columns:
        base["roas"] = base["valor_conv"] / base["coste"].replace(0, np.nan)
    if "conv" in base.columns and "clics" in base.columns:
        base["conv_rate"] = (base["conv"] / base["clics"].replace(0, np.nan)) * 100

    # Promedios (último valor disponible) de columnas no acumulables: estrategias, tCPA, % perdidas, etc.
    last_row_cols = [
        "_estrategia_puja", "_tcpa", "_troas",
        "_lost_is_budget", "_lost_is_rank", "_search_is", "_top_abs_is",
        "_ad_strength", "_opt_score", "_tipo_campana",
    ]
    avail_last = [c for c in last_row_cols if c in recent.columns]
    if avail_last:
        last_vals = (
            recent.sort_values("Día")
            .groupby(["Cuenta", "Campaña"])[avail_last]
            .last()
            .reset_index()
        )
        base = base.merge(last_vals, on=["Cuenta", "Campaña"], how="left")

    # Reglas
    suggestions = []

    def _emit(row, categoria, diagnostico, accion, impacto, metricas):
        suggestions.append({
            "Cuenta": row["Cuenta"],
            "Campaña": row["Campaña"],
            "Categoría": categoria,
            "Diagnóstico": diagnostico,
            "Acción sugerida": accion,
            "Severidad": _severity(impacto),
            "Impacto": int(impacto),
            "Métricas clave": metricas,
        })

    for _, row in base.iterrows():
        clics = row.get("clics", 0) or 0
        coste = row.get("coste", 0) or 0
        conv = row.get("conv", 0) or 0
        cpa = row.get("cpa", np.nan)
        ctr = row.get("ctr", np.nan)
        roas = row.get("roas", np.nan)
        conv_rate = row.get("conv_rate", np.nan)
        tipo = str(row.get("_tipo_campana", "")) if "_tipo_campana" in row else ""
        is_search = "search" in tipo.lower() or "búsqueda" in tipo.lower() or not tipo

        # Subir presupuesto
        lost_b = row.get("_lost_is_budget", np.nan)
        if pd.notna(lost_b) and lost_b > t["lost_is_budget_high"] and conv > 0:
            cpa_ok = pd.isna(row.get("_tcpa")) or pd.isna(cpa) or cpa <= row["_tcpa"]
            if cpa_ok:
                impacto = min(100, 50 + int(lost_b))
                _emit(row, "Presupuesto (subir)",
                      f"Pierde {lost_b:.1f}% de impresiones por presupuesto limitado y tiene conversiones.",
                      f"Aumentar el presupuesto diario ~{min(int(lost_b * 1.2), 100)}%; hay demanda no capturada con CPA saludable.",
                      impacto,
                      f"Lost IS (budget): {lost_b:.1f}% · Conv: {conv:.1f} · CPA: {cpa:.2f}" if pd.notna(cpa) else f"Lost IS (budget): {lost_b:.1f}% · Conv: {conv:.1f}")

        # Mejorar ranking
        lost_r = row.get("_lost_is_rank", np.nan)
        if pd.notna(lost_r) and lost_r > t["lost_is_rank_high"]:
            impacto = min(90, 40 + int(lost_r / 2))
            _emit(row, "Ranking",
                  f"Pierde {lost_r:.1f}% de impresiones por ranking (puja o calidad).",
                  "Subir puja base, mejorar Quality Score de keywords o reforzar relevancia de anuncios/landing.",
                  impacto,
                  f"Lost IS (rank): {lost_r:.1f}% · CTR: {ctr:.2f}%" if pd.notna(ctr) else f"Lost IS (rank): {lost_r:.1f}%")

        # Bajar / pausar
        if conv == 0 and clics >= t["min_clicks_no_conv"] and coste > 0:
            impacto = min(95, 55 + int(clics / 10))
            _emit(row, "Presupuesto (reducir)",
                  f"{int(clics)} clics y ${coste:.2f} gastados sin ninguna conversión en {window_days} días.",
                  "Pausar o reducir presupuesto; revisar segmentación, keywords negativas y conversion tracking.",
                  impacto,
                  f"Clics: {int(clics)} · Coste: ${coste:.2f} · Conv: 0")

        # Recalibrar tCPA
        tcpa = row.get("_tcpa", np.nan)
        if pd.notna(tcpa) and tcpa > 0 and pd.notna(cpa) and cpa > tcpa * t["tcpa_overshoot"]:
            impacto = 65
            _emit(row, "Puja",
                  f"CPA real (${cpa:.2f}) supera el tCPA configurado (${tcpa:.2f}) en >{int((t['tcpa_overshoot']-1)*100)}%.",
                  "Revisar tCPA: subirlo si el costo real es sostenible o auditar segmentación/keywords si no.",
                  impacto,
                  f"CPA real: ${cpa:.2f} · tCPA: ${tcpa:.2f} · Conv: {conv:.1f}")

        # Estrategia inconsistente
        estrategia = str(row.get("_estrategia_puja", "")).lower()
        if estrategia and "maximizar clics" in estrategia and conv > 0:
            impacto = 60
            _emit(row, "Puja",
                  "Estrategia 'Maximizar clics' aplicada a campaña con histórico de conversiones.",
                  "Migrar a 'Maximizar conversiones' o tCPA para optimizar por valor en lugar de volumen de clics.",
                  impacto,
                  f"Estrategia: {row.get('_estrategia_puja')} · Conv: {conv:.1f}")

        # CTR bajo
        ctr_min = t["ctr_min_search"] if is_search else t["ctr_min_other"]
        if pd.notna(ctr) and clics > 0 and ctr < ctr_min:
            impacto = 45
            _emit(row, "Anuncios",
                  f"CTR {ctr:.2f}% por debajo del benchmark ({ctr_min:.1f}%) para tipo {tipo or 'Search'}.",
                  "Revisar copy de anuncios (headlines/descriptions), añadir extensiones y revisar relevancia de keywords.",
                  impacto,
                  f"CTR: {ctr:.2f}% · Impr: {int(row.get('impr', 0))} · Clics: {int(clics)}")

        # Tasa conv. baja con CTR ok
        if pd.notna(ctr) and pd.notna(conv_rate) and ctr >= ctr_min and conv_rate < t["conv_rate_min"] and clics > 0:
            impacto = 50
            _emit(row, "Landing",
                  f"CTR aceptable ({ctr:.2f}%) pero tasa de conversión baja ({conv_rate:.2f}%).",
                  "El problema probable está en la landing: revisar velocidad, formularios, oferta y coincidencia con el anuncio.",
                  impacto,
                  f"CTR: {ctr:.2f}% · Conv rate: {conv_rate:.2f}% · Clics: {int(clics)}")

        # Ad Strength pobre
        ad_strength = str(row.get("_ad_strength", "")).strip().lower()
        if ad_strength in {"pobre", "promedio", "poor", "average"}:
            impacto = 55
            _emit(row, "Anuncios",
                  f"Eficacia del anuncio: {row.get('_ad_strength')}.",
                  "Reescribir RSAs: añadir headlines/descriptions únicos, incluir keywords principales y CTAs claros.",
                  impacto,
                  f"Ad Strength: {row.get('_ad_strength')}")

        # ROAS bajo — solo si la campaña trackea valor de conversión (valor > 0)
        valor_conv = row.get("valor_conv", 0) or 0
        if pd.notna(roas) and roas < t["roas_min"] and valor_conv > 0:
            impacto = 60
            _emit(row, "Rentabilidad",
                  f"ROAS {roas:.2f}x por debajo del mínimo ({t['roas_min']:.1f}x).",
                  "Revisar segmentación, pausar grupos no rentables o reajustar tROAS si la campaña usa puja por valor.",
                  impacto,
                  f"ROAS: {roas:.2f}x · Valor conv: ${row.get('valor_conv', 0):.2f} · Coste: ${coste:.2f}")

        # Optimization Score bajo
        opt = row.get("_opt_score", np.nan)
        if pd.notna(opt) and opt < t["opt_score_min"]:
            impacto = 35
            _emit(row, "Calidad",
                  f"Optimization Score: {opt:.1f}% (bajo).",
                  "Revisar las recomendaciones nativas de Google Ads en la pestaña 'Recomendaciones'.",
                  impacto,
                  f"Opt. score: {opt:.1f}%")

    # Reglas deshabilitadas por falta de columnas
    rule_requirements = {
        "Subir presupuesto / Mejorar ranking": "_lost_is_budget",
        "ROAS bajo": "_valor_conv",
        "CTR bajo / Tasa conv. baja": "_impresiones",
        "Recalibrar tCPA": "_tcpa",
        "Estrategia inconsistente": "_estrategia_puja",
        "Ad Strength pobre": "_ad_strength",
        "Optimization Score bajo": "_opt_score",
    }
    for rule, col in rule_requirements.items():
        if col not in df.columns:
            disabled.append(rule)

    if not suggestions:
        return pd.DataFrame(), disabled

    sug_df = pd.DataFrame(suggestions)
    # Las sugerencias de "subir presupuesto" se empujan al final del listado
    # porque pedir aumento de presupuesto a clientes es la acción más difícil
    # de ejecutar; primero deben verse las optimizaciones que no requieren
    # incremento de inversión.
    sug_df["_orden_categoria"] = (sug_df["Categoría"] == "Presupuesto (subir)").astype(int)
    return (
        sug_df.sort_values(
            ["_orden_categoria", "Impacto", "Cuenta", "Campaña"],
            ascending=[True, False, True, True],
        )
        .drop(columns="_orden_categoria")
        .reset_index(drop=True),
        disabled,
    )


def optimization_kpis(suggestions_df: pd.DataFrame) -> dict:
    """KPIs gerenciales para el bloque analítico de la pestaña."""
    if suggestions_df.empty:
        return {
            "total": 0, "alta": 0, "media": 0, "baja": 0,
            "cuentas": 0, "campanas": 0, "por_categoria": {},
        }
    return {
        "total": len(suggestions_df),
        "alta": int((suggestions_df["Severidad"] == "Alta").sum()),
        "media": int((suggestions_df["Severidad"] == "Media").sum()),
        "baja": int((suggestions_df["Severidad"] == "Baja").sum()),
        "cuentas": suggestions_df["Cuenta"].nunique(),
        "campanas": suggestions_df["Campaña"].nunique(),
        "por_categoria": suggestions_df["Categoría"].value_counts().to_dict(),
    }
