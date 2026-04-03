"""
Consultas SQL para extracción de datos de Giswater/PostgreSQL.
Esquema: abastecimiento
Tablas verificadas: rpt_node (press), rpt_arc (vel), exploitation, sector
"""
from db.connection import execute_query, execute_scalar


def get_municipio_nombre(muni_id):
    sql = "SELECT name FROM exploitation WHERE expl_id = %s LIMIT 1"
    return execute_scalar(sql, (muni_id,))


def get_result_ids_disponibles():
    sql = """
        SELECT result_id, COUNT(DISTINCT time) AS num_timesteps
        FROM rpt_node
        GROUP BY result_id
        ORDER BY result_id
    """
    return execute_query(sql)


def get_timesteps_escenarios(result_id, sector_ids):
    """Identifica los timesteps de punta, media y mínimo nocturno."""
    placeholders = ','.join(['%s'] * len(sector_ids))
    params = [result_id] + list(sector_ids)
    sql = f"""
        SELECT ra.time, SUM(ABS(ra.flow)) AS caudal_total
        FROM rpt_arc ra
        JOIN arc a ON a.arc_id = ra.arc_id
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
        'media':    min(rows, key=lambda r: abs(r['caudal_total'] - caudal_medio))['time']
    }


def get_datos_municipio(muni_id, sector_ids):
    """Extrae todos los valores escalares para DOCPROPERTY."""
    ph = ','.join(['%s'] * len(sector_ids))
    nombre = get_municipio_nombre(muni_id)

    long_data = execute_query(f"""
        SELECT
            ROUND(SUM(gis_length)/1000.0,2) AS longitud_total_km,
            ROUND(SUM(CASE WHEN cat_feature_id ILIKE '%primary%' OR cat_feature_id ILIKE '%primaria%'
                THEN gis_length ELSE 0 END)/1000.0,2) AS longitud_primaria_km,
            ROUND(SUM(CASE WHEN cat_feature_id ILIKE '%secondary%' OR cat_feature_id ILIKE '%secundaria%'
                THEN gis_length ELSE 0 END)/1000.0,2) AS longitud_secundaria_km,
            COUNT(*) AS num_arcos
        FROM arc WHERE sector_id IN ({ph}) AND state=1
    """, sector_ids)

    nodos  = execute_query(f"SELECT COUNT(*) AS v FROM node WHERE sector_id IN ({ph}) AND state=1 AND epa_type='JUNCTION'", sector_ids)
    connec = execute_query(f"SELECT COUNT(*) AS v FROM connec WHERE sector_id IN ({ph}) AND state=1", sector_ids)
    dep    = execute_query(f"SELECT COUNT(*) AS n, COALESCE(ROUND(SUM(storage),0),0) AS vol FROM node WHERE sector_id IN ({ph}) AND state=1 AND epa_type='TANK'", sector_ids)
    bombas = execute_query(f"SELECT COUNT(*) AS v FROM node WHERE sector_id IN ({ph}) AND state=1 AND epa_type='PUMP'", sector_ids)
    vrp    = execute_query(f"SELECT COUNT(*) AS v FROM node WHERE sector_id IN ({ph}) AND state=1 AND epa_type='PRV'", sector_ids)
    abo    = execute_query(f"SELECT COUNT(*) AS v FROM connec WHERE sector_id IN ({ph}) AND state=1", sector_ids)
    cotas  = execute_query(f"SELECT ROUND(MIN(elevation),0) AS cmin, ROUND(MAX(elevation),0) AS cmax FROM node WHERE sector_id IN ({ph}) AND state=1 AND epa_type='JUNCTION' AND elevation>0", sector_ids)

    return {
        "municipio":             nombre,
        "longitud_red":          long_data[0]["longitud_total_km"]      if long_data else 0,
        "longitud_primaria":     long_data[0]["longitud_primaria_km"]   if long_data else 0,
        "longitud_secundaria":   long_data[0]["longitud_secundaria_km"] if long_data else 0,
        "num_arcos":             long_data[0]["num_arcos"]              if long_data else 0,
        "num_nodos":             nodos[0]["v"]   if nodos else 0,
        "num_connecs":           connec[0]["v"]  if connec else 0,
        "num_depositos":         dep[0]["n"]     if dep else 0,
        "volumen_depositos":     dep[0]["vol"]   if dep else 0,
        "num_estaciones_bombeo": bombas[0]["v"]  if bombas else 0,
        "num_grupos_presion":    0,
        "num_reductoras":        vrp[0]["v"]     if vrp else 0,
        "num_abonados":          abo[0]["v"]     if abo else 0,
        "abonados_domesticos":   abo[0]["v"]     if abo else 0,
        "cota_min":              cotas[0]["cmin"] if cotas else 0,
        "cota_max":              cotas[0]["cmax"] if cotas else 0,
    }


def get_datos_sectores(sector_ids):
    """Devuelve lista de dicts con datos completos de cada sector."""
    ph = ','.join(['%s'] * len(sector_ids))
    sectores = execute_query(f"""
        SELECT
            s.sector_id, s.name AS nombre_sector,
            COUNT(DISTINCT a.arc_id) AS num_arcos,
            ROUND(SUM(a.gis_length)/1000.0,2) AS longitud_km,
            COUNT(DISTINCT CASE WHEN n.epa_type='JUNCTION' THEN n.node_id END) AS num_nodos,
            COUNT(DISTINCT CASE WHEN n.epa_type='TANK'     THEN n.node_id END) AS num_depositos,
            COUNT(DISTINCT CASE WHEN n.epa_type='PUMP'     THEN n.node_id END) AS num_bombas,
            COUNT(DISTINCT CASE WHEN n.epa_type='PRV'      THEN n.node_id END) AS num_vrp,
            COUNT(DISTINCT c.connec_id) AS num_abonados,
            ROUND(MIN(CASE WHEN n.epa_type='JUNCTION' AND n.elevation>0 THEN n.elevation END),0) AS cota_min,
            ROUND(MAX(CASE WHEN n.epa_type='JUNCTION' AND n.elevation>0 THEN n.elevation END),0) AS cota_max
        FROM sector s
        LEFT JOIN arc a    ON a.sector_id=s.sector_id AND a.state=1
        LEFT JOIN node n   ON n.sector_id=s.sector_id AND n.state=1
        LEFT JOIN connec c ON c.sector_id=s.sector_id AND c.state=1
        WHERE s.sector_id IN ({ph})
        GROUP BY s.sector_id, s.name
        ORDER BY s.sector_id
    """, sector_ids)

    for s in sectores:
        sid = s['sector_id']
        s['depositos'] = execute_query("""
            SELECT code, COALESCE(label,code) AS nombre,
                ROUND(elevation,2) AS cota_solera, ROUND(top_elev,2) AS cota_rebose,
                ROUND(ymin,2) AS cota_minima, ROUND(ymax,2) AS cota_maxima,
                ROUND(storage,0) AS volumen_m3
            FROM node WHERE sector_id=%s AND state=1 AND epa_type='TANK' ORDER BY code
        """, (sid,))
        s['fuentes'] = execute_query("""
            SELECT code, COALESCE(label,code) AS nombre, ROUND(elevation,2) AS cota_toma
            FROM node WHERE sector_id=%s AND state=1 AND epa_type='RESERVOIR' ORDER BY code
        """, (sid,))
        s['bombas'] = execute_query("""
            SELECT code, COALESCE(label,code) AS nombre
            FROM node WHERE sector_id=%s AND state=1 AND epa_type='PUMP' ORDER BY code
        """, (sid,))
        s['vrp'] = execute_query("""
            SELECT code, COALESCE(label,code) AS nombre
            FROM node WHERE sector_id=%s AND state=1 AND epa_type='PRV' ORDER BY code
        """, (sid,))
    return sectores


def get_materiales_red(sector_ids, nivel='primaria'):
    ph = ','.join(['%s'] * len(sector_ids))
    filtro = 'primary' if nivel == 'primaria' else 'secondary'
    return execute_query(f"""
        SELECT ca.material,
            CONCAT(MIN(ca.dint),' - ',MAX(ca.dint)) AS rango_diametros_mm,
            ROUND(SUM(a.gis_length),0) AS longitud_m,
            ROUND(100.0*SUM(a.gis_length)/SUM(SUM(a.gis_length)) OVER (),1) AS pct_total
        FROM arc a JOIN cat_arc ca ON ca.id=a.arccat_id
        WHERE a.sector_id IN ({ph}) AND a.state=1
        AND a.cat_feature_id ILIKE %s
        GROUP BY ca.material ORDER BY longitud_m DESC
    """, sector_ids + [f'%{filtro}%'])


def get_rugosidades():
    return execute_query("""
        SELECT id AS codigo, material, roughness AS coeficiente_c, descript AS observaciones
        FROM cat_arc GROUP BY id, material, roughness, descript ORDER BY material
    """)


def get_demandas_por_sector(sector_ids):
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT n.sector_id, s.name AS nombre_sector,
            COUNT(DISTINCT c.connec_id) AS num_abonados,
            ROUND(SUM(nd.demand)::numeric,3) AS demanda_media_ls,
            ROUND(SUM(nd.demand)*86.4::numeric,1) AS demanda_media_m3dia
        FROM node n
        JOIN sector s ON s.sector_id=n.sector_id
        LEFT JOIN node_demand nd ON nd.node_id=n.node_id
        LEFT JOIN connec c ON c.sector_id=n.sector_id AND c.state=1
        WHERE n.sector_id IN ({ph}) AND n.state=1 AND n.epa_type='JUNCTION'
        GROUP BY n.sector_id, s.name ORDER BY n.sector_id
    """, sector_ids)


def get_resultados_globales(result_id, sector_ids, timesteps):
    """Indicadores globales para los tres escenarios."""
    ph = ','.join(['%s'] * len(sector_ids))
    resultados = {}
    for escenario, time_val in timesteps.items():
        if not time_val:
            continue
        p = [result_id, time_val] + list(sector_ids)
        nodos = execute_query(f"""
            SELECT
                ROUND(AVG(rn.press)::numeric,2) AS presion_media,
                ROUND(MIN(rn.press)::numeric,2) AS presion_minima,
                ROUND(MAX(rn.press)::numeric,2) AS presion_maxima,
                ROUND(100.0*COUNT(CASE WHEN rn.press<10 THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_baja_presion,
                ROUND(100.0*COUNT(CASE WHEN rn.press>60 THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_alta_presion
            FROM rpt_node rn JOIN node n ON n.node_id=rn.node_id
            WHERE rn.result_id=%s AND rn.time=%s AND n.sector_id IN ({ph}) AND n.epa_type='JUNCTION'
        """, p)
        arcos = execute_query(f"""
            SELECT
                ROUND(SUM(ABS(ra.flow))::numeric,2) AS caudal_total_ls,
                ROUND(AVG(ABS(ra.vel))::numeric,3)  AS velocidad_media,
                ROUND(MAX(ABS(ra.vel))::numeric,3)  AS velocidad_maxima,
                ROUND(100.0*COUNT(CASE WHEN ABS(ra.vel)<0.05 THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_baja_vel,
                ROUND(100.0*COUNT(CASE WHEN ABS(ra.vel)>1.5  THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_alta_vel
            FROM rpt_arc ra JOIN arc a ON a.arc_id=ra.arc_id
            WHERE ra.result_id=%s AND ra.time=%s AND a.sector_id IN ({ph})
        """, p)
        resultados[escenario] = {"time": time_val, **(nodos[0] if nodos else {}), **(arcos[0] if arcos else {})}
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
                SELECT ROUND(MIN(rn.press)::numeric,2) AS presion_minima,
                    ROUND(AVG(rn.press)::numeric,2) AS presion_media,
                    ROUND(MAX(rn.press)::numeric,2) AS presion_maxima,
                    COUNT(CASE WHEN rn.press<10 THEN 1 END) AS nodos_baja_presion,
                    COUNT(CASE WHEN rn.press>60 THEN 1 END) AS nodos_alta_presion
                FROM rpt_node rn JOIN node n ON n.node_id=rn.node_id
                WHERE rn.result_id=%s AND rn.time=%s AND n.sector_id=%s AND n.epa_type='JUNCTION'
            """, p)
            vel = execute_query("""
                SELECT ROUND(AVG(ABS(ra.vel))::numeric,3) AS velocidad_media,
                    ROUND(MAX(ABS(ra.vel))::numeric,3) AS velocidad_maxima,
                    ROUND(100.0*COUNT(CASE WHEN ABS(ra.vel)<0.05 THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_baja_vel,
                    ROUND(100.0*COUNT(CASE WHEN ABS(ra.vel)>1.5  THEN 1 END)/NULLIF(COUNT(*),0),1) AS pct_alta_vel,
                    ROUND(AVG(ra.headloss/NULLIF(ra.length/1000.0,0))::numeric,3) AS perdida_unitaria_media
                FROM rpt_arc ra JOIN arc a ON a.arc_id=ra.arc_id
                WHERE ra.result_id=%s AND ra.time=%s AND a.sector_id=%s
            """, p)
            resultados[sector_id][escenario] = {"time": time_val, **(press[0] if press else {}), **(vel[0] if vel else {})}
    return resultados


def get_depositos_eps(result_id, sector_ids):
    """Comportamiento de depósitos a lo largo de la EPS."""
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT n.code AS deposito, s.name AS sector,
            ROUND(MIN(rn.head-n.elevation)::numeric,2) AS nivel_minimo,
            ROUND(MAX(rn.head-n.elevation)::numeric,2) AS nivel_maximo,
            ROUND(AVG(rn.head-n.elevation)::numeric,2) AS nivel_medio,
            ROUND(n.storage::numeric,0) AS volumen_util_m3
        FROM rpt_node rn
        JOIN node n ON n.node_id=rn.node_id
        JOIN sector s ON s.sector_id=n.sector_id
        WHERE rn.result_id=%s AND n.sector_id IN ({ph}) AND n.epa_type='TANK'
        GROUP BY n.code, s.name, n.elevation, n.storage
        ORDER BY s.name, n.code
    """, [result_id] + list(sector_ids))


def get_indicadores_retencion(result_id, sector_ids, timestep_media):
    """Tiempo de retención en red y depósitos por sector (escenario media)."""
    ph = ','.join(['%s'] * len(sector_ids))
    return execute_query(f"""
        SELECT a.sector_id,
            ROUND(SUM(PI()*POWER(ca.dint/1000.0/2.0,2)*a.gis_length)::numeric,2) AS volumen_red_m3,
            ROUND(AVG(ABS(ra.flow))::numeric,3) AS caudal_medio_ls,
            ROUND((SUM(PI()*POWER(ca.dint/1000.0/2.0,2)*a.gis_length)
                /NULLIF(AVG(ABS(ra.flow))/1000.0,0)/3600.0)::numeric,1) AS tiempo_retencion_red_h
        FROM rpt_arc ra
        JOIN arc a ON a.arc_id=ra.arc_id
        JOIN cat_arc ca ON ca.id=a.arccat_id
        WHERE ra.result_id=%s AND ra.time=%s AND a.sector_id IN ({ph})
        GROUP BY a.sector_id ORDER BY a.sector_id
    """, [result_id, timestep_media] + list(sector_ids))
