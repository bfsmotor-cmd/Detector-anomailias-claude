"""Editor del ranking: navegación y notas compartidas por cuenta."""
import hashlib
import json

import streamlit as st

import comments_store


def render_ranking(tabla, column_config):
    """Devuelve la cuenta seleccionada y guarda notas al confirmar cada celda."""
    prefix = "_search_account_notes"
    pending = st.session_state.setdefault(f"{prefix}_pending", {})
    try:
        notes = comments_store.load_search_account_notes()
        st.session_state[f"{prefix}_cache"] = notes.copy()
        editable = True
    except Exception:
        notes = st.session_state.get(f"{prefix}_cache", {}).copy()
        editable = False
        st.warning(
            "No se pudieron cargar las notas por cuenta desde la base de datos. "
            "Se muestra la última copia disponible; la edición de notas estará "
            "deshabilitada hasta recuperar la conexión."
        )

    def save(cuenta, nota):
        try:
            comments_store.set_search_account_note(cuenta, nota)
        except Exception:
            pending[cuenta] = nota
            return False
        pending.pop(cuenta, None)
        st.session_state.setdefault(f"{prefix}_cache", {})[cuenta] = nota
        return True

    tabla = tabla.copy()
    selected = st.session_state.get(f"{prefix}_selected")
    if selected not in tabla["Cuenta"].values:
        selected = None
        st.session_state[f"{prefix}_selected"] = None
    tabla.insert(0, "Ver detalle", tabla["Cuenta"].eq(selected))
    tabla["Notas de revisión"] = [
        pending.get(cuenta, notes.get(cuenta, "")) for cuenta in tabla["Cuenta"]
    ]
    # La nota se consulta mientras se interpreta el score. Ubicarla junto a
    # esa métrica evita recorrer toda la tabla hasta la última columna.
    score_column = "score_promedio"
    if score_column in tabla.columns:
        posicion_nota = tabla.columns.get_loc(score_column) + 1
        nota = tabla.pop("Notas de revisión")
        tabla.insert(posicion_nota, "Notas de revisión", nota)
    # Cada evento consume el delta y estrena editor: evita volver a guardar
    # ediciones acumuladas y sobrescribir cambios posteriores de otra persona.
    revision = st.session_state.get(f"{prefix}_revision", 0)
    accounts = json.dumps(tabla["Cuenta"].tolist(), ensure_ascii=False)
    identity = hashlib.sha256(accounts.encode()).hexdigest()[:16]
    editor_key = f"search_account_ranking::{identity}::{revision}"

    def on_change():
        edits = (st.session_state.get(editor_key) or {}).get("edited_rows", {})
        saved = 0
        for pos, changes in edits.items():
            row = tabla.iloc[int(pos)]
            cuenta = row["Cuenta"]
            if "Ver detalle" in changes:
                if changes["Ver detalle"]:
                    st.session_state[f"{prefix}_selected"] = cuenta
                elif st.session_state.get(f"{prefix}_selected") == cuenta:
                    st.session_state[f"{prefix}_selected"] = None
            if editable and "Notas de revisión" in changes:
                nota = (changes["Notas de revisión"] or "").strip()
                if nota != row["Notas de revisión"]:
                    saved += int(save(cuenta, nota))
        st.session_state[f"{prefix}_saved"] = saved
        st.session_state[f"{prefix}_revision"] = revision + 1

    config = dict(column_config)
    config["Ver detalle"] = st.column_config.CheckboxColumn(
        "Ver detalle", width="small", pinned=True,
        help="Marca una cuenta para abrir su detalle por término.",
    )
    config["Notas de revisión"] = st.column_config.TextColumn(
        "Notas de revisión", width="large", max_chars=500,
        help="Notas sobre la revisión de términos de esta cuenta. "
             "Se guardan automáticamente al presionar Enter o salir de la celda.",
    )
    enabled = {"Ver detalle", "Notas de revisión"} if editable else {"Ver detalle"}
    st.data_editor(
        tabla, column_config=config, hide_index=True, use_container_width=True,
        disabled=[c for c in tabla.columns if c not in enabled],
        key=editor_key, on_change=on_change,
    )
    st.caption(
        "✏️ Escribe en **Notas de revisión**: cada cambio se guarda automáticamente "
        "en la base de datos compartida al presionar Enter o salir de la celda."
    )
    if pending:
        st.error(
            f"Hay {len(pending)} nota(s) por cuenta sin guardar. Siguen visibles, "
            "pero se perderían al cerrar la sesión. Reintenta cuando vuelva la conexión."
        )
        if st.button("🔁 Reintentar guardado de notas por cuenta", key=f"{prefix}_retry"):
            saved = sum(int(save(cuenta, nota)) for cuenta, nota in list(pending.items()))
            st.session_state[f"{prefix}_saved"] = saved
            st.session_state[f"{prefix}_revision"] = revision + 1
            st.rerun()
    saved = st.session_state.pop(f"{prefix}_saved", 0)
    if saved:
        st.toast(f"💾 {saved} nota(s) por cuenta guardada(s) automáticamente.", icon="✅")
    return selected
