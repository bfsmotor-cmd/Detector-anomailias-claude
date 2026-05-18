# Detector de Anomalías – Google Ads

Dashboard en Streamlit para analizar exports CSV de campañas de Google Ads (MCC) y detectar automáticamente anomalías.

## Funcionalidades

- 🔴 **Sin movimiento hoy** – Campañas activas sin clics ni coste en la fecha más reciente
- 🟠 **Sin movimiento ayer** – Campañas activas sin actividad el día anterior
- 🟡 **Sin conversiones** – Cuentas sin conversiones en los últimos N días
- 🔵 **Presupuesto no consumido** – Campañas que no alcanzaron el % objetivo de presupuesto en los últimos N días
- 📊 **Ranking** – Top de campañas por conversiones, coste, clics, CPA o CPC

## Uso

```bash
pip install -r requirements.txt
streamlit run app.py
```

Luego sube tu CSV exportado desde Google Ads MCC con las columnas habituales: Día, Campaña, Cuenta, Coste, Presupuesto, Conversiones, Clics, etc.

## Stack

- Python 3.9+
- Streamlit
- Pandas
- Plotly
