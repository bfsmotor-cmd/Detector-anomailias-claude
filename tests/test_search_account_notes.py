import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

import comments_store
import db


APP = '''
import pandas as pd
import streamlit as st
from search_account_notes import render_ranking
reverse = st.checkbox("Invertir orden")
accounts = ["Cuenta B", "Cuenta A"] if reverse else ["Cuenta A", "Cuenta B"]
selected = render_ranking(pd.DataFrame({"Cuenta": accounts, "score": [30, 50]}), {})
st.write("Selección: " + str(selected))
'''


class SearchAccountNotesTest(unittest.TestCase):
    def setUp(self):
        # Base aislada: usa el SQL real sin tocar las credenciales ni datos del equipo.
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.engine_patch = patch.object(db, "get_engine", return_value=self.engine)
        self.engine_patch.start()
        db.init_db.clear()
        db.init_db(db.SCHEMA_VERSION)

    def tearDown(self):
        self.engine_patch.stop()
        db.init_db.clear()
        self.engine.dispose()

    def app(self):
        app = AppTest.from_string(APP).run()
        self.assertFalse(app.exception)
        return app

    def edit(self, app, changes):
        # AppTest no expone edición de celdas; enviamos el mismo delta JSON
        # del navegador al widget real para ejecutar su callback y rerun.
        states = app._tree.get_widget_states()
        widget = states.widgets.add()
        widget.id = app.get("arrow_data_frame")[0].proto.id
        widget.string_value = json.dumps({
            "edited_rows": changes, "added_rows": [], "deleted_rows": [],
        })
        app._run(states)
        self.assertFalse(app.exception)

    def test_persistence_update_clear_and_scope(self):
        comments_store.set_search_account_note("Cuenta A", " Revisar negativas ")
        comments_store.set_search_account_note("Cuenta B", "Pendiente")
        self.assertEqual(comments_store.load_search_account_notes()["Cuenta A"], "Revisar negativas")
        comments_store.set_search_account_note("Cuenta A", "Revisión completa")
        self.assertEqual(comments_store.load_search_account_notes()["Cuenta A"], "Revisión completa")
        comments_store.set_search_account_note("Cuenta A", "")
        self.assertEqual(comments_store.load_search_account_notes(), {"Cuenta B": "Pendiente"})
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM audit_state")).scalar(), 0)
            self.assertEqual(conn.execute(text("SELECT count(*) FROM search_term_notes")).scalar(), 0)

    def test_autosave_reopen_and_clear(self):
        app = self.app()
        self.edit(app, {"0": {"Notas de revisión": "Revisar búsquedas de Bogotá"}})
        self.assertEqual(comments_store.load_search_account_notes(), {
            "Cuenta A": "Revisar búsquedas de Bogotá",
        })
        reopened = self.app()
        self.assertEqual(reopened.dataframe[0].value.iloc[0]["Notas de revisión"],
                         "Revisar búsquedas de Bogotá")
        self.edit(reopened, {"0": {"Notas de revisión": None}})
        self.assertEqual(comments_store.load_search_account_notes(), {})

    def test_failure_keeps_note_visible_and_retry_persists(self):
        app = self.app()
        with patch.object(comments_store, "set_search_account_note", side_effect=RuntimeError("offline")):
            self.edit(app, {"1": {"Notas de revisión": "Pendiente de validar"}})
        self.assertTrue(app.error)
        self.assertEqual(app.dataframe[0].value.iloc[1]["Notas de revisión"], "Pendiente de validar")
        self.assertEqual(comments_store.load_search_account_notes(), {})
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(comments_store.load_search_account_notes(), {"Cuenta B": "Pendiente de validar"})

    def test_reorder_and_navigation_do_not_replay_old_notes(self):
        app = self.app()
        self.edit(app, {"0": {"Notas de revisión": "Primera revisión"}})
        comments_store.set_search_account_note("Cuenta A", "Actualizada por otro usuario")
        self.edit(app, {"1": {"Ver detalle": True}})
        self.assertEqual(app.session_state["_search_account_notes_selected"], "Cuenta B")
        self.assertEqual(comments_store.load_search_account_notes()["Cuenta A"],
                         "Actualizada por otro usuario")
        app.checkbox[0].check().run()
        self.edit(app, {"0": {"Notas de revisión": "Nota de B"}})
        self.assertEqual(comments_store.load_search_account_notes(), {
            "Cuenta A": "Actualizada por otro usuario", "Cuenta B": "Nota de B",
        })
        self.edit(app, {"1": {"Ver detalle": True}})
        table = app.dataframe[0].value
        self.assertEqual(table.loc[table["Ver detalle"], "Cuenta"].tolist(), ["Cuenta A"])

    def test_read_failure_disables_note_editing(self):
        comments_store.set_search_account_note("Cuenta A", "Guardada")
        app = self.app()
        with patch.object(comments_store, "load_search_account_notes", side_effect=RuntimeError("offline")):
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(app.dataframe[0].value.iloc[0]["Notas de revisión"], "Guardada")
            config = json.loads(app.get("arrow_data_frame")[0].proto.columns)
            self.assertTrue(config["Notas de revisión"]["disabled"])
            self.assertFalse(config["Ver detalle"].get("disabled", False))


if __name__ == "__main__":
    unittest.main()
