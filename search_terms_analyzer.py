from __future__ import annotations

import io
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

import analyzer


SEARCH_TERMS_NUMERIC_COLS = [
    "Clics", "Impr.", "Impresiones",
    "CPC medio", "CPC medio (moneda convertida)",
    "Coste", "Coste (moneda convertida)",
    "Conversiones",
]

SEARCH_TERMS_PERCENT_COLS = [
    "CTR",
    "% de impr. (parte sup. abs.)",
    "% de impr. (parte sup.)",
]


def _normalize(text) -> str:
    """Lowercase, quita comillas/corchetes y normaliza acentos NFKD.

    Necesario porque `Palabra clave` viene con comillas (frase) o corchetes
    (exacta) en el export de Google Ads.
    """
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(text).strip()
    # Strip comillas y corchetes externos varias veces (puede haber anidados)
    for _ in range(3):
        new = s.strip().strip('"').strip("'").strip("[").strip("]").strip()
        if new == s:
            break
        s = new
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def load_search_terms_csv(file_bytes: bytes) -> pd.DataFrame:
    """Carga el export 'Informe de términos de búsqueda' de Google Ads.

    Maneja 2-3 líneas de metadata arriba, separadores `,` o `;` y formato
    español de números (`,` decimal, `.` miles).
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Buscar la fila de encabezados: contiene "término de búsqueda"
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        normalized = _normalize(line)
        if "termino de busqueda" in normalized:
            header_idx = i
            break

    header_line = lines[header_idx]
    sep = "," if header_line.count(",") >= header_line.count(";") else ";"

    df_raw = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        sep=sep,
        thousands=".",
        decimal=",",
        dtype=str,
    )

    # Limpiar nombres de columnas
    df_raw.columns = [c.strip() for c in df_raw.columns]

    # Validar columnas mínimas
    required = {"Término de búsqueda", "Palabra clave"}
    missing = required - set(df_raw.columns)
    if missing:
        raise ValueError(
            f"Faltan columnas requeridas en el CSV: {', '.join(sorted(missing))}. "
            f"¿Es este el 'Informe de términos de búsqueda' de Google Ads?"
        )

    # Filtrar filas vacías y totales
    if "Campaña" in df_raw.columns:
        df_raw = df_raw[df_raw["Campaña"].astype(str).str.strip().replace("nan", "") != ""]
        df_raw = df_raw[~df_raw["Campaña"].astype(str).str.startswith("Total:", na=False)]
    df_raw = df_raw[df_raw["Término de búsqueda"].astype(str).str.strip().replace("nan", "") != ""]
    df_raw = df_raw[~df_raw["Término de búsqueda"].astype(str).str.startswith("Total:", na=False)]
    df_raw = df_raw.dropna(how="all").reset_index(drop=True)

    # Parsear numéricos y porcentajes con los helpers de analyzer
    for col in SEARCH_TERMS_NUMERIC_COLS:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(analyzer._parse_number)

    for col in SEARCH_TERMS_PERCENT_COLS:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].apply(analyzer._parse_percent)

    if "Cuenta" not in df_raw.columns:
        df_raw["Cuenta"] = "Sin cuenta"

    return df_raw


def compute_similarity(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula similitud 0-100 entre `Término de búsqueda` y `Palabra clave`.

    Usa rapidfuzz.fuzz.token_set_ratio sobre versiones normalizadas. Filas
    sin palabra clave válida quedan con score NaN y _sin_keyword=True.
    """
    df = df.copy()

    terms_norm = df["Término de búsqueda"].apply(_normalize)
    kws_norm = df["Palabra clave"].apply(_normalize)

    df["_sin_keyword"] = kws_norm == ""

    scores = []
    for term, kw, missing in zip(terms_norm, kws_norm, df["_sin_keyword"]):
        if missing or term == "":
            scores.append(np.nan)
        else:
            scores.append(float(fuzz.token_set_ratio(term, kw)))

    df["_score_similitud"] = scores
    return df


def aggregate_by_account(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Agrega scores por cuenta usando promedio ponderado por clics.

    threshold: umbral 0-100. Una cuenta con score_promedio < threshold se marca
    como `alerta`.
    """
    valid = df[~df["_sin_keyword"]].copy()
    valid["Clics"] = valid["Clics"].fillna(0)
    valid["Coste"] = valid.get("Coste", 0)
    if "Coste" in valid.columns:
        valid["Coste"] = valid["Coste"].fillna(0)

    rows = []
    for cuenta, grupo in df.groupby("Cuenta", dropna=False):
        grupo_valid = grupo[~grupo["_sin_keyword"]]
        total_clics = float(grupo["Clics"].fillna(0).sum()) if "Clics" in grupo else 0.0
        total_coste = float(grupo["Coste"].fillna(0).sum()) if "Coste" in grupo else 0.0
        n_terminos = int(len(grupo_valid))
        n_sin_keyword = int(grupo["_sin_keyword"].sum())

        if n_terminos == 0:
            score_promedio = np.nan
        else:
            clics_validos = grupo_valid["Clics"].fillna(0) if "Clics" in grupo_valid else pd.Series([0] * n_terminos)
            suma_clics = float(clics_validos.sum())
            if suma_clics > 0:
                score_promedio = float((grupo_valid["_score_similitud"] * clics_validos).sum() / suma_clics)
            else:
                score_promedio = float(grupo_valid["_score_similitud"].mean())

        n_baja = int((grupo_valid["_score_similitud"] < threshold).sum()) if n_terminos else 0
        alerta = (not np.isnan(score_promedio)) and (score_promedio < threshold)

        rows.append({
            "Cuenta": cuenta if pd.notna(cuenta) else "Sin cuenta",
            "score_promedio": score_promedio,
            "n_terminos": n_terminos,
            "n_terminos_baja_calidad": n_baja,
            "n_sin_keyword": n_sin_keyword,
            "total_clics": total_clics,
            "total_coste": total_coste,
            "alerta": alerta,
        })

    out = pd.DataFrame(rows)
    return out.sort_values("score_promedio", ascending=True, na_position="last").reset_index(drop=True)


def aggregate_by_campaign(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Mismo cálculo agrupado por (Cuenta, Campaña) para drill-down."""
    rows = []
    for (cuenta, campana), grupo in df.groupby(["Cuenta", "Campaña"], dropna=False):
        grupo_valid = grupo[~grupo["_sin_keyword"]]
        total_clics = float(grupo["Clics"].fillna(0).sum()) if "Clics" in grupo else 0.0
        total_coste = float(grupo["Coste"].fillna(0).sum()) if "Coste" in grupo else 0.0
        n_terminos = int(len(grupo_valid))

        if n_terminos == 0:
            score_promedio = np.nan
        else:
            clics_validos = grupo_valid["Clics"].fillna(0) if "Clics" in grupo_valid else pd.Series([0] * n_terminos)
            suma_clics = float(clics_validos.sum())
            if suma_clics > 0:
                score_promedio = float((grupo_valid["_score_similitud"] * clics_validos).sum() / suma_clics)
            else:
                score_promedio = float(grupo_valid["_score_similitud"].mean())

        n_baja = int((grupo_valid["_score_similitud"] < threshold).sum()) if n_terminos else 0

        rows.append({
            "Cuenta": cuenta if pd.notna(cuenta) else "Sin cuenta",
            "Campaña": campana if pd.notna(campana) else "Sin campaña",
            "score_promedio": score_promedio,
            "n_terminos": n_terminos,
            "n_terminos_baja_calidad": n_baja,
            "total_clics": total_clics,
            "total_coste": total_coste,
            "alerta": (not np.isnan(score_promedio)) and (score_promedio < threshold),
        })

    out = pd.DataFrame(rows)
    return out.sort_values("score_promedio", ascending=True, na_position="last").reset_index(drop=True)
