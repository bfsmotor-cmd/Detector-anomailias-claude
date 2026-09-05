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


# Súbelo cada vez que se añada una tabla o columna. `init_db` está cacheada con
# `cache_resource`, que sobrevive a los reruns y también a un push en Streamlit
# Cloud mientras el proceso siga vivo: sin este argumento el CREATE TABLE nuevo
# no llegaría a ejecutarse y la app fallaría contra un esquema viejo.
SCHEMA_VERSION = 2


@st.cache_resource
def init_db(schema_version: int = SCHEMA_VERSION) -> bool:
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
            CREATE TABLE IF NOT EXISTS search_term_notes (
                cuenta TEXT NOT NULL,
                campana TEXT NOT NULL,
                termino TEXT NOT NULL,
                veredicto TEXT NOT NULL DEFAULT '',
                nota TEXT NOT NULL DEFAULT '',
                ultima_actualizacion TIMESTAMP NOT NULL,
                PRIMARY KEY (cuenta, campana, termino)
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


def _load_shared_file_meta(kind: str) -> Optional[Tuple[str, datetime]]:
    """Devuelve (filename, uploaded_at) o None. Sin el BYTEA: son unos pocos bytes.

    Se consulta en cada rerun para detectar al instante si otra persona subió
    un archivo nuevo, sin pagar el coste de descargar el contenido.
    """
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT filename, uploaded_at FROM shared_files WHERE kind = :kind
        """), {"kind": kind}).fetchone()
    if row is None:
        return None
    return row.filename, row.uploaded_at


@st.cache_data(max_entries=8, show_spinner=False)
def _load_shared_file_content(kind: str, filename: str, uploaded_at: datetime) -> bytes:
    """Descarga el BYTEA. Cacheado por (kind, filename, uploaded_at).

    'uploaded_at' cambia con cada subida, así que la caché se invalida sola
    cuando alguien sube un archivo nuevo, pero NO en cada rerun de Streamlit.
    Los tres argumentos forman la clave de caché: no llevan '_' delante a
    propósito, porque ese prefijo los excluiría del hash.
    """
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT content FROM shared_files WHERE kind = :kind
        """), {"kind": kind}).fetchone()
    return bytes(row.content) if row is not None else b""


def load_shared_file(kind: str) -> Optional[Tuple[str, bytes, datetime]]:
    """Devuelve (filename, content, uploaded_at) o None si no hay nada guardado.

    Streamlit reejecuta el script entero en cada interacción, así que descargar
    el CSV completo aquí en cada rerun disparaba el egress de la base de datos.
    Ahora la consulta se parte en dos: metadata barata en cada rerun y contenido
    cacheado hasta que la metadata cambie.
    """
    meta = _load_shared_file_meta(kind)
    if meta is None:
        return None
    filename, uploaded_at = meta
    content = _load_shared_file_content(kind, filename, uploaded_at)
    if not content:
        return None
    return filename, content, uploaded_at
