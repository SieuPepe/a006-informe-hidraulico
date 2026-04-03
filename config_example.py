# ============================================================
# CONFIGURACION — EJEMPLO
# Copia este archivo como config.py y rellena los valores reales.
# IMPORTANTE: config.py está en .gitignore y NUNCA se sube al repo.
# ============================================================

# Conexion a PostgreSQL (servidor Giswater)
# NOTA: Estas credenciales son las del SERVIDOR PostgreSQL,
#       no las de la interfaz web de pgAdmin.
#       Las encontrarás en QGIS > Administrador de fuentes de datos > PostgreSQL
DB_HOST = "192.168.1.153"
DB_PORT = 5432
DB_NAME = "NOMBRE_DE_LA_BD"       # Nombre de la base de datos PostgreSQL — confirmar en pgAdmin
DB_USER = "postgres"
DB_PASSWORD = "postgres"

# Esquema de Giswater (compartido por todos los municipios)
DB_SCHEMA = "abastecimiento"

# API Key de Anthropic para generación de textos con Claude
# Obtenerla en: https://console.anthropic.com/
ANTHROPIC_API_KEY = "sk-ant-..."

# Directorio de salida para los informes generados
OUTPUT_DIR = "output"
