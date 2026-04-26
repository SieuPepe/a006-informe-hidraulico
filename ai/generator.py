"""
Generador de textos narrativos para el informe hidraulico mediante Claude API.

Utiliza el modelo Claude de Anthropic para redactar parrafos tecnicos
en estilo de informe de ingenieria hidraulica en castellano.
"""
import logging
import anthropic
import config

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Construccion de contexto
# ---------------------------------------------------------------------------

def _resumen_contexto(params, datos_muni, datos_sectores, resultados):
    """Construye un resumen textual con todos los datos hidraulicos disponibles."""
    lineas = []
    nombre = params.get("municipio_nombre", "Desconocido")
    lineas.append(f"Municipio: {nombre}")

    if datos_muni:
        lineas.append(f"Longitud de red: {datos_muni.get('longitud_red', '?')} km")
        lineas.append(f"Nodos: {datos_muni.get('num_nodos', '?')}, "
                      f"Arcos: {datos_muni.get('num_arcos', '?')}, "
                      f"Abonados: {datos_muni.get('num_abonados', '?')}")
        lineas.append(f"Depositos: {datos_muni.get('num_depositos', '?')} "
                      f"(volumen total: {datos_muni.get('volumen_depositos', '?')} m3)")
        lineas.append(f"Cotas: {datos_muni.get('cota_min', '?')} - "
                      f"{datos_muni.get('cota_max', '?')} msnm")

    if datos_sectores:
        lineas.append(f"\nNumero de sectores: {len(datos_sectores)}")
        for s in datos_sectores:
            lineas.append(f"  Sector '{s.get('nombre_sector', s.get('sector_id'))}' "
                          f"(id={s['sector_id']}): "
                          f"{s.get('num_nodos', '?')} nodos, "
                          f"{s.get('longitud_km', '?')} km, "
                          f"{s.get('num_abonados', '?')} abonados, "
                          f"cotas {s.get('cota_min', '?')}-{s.get('cota_max', '?')} msnm")
            if s.get('depositos'):
                for d in s['depositos']:
                    lineas.append(f"    Deposito {d.get('nombre', d.get('code', '?'))}: "
                                  f"{d.get('volumen_m3', '?')} m3, "
                                  f"cota solera {d.get('cota_solera', '?')} m")

    if resultados:
        if resultados.get("globales"):
            lineas.append("\nResultados globales de simulacion:")
            for esc, datos in resultados["globales"].items():
                lineas.append(f"  Escenario {esc} (t={datos.get('time', '?')}):")
                lineas.append(f"    Presion: min={datos.get('presion_minima', '?')}, "
                              f"media={datos.get('presion_media', '?')}, "
                              f"max={datos.get('presion_maxima', '?')} mca")
                lineas.append(f"    % baja presion (<10 mca): {datos.get('pct_baja_presion', '?')}%")
                lineas.append(f"    % alta presion (>60 mca): {datos.get('pct_alta_presion', '?')}%")
                lineas.append(f"    Velocidad: media={datos.get('velocidad_media', '?')}, "
                              f"max={datos.get('velocidad_maxima', '?')} m/s")
                lineas.append(f"    % baja velocidad (<0.05): {datos.get('pct_baja_vel', '?')}%")
                lineas.append(f"    % alta velocidad (>1.5): {datos.get('pct_alta_vel', '?')}%")

        if resultados.get("por_sector"):
            lineas.append("\nResultados por sector:")
            for sid, escenarios in resultados["por_sector"].items():
                lineas.append(f"  Sector {sid}:")
                for esc, datos in escenarios.items():
                    lineas.append(f"    {esc}: presion min/med/max = "
                                  f"{datos.get('presion_minima', '?')}/"
                                  f"{datos.get('presion_media', '?')}/"
                                  f"{datos.get('presion_maxima', '?')} mca, "
                                  f"vel media={datos.get('velocidad_media', '?')} m/s, "
                                  f"vel max={datos.get('velocidad_maxima', '?')} m/s")

        if resultados.get("depositos_eps"):
            lineas.append("\nComportamiento de depositos (EPS):")
            for d in resultados["depositos_eps"]:
                lineas.append(f"  {d.get('deposito', '?')} ({d.get('sector', '?')}): "
                              f"nivel min={d.get('nivel_minimo', '?')}, "
                              f"max={d.get('nivel_maximo', '?')}, "
                              f"medio={d.get('nivel_medio', '?')} m, "
                              f"volumen util={d.get('volumen_util_m3', '?')} m3")

        if resultados.get("retencion"):
            lineas.append("\nIndicadores de retencion:")
            for r in resultados["retencion"]:
                lineas.append(f"  Sector {r.get('sector_id', '?')}: "
                              f"volumen red={r.get('volumen_red_m3', '?')} m3, "
                              f"tiempo retencion={r.get('tiempo_retencion_red_h', '?')} h")

    return "\n".join(lineas)


def _nombre_sector(datos_sectores, idx):
    """Devuelve el nombre del sector en la posicion idx (0-based)."""
    if datos_sectores and idx < len(datos_sectores):
        return datos_sectores[idx].get("nombre_sector",
                                       str(datos_sectores[idx].get("sector_id", idx + 1)))
    return str(idx + 1)


# ---------------------------------------------------------------------------
# Definicion de prompts por marcador
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Eres un ingeniero hidraulico senior redactando un informe tecnico "
    "de analisis hidraulico de una red de abastecimiento de agua potable en Espana. "
    "Escribe en castellano formal y tecnico, de forma concisa y precisa. "
    "No uses encabezados, titulos ni listas con vinetas; redacta parrafos continuos. "
    "Limita la respuesta a 2-4 parrafos cortos."
)


def _prompt_sector_presiones(contexto, datos_sectores, resultados, idx):
    sector = datos_sectores[idx] if idx < len(datos_sectores) else {}
    sid = sector.get("sector_id")
    nombre = sector.get("nombre_sector", str(sid))
    datos_sector = ""
    if resultados and resultados.get("por_sector") and sid in resultados["por_sector"]:
        for esc, d in resultados["por_sector"][sid].items():
            datos_sector += (f"  {esc}: presion min={d.get('presion_minima', '?')}, "
                             f"media={d.get('presion_media', '?')}, "
                             f"max={d.get('presion_maxima', '?')} mca, "
                             f"nodos baja presion={d.get('nodos_baja_presion', '?')}, "
                             f"nodos alta presion={d.get('nodos_alta_presion', '?')}\n")
    return (f"Contexto general:\n{contexto}\n\n"
            f"Sector analizado: {nombre}\n"
            f"Datos de presion del sector:\n{datos_sector}\n"
            f"Redacta un parrafo de analisis de presiones para el sector '{nombre}', "
            f"comentando los valores en hora punta, media y nocturna, "
            f"e identificando si existen problemas de presion baja o excesiva.")


def _prompt_sector_velocidades(contexto, datos_sectores, resultados, idx):
    sector = datos_sectores[idx] if idx < len(datos_sectores) else {}
    sid = sector.get("sector_id")
    nombre = sector.get("nombre_sector", str(sid))
    datos_sector = ""
    if resultados and resultados.get("por_sector") and sid in resultados["por_sector"]:
        for esc, d in resultados["por_sector"][sid].items():
            datos_sector += (f"  {esc}: vel media={d.get('velocidad_media', '?')} m/s, "
                             f"vel max={d.get('velocidad_maxima', '?')} m/s, "
                             f"% baja vel={d.get('pct_baja_vel', '?')}%, "
                             f"% alta vel={d.get('pct_alta_vel', '?')}%, "
                             f"perdida unitaria={d.get('perdida_unitaria_media', '?')} m/km\n")
    return (f"Contexto general:\n{contexto}\n\n"
            f"Sector analizado: {nombre}\n"
            f"Datos de velocidad del sector:\n{datos_sector}\n"
            f"Redacta un parrafo de analisis de velocidades para el sector '{nombre}', "
            f"comentando la velocidad media y maxima en los tres escenarios, "
            f"el porcentaje de tuberias con velocidad baja (riesgo de estancamiento) "
            f"y las perdidas de carga unitarias.")


def _prompt_sector_deposito(contexto, datos_sectores, resultados, idx):
    sector = datos_sectores[idx] if idx < len(datos_sectores) else {}
    sid = sector.get("sector_id")
    nombre = sector.get("nombre_sector", str(sid))
    datos_dep = ""
    if resultados and resultados.get("depositos_eps"):
        for d in resultados["depositos_eps"]:
            if d.get("sector") == nombre or str(d.get("sector_id")) == str(sid):
                datos_dep += (f"  Deposito {d.get('deposito', '?')}: "
                              f"nivel min={d.get('nivel_minimo', '?')}, "
                              f"max={d.get('nivel_maximo', '?')}, "
                              f"medio={d.get('nivel_medio', '?')} m, "
                              f"vol util={d.get('volumen_util_m3', '?')} m3\n")
    if not datos_dep:
        datos_dep = "No se dispone de depositos en este sector o no hay datos.\n"
    return (f"Contexto general:\n{contexto}\n\n"
            f"Sector analizado: {nombre}\n"
            f"Datos de depositos del sector:\n{datos_dep}\n"
            f"Redacta un parrafo sobre el comportamiento de los depositos del sector '{nombre}' "
            f"durante la simulacion en periodo extendido (EPS), "
            f"comentando los niveles minimos y maximos, la capacidad de regulacion "
            f"y si se producen vaciados o reboses.")


def _prompt_diagnostico(contexto, tipo):
    instrucciones = {
        "presiones": (
            "Redacta un diagnostico global de presiones de la red de abastecimiento, "
            "identificando los sectores con problemas de baja o alta presion, "
            "las causas probables y la gravedad de los problemas detectados."
        ),
        "velocidades": (
            "Redacta un diagnostico global de velocidades de la red, "
            "identificando los sectores con mayor porcentaje de tuberias con velocidad "
            "baja (riesgo de estancamiento y perdida de cloro residual) "
            "o velocidad excesiva, y las causas probables."
        ),
        "retencion": (
            "Redacta un diagnostico de los tiempos de retencion del agua en la red, "
            "indicando si los valores son adecuados "
            "para garantizar la calidad del agua potable."
        ),
        "autonomia": (
            "Redacta un diagnostico de la autonomia de los depositos de regulacion, "
            "analizando si la capacidad de almacenamiento es suficiente para "
            "garantizar la continuidad del suministro ante paradas de produccion "
            "o picos de demanda. Identifica los depositos con menor autonomia."
        ),
    }
    return (f"Contexto general:\n{contexto}\n\n"
            f"{instrucciones[tipo]}")


def _prompt_diagnostico_global(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Redacta un diagnostico global del estado de la red de abastecimiento, "
            "integrando los aspectos de presiones, velocidades, depositos y retencion. "
            "Resume las principales fortalezas y debilidades del sistema.")


def _prompt_descripcion_sistema(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Redacta una descripcion del FUNCIONAMIENTO GENERAL del sistema de "
            "abastecimiento (capitulo 2.2 del informe). Debe explicar de forma "
            "tecnica y concisa, en 1 o 2 parrafos:\n"
            " - origen del agua (fuente o fuentes principales) y como llega a la red;\n"
            " - papel de los depositos de regulacion en el sistema;\n"
            " - sectorizacion hidraulica (numero de sectores y articulacion entre ellos);\n"
            " - elementos de bombeo, grupos de presion y reductoras presentes y su funcion;\n"
            " - regimen de funcionamiento (gravedad, mixto, predominantemente bombeado).\n"
            "No repitas datos numericos detallados (eso ya esta en las tablas); "
            "centra la narracion en la logica de operacion del sistema.")


def _prompt_factores_condicionantes(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Identifica y describe los factores condicionantes del funcionamiento "
            "de la red de abastecimiento: topografia, estado de las infraestructuras, "
            "patron de demanda, configuracion de la red, etc.")


def _prompt_puntos_vulnerables(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Identifica los puntos vulnerables de la red de abastecimiento "
            "a partir de los resultados de la simulacion hidraulica. "
            "Senala zonas con presion insuficiente, riesgo de estancamiento, "
            "depositos con autonomia limitada y tramos criticos.")


def _prompt_propuestas_mejora(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Propone actuaciones de mejora para la red de abastecimiento "
            "basandote en los problemas detectados en la simulacion. "
            "Las propuestas deben ser concretas, viables tecnicamente y priorizadas "
            "segun su impacto en la calidad del servicio.")


def _prompt_conclusiones(contexto):
    return (f"Contexto general:\n{contexto}\n\n"
            "Redacta las conclusiones del informe de analisis hidraulico, "
            "resumiendo el estado general de la red, los principales problemas "
            "detectados y las lineas de actuacion recomendadas.")


# ---------------------------------------------------------------------------
# Llamada a la API
# ---------------------------------------------------------------------------

def _llamar_claude(prompt):
    """Envia un prompt a Claude y devuelve el texto generado."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        logger.exception("Error al llamar a Claude API")
        return ""


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def generar_textos(params, datos_muni, datos_sectores, resultados):
    """Genera todos los textos narrativos del informe mediante Claude API.

    Args:
        params: Diccionario con parametros del usuario.
        datos_muni: Diccionario con datos del municipio.
        datos_sectores: Lista de dicts con datos por sector.
        resultados: Diccionario con resultados de simulacion (globales,
            por_sector, depositos_eps, retencion).

    Returns:
        dict: Mapa {nombre_marcador: texto_generado}.
    """
    contexto = _resumen_contexto(params, datos_muni, datos_sectores, resultados)
    textos = {}

    # Descripcion general del sistema (capitulo 2.2)
    logger.info("Generando descripcion general del sistema...")
    textos["descripcion_sistema"] = _llamar_claude(
        _prompt_descripcion_sistema(contexto))

    # Textos por sector (sector_1_presiones, sector_1_velocidades, sector_1_deposito, ...)
    num_sectores = len(datos_sectores) if datos_sectores else 0
    for i in range(num_sectores):
        idx_1 = i + 1  # 1-based
        nombre_sector = _nombre_sector(datos_sectores, i)

        logger.info("Generando texto de presiones para sector %s...", nombre_sector)
        bm = f"sector_{idx_1}_presiones"
        textos[bm] = _llamar_claude(
            _prompt_sector_presiones(contexto, datos_sectores, resultados, i))

        logger.info("Generando texto de velocidades para sector %s...", nombre_sector)
        bm = f"sector_{idx_1}_velocidades"
        textos[bm] = _llamar_claude(
            _prompt_sector_velocidades(contexto, datos_sectores, resultados, i))

        logger.info("Generando texto de deposito para sector %s...", nombre_sector)
        bm = f"sector_{idx_1}_deposito"
        textos[bm] = _llamar_claude(
            _prompt_sector_deposito(contexto, datos_sectores, resultados, i))

    # Diagnosticos globales
    logger.info("Generando diagnostico de presiones...")
    textos["diagnostico_presiones"] = _llamar_claude(
        _prompt_diagnostico(contexto, "presiones"))

    logger.info("Generando diagnostico de velocidades...")
    textos["diagnostico_velocidades"] = _llamar_claude(
        _prompt_diagnostico(contexto, "velocidades"))

    logger.info("Generando diagnostico de retencion...")
    textos["diagnostico_retencion"] = _llamar_claude(
        _prompt_diagnostico(contexto, "retencion"))

    logger.info("Generando diagnostico de autonomia...")
    textos["diagnostico_autonomia"] = _llamar_claude(
        _prompt_diagnostico(contexto, "autonomia"))

    logger.info("Generando diagnostico global...")
    textos["diagnostico_global"] = _llamar_claude(
        _prompt_diagnostico_global(contexto))

    # Capitulos finales
    logger.info("Generando factores condicionantes...")
    textos["factores_condicionantes"] = _llamar_claude(
        _prompt_factores_condicionantes(contexto))

    logger.info("Generando puntos vulnerables...")
    textos["puntos_vulnerables"] = _llamar_claude(
        _prompt_puntos_vulnerables(contexto))

    logger.info("Generando propuestas de mejora...")
    textos["propuestas_mejora"] = _llamar_claude(
        _prompt_propuestas_mejora(contexto))

    logger.info("Generando conclusiones...")
    textos["conclusiones"] = _llamar_claude(
        _prompt_conclusiones(contexto))

    logger.info("Generacion de textos completada: %d marcadores.", len(textos))
    return textos
