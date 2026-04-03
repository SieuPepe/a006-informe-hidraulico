"""
Relleno de tablas en el documento Word (.docx).

Localiza las tablas mediante marcadores ocultos {{TABLA_XXX}} en la primera
celda del encabezado, elimina las filas de datos vacías existentes y añade
las filas con los datos reales extraídos de la base de datos.
"""
from __future__ import annotations

import logging
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ─────────────────────────────────────────────────────────────
# Utilidades para localizar y manipular tablas
# ─────────────────────────────────────────────────────────────

def _find_table_by_marker(doc, marker: str):
    """Busca una tabla cuyo XML contenga el texto del marcador.

    El marcador puede estar en texto oculto (vanish) dentro de cualquier celda.
    Recorre todas las tablas y comprueba el XML crudo para detectar marcadores
    con formato <w:vanish/>.
    """
    for table in doc.tables:
        xml = etree.tostring(table._tbl, encoding="unicode")
        if marker in xml:
            return table
    return None


def _clear_data_rows(table, header_rows: int = 1) -> None:
    """Elimina todas las filas de datos (excepto las de encabezado)."""
    tbl = table._tbl
    rows = tbl.findall(f"{{{NS_W}}}tr")
    for row in rows[header_rows:]:
        tbl.remove(row)


def _add_row(table, values) -> None:
    """Añade una fila a la tabla con los valores proporcionados."""
    row = table.add_row()
    for i, val in enumerate(values):
        if i < len(row.cells):
            row.cells[i].text = _fmt(val)


def _fmt(value: Any) -> str:
    """Formatea un valor para insertar en una celda de tabla."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e12:
            return str(int(value))
        return f"{value:g}".replace(".", ",")
    return str(value)


def _safe_get(d, key: str, default: Any = "") -> Any:
    """Obtiene un valor de un dict con valor por defecto."""
    if not isinstance(d, dict):
        return default
    val = d.get(key)
    return val if val is not None else default


# ─────────────────────────────────────────────────────────────
# Clasificación por umbrales
# ─────────────────────────────────────────────────────────────

_CLASIF_ORDER = {"Óptimo": 0, "Aceptable": 1, "Deficiente": 2, "Crítico": 3, "Sin datos": 4}


def _peor(a: str, b: str) -> str:
    """Devuelve la peor de dos clasificaciones."""
    return a if _CLASIF_ORDER.get(a, 4) >= _CLASIF_ORDER.get(b, 4) else b


def _clasificar_presion(p_min_punta, p_max_nocturno) -> str:
    """Clasifica el estado de presión de un sector.

    Umbrales (m.c.a.):
        Óptimo:      20 <= p_min  y  p_max <= 40
        Aceptable:   10 <= p_min < 20  o  40 < p_max <= 50
        Deficiente:   5 <= p_min < 10  o  50 < p_max <= 60
        Crítico:      p_min < 5  o  p_max > 60
    """
    try:
        p_min = float(p_min_punta) if p_min_punta not in (None, "", "—") else None
        p_max = float(p_max_nocturno) if p_max_nocturno not in (None, "", "—") else None
    except (TypeError, ValueError):
        return "Sin datos"

    if p_min is None and p_max is None:
        return "Sin datos"

    clasif = "Óptimo"
    if p_min is not None:
        if p_min < 5:
            clasif = _peor(clasif, "Crítico")
        elif p_min < 10:
            clasif = _peor(clasif, "Deficiente")
        elif p_min < 20:
            clasif = _peor(clasif, "Aceptable")

    if p_max is not None:
        if p_max > 60:
            clasif = _peor(clasif, "Crítico")
        elif p_max > 50:
            clasif = _peor(clasif, "Deficiente")
        elif p_max > 40:
            clasif = _peor(clasif, "Aceptable")

    return clasif


def _clasificar_velocidad(vel_media, vel_max=None) -> str:
    """Clasifica el estado de velocidad de un sector.

    Umbrales (m/s):
        Óptimo:      0,30 <= v_media <= 1,00
        Aceptable:   0,05 <= v_media < 0,30
        Deficiente:  v_media < 0,05
        Crítico:     v_max > 1,50
    """
    try:
        v = float(vel_media) if vel_media not in (None, "", "—") else None
        vx = float(vel_max) if vel_max not in (None, "", "—") else None
    except (TypeError, ValueError):
        return "Sin datos"

    if v is None:
        return "Sin datos"

    if vx is not None and vx > 1.5:
        return "Crítico"
    if v < 0.05:
        return "Deficiente"
    if v < 0.30:
        return "Aceptable"
    if v <= 1.00:
        return "Óptimo"
    return "Deficiente"


def _clasificar_retencion(t_ret_h) -> str:
    """Clasifica el tiempo de retención.

    Umbrales (horas):
        Óptimo:     t <= 24
        Aceptable:  24 < t <= 72
        Deficiente: 72 < t <= 144
        Crítico:    t > 144
    """
    try:
        t = float(t_ret_h) if t_ret_h not in (None, "", "—") else None
    except (TypeError, ValueError):
        return "Sin datos"

    if t is None:
        return "Sin datos"
    if t <= 24:
        return "Óptimo"
    if t <= 72:
        return "Aceptable"
    if t <= 144:
        return "Deficiente"
    return "Crítico"


def _clasificar_global(*clasificaciones: str) -> str:
    """Devuelve la peor clasificación de las proporcionadas."""
    result = "Óptimo"
    for c in clasificaciones:
        result = _peor(result, c)
    return result


# ─────────────────────────────────────────────────────────────
# Funciones de relleno por tabla
# ─────────────────────────────────────────────────────────────

def _fill_fuentes(doc, datos_sectores):
    """TABLA_FUENTES — Fuentes de suministro (Cap 2.3).

    Columnas: Nombre | Tipo | Caudal concesional (m³/año) |
              Caudal medio registrado (m³/año) | Punto de entrega al sistema
    """
    table = _find_table_by_marker(doc, "{{TABLA_FUENTES}}")
    if not table:
        logger.warning("Tabla TABLA_FUENTES no encontrada.")
        return
    fuentes = []
    for sector in datos_sectores:
        for f in sector.get("fuentes", []):
            f_copy = dict(f)
            f_copy["_sector"] = sector.get("nombre_sector", "")
            fuentes.append(f_copy)
    if not fuentes:
        return
    _clear_data_rows(table)
    for f in fuentes:
        _add_row(table, [
            _safe_get(f, "nombre", _safe_get(f, "code")),
            _safe_get(f, "tipo", "Captación"),
            _safe_get(f, "caudal_concesional"),
            _safe_get(f, "caudal_medio"),
            _safe_get(f, "punto_entrega", f.get("_sector", "")),
        ])


def _fill_depositos(doc, datos_sectores):
    """TABLA_DEPOSITOS — Inventario de depósitos (Cap 2.4).

    Columnas: Nombre | Cota de solera (msnm) | Cota de rebose (msnm) |
              Volumen útil (m³) | Función | Alimentación | Zonas abastecidas
    """
    table = _find_table_by_marker(doc, "{{TABLA_DEPOSITOS}}")
    if not table:
        logger.warning("Tabla TABLA_DEPOSITOS no encontrada.")
        return
    depositos = []
    for sector in datos_sectores:
        for d in sector.get("depositos", []):
            d_copy = dict(d)
            d_copy["_sector"] = sector.get("nombre_sector", "")
            depositos.append(d_copy)
    if not depositos:
        return
    _clear_data_rows(table)
    for d in depositos:
        _add_row(table, [
            _safe_get(d, "nombre", _safe_get(d, "code")),
            _safe_get(d, "cota_solera"),
            _safe_get(d, "cota_rebose"),
            _safe_get(d, "volumen_m3"),
            _safe_get(d, "funcion", "Regulación"),
            _safe_get(d, "alimentacion"),
            d.get("_sector", ""),
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
    """TABLA_BOMBEOS — Estaciones de bombeo (Cap 2.6).

    Columnas: Nombre | Ubicación | Nº grupos | Caudal nominal (l/s) |
              Altura manométrica (m.c.a.) | Potencia instalada (kW) |
              Depósito de aspiración | Depósito de impulsión
    """
    table = _find_table_by_marker(doc, "{{TABLA_BOMBEOS}}")
    if not table:
        logger.warning("Tabla TABLA_BOMBEOS no encontrada.")
        return
    bombas = []
    for sector in datos_sectores:
        for b in sector.get("bombas", []):
            b_copy = dict(b)
            b_copy["_sector"] = sector.get("nombre_sector", "")
            bombas.append(b_copy)
    if not bombas:
        return
    _clear_data_rows(table)
    for b in bombas:
        _add_row(table, [
            _safe_get(b, "nombre", _safe_get(b, "code")),
            _safe_get(b, "ubicacion", b.get("_sector", "")),
            _safe_get(b, "num_grupos", 1),
            _safe_get(b, "caudal_nominal"),
            _safe_get(b, "altura_manometrica"),
            _safe_get(b, "potencia_kw"),
            _safe_get(b, "deposito_aspiracion"),
            _safe_get(b, "deposito_impulsion"),
        ])


def _fill_grupos_presion(doc, datos_muni, datos_sectores):
    """TABLA_GRUPOS_PRESION — Grupos de presión (Cap 2.6).

    Columnas: Nombre | Ubicación | Nº grupos | Presión de consigna (m.c.a.) |
              Caudal máximo (l/s) | Potencia instalada (kW) | Zona abastecida
    """
    table = _find_table_by_marker(doc, "{{TABLA_GRUPOS_PRESION}}")
    if not table:
        logger.warning("Tabla TABLA_GRUPOS_PRESION no encontrada.")
        return
    grupos = datos_muni.get("grupos_presion", [])
    if not grupos:
        for sector in datos_sectores:
            for g in sector.get("grupos_presion", []):
                g_copy = dict(g)
                g_copy["_sector"] = sector.get("nombre_sector", "")
                grupos.append(g_copy)
    if not grupos:
        return
    _clear_data_rows(table)
    for g in grupos:
        _add_row(table, [
            _safe_get(g, "nombre", _safe_get(g, "code")),
            _safe_get(g, "ubicacion"),
            _safe_get(g, "num_grupos", 1),
            _safe_get(g, "presion_consigna"),
            _safe_get(g, "caudal_maximo"),
            _safe_get(g, "potencia_kw"),
            _safe_get(g, "zona_abastecida", g.get("_sector", "")),
        ])


def _fill_vrp(doc, datos_sectores):
    """TABLA_VRP — Válvulas reductoras de presión (Cap 2.6).

    Columnas: Nombre | Ubicación | Diámetro (mm) |
              Presión de consigna aguas abajo (m.c.a.) | Zona abastecida
    """
    table = _find_table_by_marker(doc, "{{TABLA_VRP}}")
    if not table:
        logger.warning("Tabla TABLA_VRP no encontrada.")
        return
    vrps = []
    for sector in datos_sectores:
        for v in sector.get("vrp", []):
            v_copy = dict(v)
            v_copy["_sector"] = sector.get("nombre_sector", "")
            vrps.append(v_copy)
    if not vrps:
        return
    _clear_data_rows(table)
    for v in vrps:
        _add_row(table, [
            _safe_get(v, "nombre", _safe_get(v, "code")),
            _safe_get(v, "ubicacion", v.get("_sector", "")),
            _safe_get(v, "diametro_mm"),
            _safe_get(v, "presion_consigna"),
            v.get("_sector", ""),
        ])


def _fill_sectores(doc, datos_sectores):
    """TABLA_SECTORES — Sectores hidráulicos (Cap 2.7).

    Columnas: Sector | Punto de alimentación | Tipo de alimentación |
              Cota mínima servida (msnm) | Cota máxima servida (msnm) |
              Presión estática máxima estimada (m.c.a.)
    """
    table = _find_table_by_marker(doc, "{{TABLA_SECTORES}}")
    if not table:
        logger.warning("Tabla TABLA_SECTORES no encontrada.")
        return
    if not datos_sectores:
        return
    _clear_data_rows(table)
    for s in datos_sectores:
        # Estimar presión estática máxima
        cota_alim = 0
        depositos = s.get("depositos", [])
        if depositos:
            cotas_rebose = [float(_safe_get(d, "cota_rebose", 0) or 0)
                           for d in depositos]
            cota_alim = max(cotas_rebose) if cotas_rebose else 0
        cota_min = float(_safe_get(s, "cota_min", 0) or 0)
        presion_est = round(cota_alim - cota_min, 1) if cota_alim > 0 else ""

        # Punto de alimentación
        punto_alim = _safe_get(s, "punto_alimentacion")
        tipo_alim = _safe_get(s, "tipo_alimentacion")
        if not punto_alim:
            if depositos:
                punto_alim = depositos[0].get("nombre", depositos[0].get("code", ""))
                tipo_alim = tipo_alim or "Gravedad"
            fuentes = s.get("fuentes", [])
            if fuentes:
                punto_alim = fuentes[0].get("nombre", fuentes[0].get("code", ""))
                tipo_alim = tipo_alim or "Gravedad"

        _add_row(table, [
            _safe_get(s, "nombre_sector", _safe_get(s, "sector_id")),
            punto_alim,
            tipo_alim,
            _safe_get(s, "cota_min"),
            _safe_get(s, "cota_max"),
            presion_est,
        ])


def _fill_reglas(doc, datos_muni):
    """TABLA_REGLAS — Reglas de operación (Cap 2.8).

    Columnas: ID regla | Elemento controlado | Tipo de elemento |
              Condición de activación | Acción | Depósito asociado
    """
    table = _find_table_by_marker(doc, "{{TABLA_REGLAS}}")
    if not table:
        logger.warning("Tabla TABLA_REGLAS no encontrada.")
        return
    reglas = datos_muni.get("reglas", [])
    if not reglas:
        return
    _clear_data_rows(table)
    for r in reglas:
        _add_row(table, [
            _safe_get(r, "id_regla", _safe_get(r, "id")),
            _safe_get(r, "elemento_controlado"),
            _safe_get(r, "tipo_elemento"),
            _safe_get(r, "condicion", _safe_get(r, "condicion_activacion")),
            _safe_get(r, "accion"),
            _safe_get(r, "deposito_asociado"),
        ])


def _fill_elementos_modelo(doc, datos_muni):
    """TABLA_ELEMENTOS_MODELO — Resumen de elementos del modelo (Cap 3.3)."""
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
