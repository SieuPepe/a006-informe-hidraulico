# A006 — Generador de Informes de Análisis Hidráulico

Script de automatización para la generación de informes de la Actuación A006 del Proyecto URBITIK (Consorcio de Aguas de Álava – Urbide).

## Descripción

Este script se conecta a la base de datos PostgreSQL/Giswater, extrae los datos de la red hidráulica y los resultados de simulación EPANET, y genera automáticamente el informe de análisis hidráulico en formato Word para cada municipio del ámbito de estudio.

## Instalación

1. Clona el repositorio
2. Copia `config_example.py` como `config.py` y rellena tus credenciales
3. Instala las dependencias:

```
pip install -r requirements.txt
```

## Uso

```
python main.py
```

El script te pedirá interactivamente:
- `muni_id`: ID del municipio en la base de datos
- `sector_ids`: IDs de los sectores hidráulicos del municipio
- `result_id`: Nombre de la simulación EPANET importada en Giswater
- Ruta de la plantilla Word
- Texto descriptivo de la sectorización

## Estructura del proyecto

```
a006_informe/
├── main.py              # Script principal
├── config.py            # Credenciales (no incluido en repo)
├── config_example.py    # Plantilla de credenciales
├── requirements.txt
├── db/
│   ├── connection.py    # Conexión a PostgreSQL
│   └── queries.py       # Consultas SQL
├── word/
│   ├── properties.py    # Relleno de campos DOCPROPERTY
│   ├── tables.py        # Relleno de tablas
│   ├── bookmarks.py     # Relleno de marcadores
│   └── sectors.py       # Replicación de bloques de sector
└── ai/
    └── generator.py     # Generación de textos con Claude API
```

## Notas técnicas

- La plantilla Word debe tener los marcadores `{{TABLA_XXX}}` en texto oculto en la primera celda de cada tabla a rellenar.
- Los bookmarks narrativos deben existir en el documento con texto oculto.
- Los resultados EPANET deben estar importados en Giswater antes de ejecutar el script.
