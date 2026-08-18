# Detector de Anomalías – Google Ads

Dashboard en Streamlit para analizar exports CSV de campañas de Google Ads (MCC) y detectar automáticamente anomalías.

## Funcionalidades

- 🔴 **Sin movimiento hoy** – Campañas activas sin clics ni coste en la fecha más reciente
- 🟠 **Sin movimiento ayer** – Campañas activas sin actividad el día anterior
- 🟡 **Sin conversiones** – Cuentas sin conversiones en los últimos N días
- 🔵 **Presupuesto no consumido** – Campañas que no alcanzaron el % objetivo de presupuesto en los últimos N días
- 📊 **Ranking** – Top de campañas por conversiones, coste, clics, CPA o CPC
- 📘 **Fit Meta Ads** – Cuentas cuyo mercado no encaja en búsqueda y son candidatas a migrar a Meta Ads

## Fit Meta Ads

Detecta cuentas donde seguir invirtiendo en Google Ads es un riesgo de churn: mercado
demasiado caro, sin volumen de clics o sin demanda de búsqueda. Cada criterio suma
estrellas y el **Score** es el % de estrellas obtenidas.

| Criterio | Umbral por defecto | Peso |
|---|---|---|
| CPC promedio alto | > $5.000 COP | ⭐⭐⭐ |
| Volumen de clics bajo | < 8 clics/día | ⭐⭐⭐⭐ |
| Volumen de búsquedas bajo | < 300 impresiones/día | ⭐⭐⭐ |

Niveles: 🔥 **Alto** = los 3 criterios · ⚠️ **Medio** ≥ 60% del score · 🟡 **Bajo** = una sola señal.

Se evalúan solo campañas activas con al menos 3 días de datos (por defecto restringido a
campañas de Búsqueda). La pestaña incluye estado comercial por cuenta —Pendiente,
Contactado, Piloto Meta, Migrado, Descartado— compartido con el equipo, y un guion listo
para la conversación con el cliente. Todos los umbrales se ajustan en el sidebar.

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
