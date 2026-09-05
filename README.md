# Detector de Anomalías – Google Ads

Dashboard en Streamlit para analizar exports CSV de campañas de Google Ads (MCC) y detectar automáticamente anomalías.

## Funcionalidades

- 🔴 **Sin movimiento hoy** – Campañas activas sin clics ni coste en la fecha más reciente
- 🟠 **Sin movimiento ayer** – Campañas activas sin actividad el día anterior
- 🟡 **Sin conversiones** – Cuentas sin conversiones en los últimos N días
- 🔵 **Presupuesto no consumido** – Campañas que no alcanzaron el % objetivo de presupuesto en los últimos N días
- 📊 **Ranking** – Top de campañas por conversiones, coste, clics, CPA o CPC
- ✏️ **Notas de revisión de términos por cuenta** – Columna editable en el ranking de términos de búsqueda. Guarda en la base compartida al presionar Enter o salir de la celda; las notas se conservan entre cargas de CSV. Si falla el guardado, muestra el cambio pendiente y permite reintentarlo.

## Uso

### Servidor local de pruebas con la base real

La app lee sus credenciales desde `.streamlit/secrets.toml` mediante
`st.secrets`; no necesita un archivo `.env` ni dependencias adicionales.

1. Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml`
   si todavía no tienes el archivo local.
2. Edita **únicamente** `.streamlit/secrets.toml`: pon en `DATABASE_URL`
   la conexión real de PostgreSQL y en `APP_PASSWORD` una contraseña para
   entrar al servidor local. No pegues claves en la plantilla pública.
3. Desde la raíz del repositorio, ejecuta:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Abre http://localhost:8501 e ingresa tu `APP_PASSWORD` local.
Reinicia el servidor después de cambiar los secretos.

**La conexión es a la base real:** los cambios de notas, revisiones y archivos
afectan los datos compartidos. Al iniciar sesión, la app también inicializa
las tablas que falten.

El archivo local, sus copias con sufijo y los archivos `.env` / `.env.*`
están excluidos de Git. Solo las plantillas `.example` pueden versionarse.
Antes de publicar, verifica:

```bash
git check-ignore .streamlit/secrets.toml
git ls-files '.env' '.env.*' '*secrets.toml*'
git diff --cached
```

El primer comando debe mostrar el archivo ignorado; el segundo solo debe
listar plantillas `.example`. No uses `git add -f` para secretos: permite
saltarse las exclusiones. Estas reglas tampoco eliminan secretos que ya
estuvieran en el historial. No compartas el archivo local en adjuntos o ZIP.
En Streamlit Cloud las claves siguen configurándose en los secretos del
despliegue; no se sube el archivo local.

Luego sube tu CSV exportado desde Google Ads MCC con las columnas habituales: Día, Campaña, Cuenta, Coste, Presupuesto, Conversiones, Clics, etc.

## Stack

- Python 3.9+
- Streamlit
- Pandas
- Plotly
