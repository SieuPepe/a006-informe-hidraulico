"""
Relleno de tablas en el documento Word (.docx).

Localiza las tablas mediante marcadores ocultos {{TABLA_XXX}} en la primera
celda del encabezado, elimina las filas de datos vacías existentes y añade
las filas con los datos reales extraídos de la base de datos.
"""
import logging
from lxml import etree

logger = logging.getLogger(__name__)

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ─────────────────────────────────────────────────────────────
# Utilidades para localizar y manipular tablas
# ─────────────────────────────────────────────────────────────

def _find_table_by_marker(doc, marker):
    """Busca una tabla cuyo XML contenga el texto del marcador.

    El marcador puede estar en texto oculto (vanish) dentro de cualquier celda.
    """
    for table in doc.tables:
        xml = etree.tostring(table._tbl, encoding="unicode")
        if marker in xml:
            return table
    return None


def _clear_data_rows(table, header_rows=1):
    """Elimina todas las filas de datos (excepto las de encabezado)."""
    tbl = table._tbl
    rows = tbl.findall(f"{{{NS_W}}}tr")
    for row in rows[header_rows:]:
        tbl.remove(row)


def _add_row(table, values, copy_format_from=None):
    """Añade una fila a la tabla con los valores proporcionados.

    Si copy_format_from es un índice de fila, copia el formato de esa fila.
    """
    row = table.add_row()
    for i, val in enumerate(values):
        if i < len(row.cells):
            row.cells[i].text = _fmt(val)
    return row


def _fmt(value):
    """Formatea un valor para insertar en una celda de tabla."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:g}".replace(".", ",")
    return str(value)


def _safe_get(d, key, default=""):
    """Obtiene un valor de un dict con valor por defecto."""
    val = d.get(key) if d else None
    return val if val is not None else default


# ─────────────────────────────────────────────────────────────
# Clasificación por umbrales
# ─────────────────────────────────────────────────────────────

def _clasificar_presion(p_min_punta, p_max_nocturno):
    """Clasifica el estado de presión de un sector."""
    p_min = float(p_min_punta) if p_min_punta else 999
    p_max = float(p_max_nocturno) if p_max_nocturno else 0
    if p_min < 5 or p_max > 60:
        return "Crítico"
    if p_min < 10 or p_max > 50:
        return "Deficiente"
    if p_min < 20 or p_max > 40:
        return "Aceptable"
    return "Óptimo"


def _clasificar_velocidad(vel_media):
    """Clasifica el estado de velocidad de un sector."""
    v = float(vel_media) if vel_media else 0
    if v > 1.5:
        return "Crítico"
    if v < 0.05:
        return "Deficiente"
    if v < 0.30:
        return "Aceptable"
    return "Óptimo"


def _clasificar_retencion(t_ret_h):
    """Clasifica el tiempo de retención."""
    t = float(t_ret_h) if t_ret_h else 0
    if t > 144:
        return "Crítico"
    if t > 72:
        return "Deficiente"
    if t > 24:
        return "Aceptable"
    return "Óptimo"


def _clasificar_global(*clasificaciones):
    """Devuelve la peor clasificación de las proporcionadas."""
    orden = {"Crítico": 0, "Deficiente": 1, "Aceptable": 2, "Óptimo": 3}
    peor = min(clasificaciones, key=lambda c: orden.get(c, 3))
    return peor


# ─────────────────────────────────────────────────────────────
# Funciones de relleno por tabla
# ─────────────────────────────────────────────────────────────

def _fill_fuentes(doc, datos_sectores):
    """TABLA_FUENTES — Fuentes de suministro."""
    table = _find_table_by_marker(doc, "{{TABLA_FUENTES}}")
    if not table:
        logger.warning("Tabla TABLA_FUENTES no encontrada.")
        return
    _clear_data_rows(table)
    for sector in datos_sectores:
        for f in sector.get("fuentes", []):
            _add_row(table, [
                _safe_get(f, "nombre"),
                "Reservorio",
                "",  # Caudal concesional
                "",  # Caudal medio
                _safe_get(f, "cota_toma"),
            ])


def _fill_depositos(doc, datos_sectores):
    """TABLA_DEPOSITOS — Inventario de depósitos."""
    table = _find_table_by_marker(doc, "{{TABLA_DEPOSITOS}}")
    if not table:
        logger.warning("Tabla TABLA_DEPOSITOS no encontrada.")
        return
    _clear_data_rows(table)
    for sector in datos_sectores:
        for d in sector.get("depositos", []):
            _add_row(table, [
                _safe_get(d, "nombre"),
                _safe_get(d, "cota_solera"),
                _safe_get(d, "cota_rebose"),
                _safe_get(d, "volumen_m3"),
                "",  # Función
                "",  # Alimentación
                sector.get("nombre_sector", ""),
            ])


def _fill_red_materiales(doc, datos_muni, nivel):
    """TABLA_RED_PRIMARIA / TABLA_RED_SECUNDARIA — Materiales por nivel."""
    marker = "{{TABLA_RED_PRIMARIA}}" if nivel == "primaria" else "{{TABLA_RED_SECUNDARIA}}"
    table = _find_table_by_marker(doc, marker)
    if not table:
        logger.warning("Tabla %s no encontrada.", marker)
        return
    _clear_data_rows(table)
    key = f"materiales_{nivel}"
    for m in datos_muni.get(key, []):
        _add_row(table, [
            _safe_get(m, "material"),
            _safe_get(m, "rango_diametros_mm"),
            _safe_get(m, "longitud_m"),
            _safe_get(m, "pct_total"),
        ])


def _fill_bombeos(doc, datos_sectores):
    """TABLA_BOMBEOS — Estaciones de bombeo."""
    table = _find_table_by_marker(doc, "{{TABLA_BOMBEOS}}")
    if not table:
        logger.warning("Tabla TABLA_BOMBEOS no encontrada.")
        return
    _clear_data_rows(table)
    for sector in datos_sectores:
        for b in sector.get("bombas", []):
            _add_row(table, [
                _safe_get(b, "nombre"),
                sector.get("nombre_sector", ""),
                "",  # Nº grupos
                "",  # Caudal nominal
                "",  # Altura manométrica
                "",  # Potencia
                "",  # Depósito aspiración
                "",  # Depósito impulsión
            ])


def _fill_grupos_presion(doc, datos_sectores):
    """TABLA_GRUPOS_PRESION — Grupos de presión."""
    table = _find_table_by_marker(doc, "{{TABLA_GRUPOS_PRESION}}")
    if not table:
        logger.warning("Tabla TABLA_GRUPOS_PRESION no encontrada.")
        return
    _clear_data_rows(table)
    # Los grupos de presión se rellenarán manualmente o con datos adicionales


def _fill_vrp(doc, datos_sectores):
    """TABLA_VRP — Válvulas reductoras de presión."""
    table = _find_table_by_marker(doc, "{{TABLA_VRP}}")
    if not table:
        logger.warning("Tabla TABLA_VRP no encontrada.")
        return
    _clear_data_rows(table)
    for sector in datos_sectores:
        for v in sector.get("vrp", []):
            _add_row(table, [
                _safe_get(v, "nombre"),
                sector.get("nombre_sector", ""),
                "",  # Diámetro
                "",  # Presión consigna
                sector.get("nombre_sector", ""),
            ])


def _fill_sectores(doc, datos_sectores):
    """TABLA_SECTORES — Sectores hidráulicos."""
    table = _find_table_by_marker(doc, "{{TABLA_SECTORES}}")
    if not table:
        logger.warning("Tabla TABLA_SECTORES no encontrada.")
        return
    _clear_data_rows(table)
    for s in datos_sectores:
        # Estimar presión estática máxima
        cota_alim = 0
        depositos = s.get("depositos", [])
        if depositos:
            cota_alim = max(float(_safe_get(d, "cota_rebose", 0)) for d in depositos)
        cota_min = float(_safe_get(s, "cota_min", 0))
        presion_est = round((cota_alim - cota_min) * 10, 1) if cota_alim > 0 else ""

        # Punto de alimentación
        punto_alim = ""
        tipo_alim = ""
        if depositos:
            punto_alim = depositos[0].get("nombre", "")
            tipo_alim = "Depósito"
        fuentes = s.get("fuentes", [])
        if fuentes:
            punto_alim = fuentes[0].get("nombre", "")
            tipo_alim = "Reservorio"

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            punto_alim,
            tipo_alim,
            _safe_get(s, "cota_min"),
            _safe_get(s, "cota_max"),
            presion_est,
        ])


def _fill_elementos_modelo(doc, datos_muni):
    """TABLA_ELEMENTOS_MODELO — Resumen de elementos del modelo."""
    table = _find_table_by_marker(doc, "{{TABLA_ELEMENTOS_MODELO}}")
    if not table:
        logger.warning("Tabla TABLA_ELEMENTOS_MODELO no encontrada.")
        return
    _clear_data_rows(table)
    rows = [
        ("Tuberías", datos_muni.get("num_arcos", 0), ""),
        ("Nodos de red", datos_muni.get("num_nodos", 0), ""),
        ("Depósitos de regulación", datos_muni.get("num_depositos", 0), ""),
        ("Estaciones de bombeo", datos_muni.get("num_estaciones_bombeo", 0), ""),
        ("Grupos de presión", datos_muni.get("num_grupos_presion", 0), ""),
        ("Válvulas reductoras de presión", datos_muni.get("num_reductoras", 0), ""),
        ("Acometidas (connecs)", datos_muni.get("num_connecs", 0), ""),
        ("Longitud total modelizada (km)", datos_muni.get("longitud_red", 0), ""),
    ]
    for r in rows:
        _add_row(table, r)


def _fill_rugosidades(doc, datos_muni):
    """TABLA_RUGOSIDADES — Coeficientes de Hazen-Williams."""
    table = _find_table_by_marker(doc, "{{TABLA_RUGOSIDADES}}")
    if not table:
        logger.warning("Tabla TABLA_RUGOSIDADES no encontrada.")
        return
    _clear_data_rows(table)
    for r in datos_muni.get("rugosidades", []):
        _add_row(table, [
            _safe_get(r, "codigo"),
            _safe_get(r, "material"),
            _safe_get(r, "coeficiente_c"),
            "",  # Observaciones
        ])


def _fill_demandas(doc, datos_muni):
    """TABLA_DEMANDAS — Demandas por sector hidráulico."""
    table = _find_table_by_marker(doc, "{{TABLA_DEMANDAS}}")
    if not table:
        logger.warning("Tabla TABLA_DEMANDAS no encontrada.")
        return
    _clear_data_rows(table)
    demandas = datos_muni.get("demandas_sector", [])
    total_ls = sum(float(_safe_get(d, "demanda_media_ls", 0)) for d in demandas)
    for d in demandas:
        dem_ls = float(_safe_get(d, "demanda_media_ls", 0))
        pct = round(100 * dem_ls / total_ls, 1) if total_ls > 0 else 0
        _add_row(table, [
            _safe_get(d, "nombre_sector"),
            _safe_get(d, "num_abonados"),
            _safe_get(d, "demanda_media_ls"),
            _safe_get(d, "demanda_media_m3dia"),
            pct,
        ])


def _fill_resultados_globales(doc, resultados):
    """TABLA_RESULTADOS_GLOBALES — Indicadores globales por escenario."""
    table = _find_table_by_marker(doc, "{{TABLA_RESULTADOS_GLOBALES}}")
    if not table:
        logger.warning("Tabla TABLA_RESULTADOS_GLOBALES no encontrada.")
        return
    _clear_data_rows(table)

    globales = resultados.get("globales", {})
    media = globales.get("media", {})
    punta = globales.get("punta", {})
    nocturno = globales.get("nocturno", {})

    indicadores = [
        ("Caudal total inyectado (l/s)",
         _safe_get(media, "caudal_total_ls"),
         _safe_get(punta, "caudal_total_ls"),
         _safe_get(nocturno, "caudal_total_ls")),
        ("Presión media en la red (m.c.a.)",
         _safe_get(media, "presion_media"),
         _safe_get(punta, "presion_media"),
         _safe_get(nocturno, "presion_media")),
        ("Presión mínima en la red (m.c.a.)",
         _safe_get(media, "presion_minima"),
         _safe_get(punta, "presion_minima"),
         _safe_get(nocturno, "presion_minima")),
        ("Presión máxima en la red (m.c.a.)",
         _safe_get(media, "presion_maxima"),
         _safe_get(punta, "presion_maxima"),
         _safe_get(nocturno, "presion_maxima")),
        ("Velocidad media en la red (m/s)",
         _safe_get(media, "velocidad_media"),
         _safe_get(punta, "velocidad_media"),
         _safe_get(nocturno, "velocidad_media")),
        ("Velocidad máxima en la red (m/s)",
         _safe_get(media, "velocidad_maxima"),
         _safe_get(punta, "velocidad_maxima"),
         _safe_get(nocturno, "velocidad_maxima")),
        ("% tramos con velocidad < 0,05 m/s",
         _safe_get(media, "pct_baja_vel"),
         _safe_get(punta, "pct_baja_vel"),
         _safe_get(nocturno, "pct_baja_vel")),
        ("% tramos con presión < 10 m.c.a.",
         _safe_get(media, "pct_baja_presion"),
         _safe_get(punta, "pct_baja_presion"),
         _safe_get(nocturno, "pct_baja_presion")),
        ("% tramos con presión > 60 m.c.a.",
         _safe_get(media, "pct_alta_presion"),
         _safe_get(punta, "pct_alta_presion"),
         _safe_get(nocturno, "pct_alta_presion")),
    ]
    for row in indicadores:
        _add_row(table, row)


def _fill_sector_results(doc, resultados, datos_sectores, marker, escenario):
    """Rellena una tabla de resultados por sector para un escenario dado."""
    table = _find_table_by_marker(doc, marker)
    if not table:
        logger.warning("Tabla %s no encontrada.", marker)
        return
    _clear_data_rows(table)

    por_sector = resultados.get("por_sector", {})
    for s in datos_sectores:
        sid = s["sector_id"]
        datos = por_sector.get(sid, {}).get(escenario, {})
        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            _safe_get(datos, "presion_minima"),
            _safe_get(datos, "presion_media"),
            _safe_get(datos, "presion_maxima"),
            _safe_get(datos, "velocidad_media"),
            _safe_get(datos, "velocidad_maxima"),
            _safe_get(datos, "pct_baja_vel"),
        ])


def _fill_depositos_eps(doc, resultados):
    """TABLA_SECTOR_DEPOSITOS — Comportamiento de depósitos en EPS."""
    table = _find_table_by_marker(doc, "{{TABLA_SECTOR_DEPOSITOS}}")
    if not table:
        logger.warning("Tabla TABLA_SECTOR_DEPOSITOS no encontrada.")
        return
    _clear_data_rows(table)

    for d in resultados.get("depositos_eps", []):
        nivel_min = float(_safe_get(d, "nivel_minimo", 0))
        alcanza_min = "Sí" if nivel_min <= 0.5 else "No"
        _add_row(table, [
            _safe_get(d, "deposito"),
            _safe_get(d, "sector"),
            _safe_get(d, "nivel_minimo"),
            _safe_get(d, "nivel_maximo"),
            _safe_get(d, "nivel_medio"),
            _safe_get(d, "volumen_util_m3"),
            alcanza_min,
        ])


def _fill_indicadores_presion(doc, resultados, datos_sectores):
    """TABLA_INDICADORES_PRESION — Indicadores de presión por sector."""
    table = _find_table_by_marker(doc, "{{TABLA_INDICADORES_PRESION}}")
    if not table:
        logger.warning("Tabla TABLA_INDICADORES_PRESION no encontrada.")
        return
    _clear_data_rows(table)

    por_sector = resultados.get("por_sector", {})
    for s in datos_sectores:
        sid = s["sector_id"]
        punta = por_sector.get(sid, {}).get("punta", {})
        media = por_sector.get(sid, {}).get("media", {})
        nocturno = por_sector.get(sid, {}).get("nocturno", {})

        p_min_punta = _safe_get(punta, "presion_minima")
        p_max_nocturno = _safe_get(nocturno, "presion_maxima")
        total_nodos = int(_safe_get(punta, "total_nodos", 1) or 1)
        pct_baja = round(
            100 * int(_safe_get(punta, "nodos_baja_presion", 0)) / total_nodos, 1
        ) if total_nodos > 0 else 0
        pct_alta = round(
            100 * int(_safe_get(nocturno, "nodos_alta_presion", 0)) / total_nodos, 1
        ) if total_nodos > 0 else 0

        clasif = _clasificar_presion(p_min_punta, p_max_nocturno)

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            p_min_punta,
            _safe_get(media, "presion_media"),
            p_max_nocturno,
            pct_baja,
            pct_alta,
            clasif,
        ])


def _fill_indicadores_velocidad(doc, resultados, datos_sectores):
    """TABLA_INDICADORES_VELOCIDAD — Indicadores de velocidad por sector."""
    table = _find_table_by_marker(doc, "{{TABLA_INDICADORES_VELOCIDAD}}")
    if not table:
        logger.warning("Tabla TABLA_INDICADORES_VELOCIDAD no encontrada.")
        return
    _clear_data_rows(table)

    por_sector = resultados.get("por_sector", {})
    for s in datos_sectores:
        sid = s["sector_id"]
        media = por_sector.get(sid, {}).get("media", {})
        vel_media = _safe_get(media, "velocidad_media")
        clasif = _clasificar_velocidad(vel_media)

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            vel_media,
            _safe_get(media, "velocidad_maxima"),
            _safe_get(media, "pct_baja_vel"),
            _safe_get(media, "pct_alta_vel"),
            _safe_get(media, "perdida_unitaria_media"),
            clasif,
        ])


def _fill_retencion(doc, resultados, datos_sectores):
    """TABLA_RETENCION — Tiempo de retención por sector."""
    table = _find_table_by_marker(doc, "{{TABLA_RETENCION}}")
    if not table:
        logger.warning("Tabla TABLA_RETENCION no encontrada.")
        return
    _clear_data_rows(table)

    retencion = resultados.get("indicadores_retencion", [])
    depositos = resultados.get("depositos_eps", [])

    # Indexar retención por sector_id
    ret_by_sector = {r.get("sector_id"): r for r in retencion}
    # Indexar depósitos por sector
    dep_by_sector = {}
    for d in depositos:
        sec = d.get("sector", "")
        if sec not in dep_by_sector:
            dep_by_sector[sec] = []
        dep_by_sector[sec].append(d)

    for s in datos_sectores:
        sid = s["sector_id"]
        nombre = _safe_get(s, "nombre_sector")
        r = ret_by_sector.get(sid, {})

        # Datos de depósito del sector
        vol_dep = 0
        caudal_dep = 0
        deps_sector = dep_by_sector.get(nombre, [])
        for dp in deps_sector:
            vol_dep += float(_safe_get(dp, "volumen_util_m3", 0))
        caudal_dep = float(_safe_get(r, "caudal_medio_ls", 0))
        t_ret_dep = round(vol_dep / (caudal_dep / 1000) / 3600, 1) if caudal_dep > 0 else 0

        t_ret_red = _safe_get(r, "tiempo_retencion_red_h", 0)
        clasif = _clasificar_retencion(t_ret_red)

        _add_row(table, [
            nombre,
            _safe_get(r, "volumen_red_m3"),
            _safe_get(r, "caudal_medio_ls"),
            t_ret_red,
            round(vol_dep, 0) if vol_dep else "",
            round(caudal_dep, 3) if caudal_dep else "",
            round(t_ret_dep, 1) if t_ret_dep else "",
            clasif,
        ])


def _fill_clasificacion(doc, resultados, datos_sectores):
    """TABLA_CLASIFICACION — Clasificación global por sector."""
    table = _find_table_by_marker(doc, "{{TABLA_CLASIFICACION}}")
    if not table:
        logger.warning("Tabla TABLA_CLASIFICACION no encontrada.")
        return
    _clear_data_rows(table)

    por_sector = resultados.get("por_sector", {})
    retencion = resultados.get("indicadores_retencion", [])
    ret_by_sector = {r.get("sector_id"): r for r in retencion}

    for s in datos_sectores:
        sid = s["sector_id"]
        punta = por_sector.get(sid, {}).get("punta", {})
        media = por_sector.get(sid, {}).get("media", {})
        nocturno = por_sector.get(sid, {}).get("nocturno", {})
        r = ret_by_sector.get(sid, {})

        c_presion = _clasificar_presion(
            _safe_get(punta, "presion_minima"),
            _safe_get(nocturno, "presion_maxima"),
        )
        c_velocidad = _clasificar_velocidad(_safe_get(media, "velocidad_media"))
        c_retencion = _clasificar_retencion(
            _safe_get(r, "tiempo_retencion_red_h", 0)
        )
        c_global = _clasificar_global(c_presion, c_velocidad, c_retencion)

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            c_presion,
            c_velocidad,
            c_retencion,
            c_global,
        ])


# ─────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────

def rellenar_tablas(doc, datos_muni, datos_sectores, resultados):
    """Rellena todas las tablas del documento Word.

    Args:
        doc: Objeto Document de python-docx.
        datos_muni: Diccionario con datos del municipio.
        datos_sectores: Lista de dicts con datos por sector.
        resultados: Diccionario con resultados de simulación.
    """
    logger.info("Rellenando tablas del documento...")

    # Capítulo 2 — Descripción del sistema
    _fill_fuentes(doc, datos_sectores)
    _fill_depositos(doc, datos_sectores)
    _fill_red_materiales(doc, datos_muni, "primaria")
    _fill_red_materiales(doc, datos_muni, "secundaria")
    _fill_bombeos(doc, datos_sectores)
    _fill_grupos_presion(doc, datos_sectores)
    _fill_vrp(doc, datos_sectores)
    _fill_sectores(doc, datos_sectores)

    # Capítulo 3 — Construcción del modelo
    _fill_elementos_modelo(doc, datos_muni)
    _fill_rugosidades(doc, datos_muni)
    _fill_demandas(doc, datos_muni)

    # Capítulo 5 — Resultados del análisis
    _fill_resultados_globales(doc, resultados)
    _fill_sector_results(doc, resultados, datos_sectores,
                         "{{TABLA_SECTOR_MEDIA}}", "media")
    _fill_sector_results(doc, resultados, datos_sectores,
                         "{{TABLA_SECTOR_MAXIMA}}", "punta")
    _fill_sector_results(doc, resultados, datos_sectores,
                         "{{TABLA_SECTOR_MINIMA}}", "nocturno")
    _fill_depositos_eps(doc, resultados)

    # Capítulo 6 — Indicadores
    _fill_indicadores_presion(doc, resultados, datos_sectores)
    _fill_indicadores_velocidad(doc, resultados, datos_sectores)
    _fill_retencion(doc, resultados, datos_sectores)
    _fill_clasificacion(doc, resultados, datos_sectores)

    logger.info("Tablas rellenadas correctamente.")
