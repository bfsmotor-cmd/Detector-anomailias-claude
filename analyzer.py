import pandas as pd
import numpy as np
from datetime import timedelta


NUMERIC_COLS = [
    "Presupuesto", "Coste", "Coste (moneda convertida)",
    "Clics", "Conversiones", "CPC medio",
    "CPC medio (moneda convertida)", "Coste/conv.",
    "Coste (moneda convertida)/conv.", "Consumo L-V",
]

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
