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


def load_keywords_csv(file_bytes: bytes) -> pd.DataFrame:
    """Carga la sábana de palabras clave (todas las cuentas/campañas).

    Formato esperado (export Google Ads / Editor): columnas mínimas `Cuenta`,
    `Campaña`, `Palabra clave`. Tolera metadata de cabecera, separadores
    `,`/`;` y formato español de números (no se usan métricas, pero se parsean
    si vienen).
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Buscar la fila de encabezados que contenga "palabra clave"
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        normalized = _normalize(line)
        if "palabra clave" in normalized:
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
    df_raw.columns = [c.strip() for c in df_raw.columns]

    required = {"Campaña", "Palabra clave"}
    missing = required - set(df_raw.columns)
    if missing:
        raise ValueError(
            f"Faltan columnas requeridas en la sábana de KW: {', '.join(sorted(missing))}. "
            f"Se esperan al menos 'Cuenta', 'Campaña', 'Palabra clave'."
        )

    if "Cuenta" not in df_raw.columns:
        df_raw["Cuenta"] = "Sin cuenta"

    # Filtrar filas vacías y totales
    df_raw = df_raw[df_raw["Campaña"].astype(str).str.strip().replace("nan", "") != ""]
    df_raw = df_raw[~df_raw["Campaña"].astype(str).str.startswith("Total:", na=False)]
    df_raw = df_raw[df_raw["Palabra clave"].astype(str).str.strip().replace("nan", "") != ""]
    df_raw = df_raw[~df_raw["Palabra clave"].astype(str).str.startswith("Total:", na=False)]
    df_raw = df_raw.dropna(how="all").reset_index(drop=True)

    return df_raw


def build_campaign_vocab(df_kw: pd.DataFrame) -> dict:
    """Construye `{campaña_normalizada: set(palabras)}` desde la sábana de KW.

    La clave es solo el nombre de campaña normalizado (lowercase + sin acentos
    + sin comillas/corchetes) para que el match funcione tanto si la sábana
    viene del MCC (con columna `Cuenta`) como si es export por cuenta
    individual (sin `Cuenta`). Los nombres de campaña de Google Ads suelen
    incluir sufijos únicos así que colisiones cross-cuenta son raras.

    Aplica `_normalize` al vocabulario, descarta stopwords y palabras < 2 chars.
    """
    vocab: dict = {}
    for campana, grupo in df_kw.groupby("Campaña", dropna=False):
        if pd.isna(campana):
            continue
        key = _normalize(campana)
        if not key:
            continue
        words = vocab.setdefault(key, set())
        for kw_raw in grupo["Palabra clave"].dropna():
            for w in _normalize(kw_raw).split():
                if w not in _STOPWORDS and len(w) >= 2:
                    words.add(w)
    return vocab


def compute_coverage_score(df: pd.DataFrame, campaign_vocab: dict) -> pd.DataFrame:
    """Calcula score 0-100 = % de palabras del término cubiertas por las
    KW de su misma campaña.

    - Tokeniza el término con `_normalize` y filtra stopwords / palabras < 2 chars.
    - Cobertura palabra-a-palabra con `_word_covered` (prefijo 4 chars).
    - Si la campaña no tiene vocabulario cargado, la fila queda `_sin_keyword=True`.
    """
    df = df.copy()

    scores = []
    sin_kw = []
    for _, fila in df.iterrows():
        campana = fila.get("Campaña", "")
        if pd.isna(campana):
            campana = ""
        vocab = campaign_vocab.get(_normalize(campana), set())

        term_words = [
            w for w in _normalize(fila.get("Término de búsqueda", "")).split()
            if w not in _STOPWORDS and len(w) >= 2
        ]

        if not vocab or not term_words:
            scores.append(np.nan)
            sin_kw.append(True)
            continue

        covered = sum(1 for w in term_words if _word_covered(w, vocab))
        scores.append(100.0 * covered / len(term_words))
        sin_kw.append(False)

    df["_score_similitud"] = scores
    df["_sin_keyword"] = sin_kw
    return df


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


# ── Negativas sugeridas por sustracción de vocabulario ────────────────────────

_STOPWORDS = {
    "de", "del", "la", "las", "el", "los", "en", "y", "a", "con", "para",
    "por", "un", "una", "unos", "unas", "al", "o", "que", "se", "su",
    "the", "of", "in", "and", "for", "to", "a", "an",
}


def _word_covered(word: str, kw_vocab: set, min_prefix: int = 4) -> bool:
    """True si `word` está cubierta por alguna palabra del vocabulario de keywords.

    Usa prefijo compartido para que 'termometro' matchee 'termometros', etc.
    """
    if len(word) < min_prefix:
        return word in kw_vocab
    w_prefix = word[:min_prefix]
    for kw_word in kw_vocab:
        if len(kw_word) >= min_prefix and kw_word[:min_prefix] == w_prefix:
            return True
        elif len(kw_word) < min_prefix and kw_word == word:
            return True
    return False


def compute_negative_suggestions(df: pd.DataFrame, campaign_vocab: dict | None = None) -> pd.DataFrame:
    """Genera palabras negativas sugeridas por sustracción de vocabulario.

    Para cada término de búsqueda resta las palabras ya cubiertas por las
    keywords. Las palabras sobrantes son candidatas a negativa.

    Si se proporciona `campaign_vocab` (mapa `{(cuenta, campaña): set}`
    producido por `build_campaign_vocab`), se usa la cobertura **por campaña**.
    Si no, se construye vocabulario por cuenta a partir de la columna
    `Palabra clave` del CSV de términos (comportamiento histórico).
    """
    valid = df[~df["_sin_keyword"]].copy()
    rows = []

    for cuenta, grupo in valid.groupby("Cuenta", dropna=False):
        cuenta_str = cuenta if pd.notna(cuenta) else "Sin cuenta"

        # Si no hay vocab externo, construirlo por cuenta desde el CSV de términos
        kw_vocab_cuenta: set = set()
        if campaign_vocab is None:
            for kw_raw in grupo["Palabra clave"].dropna():
                for word in _normalize(kw_raw).split():
                    if word not in _STOPWORDS and len(word) >= 2:
                        kw_vocab_cuenta.add(word)

        for _, fila in grupo.iterrows():
            termino_raw = fila["Término de búsqueda"]
            termino_norm = _normalize(str(termino_raw))
            term_words = [
                w for w in termino_norm.split()
                if w not in _STOPWORDS and len(w) >= 2
            ]
            if not term_words:
                continue

            if campaign_vocab is not None:
                campana = fila.get("Campaña", "")
                if pd.isna(campana):
                    campana = ""
                vocab_actual = campaign_vocab.get(_normalize(campana), set())
            else:
                vocab_actual = kw_vocab_cuenta

            no_cubiertas = [
                w for w in term_words
                if not _word_covered(w, vocab_actual)
            ]

            if not no_cubiertas:
                continue

            rows.append({
                "Cuenta": cuenta_str,
                "Término de búsqueda": termino_raw,
                "Campaña": fila.get("Campaña", ""),
                "Palabra clave": fila.get("Palabra clave", ""),
                "palabras_no_cubiertas": " | ".join(no_cubiertas),
                "Clics": fila.get("Clics", np.nan),
                "Coste": fila.get("Coste", np.nan),
                "Conversiones": fila.get("Conversiones", np.nan),
            })

    if not rows:
        return pd.DataFrame(columns=[
            "Cuenta", "Término de búsqueda", "Campaña", "Palabra clave",
            "palabras_no_cubiertas", "Clics", "Coste", "Conversiones",
        ])

    return pd.DataFrame(rows)
