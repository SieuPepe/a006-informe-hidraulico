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
    """Busca una tabla cuyo contenido de texto contenga el marcador.

    Word puede dividir el texto del marcador en múltiples <w:t> elements,
    por lo que concatenamos todo el texto de cada celda antes de buscar.
    Busca con y sin las llaves {{ }}.
    """
    # Extraer el nombre base sin llaves para búsqueda más robusta
    marker_name = marker.replace("{{", "").replace("}}", "")

    for table in doc.tables:
        # Concatenar todo el texto de todos los <w:t> de la tabla
        t_elems = table._tbl.findall(f'.//{{{NS_W}}}t')
        full_text = ''.join(t.text or '' for t in t_elems)
        if marker_name in full_text:
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

_CLASIF_ORDER = {"Óptimo": 0, "Aceptable": 1, "Deficiente": 2, "Insuficiente": 2, "Crítico": 3, "Sin datos": 4}


def _peor(*clasificaciones):
    """Devuelve la peor clasificación de las proporcionadas."""
    result = "Óptimo"
    for c in clasificaciones:
        if _CLASIF_ORDER.get(c, 4) > _CLASIF_ORDER.get(result, 4):
            result = c
    return result


def _clasificar_tpi(tpi):
    """Clasifica un sector según su valor TPI (0-1)."""
    if tpi is None or tpi == "":
        return ""
    tpi = float(tpi)
    if tpi >= 0.90:
        return "Óptimo"
    if tpi >= 0.70:
        return "Aceptable"
    if tpi >= 0.50:
        return "Deficiente"
    return "Crítico"


def _clasificar_retencion(h):
    """Clasifica el tiempo de retención en red."""
    if h is None or h == "":
        return ""
    h = float(h)
    if h < 24:
        return "Óptimo"
    if h < 72:
        return "Aceptable"
    if h < 144:
        return "Deficiente"
    return "Crítico"


def _clasificar_autonomia(h):
    """Clasifica la autonomía de un depósito."""
    if h is None or h == "":
        return ""
    h = float(h)
    if h >= 48:
        return "Óptimo"
    if h >= 24:
        return "Aceptable"
    if h >= 12:
        return "Insuficiente"
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
        # Cols: Nombre | Tipo | Caudal concesional (m3/año) | Punto entrega | Cota toma
        _add_row(table, [
            _safe_get(f, "nombre", _safe_get(f, "code")),
            "Captación",
            "",  # Caudal concesional - no disponible en BD
            f.get("_sector", ""),  # Punto de entrega al sistema
            _safe_get(f, "cota_toma"),
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
        # Cols: Nombre | Cota solera | Cota rebose | Cota mínima | Cota máxima | Volumen | Sector
        _add_row(table, [
            _safe_get(d, "nombre", _safe_get(d, "code")),
            _safe_get(d, "cota_solera"),
            _safe_get(d, "cota_rebose"),
            _safe_get(d, "cota_minima"),
            _safe_get(d, "cota_maxima"),
            _safe_get(d, "volumen_m3"),
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
    nivel_nombre = "Primaria" if nivel == "primaria" else "Secundaria"
    for m in datos_muni.get(key, []):
        # Cols: Nivel funcional | Material | Rango diámetros | Longitud | % total
        _add_row(table, [
            nivel_nombre,
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
            if _safe_get(b, "pump_type", "").upper() == "FLOWPUMP":
                b_copy = dict(b)
                b_copy["_sector"] = sector.get("nombre_sector", "")
                bombas.append(b_copy)
    _clear_data_rows(table)
    if not bombas:
        return
    for b in bombas:
        _add_row(table, [
            _safe_get(b, "nombre", _safe_get(b, "code")),
            b.get("_sector", ""),
            1,  # Nº bombas
            _safe_get(b, "curve_id"),
            "",  # Altura manométrica
            _safe_get(b, "power"),
            "",  # Depósito aspiración
            "",  # Depósito impulsión
        ])


def _fill_grupos_presion(doc, datos_muni, datos_sectores):
    """TABLA_GRUPOS_PRESION — Grupos de presión (Cap 2.6).

    Columnas: Nombre | Ubicación | Nº bombas | Curva | Zona abastecida
    """
    table = _find_table_by_marker(doc, "{{TABLA_GRUPOS_PRESION}}")
    if not table:
        logger.warning("Tabla TABLA_GRUPOS_PRESION no encontrada.")
        return
    grupos = []
    for sector in datos_sectores:
        for b in sector.get("bombas", []):
            if _safe_get(b, "pump_type", "").upper() == "PRESSPUMP":
                b_copy = dict(b)
                b_copy["_sector"] = sector.get("nombre_sector", "")
                grupos.append(b_copy)
    _clear_data_rows(table)
    if not grupos:
        return
    for g in grupos:
        _add_row(table, [
            _safe_get(g, "nombre", _safe_get(g, "code")),
            g.get("_sector", ""),
            "",  # Nº bombas (queda vacío a propósito)
            _safe_get(g, "curve_id"),
            g.get("_sector", ""),
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
        # Presión sin decimales
        presion = _safe_get(v, "presion_consigna")
        if presion not in (None, ""):
            try:
                presion = int(round(float(presion)))
            except (ValueError, TypeError):
                pass
        # Diámetro: intentar de diametro_mm, si NULL extraer de nodecat_id
        diametro = _safe_get(v, "diametro_mm")
        if not diametro:
            nodecat = _safe_get(v, "nodecat_id", "")
            import re
            m = re.search(r'(\d+)', str(nodecat))
            if m:
                diametro = m.group(1)
        _add_row(table, [
            _safe_get(v, "code"),
            v.get("_sector", ""),
            diametro,
            presion,
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
        fuentes = s.get("fuentes", [])

        # Punto de alimentación: primera fuente (RESERVOIR) del sector
        punto_alim = ""
        tipo_alim = "Gravedad"
        cota_alim = 0
        if fuentes:
            punto_alim = _safe_get(fuentes[0], "nombre", _safe_get(fuentes[0], "code"))
            cota_alim = float(_safe_get(fuentes[0], "cota_toma", 0) or 0)

        # Cotas servidas de red secundaria
        cota_min = float(_safe_get(s, "cota_min_sc", _safe_get(s, "cota_min", 0)) or 0)
        cota_max = float(_safe_get(s, "cota_max_sc", _safe_get(s, "cota_max", 0)) or 0)
        presion_est = round(cota_alim - cota_min, 1) if cota_alim > 0 and cota_min > 0 else ""

        _add_row(table, [
            _safe_get(s, "nombre_sector", _safe_get(s, "sector_id")),
            punto_alim,
            tipo_alim,
            int(cota_min) if cota_min else "",
            int(cota_max) if cota_max else "",
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
    # Lookup de node_id → nombre de depósito
    nombres_nodos = datos_muni.get("nombres_nodos", {})
    _clear_data_rows(table)
    rule_num = 0
    for r in reglas:
        # Un registro puede contener múltiples líneas de control
        text = _safe_get(r, "text", "")
        tipo = _safe_get(r, "tipo", "Control")
        lines = [l.strip() for l in text.split('\n') if l.strip()] if text else []
        for line in lines:
            rule_num += 1
            parts = line.split()
            # Formato: LINK 12860_n2a CLOSED IF NODE 208 ABOVE 2.5
            elemento = parts[1] if len(parts) > 1 else ""
            accion = parts[2] if len(parts) > 2 else ""
            condicion = ""
            deposito = ""
            if "IF" in parts:
                idx_if = parts.index("IF")
                condicion = " ".join(parts[idx_if:])
                node_id = parts[idx_if + 2] if len(parts) > idx_if + 2 else ""
                deposito = nombres_nodos.get(node_id, node_id)
            _add_row(table, [
                rule_num,
                elemento,
                tipo,
                condicion,
                accion,
                deposito,
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
    """TABLA_RUGOSIDADES — Coeficientes de Hazen-Williams (Cap 3.4).

    Columnas: Código | Material | Coeficiente C | Observaciones
    """
    table = _find_table_by_marker(doc, "{{TABLA_RUGOSIDADES}}")
    if not table:
        logger.warning("Tabla TABLA_RUGOSIDADES no encontrada.")
        return
    rugosidades = datos_muni.get("rugosidades", [])
    if not rugosidades:
        return
    _clear_data_rows(table)
    for r in rugosidades:
        _add_row(table, [
            _safe_get(r, "codigo", _safe_get(r, "id")),
            _safe_get(r, "material"),
            _safe_get(r, "coeficiente_c"),
            _safe_get(r, "observaciones", _safe_get(r, "descript")),
        ])


def _fill_demandas(doc, datos_muni):
    """TABLA_DEMANDAS — Demandas por sector hidráulico (Cap 3.5).

    Columnas: Sector hidráulico | Nº abonados | Demanda media (l/s) |
              Demanda media (m³/día) | % sobre total

    Las demandas se muestran con el DEMAND MULTIPLIER de EPANET aplicado
    (caudal en alta = base × multiplicador) para que cuadren con el
    volumen anual del balance hídrico.
    """
    table = _find_table_by_marker(doc, "{{TABLA_DEMANDAS}}")
    if not table:
        logger.warning("Tabla TABLA_DEMANDAS no encontrada.")
        return
    demandas = datos_muni.get("demandas_sector", [])
    if not demandas:
        return
    multiplicador = float(datos_muni.get("multiplicador_demanda", 1.0) or 1.0)
    _clear_data_rows(table)
    # Total en alta para calcular %
    total_alta_ls = sum(
        float(_safe_get(d, "demanda_media_ls", 0) or 0) * multiplicador
        for d in demandas
    )
    for d in demandas:
        dem_base_ls = float(_safe_get(d, "demanda_media_ls", 0) or 0)
        dem_alta_ls = dem_base_ls * multiplicador
        dem_alta_m3dia = dem_alta_ls * 86.4
        pct = round(100 * dem_alta_ls / total_alta_ls, 1) if total_alta_ls > 0 else 0
        _add_row(table, [
            _safe_get(d, "nombre_sector", _safe_get(d, "sector_id")),
            _safe_get(d, "num_abonados"),
            round(dem_alta_ls, 3),
            round(dem_alta_m3dia, 1),
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

    # Cols: Indicador | Unidad | Demanda media | Demanda máxima | Demanda mínima nocturna
    indicadores = [
        ("Caudal total inyectado", "l/s",
         _safe_get(media, "caudal_total_ls"),
         _safe_get(punta, "caudal_total_ls"),
         _safe_get(nocturno, "caudal_total_ls")),
        ("Presión media en la red", "m.c.a.",
         _safe_get(media, "presion_media"),
         _safe_get(punta, "presion_media"),
         _safe_get(nocturno, "presion_media")),
        ("Presión mínima en la red", "m.c.a.",
         _safe_get(media, "presion_minima"),
         _safe_get(punta, "presion_minima"),
         _safe_get(nocturno, "presion_minima")),
        ("Presión máxima en la red", "m.c.a.",
         _safe_get(media, "presion_maxima"),
         _safe_get(punta, "presion_maxima"),
         _safe_get(nocturno, "presion_maxima")),
        ("Velocidad media en la red", "m/s",
         _safe_get(media, "velocidad_media"),
         _safe_get(punta, "velocidad_media"),
         _safe_get(nocturno, "velocidad_media")),
        ("Velocidad máxima en la red", "m/s",
         _safe_get(media, "velocidad_maxima"),
         _safe_get(punta, "velocidad_maxima"),
         _safe_get(nocturno, "velocidad_maxima")),
        ("% tramos con velocidad < 0,05 m/s", "%",
         _safe_get(media, "pct_baja_vel"),
         _safe_get(punta, "pct_baja_vel"),
         _safe_get(nocturno, "pct_baja_vel")),
        ("% nodos con presión < 10 m.c.a.", "%",
         _safe_get(media, "pct_baja_presion"),
         _safe_get(punta, "pct_baja_presion"),
         _safe_get(nocturno, "pct_baja_presion")),
        ("% nodos con presión > 60 m.c.a.", "%",
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
        nivel_min = float(_safe_get(d, "nivel_minimo", 0) or 0)
        alcanza_min = "Sí" if nivel_min <= 0.5 else "No"
        # Cols: Depósito | Nivel inicial | Nivel mín alcanzado | Nivel máx alcanzado | Nº ciclos | ¿Alcanza mín operativo?
        _add_row(table, [
            _safe_get(d, "deposito"),
            _safe_get(d, "nivel_medio"),  # Nivel inicial ≈ nivel medio como aproximación
            _safe_get(d, "nivel_minimo"),
            _safe_get(d, "nivel_maximo"),
            _safe_get(d, "num_ciclos"),
            alcanza_min,
        ])


def _fill_indicadores_presion(doc, resultados, datos_sectores):
    """TABLA_INDICADORES_PRESION — Indicadores de presión por sector (Cap 6.2).

    Cols: Sector | P.min punta | P.media media | P.max nocturno |
          % nodos <10 | % nodos >60 | TPI presión | Clasificación
    """
    table = _find_table_by_marker(doc, "{{TABLA_INDICADORES_PRESION}}")
    if not table:
        logger.warning("Tabla TABLA_INDICADORES_PRESION no encontrada.")
        return
    por_sector = resultados.get("por_sector", {})
    tpi = resultados.get("tpi", {})
    _clear_data_rows(table)

    for s in datos_sectores:
        sid = s["sector_id"]
        punta = por_sector.get(sid, {}).get("punta", {})
        media = por_sector.get(sid, {}).get("media", {})
        nocturno = por_sector.get(sid, {}).get("nocturno", {})
        tpi_val = _safe_get(tpi.get(sid, {}), "tpi_presion")
        clasif = _clasificar_tpi(tpi_val)

        pct_baja = _safe_get(punta, "pct_baja_presion")
        pct_alta = _safe_get(nocturno, "pct_alta_presion")
        if not pct_baja and punta:
            total = int(_safe_get(punta, "total_nodos", 0) or 0)
            n_baja = int(_safe_get(punta, "nodos_baja_presion", 0) or 0)
            pct_baja = round(100 * n_baja / total, 1) if total > 0 else 0
        if not pct_alta and nocturno:
            total = int(_safe_get(nocturno, "total_nodos", 0) or 0)
            n_alta = int(_safe_get(nocturno, "nodos_alta_presion", 0) or 0)
            pct_alta = round(100 * n_alta / total, 1) if total > 0 else 0

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            _safe_get(punta, "presion_minima"),
            _safe_get(media, "presion_media"),
            _safe_get(nocturno, "presion_maxima"),
            pct_baja,
            pct_alta,
            tpi_val,
            clasif,
        ])


def _fill_indicadores_velocidad(doc, resultados, datos_sectores):
    """TABLA_INDICADORES_VELOCIDAD — Indicadores de velocidad por sector (Cap 6.3).

    Cols: Sector | V.media | V.máx | % v<0,05 | % v>1,5 |
          Pérd. unit. media | TPI velocidad | Clasificación
    """
    table = _find_table_by_marker(doc, "{{TABLA_INDICADORES_VELOCIDAD}}")
    if not table:
        logger.warning("Tabla TABLA_INDICADORES_VELOCIDAD no encontrada.")
        return
    por_sector = resultados.get("por_sector", {})
    tpi = resultados.get("tpi", {})
    _clear_data_rows(table)

    for s in datos_sectores:
        sid = s["sector_id"]
        media = por_sector.get(sid, {}).get("media", {})
        tpi_val = _safe_get(tpi.get(sid, {}), "tpi_velocidad")
        clasif = _clasificar_tpi(tpi_val)

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            _safe_get(media, "velocidad_media"),
            _safe_get(media, "velocidad_maxima"),
            _safe_get(media, "pct_baja_vel"),
            _safe_get(media, "pct_alta_vel"),
            tpi_val,
            clasif,
        ])


def _fill_retencion(doc, resultados, datos_sectores):
    """TABLA_RETENCION — Tiempo de retención en red por sector (simplificada).

    Cols: Sector | Volumen red (m³) | Caudal medio (l/s) |
          Tiempo retención (h) | Clasificación
    """
    table = _find_table_by_marker(doc, "{{TABLA_RETENCION}}")
    if not table:
        logger.warning("Tabla TABLA_RETENCION no encontrada.")
        return
    _clear_data_rows(table)

    retencion = resultados.get("indicadores_retencion", [])
    ret_by_sector = {r.get("sector_id"): r for r in retencion}

    for s in datos_sectores:
        sid = s["sector_id"]
        r = ret_by_sector.get(sid, {})
        t_ret = _safe_get(r, "tiempo_retencion_red_h", 0)
        clasif = _clasificar_retencion(t_ret)

        _add_row(table, [
            _safe_get(s, "nombre_sector"),
            _safe_get(r, "volumen_red_m3"),
            _safe_get(r, "caudal_medio_ls"),
            t_ret,
            clasif,
        ])


def _fill_autonomia(doc, resultados):
    """TABLA_AUTONOMIA — Autonomía de depósitos individuales (Cap 6.5).

    Cols: Sector | Depósito | Volumen útil medio (m³) |
          Caudal salida medio (l/s) | Autonomía (h) | Clasificación
    """
    table = _find_table_by_marker(doc, "{{TABLA_AUTONOMIA}}")
    if not table:
        logger.warning("Tabla TABLA_AUTONOMIA no encontrada.")
        return
    _clear_data_rows(table)

    autonomia = resultados.get("autonomia", [])
    for d in autonomia:
        clasif = _clasificar_autonomia(_safe_get(d, "autonomia_h"))
        _add_row(table, [
            _safe_get(d, "sector"),
            _safe_get(d, "deposito"),
            _safe_get(d, "volumen_util_m3"),
            _safe_get(d, "caudal_salida_ls"),
            _safe_get(d, "autonomia_h"),
            clasif,
        ])


def _fill_clasificacion(doc, resultados, datos_sectores):
    """TABLA_CLASIFICACION — Clasificación global por sector (Cap 6.5).

    Cols: Sector | Clasif. presión | Clasif. velocidad |
          Clasif. retención | Clasif. autonomía | Clasificación global
    """
    table = _find_table_by_marker(doc, "{{TABLA_CLASIFICACION}}")
    if not table:
        logger.warning("Tabla TABLA_CLASIFICACION no encontrada.")
        return
    _clear_data_rows(table)

    tpi = resultados.get("tpi", {})
    retencion = resultados.get("indicadores_retencion", [])
    autonomia = resultados.get("autonomia", [])
    ret_by_sector = {r.get("sector_id"): r for r in retencion}

    # Peor autonomía por sector
    aut_by_sector = {}
    for d in autonomia:
        sid = d.get("sector_id")
        a_h = d.get("autonomia_h")
        if sid not in aut_by_sector or (a_h is not None and (
                aut_by_sector[sid] is None or float(a_h) < float(aut_by_sector[sid]))):
            aut_by_sector[sid] = a_h

    for s in datos_sectores:
        sid = s["sector_id"]
        nombre = _safe_get(s, "nombre_sector")

        c_presion = _clasificar_tpi(_safe_get(tpi.get(sid, {}), "tpi_presion"))
        c_velocidad = _clasificar_tpi(_safe_get(tpi.get(sid, {}), "tpi_velocidad"))

        r = ret_by_sector.get(sid, {})
        c_retencion = _clasificar_retencion(_safe_get(r, "tiempo_retencion_red_h"))

        c_autonomia = _clasificar_autonomia(aut_by_sector.get(sid))

        c_global = _peor(c_presion, c_velocidad, c_retencion, c_autonomia)

        _add_row(table, [
            nombre,
            c_presion,
            c_velocidad,
            c_retencion,
            c_autonomia,
            c_global,
        ])



# ─────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────

def rellenar_tablas(doc, datos_muni, datos_sectores, resultados):
    """Rellena todas las tablas del documento Word.

    Busca tablas por marcadores ocultos {{TABLA_XXX}}, elimina las filas de
    datos vacías existentes y añade filas con los datos reales.

    Args:
        doc: Objeto Document de python-docx.
        datos_muni: Diccionario con datos del municipio. Puede incluir claves
            opcionales: 'materiales_primaria', 'materiales_secundaria',
            'rugosidades', 'demandas_sector', 'reglas', 'caudalimetros',
            'grupos_presion'.
        datos_sectores: Lista de dicts con datos por sector. Cada dict puede
            contener listas anidadas: 'depositos', 'fuentes', 'bombas', 'vrp'.
        resultados: Diccionario con resultados de simulación. Claves esperadas:
            'globales' (dict escenario -> valores),
            'por_sector' (dict sector_id -> escenario -> valores),
            'depositos_eps' (lista), 'indicadores_retencion' (lista),
            'timesteps' (dict).
    """
    logger.info("Rellenando tablas del documento...")

    # Capítulo 2 — Descripción del sistema
    _fill_fuentes(doc, datos_sectores)                          # Cap 2.3
    _fill_depositos(doc, datos_sectores)                        # Cap 2.4
    _fill_red_materiales(doc, datos_muni, "primaria")           # Cap 2.5
    _fill_red_materiales(doc, datos_muni, "secundaria")         # Cap 2.5
    _fill_bombeos(doc, datos_sectores)                          # Cap 2.6
    _fill_grupos_presion(doc, datos_muni, datos_sectores)       # Cap 2.6
    _fill_vrp(doc, datos_sectores)                              # Cap 2.6
    _fill_sectores(doc, datos_sectores)                         # Cap 2.7
    _fill_reglas(doc, datos_muni)                               # Cap 2.8

    # Capítulo 3 — Construcción del modelo
    _fill_elementos_modelo(doc, datos_muni)                     # Cap 3.3
    _fill_rugosidades(doc, datos_muni)                          # Cap 3.4
    _fill_demandas(doc, datos_muni)                             # Cap 3.5

    # Capítulo 5 — Resultados del análisis
    _fill_resultados_globales(doc, resultados)                  # Cap 5.2
    # NOTA: Las tablas de sector (MEDIA, MAXIMA, MINIMA, DEPOSITOS)
    # se rellenan en replicar_sectores() con datos de cada sector individual

    # Capítulo 6 — Indicadores
    _fill_indicadores_presion(doc, resultados, datos_sectores)  # Cap 6.2
    _fill_indicadores_velocidad(doc, resultados, datos_sectores)  # Cap 6.3
    _fill_retencion(doc, resultados, datos_sectores)            # Cap 6.4
    _fill_autonomia(doc, resultados)                            # Cap 6.5
    _fill_clasificacion(doc, resultados, datos_sectores)        # Cap 6.5


    logger.info("Tablas rellenadas correctamente.")


def rellenar_tabla_sector(doc, sector_data, sector_id, resultados, marker_suffix):
    """Rellena las tablas de un sector individual (dentro de un bloque clonado).

    Se llama desde replicar_sectores() para cada sector.
    marker_suffix es el número de sector (1, 2, 3...) que se añadió al clonar.
    """
    por_sector = resultados.get("por_sector", {})
    datos = por_sector.get(sector_id, {})
    nombre = sector_data.get("nombre_sector", "")

    # Tabla de resultados media
    for escenario, marker_base in [("media", "MEDIA"), ("punta", "MAXIMA"), ("nocturno", "MINIMA")]:
        marker = f"{{{{TABLA_SECTOR_{marker_suffix}_{marker_base}}}}}"
        table = _find_table_by_marker(doc, marker)
        if not table:
            continue
        _clear_data_rows(table)
        esc_datos = datos.get(escenario, {})
        _add_row(table, [
            nombre,
            _safe_get(esc_datos, "presion_minima"),
            _safe_get(esc_datos, "presion_media"),
            _safe_get(esc_datos, "presion_maxima"),
            _safe_get(esc_datos, "velocidad_media"),
            _safe_get(esc_datos, "velocidad_maxima"),
            _safe_get(esc_datos, "pct_baja_vel"),
        ])

    # Tabla de depósitos
    marker = f"{{{{TABLA_SECTOR_{marker_suffix}_DEPOSITOS}}}}"
    table = _find_table_by_marker(doc, marker)
    if table:
        _clear_data_rows(table)
        for d in resultados.get("depositos_eps", []):
            if d.get("sector") == nombre:
                nivel_min = float(_safe_get(d, "nivel_minimo", 0) or 0)
                alcanza_min = "Sí" if nivel_min <= 0.5 else "No"
                _add_row(table, [
                    _safe_get(d, "deposito"),
                    _safe_get(d, "nivel_medio"),
                    _safe_get(d, "nivel_minimo"),
                    _safe_get(d, "nivel_maximo"),
                    _safe_get(d, "num_ciclos"),
                    alcanza_min,
                ])
