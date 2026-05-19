import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import analyzer
import comments_store
import search_terms_analyzer

# ─── Config ──────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Detector de Anomalías – Google Ads",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Estilos ──────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.metric-card {
    background: #1e1e2e;
    border-radius: 12px;
    padding: 20px 24px;
    border-left: 4px solid #6366f1;
}
.anomaly-header {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 4px;
}
.stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔍 Detector de Anomalías")
    st.caption("Google Ads · MCC Dashboard")
    st.divider()

    uploaded_file = st.file_uploader(
        "Sube tu CSV de Google Ads",
        type=["csv"],
        help="Exporta el reporte directamente desde Google Ads o el Editor MCC.",
    )

    st.divider()
    st.subheader("🔎 Términos de búsqueda")
    search_terms_file = st.file_uploader(
        "Reporte de términos de búsqueda",
        type=["csv"],
        key="search_terms_upl",
        help="Export del 'Informe de términos de búsqueda' de Google Ads.",
    )
    quality_threshold = st.slider(
        "Umbral de calidad (%)",
        50, 90, 70,
        key="quality_thr",
        help="Cuentas con score promedio por debajo de este umbral generan alerta.",
    )

    st.divider()
    st.subheader("Filtros")
    show_paused = st.checkbox(
        "Mostrar campañas pausadas",
        value=False,
        help="Por defecto se ocultan las campañas con estado 'Pausada'. Actívalo para incluirlas en métricas y tablas.",
    )

    st.divider()
    st.subheader("Parámetros")
    threshold_pct = st.slider(
        "Umbral de consumo de presupuesto (%)",
        min_value=50, max_value=100, value=90, step=5,
        help="Se marcan como anomalía las campañas que no alcanzaron este % del presupuesto diario.",
    )
    budget_days = st.slider("Ventana presupuesto (días)", 3, 14, 7)
    conv_days = st.slider("Ventana conversiones sin actividad (días)", 2, 7, 3)
    ranking_days = st.slider("Ventana ranking (días)", 7, 90, 30)

    st.divider()
    st.subheader("Reglas auditoría")
    conv_rate_threshold_pct = st.slider(
        "Tasa de conversión 7d mínima (%)", 1, 50, 10,
        help="Campañas con tasa < a este valor se marcan como anomalía.",
    )

    st.divider()
    st.subheader("Sugerencias de optimización")
    opt_window_days = st.slider("Ventana de análisis (días)", 3, 30, 7, key="opt_window")
    opt_lost_budget = st.slider("% impr. perdidas por presupuesto (mín)", 5, 50, 20, key="opt_lost_b")
    opt_lost_rank = st.slider("% impr. perdidas por ranking (mín)", 10, 60, 30, key="opt_lost_r")
    opt_min_clicks_no_conv = st.slider("Clics sin conversión para sugerir pausa", 10, 200, 30, key="opt_clicks_pause")
    opt_ctr_search = st.slider("CTR mínimo Search (%)", 1, 10, 3, key="opt_ctr_s")
    opt_roas_min = st.slider("ROAS mínimo (x)", 1, 10, 2, key="opt_roas")

    st.divider()
    st.caption("v1.0 · Desarrollado con Streamlit")

# ─── Main ─────────────────────────────────────────────────────────────────────

if uploaded_file is None and search_terms_file is None:
    st.title("Detector de Anomalías – Google Ads")
    st.markdown("""
    ### Cómo usar esta herramienta

    1. **Exporta** tu reporte de campañas desde Google Ads MCC con las columnas habituales (Día, Campaña, Cuenta, Coste, Presupuesto, Conversiones, Clics…)
    2. **Sube el CSV** en el panel izquierdo
    3. La herramienta detectará automáticamente:

    | Anomalía | Descripción |
    |---|---|
    | 🔴 Sin movimiento hoy | Campañas activas sin clics ni coste en la fecha más reciente |
    | 🟠 Sin movimiento ayer | Campañas activas sin clics ni coste el día anterior |
    | 🟡 Sin conversiones | Cuentas sin conversiones en los últimos N días |
    | 🔵 Presupuesto no consumido | Campañas que nunca alcanzaron el umbral de presupuesto |
    | 🎯 Sugerencias de optimización | Vista proactiva: oportunidades de puja, ranking, anuncios, ROAS y calidad |
    | 🔎 Calidad de términos de búsqueda | Score de similitud entre término y palabra clave, con alertas por cuenta |

    💡 Para aprovechar la pestaña **Sugerencias de optimización**, añade al export columnas adicionales como:
    Impresiones, CTR, Tasa de conv., Valor de conv., Valor conv./coste (ROAS), Estrategia de puja, CPA/ROAS objetivo,
    % impresiones perdidas (presupuesto/ranking), Eficacia del anuncio y Optimization score. La pestaña tolera columnas
    faltantes y solo deshabilita las reglas que las necesitan.

    🔎 Para la pestaña **Calidad de términos de búsqueda**, exporta el "Informe de términos de búsqueda" desde Google Ads
    (incluye las columnas `Término de búsqueda`, `Palabra clave`, `Campaña`, `Cuenta`, `Clics`, `Coste`...). Súbelo en el
    uploader independiente del sidebar — funciona aún sin el reporte diario.
    """)
    st.stop()


# ─── Calidad de términos de búsqueda ─────────────────────────────────────────

@st.cache_data(show_spinner="Calculando similitud de términos…")
def load_search_terms(file_bytes: bytes, filename: str) -> pd.DataFrame:
    df_terms = search_terms_analyzer.load_search_terms_csv(file_bytes)
    return search_terms_analyzer.compute_similarity(df_terms)


def render_search_terms_section(file_bytes: bytes, filename: str, threshold: int):
    st.header("🔎 Calidad de términos de búsqueda")
    st.caption(
        "Score de similitud (0–100) entre `Término de búsqueda` y `Palabra clave`. "
        "Las cuentas se ponderan por clics; las que estén por debajo del umbral generan alerta."
    )

    try:
        df_terms = load_search_terms(file_bytes, filename)
    except Exception as e:
        st.error(f"Error al procesar el reporte de términos: {e}")
        st.info("Asegúrate de exportar el 'Informe de términos de búsqueda' con codificación UTF-8.")
        return

    if df_terms.empty:
        st.warning("El archivo no contiene filas válidas.")
        return

    agg = search_terms_analyzer.aggregate_by_account(df_terms, threshold=threshold)
    n_alertadas = int(agg["alerta"].sum())
    n_cuentas = int(len(agg))

    # ── Banner de alerta ────────────────────────────────────────────────────
    if n_alertadas > 0:
        cuentas_alertadas = agg[agg["alerta"]]["Cuenta"].tolist()
        preview = ", ".join(cuentas_alertadas[:3])
        if len(cuentas_alertadas) > 3:
            preview += f", … (+{len(cuentas_alertadas) - 3})"
        st.error(
            f"🚨 **{n_alertadas} de {n_cuentas} cuentas** tienen calidad de términos < {threshold}%. "
            f"Revisar prioritariamente: _{preview}_."
        )
    else:
        st.success(f"✅ Todas las {n_cuentas} cuentas superan el umbral de {threshold}% de calidad.")

    # ── Métricas globales ───────────────────────────────────────────────────
    df_validos = df_terms[~df_terms["_sin_keyword"]]
    total_terminos = int(len(df_validos))
    n_sin_kw = int(df_terms["_sin_keyword"].sum())
    clics_validos = df_validos["Clics"].fillna(0) if "Clics" in df_validos else None
    if clics_validos is not None and clics_validos.sum() > 0:
        score_global = float((df_validos["_score_similitud"] * clics_validos).sum() / clics_validos.sum())
    else:
        score_global = float(df_validos["_score_similitud"].mean()) if total_terminos else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Términos analizados", f"{total_terminos:,}")
    m2.metric("Score global (ponderado)", f"{score_global:.1f}%")
    m3.metric("Cuentas alertadas", f"{n_alertadas} / {n_cuentas}")
    m4.metric("Sin palabra clave", f"{n_sin_kw:,}", help="Filas excluidas del cálculo por no tener palabra clave.")

    st.divider()

    # ── Tabla 1: ranking de cuentas ─────────────────────────────────────────
    st.subheader("Ranking de cuentas (peores primero)")
    tabla_cuentas = agg.copy()
    tabla_cuentas["alerta"] = tabla_cuentas["alerta"].map({True: "🚨", False: "✅"})
    st.dataframe(
        tabla_cuentas,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cuenta": st.column_config.TextColumn("Cuenta", width="large"),
            "score_promedio": st.column_config.ProgressColumn(
                "Score promedio",
                min_value=0, max_value=100,
                format="%.1f",
            ),
            "n_terminos": st.column_config.NumberColumn("Términos", format="%d"),
            "n_terminos_baja_calidad": st.column_config.NumberColumn(
                f"Bajo umbral ({threshold}%)", format="%d",
            ),
            "n_sin_keyword": st.column_config.NumberColumn("Sin keyword", format="%d"),
            "total_clics": st.column_config.NumberColumn("Clics", format="%.0f"),
            "total_coste": st.column_config.NumberColumn("Coste", format="%.2f"),
            "alerta": st.column_config.TextColumn("Alerta", width="small"),
        },
    )

    # ── Gráfico Plotly ──────────────────────────────────────────────────────
    if not agg["score_promedio"].isna().all():
        fig = go.Figure()
        plot_df = agg.dropna(subset=["score_promedio"]).copy()
        colors = ["#ef4444" if a else "#10b981" for a in plot_df["alerta"]]
        fig.add_trace(go.Bar(
            x=plot_df["score_promedio"],
            y=plot_df["Cuenta"],
            orientation="h",
            marker_color=colors,
            text=[f"{s:.1f}%" for s in plot_df["score_promedio"]],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}%<extra></extra>",
        ))
        fig.add_vline(x=threshold, line_dash="dash", line_color="#6366f1",
                      annotation_text=f"Umbral {threshold}%", annotation_position="top")
        fig.update_layout(
            height=max(300, 22 * len(plot_df) + 80),
            xaxis_title="Score promedio (%)",
            yaxis_title=None,
            yaxis=dict(autorange="reversed"),
            margin=dict(l=10, r=40, t=30, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Tabla 2: detalle por término ────────────────────────────────────────
    st.subheader("Detalle por término")
    cuentas_disponibles = sorted(df_terms["Cuenta"].dropna().unique().tolist())
    # Default: cuenta con peor score
    default_idx = 0
    if not agg.empty and pd.notna(agg.iloc[0]["score_promedio"]):
        peor = agg.iloc[0]["Cuenta"]
        if peor in cuentas_disponibles:
            default_idx = cuentas_disponibles.index(peor)

    sel_cuenta = st.selectbox(
        "Filtrar por cuenta",
        cuentas_disponibles,
        index=default_idx,
        key="search_terms_cuenta",
    )

    detalle = df_terms[df_terms["Cuenta"] == sel_cuenta].copy()
    detalle = detalle[~detalle["_sin_keyword"]]
    detalle = detalle.sort_values("_score_similitud", ascending=True, na_position="last")

    cols_detalle = ["Término de búsqueda", "Palabra clave", "Campaña",
                    "Tipo de concordancia", "Clics", "Coste", "Conversiones",
                    "_score_similitud"]
    cols_existentes = [c for c in cols_detalle if c in detalle.columns]
    st.dataframe(
        detalle[cols_existentes],
        use_container_width=True,
        hide_index=True,
        column_config={
            "_score_similitud": st.column_config.ProgressColumn(
                "Score similitud",
                min_value=0, max_value=100,
                format="%.1f",
            ),
            "Clics": st.column_config.NumberColumn("Clics", format="%.0f"),
            "Coste": st.column_config.NumberColumn("Coste", format="%.2f"),
            "Conversiones": st.column_config.NumberColumn("Conversiones", format="%.2f"),
        },
    )

    sin_kw_cuenta = int(df_terms[(df_terms["Cuenta"] == sel_cuenta) & df_terms["_sin_keyword"]].shape[0])
    if sin_kw_cuenta > 0:
        st.caption(f"ℹ️ {sin_kw_cuenta} fila(s) sin palabra clave excluidas del detalle.")

    st.divider()

    # ── Negativas sugeridas por sustracción de vocabulario ──────────────────
    st.subheader("🚫 Negativas sugeridas por cuenta")
    st.caption(
        "Para cada término se restan las palabras ya cubiertas por las keywords de esa cuenta. "
        "Las palabras sobrantes son las candidatas a negativa exacta `[término]`."
    )

    neg_sugeridas = search_terms_analyzer.compute_negative_suggestions(df_terms)

    if neg_sugeridas.empty:
        st.success("No se encontraron palabras sin cubrir en ninguna cuenta.")
    else:
        resumen_neg = (
            neg_sugeridas.groupby("Cuenta")
            .agg(
                n_terminos=("Término de búsqueda", "nunique"),
                total_coste=("Coste", lambda x: x.fillna(0).sum()),
            )
            .reset_index()
            .sort_values("n_terminos", ascending=False)
        )
        st.caption(f"{len(resumen_neg)} cuenta(s) con términos que contienen palabras no cubiertas por sus keywords.")

        for _, row in resumen_neg.iterrows():
            cuenta_neg = row["Cuenta"]
            n_neg = int(row["n_terminos"])
            total_coste_neg = float(row["total_coste"])

            label = f"{cuenta_neg}  —  {n_neg} término(s) con palabras no cubiertas"
            if total_coste_neg > 0:
                label += f"  ·  Coste acumulado: ${total_coste_neg:,.0f}"

            expanded = cuenta_neg == sel_cuenta
            with st.expander(label, expanded=expanded):
                cuenta_neg_data = neg_sugeridas[neg_sugeridas["Cuenta"] == cuenta_neg].copy()

                st.dataframe(
                    cuenta_neg_data[[
                        "Término de búsqueda", "palabras_no_cubiertas",
                        "Palabra clave", "Campaña",
                        "Clics", "Coste", "Conversiones",
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "palabras_no_cubiertas": st.column_config.TextColumn(
                            "Palabras no cubiertas",
                            help="Palabras del término que no aparecen en ninguna keyword de esta cuenta.",
                            width="medium",
                        ),
                        "Clics": st.column_config.NumberColumn("Clics", format="%.0f"),
                        "Coste": st.column_config.NumberColumn("Coste", format="%.2f"),
                        "Conversiones": st.column_config.NumberColumn("Conv.", format="%.2f"),
                    },
                )

                # Bloque copiable: el término completo como negativa exacta
                terminos_unicos = sorted(
                    cuenta_neg_data["Término de búsqueda"].dropna().unique().tolist()
                )
                negativas_texto = "\n".join(f"[{t}]" for t in terminos_unicos)
                st.caption("Copiar como negativas exactas (términos completos):")
                st.code(negativas_texto, language=None)


# ── Si solo se cargó el reporte de términos, renderizar esa sección y salir ──
if uploaded_file is None and search_terms_file is not None:
    render_search_terms_section(
        search_terms_file.getvalue(),
        search_terms_file.name,
        quality_threshold,
    )
    st.stop()


# ─── Carga y limpieza ─────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Procesando datos…")
def load_data(file_bytes: bytes, filename: str) -> pd.DataFrame:
    import io

    # Decodificar y detectar la fila de encabezados (Google Ads pone 1-3 líneas de metadata arriba)
    text = file_bytes.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    header_idx = 0
    for i, line in enumerate(lines[:10]):
        lower = line.lower()
        if ("día" in lower or "dia" in lower or "date" in lower) and ("campaña" in lower or "campaign" in lower):
            header_idx = i
            break

    # Detectar separador en la línea de header
    header_line = lines[header_idx]
    sep = "," if header_line.count(",") >= header_line.count(";") else ";"

    df_raw = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        sep=sep,
        thousands=".",
        decimal=",",
        dtype=str,
    )

    # Filtrar filas de totales que mete Google Ads.
    # Aparecen con "Estado de la campaña" = "Total: X" y la columna "Campaña" vacía.
    if "Campaña" in df_raw.columns:
        df_raw = df_raw[df_raw["Campaña"].astype(str).str.strip().replace("nan", "") != ""]
        df_raw = df_raw[~df_raw["Campaña"].astype(str).str.startswith("Total:", na=False)]
    if "Estado de la campaña" in df_raw.columns:
        df_raw = df_raw[~df_raw["Estado de la campaña"].astype(str).str.startswith("Total:", na=False)]
    df_raw = df_raw.dropna(how="all")

    return analyzer.load_and_clean(df_raw)


try:
    df_full = load_data(uploaded_file.read(), uploaded_file.name)
except Exception as e:
    st.error(f"Error al procesar el archivo: {e}")
    st.info("Asegúrate de exportar el CSV con separador `;` o `,` y codificación UTF-8.")
    st.stop()

# Filtrar campañas pausadas según toggle del sidebar
PAUSED_STATUSES = {"En pausa", "Pausada", "Paused"}
if show_paused:
    df = df_full
    paused_rows = 0
else:
    mask_paused = df_full["_estado"].isin(PAUSED_STATUSES)
    paused_rows = int(mask_paused.sum())
    df = df_full[~mask_paused].copy()

summary = analyzer.general_summary(df)
latest_date = summary["latest_date"]
yesterday = latest_date - timedelta(days=1) if latest_date else None

# ─── Header + KPIs ───────────────────────────────────────────────────────────

st.title("Dashboard de Anomalías – Google Ads")
date_min, date_max = summary["date_range"]
caption = f"Datos del {date_min.strftime('%d/%m/%Y')} al {date_max.strftime('%d/%m/%Y')}  ·  Última fecha: **{latest_date.strftime('%d/%m/%Y')}**"
if paused_rows > 0:
    paused_campaigns = df_full[df_full["_estado"].isin(PAUSED_STATUSES)]["Campaña"].nunique()
    caption += f"  ·  🔕 {paused_campaigns} campaña(s) pausadas ocultas ({paused_rows} filas)"
st.caption(caption)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cuentas", summary["total_accounts"])
c2.metric("Campañas", summary["total_campaigns"])
c3.metric("Coste total", f"${summary['total_cost']:,.2f}")
c4.metric("Conversiones totales", f"{summary['total_conversions']:,.0f}")

st.divider()

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🚨 Auditoría diaria",
    "🔴 Sin movimiento hoy",
    "🟠 Sin movimiento ayer",
    "🟡 Sin conversiones",
    "🔵 Presupuesto no consumido",
    "📊 Ranking de campañas",
    "🎯 Sugerencias de optimización",
])

# ── Tab 0: Auditoría diaria consolidada ──────────────────────────────────────
with tab0:
    st.subheader("Auditoría diaria — campañas con anomalías")
    st.caption(
        "Una fila por campaña que dispare al menos una regla. Score = suma ponderada de las "
        "reglas activas (50/40/35/20/11). Ordenado por mayor score."
    )

    audit = analyzer.compute_anomaly_table(
        df,
        conv_rate_threshold=conv_rate_threshold_pct / 100,
        budget_threshold=threshold_pct / 100,
        conv_days=conv_days,
        budget_days=budget_days,
    )

    if audit.empty:
        st.success("✅ Ninguna campaña activa dispara reglas de anomalía.")
    else:
        # KPIs rápidos
        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("Campañas con anomalía", len(audit))
        kc2.metric("Score máximo", int(audit["Score"].max()))
        kc3.metric("Score promedio", round(audit["Score"].mean(), 1))
        kc4.metric("Cuentas afectadas", audit["Cuenta"].nunique())

        # Filtros
        f1, f2 = st.columns([1, 2])
        with f1:
            min_score = st.number_input("Score mínimo", 0, int(audit["Score"].max()), 0, 5)
        with f2:
            accounts_filter = st.multiselect(
                "Filtrar por cuenta", sorted(audit["Cuenta"].unique()),
                placeholder="Todas las cuentas",
            )

        filtered_audit = audit[audit["Score"] >= min_score].copy()
        if accounts_filter:
            filtered_audit = filtered_audit[filtered_audit["Cuenta"].isin(accounts_filter)]

        # Hidratar Revisada + Comentarios desde almacenamiento local
        stored = comments_store.load_all()

        def _stored_revisada(row):
            entry = stored.get(f"{row['Cuenta']}||{row['Campaña']}", {})
            return bool(entry.get("revisada", False))

        def _stored_comentario(row):
            entry = stored.get(f"{row['Cuenta']}||{row['Campaña']}", {})
            return entry.get("comentario", "")

        filtered_audit["Revisada"] = filtered_audit.apply(_stored_revisada, axis=1)
        filtered_audit["Comentarios"] = filtered_audit.apply(_stored_comentario, axis=1)

        # Reordenar: Score primero, 'Reglas activas' al final
        col_order = [
            "Score", "Cuenta", "Campaña",
            "Clicks hoy", "Clicks ayer", "Tasa conv. 7d", "Consumo presupuesto 7d",
            "Estado", "Motivo del estado", "Revisada", "Comentarios",
            "Reglas activas",
        ]
        filtered_audit = filtered_audit[[c for c in col_order if c in filtered_audit.columns]]

        edited = st.data_editor(
            filtered_audit,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=156, format="%d",
                    width="small", pinned=True,
                ),
                "Cuenta": st.column_config.TextColumn(disabled=True, pinned=True),
                "Campaña": st.column_config.TextColumn(disabled=True, width="medium", pinned=True),
                "Reglas activas": st.column_config.TextColumn(width="large", disabled=True),
                "Clicks hoy": st.column_config.NumberColumn(disabled=True, width="small"),
                "Clicks ayer": st.column_config.NumberColumn(disabled=True, width="small"),
                "Tasa conv. 7d": st.column_config.NumberColumn(
                    "Tasa conv. 7d", format="%.1f%%", disabled=True,
                ),
                "Consumo presupuesto 7d": st.column_config.NumberColumn(
                    "Consumo ppto. 7d", format="%.1f%%", disabled=True,
                ),
                "Estado": st.column_config.TextColumn(disabled=True),
                "Motivo del estado": st.column_config.TextColumn(disabled=True, width="medium"),
                "Revisada": st.column_config.CheckboxColumn("Revisada", default=False),
                "Comentarios": st.column_config.TextColumn(
                    "Comentarios",
                    help="Notas personales. Se guardan en disco y se sincronizan por Cuenta+Campaña al subir nuevos CSV.",
                    width="large",
                    max_chars=500,
                ),
            },
            hide_index=True,
            use_container_width=True,
            height=min(600, 60 + len(filtered_audit) * 38),
            key="audit_editor",
        )

        # Detectar cambios contra lo almacenado y persistir
        cambios = []
        for _, row in edited.iterrows():
            prev_rev, prev_com = comments_store.hydrate(row["Cuenta"], row["Campaña"])
            new_rev = bool(row["Revisada"])
            new_com = (row.get("Comentarios") or "").strip()
            if new_rev != prev_rev or new_com != prev_com:
                cambios.append({
                    "cuenta": row["Cuenta"],
                    "campana": row["Campaña"],
                    "revisada": new_rev,
                    "comentario": new_com,
                })

        if cambios:
            comments_store.sync_bulk(cambios)
            st.toast(f"💾 {len(cambios)} cambio(s) guardado(s)", icon="✅")

        # Botones de acción
        c_dl, c_clr, c_info = st.columns([1, 1, 2])
        with c_dl:
            csv_audit = edited.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar auditoría (CSV)",
                csv_audit,
                f"auditoria_{latest_date.strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True,
            )
        with c_clr:
            if st.button("🗑️ Limpiar todo el historial", use_container_width=True):
                comments_store.save_all({})
                st.toast("Historial borrado", icon="🗑️")
                st.rerun()
        with c_info:
            total_persisted = len(comments_store.load_all())
            st.caption(f"💾 {total_persisted} entrada(s) guardadas en `.audit_state.json`")

# ── Tab 1: Sin movimiento HOY ─────────────────────────────────────────────────
with tab1:
    st.subheader(f"Campañas activas sin movimiento — {latest_date.strftime('%d/%m/%Y')}")
    st.caption("Campañas con estado habilitado que no registraron clics ni coste en la fecha más reciente.")

    no_move_today = analyzer.campaigns_not_moving(df, latest_date)

    if no_move_today.empty:
        st.success("✅ Todas las campañas activas tuvieron actividad hoy.")
    else:
        st.error(f"⚠️ {len(no_move_today)} campaña(s) activas sin actividad hoy")
        _cols = {"Cuenta": "Cuenta", "Campaña": "Campaña", "Estado": "Estado",
                 "Clics": "Clics", "Coste": "Coste", "Conversiones": "Conv."}
        st.dataframe(
            no_move_today.rename(columns=_cols),
            use_container_width=True,
            hide_index=True,
        )

        # Gráfico por cuenta
        if "Cuenta" in no_move_today.columns:
            by_account = no_move_today.groupby("Cuenta").size().reset_index(name="Campañas sin movimiento")
            fig = px.bar(by_account, x="Cuenta", y="Campañas sin movimiento",
                         color_discrete_sequence=["#ef4444"], title="Por cuenta")
            fig.update_layout(height=300, margin=dict(t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

# ── Tab 2: Sin movimiento AYER ────────────────────────────────────────────────
with tab2:
    if yesterday is None:
        st.warning("No hay suficientes días de datos para analizar ayer.")
    else:
        st.subheader(f"Campañas activas sin movimiento — {yesterday.strftime('%d/%m/%Y')}")
        st.caption("Campañas con estado habilitado que no registraron clics ni coste ayer.")

        no_move_yday = analyzer.campaigns_not_moving(df, yesterday)

        if no_move_yday.empty:
            st.success("✅ Todas las campañas activas tuvieron actividad ayer.")
        else:
            st.error(f"⚠️ {len(no_move_yday)} campaña(s) activas sin actividad ayer")
            st.dataframe(no_move_yday, use_container_width=True, hide_index=True)

            if "Cuenta" in no_move_yday.columns:
                by_account = no_move_yday.groupby("Cuenta").size().reset_index(name="Campañas sin movimiento")
                fig = px.bar(by_account, x="Cuenta", y="Campañas sin movimiento",
                             color_discrete_sequence=["#f97316"], title="Por cuenta")
                fig.update_layout(height=300, margin=dict(t=40, b=0))
                st.plotly_chart(fig, use_container_width=True)

# ── Tab 3: Sin conversiones ───────────────────────────────────────────────────
with tab3:
    st.subheader(f"Cuentas sin conversiones en los últimos {conv_days} días")
    st.caption(f"Cuentas que no registraron ninguna conversión en los {conv_days} días más recientes del dataset.")

    no_conv = analyzer.accounts_no_conversions(df, conv_days)

    if no_conv.empty:
        st.success(f"✅ Todas las cuentas tuvieron conversiones en los últimos {conv_days} días.")
    else:
        st.warning(f"⚠️ {len(no_conv)} cuenta(s) sin conversiones en {conv_days} días")
        st.dataframe(no_conv, use_container_width=True, hide_index=True)

        # Mostrar evolución de conversiones por cuenta afectada
        st.markdown("#### Evolución de conversiones por cuenta")
        affected_accounts = no_conv["Cuenta"].tolist()
        conv_hist = df[df["Cuenta"].isin(affected_accounts)].copy()
        if "Conversiones" in conv_hist.columns:
            conv_by_day = (
                conv_hist.groupby(["Día", "Cuenta"])["Conversiones"]
                .sum().reset_index()
            )
            fig = px.line(
                conv_by_day, x="Día", y="Conversiones", color="Cuenta",
                markers=True, title="Historial de conversiones (cuentas afectadas)",
            )
            fig.update_layout(height=350, margin=dict(t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

# ── Tab 4: Presupuesto no consumido ──────────────────────────────────────────
with tab4:
    threshold = threshold_pct / 100
    st.subheader(f"Campañas que no consumieron el {threshold_pct}% del presupuesto en {budget_days} días")
    st.caption(
        f"Campañas activas que en ninguno de los últimos {budget_days} días alcanzaron "
        f"el {threshold_pct}% del presupuesto diario asignado."
    )

    underbudget = analyzer.campaigns_underbudget(df, budget_days, threshold)

    if underbudget.empty:
        st.success(f"✅ Todas las campañas activas consumieron el {threshold_pct}% del presupuesto.")
    else:
        st.warning(f"⚠️ {len(underbudget)} campaña(s) con bajo consumo de presupuesto")

        # Color por consumo promedio
        def color_consumption(val):
            if val < 50:
                return "background-color: #fee2e2"
            elif val < 75:
                return "background-color: #fef3c7"
            return "background-color: #fefce8"

        st.dataframe(
            underbudget.style.applymap(color_consumption, subset=["Consumo promedio (%)"]),
            use_container_width=True,
            hide_index=True,
        )

        fig = px.bar(
            underbudget.sort_values("Consumo promedio (%)"),
            x="Consumo promedio (%)", y="Campaña",
            color="Consumo promedio (%)",
            color_continuous_scale=["#ef4444", "#f97316", "#eab308"],
            orientation="h",
            title="Consumo promedio de presupuesto (%)",
            hover_data=["Cuenta", "Presupuesto diario prom.", "Coste_total"],
        )
        fig.add_vline(x=threshold_pct, line_dash="dash", line_color="white",
                      annotation_text=f"Umbral {threshold_pct}%")
        fig.update_layout(height=max(300, len(underbudget) * 28 + 60),
                          margin=dict(t=40, b=0), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 5: Ranking ────────────────────────────────────────────────────────────
with tab5:
    st.subheader(f"Ranking de campañas — últimos {ranking_days} días")

    ranking = analyzer.rank_campaigns(df, ranking_days)

    if ranking.empty:
        st.warning("No hay datos suficientes para generar el ranking.")
    else:
        # Filtros
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            accounts = ["Todas"] + sorted(ranking["Cuenta"].unique().tolist())
            sel_account = st.selectbox("Filtrar por cuenta", accounts)
        with col_f2:
            sort_by = st.selectbox(
                "Ordenar por",
                [c for c in ["Conversiones", "Coste", "Clics", "CPA", "CPC"] if c in ranking.columns],
            )

        filtered = ranking.copy()
        if sel_account != "Todas":
            filtered = filtered[filtered["Cuenta"] == sel_account]

        ascending = sort_by in ("CPA", "CPC")
        filtered = filtered.sort_values(sort_by, ascending=ascending, na_position="last")
        filtered["Rank"] = range(1, len(filtered) + 1)

        st.dataframe(
            filtered.set_index("Rank"),
            use_container_width=True,
        )

        # Top 10 por conversiones
        if "Conversiones" in filtered.columns:
            top10 = filtered.head(10)
            fig = px.bar(
                top10, x="Conversiones", y="Campaña",
                color="Cuenta", orientation="h",
                title=f"Top 10 campañas por {sort_by}",
            )
            fig.update_layout(height=400, margin=dict(t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

# ── Tab 6: Sugerencias de optimización ───────────────────────────────────────
with tab6:
    st.subheader(f"Sugerencias de optimización — últimos {opt_window_days} días")
    st.caption(
        "Vista proactiva: detecta oportunidades de optimización profunda por campaña "
        "(puja, presupuesto, calidad de anuncios, ranking, rentabilidad). Una fila por sugerencia."
    )

    opt_thresholds = {
        "lost_is_budget_high": float(opt_lost_budget),
        "lost_is_rank_high": float(opt_lost_rank),
        "min_clicks_no_conv": int(opt_min_clicks_no_conv),
        "ctr_min_search": float(opt_ctr_search),
        "roas_min": float(opt_roas_min),
    }

    suggestions, disabled_rules = analyzer.compute_optimization_suggestions(
        df, thresholds=opt_thresholds, window_days=opt_window_days,
    )

    if disabled_rules:
        st.info(
            "ℹ️ Algunas reglas están deshabilitadas por columnas faltantes en el CSV: "
            + ", ".join(disabled_rules)
            + ". Añádelas al export de Google Ads para obtener más sugerencias."
        )

    kpis = analyzer.optimization_kpis(suggestions)

    # KPIs gerenciales
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Sugerencias", kpis["total"])
    k2.metric("Severidad Alta", kpis["alta"])
    k3.metric("Severidad Media", kpis["media"])
    k4.metric("Cuentas", kpis["cuentas"])
    k5.metric("Campañas", kpis["campanas"])

    if suggestions.empty:
        st.success("✅ No se detectaron oportunidades de optimización con los umbrales actuales.")
    else:
        # Gráfico por categoría
        if kpis["por_categoria"]:
            cat_df = pd.DataFrame(
                {"Categoría": list(kpis["por_categoria"].keys()),
                 "Sugerencias": list(kpis["por_categoria"].values())}
            ).sort_values("Sugerencias", ascending=True)
            fig = px.bar(
                cat_df, x="Sugerencias", y="Categoría", orientation="h",
                color="Sugerencias", color_continuous_scale=["#6366f1", "#f97316", "#ef4444"],
                title="Sugerencias por categoría",
            )
            fig.update_layout(height=280, margin=dict(t=40, b=0), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

        # Filtros
        ff1, ff2, ff3 = st.columns(3)
        with ff1:
            sev_filter = st.multiselect(
                "Severidad", ["Alta", "Media", "Baja"], default=["Alta", "Media"],
                key="opt_sev",
            )
        with ff2:
            cat_filter = st.multiselect(
                "Categoría", sorted(suggestions["Categoría"].unique()),
                placeholder="Todas",
                key="opt_cat",
            )
        with ff3:
            acc_filter = st.multiselect(
                "Cuenta", sorted(suggestions["Cuenta"].unique()),
                placeholder="Todas",
                key="opt_acc",
            )

        filt = suggestions.copy()
        if sev_filter:
            filt = filt[filt["Severidad"].isin(sev_filter)]
        if cat_filter:
            filt = filt[filt["Categoría"].isin(cat_filter)]
        if acc_filter:
            filt = filt[filt["Cuenta"].isin(acc_filter)]

        # Hidratar estado guardado
        sug_store = comments_store.load_suggestions_state()

        def _sg(row, field, default=""):
            entry = sug_store.get(f"{row['Cuenta']}||{row['Campaña']}||{row['Categoría']}", {})
            return entry.get(field, default)

        filt["Estado"] = filt.apply(lambda r: _sg(r, "estado", "Pendiente"), axis=1)
        filt["Asignado a"] = filt.apply(lambda r: _sg(r, "asignado_a", ""), axis=1)
        filt["Nota"] = filt.apply(lambda r: _sg(r, "nota", ""), axis=1)

        col_order = [
            "Impacto", "Severidad", "Categoría", "Cuenta", "Campaña",
            "Diagnóstico", "Acción sugerida", "Métricas clave",
            "Estado", "Asignado a", "Nota",
        ]
        filt = filt[[c for c in col_order if c in filt.columns]]

        edited_sug = st.data_editor(
            filt,
            column_config={
                "Impacto": st.column_config.ProgressColumn(
                    "Impacto", min_value=0, max_value=100, format="%d",
                    width="small", pinned=True,
                ),
                "Severidad": st.column_config.TextColumn(disabled=True, width="small"),
                "Categoría": st.column_config.TextColumn(disabled=True, width="small"),
                "Cuenta": st.column_config.TextColumn(disabled=True, pinned=True),
                "Campaña": st.column_config.TextColumn(disabled=True, width="medium", pinned=True),
                "Diagnóstico": st.column_config.TextColumn(disabled=True, width="large"),
                "Acción sugerida": st.column_config.TextColumn(disabled=True, width="large"),
                "Métricas clave": st.column_config.TextColumn(disabled=True, width="medium"),
                "Estado": st.column_config.SelectboxColumn(
                    "Estado", options=["Pendiente", "En curso", "Hecho", "Descartada"],
                    default="Pendiente", required=True,
                ),
                "Asignado a": st.column_config.TextColumn("Asignado a", max_chars=80),
                "Nota": st.column_config.TextColumn("Nota", max_chars=500, width="large"),
            },
            hide_index=True,
            use_container_width=True,
            height=min(700, 60 + len(filt) * 38),
            key="opt_editor",
        )

        # Persistir cambios
        cambios = []
        for _, row in edited_sug.iterrows():
            prev_est, prev_asig, prev_nota = comments_store.hydrate_suggestion(
                row["Cuenta"], row["Campaña"], row["Categoría"],
            )
            new_est = row.get("Estado", "Pendiente") or "Pendiente"
            new_asig = (row.get("Asignado a") or "").strip()
            new_nota = (row.get("Nota") or "").strip()
            if new_est != prev_est or new_asig != prev_asig or new_nota != prev_nota:
                cambios.append({
                    "cuenta": row["Cuenta"],
                    "campana": row["Campaña"],
                    "categoria": row["Categoría"],
                    "estado": new_est,
                    "asignado_a": new_asig,
                    "nota": new_nota,
                })

        if cambios:
            comments_store.sync_suggestions_bulk(cambios)
            st.toast(f"💾 {len(cambios)} sugerencia(s) actualizada(s)", icon="✅")

        # Descarga
        d1, d2 = st.columns([1, 3])
        with d1:
            csv_sug = edited_sug.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar sugerencias (CSV)",
                csv_sug,
                f"sugerencias_{latest_date.strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True,
            )
        with d2:
            total_p = len(comments_store.load_suggestions_state())
            st.caption(f"💾 {total_p} sugerencia(s) con estado guardado en `.suggestions_state.json`")


# ─── Footer ──────────────────────────────────────────────────────────────────
st.divider()
with st.expander("Ver datos completos"):
    st.dataframe(df.drop(columns=["_estado", "_activa"], errors="ignore"), use_container_width=True)
    csv_export = df.drop(columns=["_estado", "_activa"], errors="ignore").to_csv(index=False).encode("utf-8")
    st.download_button("Descargar datos procesados (CSV)", csv_export, "datos_procesados.csv", "text/csv")


# ─── Sección de calidad de términos (si también se subió ese CSV) ────────────
if search_terms_file is not None:
    st.divider()
    render_search_terms_section(
        search_terms_file.getvalue(),
        search_terms_file.name,
        quality_threshold,
    )
