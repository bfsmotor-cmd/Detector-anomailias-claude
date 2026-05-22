"""Persistencia local de comentarios y estado 'revisada' por campaña.

Guarda en un JSON local. Clave compuesta: 'Cuenta||Campaña'.
Se sincroniza automáticamente al subir un nuevo CSV.
"""
import json
import os
from datetime import datetime
from typing import Dict

STORE_PATH = os.path.join(os.path.dirname(__file__), ".audit_state.json")
SUGGESTIONS_PATH = os.path.join(os.path.dirname(__file__), ".suggestions_state.json")


def _key(cuenta: str, campana: str) -> str:
    return f"{cuenta}||{campana}"


def load_all() -> Dict[str, dict]:
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_all(data: Dict[str, dict]) -> None:
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


def get(cuenta: str, campana: str) -> dict:
    return load_all().get(_key(cuenta, campana), {})


def set_entry(cuenta: str, campana: str, revisada: bool, comentario: str) -> None:
    data = load_all()
    k = _key(cuenta, campana)
    # No persistir entradas vacías
    if not revisada and not (comentario or "").strip():
        data.pop(k, None)
    else:
        data[k] = {
            "cuenta": cuenta,
            "campana": campana,
            "revisada": bool(revisada),
            "comentario": (comentario or "").strip(),
            "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
        }
    save_all(data)


def reset_revisadas() -> int:
    """Desmarca todas las casillas 'revisada' pero conserva los comentarios.

    - Entradas con comentario: revisada → False, comentario intacto.
    - Entradas sin comentario y revisada=True: se eliminan (no aportan estado).

    Devuelve el número de entradas afectadas.
    """
    data = load_all()
    now = datetime.now().isoformat(timespec="seconds")
    afectadas = 0
    for k in list(data.keys()):
        entry = data[k]
        if not entry.get("revisada"):
            continue
        afectadas += 1
        if (entry.get("comentario") or "").strip():
            entry["revisada"] = False
            entry["ultima_actualizacion"] = now
        else:
            data.pop(k, None)
    save_all(data)
    return afectadas


def sync_bulk(rows: list) -> None:
    """Recibe lista de dicts con cuenta/campana/revisada/comentario y guarda todo."""
    data = load_all()
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        k = _key(r["cuenta"], r["campana"])
        rev = bool(r.get("revisada", False))
        com = (r.get("comentario") or "").strip()
        if not rev and not com:
            data.pop(k, None)
            continue
        data[k] = {
            "cuenta": r["cuenta"],
            "campana": r["campana"],
            "revisada": rev,
            "comentario": com,
            "ultima_actualizacion": now,
        }
    save_all(data)


def hydrate(cuenta: str, campana: str) -> tuple[bool, str]:
    """Devuelve (revisada, comentario) para una campaña."""
    entry = get(cuenta, campana)
    return bool(entry.get("revisada", False)), entry.get("comentario", "")


def import_from_audit_csv(file_bytes: bytes) -> dict:
    """Importa un CSV de auditoría exportado previamente y fusiona los
    estados 'Revisada' + 'Comentarios' con el store local.

    Pensado para sincronizar entre equipos: un colaborador descarga el CSV
    de auditoría, lo comparte, y otro lo carga en su instancia para tener
    los mismos comentarios y campañas revisadas.

    Política de merge:
    - Si la fila tiene revisada=True o comentario no vacío, se importa
      (sobreescribe lo que haya local).
    - Si tiene ambos vacíos, se ignora (no borra entradas existentes).
    - Los nombres se hacen match exacto por (Cuenta, Campaña).

    Devuelve dict con estadísticas: {importadas, filas_totales}.
    Lanza ValueError si el CSV no tiene las columnas requeridas.
    """
    import io
    import pandas as pd

    text = file_bytes.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text))

    required = {"Cuenta", "Campaña"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"El CSV no tiene columnas requeridas: {', '.join(sorted(missing))}. "
            f"¿Es un CSV de auditoría exportado desde este dashboard?"
        )

    has_revisada = "Revisada" in df.columns
    has_comentarios = "Comentarios" in df.columns
    if not has_revisada and not has_comentarios:
        raise ValueError(
            "El CSV no tiene ni la columna 'Revisada' ni 'Comentarios'. Nada para importar."
        )

    truthy = {"true", "1", "yes", "sí", "si", "x", "verdadero"}
    rows = []
    for _, r in df.iterrows():
        cuenta = str(r["Cuenta"]).strip() if pd.notna(r["Cuenta"]) else ""
        campana = str(r["Campaña"]).strip() if pd.notna(r["Campaña"]) else ""
        if not cuenta or not campana:
            continue

        rev = False
        if has_revisada:
            val = r["Revisada"]
            if pd.notna(val):
                rev = str(val).strip().lower() in truthy

        com = ""
        if has_comentarios:
            val = r["Comentarios"]
            if pd.notna(val):
                com = str(val).strip()

        if not rev and not com:
            continue

        rows.append({
            "cuenta": cuenta,
            "campana": campana,
            "revisada": rev,
            "comentario": com,
        })

    if rows:
        sync_bulk(rows)

    return {"importadas": len(rows), "filas_totales": int(len(df))}


# ─── Sugerencias de optimización ─────────────────────────────────────────────
# Clave: 'Cuenta||Campaña||Categoría' — varias sugerencias por campaña.

def _sug_key(cuenta: str, campana: str, categoria: str) -> str:
    return f"{cuenta}||{campana}||{categoria}"


def load_suggestions_state() -> Dict[str, dict]:
    if not os.path.exists(SUGGESTIONS_PATH):
        return {}
    try:
        with open(SUGGESTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_suggestions_state(data: Dict[str, dict]) -> None:
    tmp = SUGGESTIONS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SUGGESTIONS_PATH)


def hydrate_suggestion(cuenta: str, campana: str, categoria: str) -> tuple[str, str, str]:
    """Devuelve (estado, asignado_a, nota)."""
    entry = load_suggestions_state().get(_sug_key(cuenta, campana, categoria), {})
    return (
        entry.get("estado", "Pendiente"),
        entry.get("asignado_a", ""),
        entry.get("nota", ""),
    )


def sync_suggestions_bulk(rows: list) -> None:
    """rows: dicts con cuenta/campana/categoria/estado/asignado_a/nota."""
    data = load_suggestions_state()
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        k = _sug_key(r["cuenta"], r["campana"], r["categoria"])
        estado = (r.get("estado") or "Pendiente").strip()
        asignado = (r.get("asignado_a") or "").strip()
        nota = (r.get("nota") or "").strip()
        if estado == "Pendiente" and not asignado and not nota:
            data.pop(k, None)
            continue
        data[k] = {
            "cuenta": r["cuenta"],
            "campana": r["campana"],
            "categoria": r["categoria"],
            "estado": estado,
            "asignado_a": asignado,
            "nota": nota,
            "ultima_actualizacion": now,
        }
    save_suggestions_state(data)
