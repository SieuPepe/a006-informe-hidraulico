"""
Consultas SQL para extracción de datos de Giswater/PostgreSQL.
Esquema: abastecimiento
Tablas verificadas: rpt_node (press), rpt_arc (vel), exploitation, sector
Campo time: varchar formato 'H:00:00' (0:00:00 a 167:00:00 para EPS 168h)
"""
from db.connection import execute_query, execute_scalar


# ─────────────────────────────────────────────────────────────
# CONSULTAS DE IDENTIFICACIÓN
# ─────────────────────────────────────────────────────────────

def get_municipio_nombre(muni_id):
    """Devuelve el nombre del municipio a partir de su muni_id."""
    sql = "SELECT name FROM ext_municipality WHERE muni_id = %s LIMIT 1"
    return execute_scalar(sql, (muni_id,))


def get_result_ids_disponibles():
    """Lista los result_id disponibles con su número de timesteps."""
    sql = """
        SELECT result_id, COUNT(DISTINCT time) AS num_timesteps
        FROM rpt_node
        GROUP BY result_id
        ORDER BY result_id
    """
    return execute_query(sql)


# ─────────────────────────────────────────────────────────────
# IDENTIFICACIÓN DE ESCENARIOS (timesteps de interés)
# ─────────────────────────────────────────────────────────────

def get_timesteps_escenarios(result_id, sector_ids):
    """
    Identifica los timesteps de punta, media y mínimo nocturno
    a partir del caudal total inyectado en cada hora.
    """
    placeholders = ','.join(['%s'] * len(sector_ids))
    params = [result_id] + list(sector_ids)
    sql = f"""
        SELECT ra.time, SUM(ABS(ra.flow)) AS caudal_total
        FROM rpt_arc ra
        JOIN v_edit_arc a ON a.arc_id = ra.arc_id
        WHERE ra.result_id = %s
          AND a.sector_id IN ({placeholders})
        GROUP BY ra.time
        ORDER BY caudal_total DESC
    """
    rows = execute_query(sql, params)
    if not rows:
        return {'punta': None, 'media': None, 'nocturno': None}

    caudal_medio = sum(r['caudal_total'] for r in rows) / len(rows)
    return {
        'punta':    rows[0]['time'],
        'nocturno': rows[-1]['time'],
        'media':    min(rows, key=lambda r: abs(r['caudal_total'] - caudal_medio))['time'],
    }


# ─────────────────────────────────────────────────────────────
# DATOS DEL MUNICIPIO (valores escalares para DOCPROPERTY)
# ─────────────────────────────────────────────────────────────

def get_datos_municipio(muni_id, sector_ids):
    """Extrae todos los valores escalares del municipio a partir de los sectores."""
    ph = ','.join(['%s'] * len(sector_ids))
    nombre = get_municipio_nombre(muni_id)

    # Longitudes y conteo de arcos
    long_data = execute_query(f"""
        SELECT
            ROUND(SUM(gis_length) / 1000.0, 2) AS longitud_total_km,
            COUNT(*) AS num_arcos
        FROM v_edit_arc
        WHERE sector_id IN ({ph}) AND state = 1
    """, sector_ids)

    # Longitud por nivel funcional — usa feature_type del arc
    long_prim = execute_scalar(f"""
        SELECT ROUND(SUM(gis_length) / 1000.0, 2)
        FROM v_edit_arc
        WHERE sector_id IN ({ph}) AND state = 1
          AND category_type = 'PR'
    """, sector_ids) or 0

    # Nodos
    nodos = execute_scalar(f"""
        SELECT COUNT(*)
        FROM node
        WHERE sector_id IN ({ph}) AND state = 1 AND epa_type = 'JUNCTION'
    """, sector_ids) or 0

    # Connecs (acometidas)
    connecs = execute_scalar(f"""
        SELECT COUNT(*)
        FROM connec
        WHERE sector_id IN ({ph}) AND state = 1
    """, sector_ids) or 0

    # Depósitos (volumen desde man_tank)
    dep = execute_query(f"""
        SELECT COUNT(*) AS n,
               COALESCE(ROUND(SUM(COALESCE(mt.vutil, mt.vmax, 0))::numeric, 0), 0) AS vol
        FROM node n
        LEFT JOIN man_tank mt ON mt.node_id = n.node_id
        WHERE n.sector_id IN ({ph}) AND n.state = 1 AND n.epa_type = 'TANK'
    """, sector_ids)

    # Bombas (PUMP con pump_type=FLOWPUMP)
    bombas = execute_scalar(f"""
        SELECT COUNT(*)
        FROM node n
        JOIN inp_pump ip ON ip.node_id = n.node_id
        WHERE n.sector_id IN ({ph}) AND n.state = 1
          AND n.epa_type = 'PUMP' AND ip.pump_type = 'FLOWPUMP'
    """, sector_ids) or 0

    # Grupos de presión (PUMP con pump_type=PRESSPUMP)
    grupos_presion = execute_scalar(f"""
        SELECT COUNT(*)
        FROM node n
        JOIN inp_pump ip ON ip.node_id = n.node_id
        WHERE n.sector_id IN ({ph}) AND n.state = 1
          AND n.epa_type = 'PUMP' AND ip.pump_type = 'PRESSPUMP'
    """, sector_ids) or 0

    # Válvulas reductoras
    vrp = execute_scalar(f"""
        SELECT COUNT(*)
        FROM node
        WHERE sector_id IN ({ph}) AND state = 1
          AND epa_type IN ('PRV', 'VALVE')
    """, sector_ids) or 0

    # Cotas
    cotas = execute_query(f"""
        SELECT ROUND(MIN(elevation)::numeric, 0) AS cmin,
               ROUND(MAX(elevation)::numeric, 0) AS cmax
        FROM node
        WHERE sector_id IN ({ph}) AND state = 1
          AND epa_type = 'JUNCTION' AND elevation > 0
    """, sector_ids)

    # Materiales de red
    materiales_primaria = get_materiales_red(sector_ids, nivel='primaria')
    materiales_secundaria = get_materiales_red(sector_ids, nivel='secundaria')

    # Rugosidades
    rugosidades = get_rugosidades(sector_ids)

    # Reglas de operación
    reglas = get_reglas(sector_ids)

    # Lookup node_id → nombre (para depósitos referenciados en reglas)
    nombres_nodos_raw = execute_query("""
        SELECT n.node_id::text AS nid, COALESCE(mt.name, n.descript, n.code) AS nombre
        FROM node n
        LEFT JOIN man_tank mt ON mt.node_id = n.node_id
        WHERE n.epa_type = 'TANK' AND n.state = 1
    """)
    nombres_nodos = {r['nid']: r['nombre'] for r in (nombres_nodos_raw or [])}

    # Demandas por sector
    demandas_sector = get_demandas_por_sector(sector_ids)

    # Demanda total
    demanda_total_ls = sum(
        float(d.get('demanda_media_ls') or 0) for d in demandas_sector
    )

    longitud_total = float(long_data[0]["longitud_total_km"] or 0) if long_data else 0
    longitud_primaria = float(long_prim or 0)
    longitud_secundaria = round(longitud_total - longitud_primaria, 2)

    return {
        "municipio": nombre,
        "longitud_red": longitud_total,
        "longitud_primaria": longitud_primaria,
        "longitud_secundaria": longitud_secundaria,
        "num_arcos": int(long_data[0]["num_arcos"]) if long_data else 0,
        "num_nodos": int(nodos),
        "num_connecs": int(connecs),
        "num_depositos": int(dep[0]["n"]) if dep else 0,
        "volumen_depositos": int(dep[0]["vol"]) if dep else 0,
        "num_estaciones_bombeo": int(bombas),
        "num_grupos_presion": int(grupos_presion),
        "num_reductoras": int(vrp),
        "num_abonados": int(connecs),
        "cota_min": int(cotas[0]["cmin"]) if cotas and cotas[0]["cmin"] else 0,
        "cota_max": int(cotas[0]["cmax"]) if cotas and cotas[0]["cmax"] else 0,
        "materiales_primaria": materiales_primaria,
        "materiales_secundaria": materiales_secundaria,
        "rugosidades": rugosidades,
        "reglas": reglas,
        "nombres_nodos": nombres_nodos,
        "demandas_sector": demandas_sector,
        "demanda_media_ls": round(demanda_total_ls, 3),
        "demanda_media_m3ano": round(demanda_total_ls * 86.4 * 365, 0),
    }


# ─────────────────────────────────────────────────────────────
# DATOS POR SECTOR
# ─────────────────────────────────────────────────────────────

def get_datos_sectores(sector_ids):
    """Devuelve lista de dicts con datos completos de cada sector."""
    ph = ','.join(['%s'] * len(sector_ids))
    sectores = execute_query(f"""
        SELECT
            s.sector_id,
            s.name AS nombre_sector,
            COUNT(DISTINCT a.arc_id) AS num_arcos,
            ROUND(SUM(a.gis_length) / 1000.0, 2) AS longitud_km,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'JUNCTION' THEN n.node_id END) AS num_nodos,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'TANK'     THEN n.node_id END) AS num_depositos,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'PUMP'     THEN n.node_id END) AS num_bombas,
            COUNT(DISTINCT CASE WHEN n.epa_type IN ('PRV','VALVE') THEN n.node_id END) AS num_vrp,
            COUNT(DISTINCT c.connec_id) AS num_abonados,
            ROUND(MIN(CASE WHEN n.epa_type = 'JUNCTION' AND n.elevation > 0
                       THEN n.elevation END)::numeric, 0) AS cota_min,
            ROUND(MAX(CASE WHEN n.epa_type = 'JUNCTION' AND n.elevation > 0
                       THEN n.elevation END)::numeric, 0) AS cota_max
        FROM sector s
        LEFT JOIN v_edit_arc a ON a.sector_id = s.sector_id AND a.state = 1
        LEFT JOIN node n   ON n.sector_id = s.sector_id AND n.state = 1
        LEFT JOIN connec c ON c.sector_id = s.sector_id AND c.state = 1
        WHERE s.sector_id IN ({ph})
        GROUP BY s.sector_id, s.name
        ORDER BY s.sector_id
    """, sector_ids)

    # Cotas servidas solo de red secundaria (category_type = 'SC')
    for s in sectores:
        sid = s['sector_id']
        cotas_sc = execute_query("""
            SELECT ROUND(MIN(n.elevation)::numeric, 0) AS cota_min_sc,
                   ROUND(MAX(n.elevation)::numeric, 0) AS cota_max_sc
            FROM node n
            JOIN v_edit_arc a ON (a.node_1 = n.node_id OR a.node_2 = n.node_id)
            WHERE a.sector_id = %s AND a.state = 1 AND a.category_type = 'SC'
              AND n.epa_type = 'JUNCTION' AND n.elevation > 0
        """, (sid,))
        if cotas_sc and cotas_sc[0]:
            s['cota_min_sc'] = cotas_sc[0].get('cota_min_sc')
            s['cota_max_sc'] = cotas_sc[0].get('cota_max_sc')
        else:
            s['cota_min_sc'] = s.get('cota_min')
            s['cota_max_sc'] = s.get('cota_max')

        s['depositos'] = execute_query("""
            SELECT n.code,
                COALESCE(mt.name, n.descript, n.code) AS nombre,
                ROUND(n.elevation::numeric, 2) AS cota_solera,
                ROUND((n.elevation + COALESCE(it.maxlevel, 0))::numeric, 2) AS cota_rebose,
                ROUND((n.elevation + COALESCE(it.minlevel, 0))::numeric, 2) AS cota_minima,
                ROUND((n.elevation + COALESCE(it.maxlevel, 0))::numeric, 2) AS cota_maxima,
                ROUND(COALESCE(mt.vutil, mt.vmax, 0)::numeric, 0) AS volumen_m3
            FROM node n
            LEFT JOIN man_tank mt ON mt.node_id = n.node_id
            LEFT JOIN inp_tank it ON it.node_id = n.node_id
            WHERE n.sector_id = %s AND n.state = 1 AND n.epa_type = 'TANK'
            ORDER BY n.code
        """, (sid,))
        s['fuentes'] = execute_query("""
            SELECT n.code, COALESCE(ms.name, n.descript, n.code) AS nombre,
                ROUND(n.elevation::numeric, 2) AS cota_toma
            FROM node n
            LEFT JOIN man_source ms ON ms.node_id = n.node_id
            WHERE n.sector_id = %s AND n.state = 1 AND n.epa_type = 'RESERVOIR'
            ORDER BY n.code
        """, (sid,))
        s['bombas'] = execute_query("""
            SELECT n.code, COALESCE(n.descript, n.code) AS nombre,
                ip.pump_type, ip.curve_id, ip.power,
                mp.pressure AS presion_consigna
            FROM node n
            JOIN inp_pump ip ON ip.node_id = n.node_id
            LEFT JOIN man_pump mp ON mp.node_id = n.node_id
            WHERE n.sector_id = %s AND n.state = 1
              AND n.epa_type = 'PUMP'
            ORDER BY n.code
        """, (sid,))
        s['vrp'] = execute_query("""
            SELECT n.code, COALESCE(n.descript, n.code) AS nombre,
                iv.valv_type,
                iv.nodecat_id,
                COALESCE(iv.custom_dint, iv.cat_dint) AS diametro_mm,
                ROUND(COALESCE(iv.pressure, iv.flow)::numeric, 0) AS presion_consigna
            FROM node n
            LEFT JOIN v_edit_inp_valve iv ON iv.node_id::text = n.node_id::text
            WHERE n.sector_id = %s AND n.state = 1
              AND n.epa_type IN ('PRV', 'VALVE')
            ORDER BY n.code
        """, (sid,))
    return sectores


# ─────────────────────────────────────────────────────────────
# MATERIALES Y RUGOSIDADES
# ─────────────────────────────────────────────────────────────

def get_materiales_red(sector_ids, nivel='primaria'):
    """Composición de la red por material para un nivel funcional."""
    ph = ','.join(['%s'] * len(sector_ids))
    cat_type = 'PR' if nivel == 'primaria' else 'SC'
    return execute_query(f"""
        SELECT
            ca.matcat_id AS material,
            CONCAT(MIN(ca.dnom)::text, ' - ', MAX(ca.dnom)::text) AS rango_diametros_mm,
            ROUND(SUM(a.gis_length)::numeric, 0) AS longitud_m,
            ROUND(100.0 * SUM(a.gis_length) /
                NULLIF(SUM(SUM(a.gis_length)) OVER (), 0), 1) AS pct_total
        FROM v_edit_arc a
        JOIN cat_arc ca ON ca.id = a.arccat_id
        WHERE a.sector_id IN ({ph}) AND a.state = 1
          AND a.category_type = %s
        GROUP BY ca.matcat_id
        ORDER BY longitud_m DESC
    """, list(sector_ids) + [cat_type])


def get_rugosidades(sector_ids):
    """Coeficientes de Hazen-Williams por material presente en la red."""
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT DISTINCT
            ca.matcat_id AS codigo,
            ca.matcat_id AS material,
            r.roughness AS coeficiente_c
        FROM v_edit_arc a
        JOIN cat_arc ca ON ca.id = a.arccat_id
        JOIN cat_mat_roughness r ON r.matcat_id = ca.matcat_id
        WHERE a.sector_id IN ({ph}) AND a.state = 1
          AND r.period_id = 'Default'
        ORDER BY r.roughness DESC
    """, sector_ids)


def get_reglas(sector_ids):
    """Reglas y controles de operación desde Giswater.

    Trae tanto Controls (reglas simples) como Rules (reglas complejas).
    """
    controls = execute_query("""
        SELECT id, sector_id, text, 'Control' AS tipo
        FROM v_edit_inp_controls
        WHERE active IS TRUE
        ORDER BY id
    """)
    rules = execute_query("""
        SELECT id, sector_id, text, 'Rule' AS tipo
        FROM v_edit_inp_rules
        WHERE active IS TRUE
        ORDER BY id
    """)
    return (controls or []) + (rules or [])


def get_demandas_por_sector(sector_ids):
    """Demanda media por sector hidráulico.

    Usa inp_connec.demand (demanda asignada a cada acometida en l/s).
    v_edit_connec.demand es NULL; inp_connec tiene los valores reales.
    """
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT
            s.sector_id,
            s.name AS nombre_sector,
            COUNT(DISTINCT c.connec_id) AS num_abonados,
            ROUND(COALESCE(SUM(ic.demand), 0)::numeric, 3) AS demanda_media_ls,
            ROUND(COALESCE(SUM(ic.demand), 0) * 86.4, 1) AS demanda_media_m3dia
        FROM sector s
        LEFT JOIN connec c ON c.sector_id = s.sector_id AND c.state = 1
        LEFT JOIN inp_connec ic ON ic.connec_id = c.connec_id
        WHERE s.sector_id IN ({ph})
        GROUP BY s.sector_id, s.name
        ORDER BY s.sector_id
    """, sector_ids)


# ─────────────────────────────────────────────────────────────
# INDICADORES TPI (Alegre & Coelho, 1995 — IWA)
# ─────────────────────────────────────────────────────────────

def get_tpi_por_sector(result_id, sector_ids):
    """Calcula TPI de presión y velocidad promediando sobre todos los timesteps.

    Método TPI: curva de penalización trapecial continua 0-1, promedio aritmético.
    press > 0 excluye nodos de aducción próximos a reservorios.
    ABS(vel) porque EPANET puede devolver negativos según dirección del flujo.
    """
    ph = ','.join(['%s'] * len(sector_ids))

    # TPI presión
    tpi_press = execute_query(f"""
        SELECT n.sector_id,
            ROUND(AVG(
                CASE
                    WHEN rn.press < 10 THEN 0.0
                    WHEN rn.press < 20 THEN (rn.press - 10.0) / 10.0
                    WHEN rn.press <= 60 THEN 1.0
                    WHEN rn.press <= 80 THEN (80.0 - rn.press) / 20.0
                    ELSE 0.0
                END
            )::numeric, 4) AS tpi_presion
        FROM rpt_node rn
        JOIN node n ON n.node_id = rn.node_id
        WHERE rn.result_id = %s
          AND n.sector_id IN ({ph})
          AND n.epa_type = 'JUNCTION'
          AND rn.press > 0
        GROUP BY n.sector_id
    """, [result_id] + list(sector_ids))

    # TPI velocidad
    tpi_vel = execute_query(f"""
        SELECT a.sector_id,
            ROUND(AVG(
                CASE
                    WHEN ABS(ra.vel) < 0.02 THEN 0.0
                    WHEN ABS(ra.vel) < 0.05 THEN (ABS(ra.vel) - 0.02) / 0.03
                    WHEN ABS(ra.vel) <= 1.50 THEN 1.0
                    WHEN ABS(ra.vel) <= 3.00 THEN (3.00 - ABS(ra.vel)) / 1.50
                    ELSE 0.0
                END
            )::numeric, 4) AS tpi_velocidad
        FROM rpt_arc ra
        JOIN v_edit_arc a ON a.arc_id = ra.arc_id
        WHERE ra.result_id = %s
          AND a.sector_id IN ({ph})
        GROUP BY a.sector_id
    """, [result_id] + list(sector_ids))

    # Combinar en dict por sector_id
    result = {}
    for r in tpi_press:
        sid = r['sector_id']
        result[sid] = {'tpi_presion': r['tpi_presion']}
    for r in tpi_vel:
        sid = r['sector_id']
        if sid not in result:
            result[sid] = {}
        result[sid]['tpi_velocidad'] = r['tpi_velocidad']

    return result


def get_autonomia_depositos(result_id, sector_ids):
    """Calcula la autonomía de cada depósito individual.

    Autonomía (h) = volumen útil medio (m³) / caudal salida medio (m³/h)
    Caudal salida: promedio de ABS(flow) en arcos cuyo node_1 es el depósito.
    """
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        WITH dep_nivel AS (
            SELECT n.node_id, COALESCE(mt.name, n.descript, n.code) AS deposito, s.name AS sector,
                n.sector_id,
                ROUND(AVG(rn.head - n.elevation)::numeric, 2) AS nivel_medio,
                COALESCE(mt.vutil, mt.vmax, 0) AS volumen_ref
            FROM rpt_node rn
            JOIN node n ON n.node_id = rn.node_id
            JOIN sector s ON s.sector_id = n.sector_id
            LEFT JOIN man_tank mt ON mt.node_id = n.node_id
            WHERE rn.result_id = %s
              AND n.sector_id IN ({ph})
              AND n.epa_type = 'TANK'
            GROUP BY n.node_id, n.code, n.descript, s.name, n.sector_id, n.elevation, mt.name, mt.vutil, mt.vmax
        ),
        dep_caudal AS (
            SELECT a.node_1 AS node_id,
                ROUND(AVG(ABS(ra.flow))::numeric, 3) AS caudal_salida_ls
            FROM rpt_arc ra
            JOIN v_edit_arc a ON a.arc_id = ra.arc_id
            JOIN node n ON n.node_id = a.node_1 AND n.epa_type = 'TANK'
            WHERE ra.result_id = %s
              AND n.sector_id IN ({ph})
            GROUP BY a.node_1
        )
        SELECT dn.deposito, dn.sector, dn.sector_id,
            dn.nivel_medio,
            dn.volumen_ref AS volumen_util_m3,
            COALESCE(dc.caudal_salida_ls, 0) AS caudal_salida_ls,
            CASE WHEN COALESCE(dc.caudal_salida_ls, 0) > 0
                THEN ROUND((dn.volumen_ref / (dc.caudal_salida_ls * 3.6))::numeric, 1)
                ELSE NULL
            END AS autonomia_h
        FROM dep_nivel dn
        LEFT JOIN dep_caudal dc ON dc.node_id = dn.node_id
        ORDER BY dn.sector, dn.deposito
    """, [result_id] + list(sector_ids) + [result_id] + list(sector_ids))


# ─────────────────────────────────────────────────────────────
# RESULTADOS DE SIMULACIÓN
# ─────────────────────────────────────────────────────────────

def get_resultados_simulacion(result_id, sector_ids):
    """
    Wrapper principal que extrae todos los resultados de la simulación.
    Devuelve un dict con: timesteps, globales, por_sector, depositos_eps,
    indicadores_retencion.
    """
    timesteps = get_timesteps_escenarios(result_id, sector_ids)

    globales = get_resultados_globales(result_id, sector_ids, timesteps)
    por_sector = get_resultados_por_sector(result_id, sector_ids, timesteps)
    depositos_eps = get_depositos_eps(result_id, sector_ids)
    indicadores_ret = get_indicadores_retencion(
        result_id, sector_ids, timesteps.get('media')
    )
    tpi = get_tpi_por_sector(result_id, sector_ids)
    autonomia = get_autonomia_depositos(result_id, sector_ids)

    return {
        'timesteps': timesteps,
        'globales': globales,
        'por_sector': por_sector,
        'depositos_eps': depositos_eps,
        'indicadores_retencion': indicadores_ret,
        'tpi': tpi,
        'autonomia': autonomia,
    }


def get_resultados_globales(result_id, sector_ids, timesteps):
    """Indicadores globales para los tres escenarios."""
    ph = ','.join(['%s'] * len(sector_ids))
    resultados = {}

    for escenario, time_val in timesteps.items():
        if not time_val:
            continue
        p_nodos = [result_id, time_val] + list(sector_ids)
        p_arcos = [result_id, time_val] + list(sector_ids)

        nodos = execute_query(f"""
            SELECT
                ROUND(AVG(rn.press)::numeric, 2) AS presion_media,
                ROUND(MIN(rn.press)::numeric, 2) AS presion_minima,
                ROUND(MAX(rn.press)::numeric, 2) AS presion_maxima,
                ROUND(100.0 * COUNT(CASE WHEN rn.press < 10 THEN 1 END)
                    / NULLIF(COUNT(*), 0), 1) AS pct_baja_presion,
                ROUND(100.0 * COUNT(CASE WHEN rn.press > 60 THEN 1 END)
                    / NULLIF(COUNT(*), 0), 1) AS pct_alta_presion
            FROM rpt_node rn
            JOIN node n ON n.node_id = rn.node_id
            WHERE rn.result_id = %s AND rn.time = %s
              AND n.sector_id IN ({ph}) AND n.epa_type = 'JUNCTION'
        """, p_nodos)

        # Caudal inyectado = sum(demand) de nodos TANK + RESERVOIR
        caudal_inj = execute_query(f"""
            SELECT ROUND(SUM(ABS(rn.demand))::numeric, 2) AS caudal_total_ls
            FROM rpt_node rn
            JOIN node n ON n.node_id = rn.node_id
            WHERE rn.result_id = %s AND rn.time = %s
              AND n.sector_id IN ({ph})
              AND n.epa_type IN ('TANK', 'RESERVOIR')
        """, p_nodos)

        arcos = execute_query(f"""
            SELECT
                ROUND(AVG(ABS(ra.vel))::numeric, 3) AS velocidad_media,
                ROUND(MAX(ABS(ra.vel))::numeric, 3) AS velocidad_maxima,
                ROUND(100.0 * COUNT(CASE WHEN ABS(ra.vel) < 0.05 THEN 1 END)
                    / NULLIF(COUNT(*), 0), 1) AS pct_baja_vel,
                ROUND(100.0 * COUNT(CASE WHEN ABS(ra.vel) > 1.5 THEN 1 END)
                    / NULLIF(COUNT(*), 0), 1) AS pct_alta_vel
            FROM rpt_arc ra
            JOIN v_edit_arc a ON a.arc_id = ra.arc_id
            WHERE ra.result_id = %s AND ra.time = %s
              AND a.sector_id IN ({ph})
        """, p_arcos)

        resultados[escenario] = {
            "time": time_val,
            **(caudal_inj[0] if caudal_inj else {}),
            **(nodos[0] if nodos else {}),
            **(arcos[0] if arcos else {}),
        }
    return resultados


def get_resultados_por_sector(result_id, sector_ids, timesteps):
    """Resultados agregados por sector para los tres escenarios."""
    resultados = {}
    for sector_id in sector_ids:
        resultados[sector_id] = {}
        for escenario, time_val in timesteps.items():
            if not time_val:
                continue
            p = [result_id, time_val, sector_id]

            press = execute_query("""
                SELECT
                    ROUND(MIN(rn.press)::numeric, 2) AS presion_minima,
                    ROUND(AVG(rn.press)::numeric, 2) AS presion_media,
                    ROUND(MAX(rn.press)::numeric, 2) AS presion_maxima,
                    COUNT(CASE WHEN rn.press < 10 THEN 1 END) AS nodos_baja_presion,
                    COUNT(CASE WHEN rn.press > 60 THEN 1 END) AS nodos_alta_presion,
                    COUNT(*) AS total_nodos
                FROM rpt_node rn
                JOIN node n ON n.node_id = rn.node_id
                WHERE rn.result_id = %s AND rn.time = %s
                  AND n.sector_id = %s AND n.epa_type = 'JUNCTION'
            """, p)

            vel = execute_query("""
                SELECT
                    ROUND(AVG(ABS(ra.vel))::numeric, 3) AS velocidad_media,
                    ROUND(MAX(ABS(ra.vel))::numeric, 3) AS velocidad_maxima,
                    ROUND(100.0 * COUNT(CASE WHEN ABS(ra.vel) < 0.05 THEN 1 END)
                        / NULLIF(COUNT(*), 0), 1) AS pct_baja_vel,
                    ROUND(100.0 * COUNT(CASE WHEN ABS(ra.vel) > 1.5 THEN 1 END)
                        / NULLIF(COUNT(*), 0), 1) AS pct_alta_vel,
                    ROUND(AVG(ra.headloss / NULLIF(ra.length / 1000.0, 0))::numeric, 3)
                        AS perdida_unitaria_media
                FROM rpt_arc ra
                JOIN v_edit_arc a ON a.arc_id = ra.arc_id
                WHERE ra.result_id = %s AND ra.time = %s AND a.sector_id = %s
            """, p)

            resultados[sector_id][escenario] = {
                "time": time_val,
                **(press[0] if press else {}),
                **(vel[0] if vel else {}),
            }
    return resultados


def get_depositos_eps(result_id, sector_ids):
    """Comportamiento de depósitos a lo largo de la EPS."""
    ph = ','.join(['%s'] * len(sector_ids))
    depositos = execute_query(f"""
        SELECT
            COALESCE(mt.name, n.descript, n.code) AS deposito,
            s.name AS sector,
            ROUND(MIN(rn.head - n.elevation)::numeric, 2) AS nivel_minimo,
            ROUND(MAX(rn.head - n.elevation)::numeric, 2) AS nivel_maximo,
            ROUND(AVG(rn.head - n.elevation)::numeric, 2) AS nivel_medio,
            COALESCE(mt.vutil, mt.vmax, 0) AS volumen_util_m3
        FROM rpt_node rn
        JOIN node n ON n.node_id = rn.node_id
        JOIN sector s ON s.sector_id = n.sector_id
        LEFT JOIN man_tank mt ON mt.node_id = n.node_id
        WHERE rn.result_id = %s
          AND n.sector_id IN ({ph})
          AND n.epa_type = 'TANK'
        GROUP BY mt.name, n.descript, n.code, s.name, n.elevation, mt.vutil, mt.vmax
        ORDER BY s.name, n.code
    """, [result_id] + list(sector_ids))

    # Calcular ciclos llenado/vaciado por depósito
    for dep in depositos:
        dep_name = dep['deposito']
        # Obtener serie temporal del nivel
        serie = execute_query(f"""
            SELECT rn.time, (rn.head - n.elevation) AS nivel
            FROM rpt_node rn
            JOIN node n ON n.node_id = rn.node_id
            LEFT JOIN man_tank mt ON mt.node_id = n.node_id
            WHERE rn.result_id = %s
              AND n.epa_type = 'TANK'
              AND n.sector_id IN ({ph})
              AND COALESCE(mt.name, n.descript, n.code) = %s
            ORDER BY rn.id
        """, [result_id] + list(sector_ids) + [dep_name])
        # Contar cambios de dirección (subida → bajada = 1 ciclo)
        ciclos = 0
        if serie and len(serie) > 2:
            subiendo = None
            for i in range(1, len(serie)):
                nivel_ant = float(serie[i-1]['nivel'] or 0)
                nivel_act = float(serie[i]['nivel'] or 0)
                if nivel_act > nivel_ant + 0.01:
                    if subiendo is False:
                        ciclos += 1
                    subiendo = True
                elif nivel_act < nivel_ant - 0.01:
                    subiendo = False
        dep['num_ciclos'] = ciclos

    return depositos


def get_indicadores_retencion(result_id, sector_ids, timestep_media):
    """Tiempo de retención en red y depósitos por sector (escenario media)."""
    if not timestep_media:
        return []
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT
            a.sector_id,
            s.name AS nombre_sector,
            ROUND(SUM(PI() * POWER(ca.dnom::numeric / 1000.0 / 2.0, 2) * a.gis_length)::numeric, 2)
                AS volumen_red_m3,
            ROUND(AVG(ABS(ra.flow))::numeric, 3) AS caudal_medio_ls,
            ROUND(
                (SUM(PI() * POWER(ca.dnom::numeric / 1000.0 / 2.0, 2) * a.gis_length)
                 / NULLIF(AVG(ABS(ra.flow)) / 1000.0, 0) / 3600.0)::numeric, 1
            ) AS tiempo_retencion_red_h
        FROM rpt_arc ra
        JOIN v_edit_arc a ON a.arc_id = ra.arc_id
        JOIN cat_arc ca ON ca.id = a.arccat_id
        JOIN sector s ON s.sector_id = a.sector_id
        WHERE ra.result_id = %s AND ra.time = %s
          AND a.sector_id IN ({ph})
        GROUP BY a.sector_id, s.name
        ORDER BY a.sector_id
    """, [result_id, timestep_media] + list(sector_ids))
