"""Persistencia compartida (PostgreSQL) de comentarios y estado 'revisada' por campaña.

Clave compuesta: (Cuenta, Campaña). Se sincroniza automáticamente al subir un nuevo CSV.
Todo el equipo lee y escribe sobre la misma base de datos, así que los cambios
de una persona son visibles de inmediato para las demás.
"""
from datetime import datetime
from typing import Dict

from sqlalchemy import text

import db


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def load_all() -> Dict[str, dict]:
    engine = db.get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT cuenta, campana, revisada, comentario, ultima_actualizacion
            FROM audit_state
        """)).fetchall()
    return {
        f"{r.cuenta}||{r.campana}": {
            "cuenta": r.cuenta,
            "campana": r.campana,
            "revisada": bool(r.revisada),
            "comentario": r.comentario or "",
            "ultima_actualizacion": _iso(r.ultima_actualizacion),
        }
        for r in rows
    }


def save_all(data: Dict[str, dict]) -> None:
    """Reemplaza todo el estado de auditoría (usado por 'Limpiar todo el historial')."""
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_state"))
        for entry in data.values():
            conn.execute(text("""
                INSERT INTO audit_state (cuenta, campana, revisada, comentario, ultima_actualizacion)
                VALUES (:cuenta, :campana, :revisada, :comentario, :ultima_actualizacion)
            """), {
                "cuenta": entry["cuenta"],
                "campana": entry["campana"],
                "revisada": bool(entry.get("revisada", False)),
                "comentario": (entry.get("comentario") or "").strip(),
                "ultima_actualizacion": datetime.now(),
            })


def get(cuenta: str, campana: str) -> dict:
    engine = db.get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT cuenta, campana, revisada, comentario, ultima_actualizacion
            FROM audit_state WHERE cuenta = :cuenta AND campana = :campana
        """), {"cuenta": cuenta, "campana": campana}).fetchone()
    if row is None:
        return {}
    return {
        "cuenta": row.cuenta,
        "campana": row.campana,
        "revisada": bool(row.revisada),
        "comentario": row.comentario or "",
        "ultima_actualizacion": _iso(row.ultima_actualizacion),
    }


def set_entry(cuenta: str, campana: str, revisada: bool, comentario: str) -> None:
    comentario = (comentario or "").strip()
    engine = db.get_engine()
    with engine.begin() as conn:
        if not revisada and not comentario:
            conn.execute(text("""
                DELETE FROM audit_state WHERE cuenta = :cuenta AND campana = :campana
            """), {"cuenta": cuenta, "campana": campana})
        else:
            conn.execute(text("""
                INSERT INTO audit_state (cuenta, campana, revisada, comentario, ultima_actualizacion)
                VALUES (:cuenta, :campana, :revisada, :comentario, :ultima_actualizacion)
                ON CONFLICT (cuenta, campana) DO UPDATE SET
                    revisada = EXCLUDED.revisada,
                    comentario = EXCLUDED.comentario,
                    ultima_actualizacion = EXCLUDED.ultima_actualizacion
            """), {
                "cuenta": cuenta,
                "campana": campana,
                "revisada": bool(revisada),
                "comentario": comentario,
                "ultima_actualizacion": datetime.now(),
            })


def reset_revisadas() -> int:
    """Desmarca todas las casillas 'revisada' pero conserva los comentarios.

    - Entradas con comentario: revisada → False, comentario intacto.
    - Entradas sin comentario y revisada=True: se eliminan (no aportan estado).

    Devuelve el número de entradas afectadas.
    """
    engine = db.get_engine()
    now = datetime.now()
    with engine.begin() as conn:
        con_comentario = conn.execute(text("""
            UPDATE audit_state SET revisada = FALSE, ultima_actualizacion = :now
            WHERE revisada = TRUE AND comentario <> ''
        """), {"now": now})
        sin_comentario = conn.execute(text("""
            DELETE FROM audit_state WHERE revisada = TRUE AND comentario = ''
        """))
    return con_comentario.rowcount + sin_comentario.rowcount


def sync_bulk(rows: list) -> None:
    """Recibe lista de dicts con cuenta/campana/revisada/comentario y guarda todo."""
    engine = db.get_engine()
    now = datetime.now()
    with engine.begin() as conn:
        for r in rows:
            cuenta, campana = r["cuenta"], r["campana"]
            rev = bool(r.get("revisada", False))
            com = (r.get("comentario") or "").strip()
            if not rev and not com:
                conn.execute(text("""
                    DELETE FROM audit_state WHERE cuenta = :cuenta AND campana = :campana
                """), {"cuenta": cuenta, "campana": campana})
            else:
                conn.execute(text("""
                    INSERT INTO audit_state (cuenta, campana, revisada, comentario, ultima_actualizacion)
                    VALUES (:cuenta, :campana, :revisada, :comentario, :ultima_actualizacion)
                    ON CONFLICT (cuenta, campana) DO UPDATE SET
                        revisada = EXCLUDED.revisada,
                        comentario = EXCLUDED.comentario,
                        ultima_actualizacion = EXCLUDED.ultima_actualizacion
                """), {
                    "cuenta": cuenta,
                    "campana": campana,
                    "revisada": rev,
                    "comentario": com,
                    "ultima_actualizacion": now,
                })


def hydrate(cuenta: str, campana: str) -> tuple[bool, str]:
    """Devuelve (revisada, comentario) para una campaña."""
    entry = get(cuenta, campana)
    return bool(entry.get("revisada", False)), entry.get("comentario", "")


def import_from_audit_csv(file_bytes: bytes) -> dict:
    """Importa un CSV de auditoría exportado previamente y fusiona los
    estados 'Revisada' + 'Comentarios' con la base de datos compartida.

    Útil para fusionar auditorías hechas offline o en otra instancia.

    Política de merge:
    - Si la fila tiene revisada=True o comentario no vacío, se importa
      (sobreescribe lo que haya).
    - Si tiene ambos vacíos, se ignora (no borra entradas existentes).
    - Los nombres se hacen match exacto por (Cuenta, Campaña).

    Devuelve dict con estadísticas: {importadas, filas_totales}.
    Lanza ValueError si el CSV no tiene las columnas requeridas.
    """
    import io
    import pandas as pd

    text_content = file_bytes.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text_content))

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

def load_suggestions_state() -> Dict[str, dict]:
    engine = db.get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT cuenta, campana, categoria, estado, asignado_a, nota, ultima_actualizacion
            FROM suggestions_state
        """)).fetchall()
    return {
        f"{r.cuenta}||{r.campana}||{r.categoria}": {
            "cuenta": r.cuenta,
            "campana": r.campana,
            "categoria": r.categoria,
            "estado": r.estado,
            "asignado_a": r.asignado_a or "",
            "nota": r.nota or "",
            "ultima_actualizacion": _iso(r.ultima_actualizacion),
        }
        for r in rows
    }


def hydrate_suggestion(cuenta: str, campana: str, categoria: str) -> tuple[str, str, str]:
    """Devuelve (estado, asignado_a, nota)."""
    engine = db.get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT estado, asignado_a, nota FROM suggestions_state
            WHERE cuenta = :cuenta AND campana = :campana AND categoria = :categoria
        """), {"cuenta": cuenta, "campana": campana, "categoria": categoria}).fetchone()
    if row is None:
        return "Pendiente", "", ""
    return row.estado, row.asignado_a or "", row.nota or ""


def sync_suggestions_bulk(rows: list) -> None:
    """rows: dicts con cuenta/campana/categoria/estado/asignado_a/nota."""
    engine = db.get_engine()
    now = datetime.now()
    with engine.begin() as conn:
        for r in rows:
            cuenta, campana, categoria = r["cuenta"], r["campana"], r["categoria"]
            estado = (r.get("estado") or "Pendiente").strip()
            asignado = (r.get("asignado_a") or "").strip()
            nota = (r.get("nota") or "").strip()
            if estado == "Pendiente" and not asignado and not nota:
                conn.execute(text("""
                    DELETE FROM suggestions_state
                    WHERE cuenta = :cuenta AND campana = :campana AND categoria = :categoria
                """), {"cuenta": cuenta, "campana": campana, "categoria": categoria})
            else:
                conn.execute(text("""
                    INSERT INTO suggestions_state
                        (cuenta, campana, categoria, estado, asignado_a, nota, ultima_actualizacion)
                    VALUES
                        (:cuenta, :campana, :categoria, :estado, :asignado_a, :nota, :ultima_actualizacion)
                    ON CONFLICT (cuenta, campana, categoria) DO UPDATE SET
                        estado = EXCLUDED.estado,
                        asignado_a = EXCLUDED.asignado_a,
                        nota = EXCLUDED.nota,
                        ultima_actualizacion = EXCLUDED.ultima_actualizacion
                """), {
                    "cuenta": cuenta,
                    "campana": campana,
                    "categoria": categoria,
                    "estado": estado,
                    "asignado_a": asignado,
                    "nota": nota,
                    "ultima_actualizacion": now,
                })


# ─── Fit Meta Ads: gestión comercial por cuenta ──────────────────────────────

META_FIT_ESTADOS = ["Pendiente", "Contactado", "Piloto Meta", "Migrado", "Descartado"]


def load_meta_fit_state() -> Dict[str, dict]:
    engine = db.get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT cuenta, estado, asignado_a, nota, ultima_actualizacion
            FROM meta_fit_state
        """)).fetchall()
    return {
        r.cuenta: {
            "cuenta": r.cuenta,
            "estado": r.estado,
            "asignado_a": r.asignado_a or "",
            "nota": r.nota or "",
            "ultima_actualizacion": _iso(r.ultima_actualizacion),
        }
        for r in rows
    }


def sync_meta_fit_bulk(rows: list) -> None:
    """rows: dicts con cuenta/estado/asignado_a/nota."""
    engine = db.get_engine()
    now = datetime.now()
    with engine.begin() as conn:
        for r in rows:
            cuenta = r["cuenta"]
            estado = (r.get("estado") or "Pendiente").strip()
            asignado = (r.get("asignado_a") or "").strip()
            nota = (r.get("nota") or "").strip()
            if estado == "Pendiente" and not asignado and not nota:
                conn.execute(
                    text("DELETE FROM meta_fit_state WHERE cuenta = :cuenta"),
                    {"cuenta": cuenta},
                )
            else:
                conn.execute(text("""
                    INSERT INTO meta_fit_state
                        (cuenta, estado, asignado_a, nota, ultima_actualizacion)
                    VALUES
                        (:cuenta, :estado, :asignado_a, :nota, :ultima_actualizacion)
                    ON CONFLICT (cuenta) DO UPDATE SET
                        estado = EXCLUDED.estado,
                        asignado_a = EXCLUDED.asignado_a,
                        nota = EXCLUDED.nota,
                        ultima_actualizacion = EXCLUDED.ultima_actualizacion
                """), {
                    "cuenta": cuenta,
                    "estado": estado,
                    "asignado_a": asignado,
                    "nota": nota,
                    "ultima_actualizacion": now,
                })
