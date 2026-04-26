"""
Script de diagnóstico — ejecutar para verificar datos reales de Giswater.
Modifica los sector_ids y result_id según el municipio a analizar.

Uso: python diagnostico.py
"""
import sys
sys.path.insert(0, '.')
from db.connection import execute_query, execute_scalar, test_connection

# ═══════════════════════════════════════════════════
# CONFIGURACIÓN — Cambiar según el municipio
# ═══════════════════════════════════════════════════
SECTOR_IDS = [11100, 11101, 11102]  # Artziniega
RESULT_ID = "Delika"
# ═══════════════════════════════════════════════════

print("Conectando a la BD...")
if not test_connection():
    sys.exit(1)

ph = ','.join([str(s) for s in SECTOR_IDS])

# ─── 1. FUENTES (RESERVOIR) ───
print("\n" + "="*60)
print("1. FUENTES / CAPTACIONES (epa_type = RESERVOIR)")
print("="*60)
rows = execute_query(f"""
    SELECT n.node_id, n.code, n.epa_type, n.descript,
        ROUND(n.elevation::numeric, 2) AS elevation,
        n.sector_id
    FROM node n
    WHERE n.sector_id IN ({ph}) AND n.state = 1
      AND n.epa_type = 'RESERVOIR'
    ORDER BY n.sector_id, n.code
""")
print(f"  Encontrados: {len(rows)}")
for r in rows:
    print(f"  node_id={r['node_id']} code={r['code']} epa={r['epa_type']} "
          f"descript={r['descript']} elev={r['elevation']} sector={r['sector_id']}")

# Verificar si hay man_source
print("\n  --- man_source ---")
for r in rows:
    ms = execute_query(f"SELECT * FROM man_source WHERE node_id = {r['node_id']}")
    if ms:
        print(f"  node_id={r['node_id']}: {dict(ms[0])}")
    else:
        print(f"  node_id={r['node_id']}: NO HAY man_source")


# ─── 2. DEPÓSITOS (TANK) ───
print("\n" + "="*60)
print("2. DEPÓSITOS (epa_type = TANK)")
print("="*60)
rows = execute_query(f"""
    SELECT n.node_id, n.code, n.epa_type, n.descript,
        ROUND(n.elevation::numeric, 2) AS elevation,
        n.sector_id,
        mt.name AS mt_name, mt.vutil, mt.vmax, mt.hmax,
        ROUND(mt.elev_fondo::numeric, 2) AS elev_fondo,
        it.initlevel, it.minlevel, it.maxlevel, it.diameter
    FROM node n
    LEFT JOIN man_tank mt ON mt.node_id = n.node_id
    LEFT JOIN inp_tank it ON it.node_id = n.node_id
    WHERE n.sector_id IN ({ph}) AND n.state = 1
      AND n.epa_type = 'TANK'
    ORDER BY n.sector_id, n.code
""")
print(f"  Encontrados: {len(rows)}")
for r in rows:
    print(f"  node_id={r['node_id']} code={r['code']} sector={r['sector_id']}")
    print(f"    descript={r['descript']} elevation={r['elevation']}")
    print(f"    man_tank: name={r['mt_name']} vutil={r['vutil']} vmax={r['vmax']} "
          f"hmax={r['hmax']} elev_fondo={r['elev_fondo']}")
    print(f"    inp_tank: init={r['initlevel']} min={r['minlevel']} "
          f"max={r['maxlevel']} diameter={r['diameter']}")

# También buscar TODOS los nodos tipo TANK sin filtro de sector
print("\n  --- TODOS los TANK en los sectores (incluyendo state != 1) ---")
rows2 = execute_query(f"""
    SELECT n.node_id, n.code, n.state, n.epa_type, n.sector_id
    FROM node n
    WHERE n.sector_id IN ({ph}) AND n.epa_type = 'TANK'
    ORDER BY n.sector_id, n.code
""")
for r in rows2:
    print(f"  node_id={r['node_id']} code={r['code']} state={r['state']} sector={r['sector_id']}")


# ─── 3. MATERIALES POR CATEGORY_TYPE ───
print("\n" + "="*60)
print("3. MATERIALES POR CATEGORY_TYPE")
print("="*60)
rows = execute_query(f"""
    SELECT a.category_type, ca.matcat_id,
        CONCAT(MIN(ca.dnom)::text, ' - ', MAX(ca.dnom)::text) AS rango,
        ROUND(SUM(a.gis_length)::numeric, 0) AS longitud_m,
        COUNT(*) AS num_arcos
    FROM v_edit_arc a
    JOIN cat_arc ca ON ca.id = a.arccat_id
    WHERE a.sector_id IN ({ph}) AND a.state = 1
    GROUP BY a.category_type, ca.matcat_id
    ORDER BY a.category_type, longitud_m DESC
""")
for r in rows:
    print(f"  cat_type={r['category_type']} material={r['matcat_id']} "
          f"rango={r['rango']} longitud={r['longitud_m']}m arcos={r['num_arcos']}")

# Verificar longitudes totales
print("\n  --- Longitudes totales ---")
rows = execute_query(f"""
    SELECT category_type,
        ROUND(SUM(gis_length)::numeric, 0) AS total_m,
        ROUND(SUM(gis_length)/1000.0, 2) AS total_km,
        COUNT(*) AS arcos
    FROM v_edit_arc
    WHERE sector_id IN ({ph}) AND state = 1
    GROUP BY category_type
    ORDER BY category_type
""")
for r in rows:
    print(f"  {r['category_type']}: {r['total_km']} km ({r['arcos']} arcos)")


# ─── 4. BOMBAS ───
print("\n" + "="*60)
print("4. BOMBAS (epa_type en node)")
print("="*60)
rows = execute_query(f"""
    SELECT n.node_id, n.code, n.epa_type, n.descript, n.sector_id
    FROM node n
    WHERE n.sector_id IN ({ph}) AND n.state = 1
      AND n.epa_type IN ('PUMP', 'UNDEFINED', 'SHORTPIPE')
    ORDER BY n.epa_type, n.code
""")
print(f"  Encontrados: {len(rows)}")
for r in rows:
    print(f"  node_id={r['node_id']} code={r['code']} epa_type={r['epa_type']} "
          f"descript={r['descript']} sector={r['sector_id']}")

# inp_pump
print("\n  --- inp_pump ---")
pump_rows = execute_query(f"""
    SELECT ip.node_id, ip.pump_type, ip.power, ip.curve_id, ip.speed,
        n.code, n.epa_type
    FROM inp_pump ip
    JOIN node n ON n.node_id = ip.node_id
    WHERE n.sector_id IN ({ph})
""")
for r in pump_rows:
    print(f"  node_id={r['node_id']} code={r['code']} epa_type={r['epa_type']} "
          f"pump_type={r['pump_type']} power={r['power']} curve={r['curve_id']}")


# ─── 5. VRP ───
print("\n" + "="*60)
print("5. VÁLVULAS REDUCTORAS (epa_type)")
print("="*60)
rows = execute_query(f"""
    SELECT n.node_id, n.code, n.epa_type, n.descript, n.sector_id
    FROM node n
    WHERE n.sector_id IN ({ph}) AND n.state = 1
      AND n.epa_type IN ('PRV', 'PSV', 'PBV', 'FCV', 'TCV', 'GPV', 'VALVE')
    ORDER BY n.code
""")
print(f"  Encontrados: {len(rows)}")
for r in rows:
    print(f"  node_id={r['node_id']} code={r['code']} epa_type={r['epa_type']} sector={r['sector_id']}")

# v_edit_inp_valve
print("\n  --- v_edit_inp_valve ---")
vrv_rows = execute_query(f"""
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'abastecimiento' AND table_name = 'v_edit_inp_valve'
    ORDER BY ordinal_position
""")
print(f"  Columnas: {[r['column_name'] for r in vrv_rows]}")

valve_rows = execute_query(f"""
    SELECT * FROM v_edit_inp_valve
    WHERE sector_id IN ({ph})
    LIMIT 5
""")
if valve_rows:
    for r in valve_rows:
        print(f"  {dict(r)}")
else:
    print("  SIN DATOS en v_edit_inp_valve para estos sectores")
    # Probar inp_valve directamente
    valve_rows2 = execute_query(f"""
        SELECT iv.node_id, iv.valv_type, iv.pressure, iv.custom_dint, n.code
        FROM inp_valve iv
        JOIN node n ON n.node_id = iv.node_id
        WHERE n.sector_id IN ({ph})
    """)
    if valve_rows2:
        print("  --- inp_valve directamente ---")
        for r in valve_rows2:
            print(f"  {dict(r)}")
    else:
        print("  SIN DATOS en inp_valve tampoco")


# ─── 6. REGLAS / CONTROLS ───
print("\n" + "="*60)
print("6. REGLAS Y CONTROLS")
print("="*60)
controls = execute_query(f"""
    SELECT id, sector_id, text, active FROM v_edit_inp_controls
    WHERE active IS TRUE AND sector_id IN ({ph})
""")
print(f"  Controls (filtrado por sector): {len(controls or [])}")

controls_all = execute_query("SELECT id, sector_id, text FROM v_edit_inp_controls WHERE active IS TRUE")
print(f"  Controls (todos): {len(controls_all or [])}")
for r in (controls_all or []):
    print(f"  id={r['id']} sector={r['sector_id']} text={r['text'][:80]}")

rules = execute_query("SELECT id, sector_id, text FROM v_edit_inp_rules WHERE active IS TRUE")
print(f"  Rules (todos): {len(rules or [])}")
for r in (rules or []):
    print(f"  id={r['id']} sector={r['sector_id']} text={r['text'][:80] if r['text'] else 'NULL'}")


# ─── 7. DEMANDAS ───
print("\n" + "="*60)
print("7. DEMANDAS")
print("="*60)
dem_connec = execute_query(f"""
    SELECT c.sector_id, COUNT(*) AS n,
        SUM(ic.demand) AS total_demand_ls
    FROM connec c
    JOIN inp_connec ic ON ic.connec_id = c.connec_id
    WHERE c.sector_id IN ({ph}) AND c.state = 1
    GROUP BY c.sector_id
    ORDER BY c.sector_id
""")
print("  inp_connec.demand por sector:")
for r in (dem_connec or []):
    print(f"  sector={r['sector_id']} abonados={r['n']} demanda={r['total_demand_ls']} l/s")


# ─── 8. CAUDAL INYECTADO (rpt) ───
print("\n" + "="*60)
print("8. CAUDAL INYECTADO — rpt_node (RESERVOIR + TANK)")
print("="*60)
# Verificar qué nodos inyectan caudal
rows = execute_query(f"""
    SELECT rn.node_id, n.code, n.epa_type, rn.time,
        ROUND(rn.demand::numeric, 3) AS demand,
        ROUND(rn.head::numeric, 2) AS head
    FROM rpt_node rn
    JOIN node n ON n.node_id = rn.node_id
    WHERE rn.result_id = '{RESULT_ID}'
      AND n.sector_id IN ({ph})
      AND n.epa_type IN ('RESERVOIR', 'TANK')
      AND rn.time = '0:00:00'
    ORDER BY n.epa_type, n.code
""")
print(f"  Nodos RESERVOIR/TANK en timestep 0:")
for r in rows:
    print(f"  {r['epa_type']} {r['code']} demand={r['demand']} head={r['head']}")

# Caudal total por timestep (primeros 3)
print("\n  --- Caudal total inyectado (SUM ABS flow) por timestep ---")
rows = execute_query(f"""
    SELECT ra.time,
        ROUND(SUM(ABS(ra.flow))::numeric, 2) AS total_flow
    FROM rpt_arc ra
    JOIN v_edit_arc a ON a.arc_id = ra.arc_id
    WHERE ra.result_id = '{RESULT_ID}'
      AND a.sector_id IN ({ph})
    GROUP BY ra.time
    ORDER BY ra.time
    LIMIT 5
""")
for r in rows:
    print(f"  time={r['time']} total_flow={r['total_flow']} l/s")


# ─── 9. DEPÓSITOS EN rpt_node ───
print("\n" + "="*60)
print("9. DEPÓSITOS EN rpt_node (para EPS)")
print("="*60)
rows = execute_query(f"""
    SELECT DISTINCT rn.node_id, n.code, n.epa_type, n.sector_id,
        COALESCE(mt.name, n.descript, n.code) AS nombre
    FROM rpt_node rn
    JOIN node n ON n.node_id = rn.node_id
    LEFT JOIN man_tank mt ON mt.node_id = n.node_id
    WHERE rn.result_id = '{RESULT_ID}'
      AND n.sector_id IN ({ph})
      AND n.epa_type = 'TANK'
""")
print(f"  Depósitos con resultados EPS: {len(rows)}")
for r in rows:
    print(f"  node_id={r['node_id']} code={r['code']} nombre={r['nombre']} sector={r['sector_id']}")


print("\n" + "="*60)
print("DIAGNÓSTICO COMPLETADO")
print("="*60)
