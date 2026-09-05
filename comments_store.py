"""Persistencia compartida (PostgreSQL) de comentarios y estado 'revisada' por campaña.

Clave compuesta: (Cuenta, Campaña). Se sincroniza automáticamente al subir un nuevo CSV.
Todo el equipo lee y escribe sobre la misma base de datos, así que los cambios
de una persona son visibles de inmediato para las demás.
"""
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import text

import db


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def load_search_account_notes() -> Dict[str, str]:
    """Notas de revisión de términos por cuenta, compartidas entre cargas de CSV."""
    with db.get_engine().begin() as conn:
        rows = conn.execute(text("SELECT cuenta, nota FROM search_account_notes")).fetchall()
    return {r.cuenta: r.nota or "" for r in rows}


def set_search_account_note(cuenta: str, nota: str) -> None:
    """Guarda solo la cuenta editada; vaciar la celda elimina su nota."""
    nota = (nota or "").strip()
    with db.get_engine().begin() as conn:
        if not nota:
            conn.execute(text("DELETE FROM search_account_notes WHERE cuenta = :cuenta"),
                         {"cuenta": cuenta})
        else:
            conn.execute(text("""
                INSERT INTO search_account_notes (cuenta, nota, ultima_actualizacion)
                VALUES (:cuenta, :nota, :ultima_actualizacion)
                ON CONFLICT (cuenta) DO UPDATE SET
                    nota = EXCLUDED.nota,
                    ultima_actualizacion = EXCLUDED.ultima_actualizacion
            """), {"cuenta": cuenta, "nota": nota, "ultima_actualizacion": datetime.now()})


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


# ─── Notas por término de búsqueda ───────────────────────────────────────────
# Clave: (Cuenta, Campaña, Término). Sirve para dejar constancia de por qué un
# término con score bajo es en realidad bueno: Google opera cada vez más en
# concordancia amplia, así que la palabra no coincide con la KW pero la
# intención sí es relevante. Marcarlo una vez evita volver a revisarlo en la
# siguiente auditoría.

VEREDICTO_DEFAULT = "Sin revisar"
VEREDICTOS_TERMINO = [
    VEREDICTO_DEFAULT,
    "Relevante",       # falso negativo: score bajo pero intención buena
    "Irrelevante",     # confirmado malo: candidato a negativa
    "Dudoso",          # hay que mirarlo con el cliente / más datos
]


def clave_termino(campana, termino) -> str:
    return f"{str(campana or '').strip()}||{str(termino or '').strip()}"


def load_search_term_notes(cuenta: str) -> Dict[str, dict]:
    """Notas de UNA cuenta, indexadas por 'Campaña||Término'.

    Se consulta por cuenta y no todo el histórico porque el detalle siempre se
    mira de una cuenta a la vez y Streamlit reejecuta el script entero en cada
    interacción: traer la tabla completa en cada rerun dispararía el egress.
    """
    engine = db.get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT campana, termino, veredicto, nota, ultima_actualizacion
            FROM search_term_notes WHERE cuenta = :cuenta
        """), {"cuenta": cuenta}).fetchall()
    return {
        clave_termino(r.campana, r.termino): {
            "campana": r.campana,
            "termino": r.termino,
            "veredicto": r.veredicto or VEREDICTO_DEFAULT,
            "nota": r.nota or "",
            "ultima_actualizacion": _iso(r.ultima_actualizacion),
        }
        for r in rows
    }


def set_search_term_note(
    cuenta: str, campana: str, termino: str, veredicto: str, nota: str,
) -> None:
    veredicto = (veredicto or "").strip()
    if veredicto == VEREDICTO_DEFAULT:
        veredicto = ""
    nota = (nota or "").strip()

    engine = db.get_engine()
    with engine.begin() as conn:
        if not veredicto and not nota:
            conn.execute(text("""
                DELETE FROM search_term_notes
                WHERE cuenta = :cuenta AND campana = :campana AND termino = :termino
            """), {"cuenta": cuenta, "campana": campana, "termino": termino})
        else:
            conn.execute(text("""
                INSERT INTO search_term_notes
                    (cuenta, campana, termino, veredicto, nota, ultima_actualizacion)
                VALUES
                    (:cuenta, :campana, :termino, :veredicto, :nota, :ultima_actualizacion)
                ON CONFLICT (cuenta, campana, termino) DO UPDATE SET
                    veredicto = EXCLUDED.veredicto,
                    nota = EXCLUDED.nota,
                    ultima_actualizacion = EXCLUDED.ultima_actualizacion
            """), {
                "cuenta": cuenta,
                "campana": campana,
                "termino": termino,
                "veredicto": veredicto,
                "nota": nota,
                "ultima_actualizacion": datetime.now(),
            })


def count_search_term_notes(cuenta: Optional[str] = None) -> int:
    """Número de términos anotados (de una cuenta, o de todas si es None)."""
    engine = db.get_engine()
    with engine.begin() as conn:
        if cuenta is None:
            row = conn.execute(text(
                "SELECT COUNT(*) AS n FROM search_term_notes"
            )).fetchone()
        else:
            row = conn.execute(text(
                "SELECT COUNT(*) AS n FROM search_term_notes WHERE cuenta = :cuenta"
            ), {"cuenta": cuenta}).fetchone()
    return int(row.n) if row else 0


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
