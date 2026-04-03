"""
Consultas SQL para extracción de datos de Giswater/PostgreSQL.
Todas las consultas trabajan sobre el esquema definido en config.py (DB_SCHEMA).
"""
from db.connection import execute_query, execute_scalar


# ============================================================
# MUNICIPIO
# ============================================================

def get_municipio_nombre(muni_id):
    """Devuelve el nombre del municipio a partir de su muni_id."""
    sql = """
        SELECT name
        FROM exploitation
        WHERE expl_id = %s
        LIMIT 1
    """
    return execute_scalar(sql, (muni_id,))


def get_result_ids_disponibles(sector_ids):
    """
    Devuelve los result_id disponibles en rpt_result_cat
    que tengan datos para los sectores indicados.
    """
    sql = """
        SELECT DISTINCT
            rc.result_id,
            rc.descript,
            rc.tstep,
            COUNT(DISTINCT rn.id) AS tstep_count
        FROM rpt_result_cat rc
        LEFT JOIN rpt_node rn ON rn.result_id = rc.result_id
        GROUP BY rc.result_id, rc.descript, rc.tstep
        ORDER BY rc.result_id
    """
    return execute_query(sql)


# ============================================================
# DATOS DEL MUNICIPIO (suma de sectores)
# ============================================================

def get_datos_municipio(muni_id, sector_ids):
    """
    Extrae todos los datos necesarios para rellenar los DOCPROPERTY.
    Todos los valores numéricos se obtienen sumando los sectores indicados.
    """
    placeholders = ','.join(['%s'] * len(sector_ids))

    # Nombre del municipio
    nombre = get_municipio_nombre(muni_id)

    # Longitudes de red por nivel funcional
    sql_longitudes = f"""
        SELECT
            ROUND(SUM(gis_length) / 1000.0, 2) AS longitud_total_km,
            ROUND(SUM(CASE WHEN cat_feature_id ILIKE '%PRIMARY%'
                THEN gis_length ELSE 0 END) / 1000.0, 2) AS longitud_primaria_km,
            ROUND(SUM(CASE WHEN cat_feature_id ILIKE '%SECONDARY%'
                THEN gis_length ELSE 0 END) / 1000.0, 2) AS longitud_secundaria_km,
            COUNT(*) AS num_arcos
        FROM arc
        WHERE sector_id IN ({placeholders})
        AND state = 1
    """
    long_data = execute_query(sql_longitudes, sector_ids)

    # Nodos
    sql_nodos = f"""
        SELECT COUNT(*) AS num_nodos
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'JUNCTION'
    """
    nodos_data = execute_query(sql_nodos, sector_ids)

    # Acometidas (connecs)
    sql_connecs = f"""
        SELECT COUNT(*) AS num_connecs
        FROM connec
        WHERE sector_id IN ({placeholders})
        AND state = 1
    """
    connecs_data = execute_query(sql_connecs, sector_ids)

    # Depósitos
    sql_depositos = f"""
        SELECT
            COUNT(*) AS num_depositos,
            ROUND(SUM(COALESCE(storage, 0)), 0) AS volumen_total_m3
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'TANK'
    """
    depositos_data = execute_query(sql_depositos, sector_ids)

    # Estaciones de bombeo
    sql_bombas = f"""
        SELECT COUNT(*) AS num_estaciones_bombeo
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'PUMP'
    """
    bombas_data = execute_query(sql_bombas, sector_ids)

    # Grupos de presión (booster)
    sql_grupos = f"""
        SELECT COUNT(*) AS num_grupos_presion
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'PUMP'
        AND lower(descript) LIKE '%grupo%'
    """
    grupos_data = execute_query(sql_grupos, sector_ids)

    # VRP
    sql_vrp = f"""
        SELECT COUNT(*) AS num_reductoras
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'PRV'
    """
    vrp_data = execute_query(sql_vrp, sector_ids)

    # Abonados
    sql_abonados = f"""
        SELECT
            COUNT(*) AS num_abonados,
            COUNT(CASE WHEN lower(cat_feature_id) LIKE '%dom%' THEN 1 END)
                AS abonados_domesticos
        FROM connec
        WHERE sector_id IN ({placeholders})
        AND state = 1
    """
    abonados_data = execute_query(sql_abonados, sector_ids)

    # Cotas min/max
    sql_cotas = f"""
        SELECT
            ROUND(MIN(elevation), 0) AS cota_min,
            ROUND(MAX(elevation), 0) AS cota_max
        FROM node
        WHERE sector_id IN ({placeholders})
        AND state = 1
        AND epa_type = 'JUNCTION'
        AND elevation > 0
    """
    cotas_data = execute_query(sql_cotas, sector_ids)

    return {
        "municipio": nombre,
        "longitud_red": long_data[0]["longitud_total_km"] if long_data else 0,
        "longitud_primaria": long_data[0]["longitud_primaria_km"] if long_data else 0,
        "longitud_secundaria": long_data[0]["longitud_secundaria_km"] if long_data else 0,
        "num_arcos": long_data[0]["num_arcos"] if long_data else 0,
        "num_nodos": nodos_data[0]["num_nodos"] if nodos_data else 0,
        "num_connecs": connecs_data[0]["num_connecs"] if connecs_data else 0,
        "num_depositos": depositos_data[0]["num_depositos"] if depositos_data else 0,
        "volumen_depositos": depositos_data[0]["volumen_total_m3"] if depositos_data else 0,
        "num_estaciones_bombeo": bombas_data[0]["num_estaciones_bombeo"] if bombas_data else 0,
        "num_grupos_presion": grupos_data[0]["num_grupos_presion"] if grupos_data else 0,
        "num_reductoras": vrp_data[0]["num_reductoras"] if vrp_data else 0,
        "num_abonados": abonados_data[0]["num_abonados"] if abonados_data else 0,
        "abonados_domesticos": abonados_data[0]["abonados_domesticos"] if abonados_data else 0,
        "cota_min": cotas_data[0]["cota_min"] if cotas_data else 0,
        "cota_max": cotas_data[0]["cota_max"] if cotas_data else 0,
    }


# ============================================================
# DATOS DE SECTORES
# ============================================================

def get_datos_sectores(sector_ids):
    """
    Devuelve información detallada de cada sector hidráulico.
    Un dict por sector_id con todos los datos necesarios para
    las tablas de capítulos 2, 3, 5 y 6.
    """
    placeholders = ','.join(['%s'] * len(sector_ids))

    sql = f"""
        SELECT
            s.sector_id,
            s.name AS nombre_sector,
            -- Longitudes
            ROUND(SUM(a.gis_length) / 1000.0, 2) AS longitud_km,
            -- Nodos
            COUNT(DISTINCT CASE WHEN n.epa_type = 'JUNCTION' THEN n.node_id END)
                AS num_nodos,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'TANK' THEN n.node_id END)
                AS num_depositos,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'PUMP' THEN n.node_id END)
                AS num_bombas,
            COUNT(DISTINCT CASE WHEN n.epa_type = 'PRV' THEN n.node_id END)
                AS num_vrp,
            -- Abonados
            COUNT(DISTINCT c.connec_id) AS num_abonados,
            -- Cotas
            ROUND(MIN(CASE WHEN n.epa_type='JUNCTION' AND n.elevation > 0
                THEN n.elevation END), 0) AS cota_min,
            ROUND(MAX(CASE WHEN n.epa_type='JUNCTION' AND n.elevation > 0
                THEN n.elevation END), 0) AS cota_max
        FROM sector s
        LEFT JOIN arc a ON a.sector_id = s.sector_id AND a.state = 1
        LEFT JOIN node n ON n.sector_id = s.sector_id AND n.state = 1
        LEFT JOIN connec c ON c.sector_id = s.sector_id AND c.state = 1
        WHERE s.sector_id IN ({placeholders})
        GROUP BY s.sector_id, s.name
        ORDER BY s.sector_id
    """
    return execute_query(sql, sector_ids)


# ============================================================
# RESULTADOS DE SIMULACION EPANET
# ============================================================

def get_timesteps_escenarios(result_id, sector_ids):
    """
    Identifica los timesteps correspondientes a los tres escenarios:
    - media: hora más próxima al caudal medio diario
    - punta: hora de máximo caudal total
    - nocturno: hora de mínimo caudal total

    Devuelve: {'media': id, 'punta': id, 'nocturno': id}
    """
    placeholders = ','.join(['%s'] * len(sector_ids))

    # Caudal total inyectado por timestep
    # (suma de flows en arcos que salen de RESERVOIR o TANK)
    sql = f"""
        SELECT
            rn.id AS timestep_id,
            SUM(ABS(ra.flow)) AS caudal_total
        FROM rpt_arc ra
        JOIN arc a ON a.arc_id = ra.arc_id
        JOIN node n_orig ON n_orig.node_id = a.node_1
        WHERE ra.result_id = %s
        AND a.sector_id IN ({placeholders})
        AND n_orig.epa_type IN ('RESERVOIR', 'TANK')
        GROUP BY rn.id
        ORDER BY rn.id
    """
    # Nota: esta query necesita ajuste una vez verifiquemos la estructura real
    # de rpt_arc en la BD. La columna 'id' puede ser diferente.
    # Se ajustará en la fase de verificación con datos reales.

    params = [result_id] + sector_ids

    # Por ahora devolvemos placeholder — se completará al verificar la estructura real
    return {"media": None, "punta": None, "nocturno": None}


def get_resultados_simulacion(result_id, sector_ids):
    """
    Extrae los resultados de la simulación para los tres escenarios.
    Devuelve un dict con claves 'media', 'punta', 'nocturno',
    cada una con datos agregados por sector.

    NOTA: Esta función será completada una vez se verifique
    la estructura exacta de rpt_node y rpt_arc en la BD real.
    """
    # Placeholder — se completará en la siguiente fase
    return {
        "result_id": result_id,
        "escenarios": {},
        "pendiente": True
    }
