"""Conexión y esquema de la base de datos compartida (PostgreSQL).

Permite que las 3 personas del equipo (quien sube la data, quien audita y
quien supervisa) trabajen sobre la misma información, sin depender del
filesystem efímero de Streamlit Community Cloud.
"""
from datetime import datetime
from typing import Optional, Tuple

import streamlit as st
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine():
    return create_engine(st.secrets["DATABASE_URL"], pool_pre_ping=True)


@st.cache_resource
def init_db() -> bool:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shared_files (
                kind TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                content BYTEA NOT NULL,
                uploaded_at TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_state (
                cuenta TEXT NOT NULL,
                campana TEXT NOT NULL,
                revisada BOOLEAN NOT NULL DEFAULT FALSE,
                comentario TEXT NOT NULL DEFAULT '',
                ultima_actualizacion TIMESTAMP NOT NULL,
                PRIMARY KEY (cuenta, campana)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS meta_fit_state (
                cuenta TEXT PRIMARY KEY,
                estado TEXT NOT NULL DEFAULT 'Pendiente',
                asignado_a TEXT NOT NULL DEFAULT '',
                nota TEXT NOT NULL DEFAULT '',
                ultima_actualizacion TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suggestions_state (
                cuenta TEXT NOT NULL,
                campana TEXT NOT NULL,
                categoria TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Pendiente',
                asignado_a TEXT NOT NULL DEFAULT '',
                nota TEXT NOT NULL DEFAULT '',
                ultima_actualizacion TIMESTAMP NOT NULL,
                PRIMARY KEY (cuenta, campana, categoria)
            )
        """))
    return True


def save_shared_file(kind: str, filename: str, content: bytes) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO shared_files (kind, filename, content, uploaded_at)
            VALUES (:kind, :filename, :content, :uploaded_at)
            ON CONFLICT (kind) DO UPDATE SET
                filename = EXCLUDED.filename,
                content = EXCLUDED.content,
                uploaded_at = EXCLUDED.uploaded_at
        """), {
            "kind": kind,
            "filename": filename,
            "content": content,
            "uploaded_at": datetime.now(),
        })


def load_shared_file(kind: str) -> Optional[Tuple[str, bytes, datetime]]:
    """Devuelve (filename, content, uploaded_at) o None si no hay nada guardado."""
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT filename, content, uploaded_at FROM shared_files WHERE kind = :kind
        """), {"kind": kind}).fetchone()
    if row is None:
        return None
    return row.filename, bytes(row.content), row.uploaded_at
