"""
A006 — Generador de Informes de Análisis Hidráulico
Proyecto URBITIK — Consorcio de Aguas de Álava (Urbide)

Uso: python main.py
"""
import sys
from pathlib import Path
from db.connection import test_connection
from db.queries import (
    get_municipio_nombre,
    get_result_ids_disponibles,
    get_datos_municipio,
    get_datos_sectores,
    get_resultados_simulacion,
)


# Campos que el usuario introduce manualmente porque no están en la BD
CAMPOS_MANUALES = [
    ("habitantes", "Población abastecida (habitantes)"),
    ("topografia", "Topografía del municipio (llana/ondulada/montañosa)"),
    ("fuentes_abastecimiento", "Fuentes de abastecimiento (texto breve)"),
    ("ubicacion_depositos", "Ubicación de los depósitos (texto breve)"),
    ("descripcion_bombeos", "Descripción de los bombeos (texto breve)"),
    ("abonados_domesticos", "Número de abonados domésticos"),
    ("factores_estacionales", "Factores estacionales (texto breve)"),
    ("periodo_demanda", "Periodo de referencia de demanda (ej: 16/03/2025-23/03/2025)"),
]


def solicitar_parametros():
    """Solicita al usuario los parámetros necesarios de forma interactiva."""

    print("\n" + "=" * 60)
    print("  A006 — GENERADOR DE INFORMES DE ANÁLISIS HIDRÁULICO")
    print("=" * 60)

    # 1. Verificar conexión
    print("\n[1/8] Verificando conexión a la base de datos...")
    if not test_connection():
        print("\nERROR: No se puede conectar a la base de datos.")
        print("Comprueba los parámetros en config.py y que el servidor esté accesible.")
        sys.exit(1)

    # 2. muni_id
    print("\n[2/8] Identificación del municipio")
    muni_id = input("  Introduce el muni_id (muni_id): ").strip()
    nombre = get_municipio_nombre(muni_id)
    if not nombre:
        print(f"  ERROR: No se encontró ningún municipio con muni_id={muni_id}")
        sys.exit(1)
    print(f"  Municipio: {nombre}")

    # 3. Número de sectores y sector_ids
    print("\n[3/8] Sectores hidráulicos")
    num_sectores = int(input("  Número de sectores hidráulicos: ").strip())
    sector_ids = []
    for i in range(num_sectores):
        sid = input(f"    sector_id [{i + 1}/{num_sectores}]: ").strip()
        sector_ids.append(int(sid))
    print(f"  Sectores: {sector_ids}")

    # 4. result_id de la simulación
    print("\n[4/8] Simulación EPANET")
    disponibles = get_result_ids_disponibles()
    if disponibles:
        print("  Simulaciones disponibles en la base de datos:")
        for r in disponibles:
            print(f"    - {r['result_id']}  ({r.get('num_timesteps', '?')} timesteps)")
    result_id = input("  Introduce el result_id a usar: ").strip()

    # 5. Plantilla Word
    print("\n[5/8] Plantilla Word")
    plantilla = input("  Ruta completa de la plantilla (.docx): ").strip().strip('"')
    if not Path(plantilla).exists():
        print(f"  ERROR: No se encontró el archivo {plantilla}")
        sys.exit(1)
    print(f"  Plantilla: {Path(plantilla).name}")

    # 6. Campos manuales
    print("\n[6/8] Datos manuales del municipio")
    print("  (Introduce los valores o pulsa Enter para dejar vacío)")
    campos_manuales = {}
    for clave, descripcion in CAMPOS_MANUALES:
        valor = input(f"  {descripcion}: ").strip()
        campos_manuales[clave] = valor

    # 7. Texto de descripción de sectores
    print("\n[7/8] Descripción de la sectorización")
    print("  Escribe un párrafo descriptivo de los sectores hidráulicos del municipio.")
    print("  (Este texto se insertará en el marcador 'descripcion_sectores')")
    descripcion_sectores = input("  Texto: ").strip()

    # 8. Confirmación
    print("\n[8/8] Resumen de parámetros")
    print(f"  Municipio:  {nombre} (muni_id={muni_id})")
    print(f"  Sectores:   {sector_ids}")
    print(f"  Simulación: {result_id}")
    print(f"  Plantilla:  {Path(plantilla).name}")
    confirmar = input("\n  ¿Continuar? (s/n): ").strip().lower()
    if confirmar != "s":
        print("  Operación cancelada.")
        sys.exit(0)

    return {
        "muni_id": muni_id,
        "municipio_nombre": nombre,
        "num_sectores": num_sectores,
        "sector_ids": sector_ids,
        "result_id": result_id,
        "plantilla": plantilla,
        "descripcion_sectores": descripcion_sectores,
        "campos_manuales": campos_manuales,
    }


def main():
    # Verificar que existe config.py
    if not Path("config.py").exists():
        print("ERROR: No se encuentra config.py")
        print("Copia config_example.py como config.py y rellena tus credenciales.")
        sys.exit(1)

    # Crear directorio de salida si no existe
    from config import OUTPUT_DIR

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Solicitar parámetros
    params = solicitar_parametros()

    print("\n" + "=" * 60)
    print("  EXTRAYENDO DATOS DE LA BASE DE DATOS...")
    print("=" * 60)

    # Extraer datos
    print("\n  Datos del municipio...")
    datos_muni = get_datos_municipio(params["muni_id"], params["sector_ids"])

    print("  Datos de sectores...")
    datos_sectores = get_datos_sectores(params["sector_ids"])

    print("  Resultados de simulación...")
    resultados = get_resultados_simulacion(params["result_id"], params["sector_ids"])

    print("\n" + "=" * 60)
    print("  GENERANDO INFORME WORD...")
    print("=" * 60)

    # Importar módulos Word
    from word.properties import rellenar_docproperties
    from word.tables import rellenar_tablas
    from word.sectors import replicar_sectores
    from word.bookmarks import rellenar_marcadores

    import docx

    doc = docx.Document(params["plantilla"])

    # 1. Rellenar DOCPROPERTY
    print("\n  [1/5] Rellenando campos DOCPROPERTY...")
    rellenar_docproperties(doc, params, datos_muni, resultados)

    # 2. Rellenar tablas genéricas (capítulos 2, 3, 6)
    print("  [2/5] Rellenando tablas...")
    rellenar_tablas(doc, datos_muni, datos_sectores, resultados)

    # 3. Replicar bloques de sector (capítulo 5.3) y rellenar sus tablas
    print("  [3/5] Replicando bloques de sector...")
    replicar_sectores(doc, datos_sectores, resultados)

    # 4. Rellenar marcadores narrativos con Claude
    print("  [4/5] Generando textos con Claude API...")
    rellenar_marcadores(doc, params, datos_muni, datos_sectores, resultados)

    # 5. Guardar documento
    print("  [5/5] Guardando documento...")
    nombre_salida = (
        f"A006_{params['municipio_nombre'].upper().replace(' ', '_')}.docx"
    )
    ruta_salida = Path(OUTPUT_DIR) / nombre_salida
    doc.save(str(ruta_salida))

    print("\n" + "=" * 60)
    print(f"  ✓ Informe generado: {ruta_salida}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
