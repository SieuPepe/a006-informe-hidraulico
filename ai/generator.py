"""
Generador de textos narrativos para el informe hidraulico mediante Claude API.

Utiliza el modelo Claude de Anthropic para redactar parrafos tecnicos
en estilo de informe de ingenieria hidraulica en castellano.
"""
import logging
import anthropic
import config
from console import ask  # input() que descarta type-ahead antes de leer

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 2048

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
    sector_type = (sector.get("sector_type") or "DISTRIBUTION").upper()
    datos_sector = ""
    tipo_eval = "connec"
    if resultados and resultados.get("por_sector") and sid in resultados["por_sector"]:
        for esc, d in resultados["por_sector"][sid].items():
            datos_sector += (f"  {esc}: presion min={d.get('presion_minima', '?')}, "
                             f"media={d.get('presion_media', '?')}, "
                             f"max={d.get('presion_maxima', '?')} mca, "
                             f"nodos baja presion={d.get('nodos_baja_presion', '?')}, "
                             f"nodos alta presion={d.get('nodos_alta_presion', '?')}\n")
            # El campo tipo_evaluacion_presion es el mismo en los 3 escenarios
            tipo_eval = d.get("tipo_evaluacion_presion", tipo_eval)

    if sector_type == "SOURCE" or tipo_eval == "junction":
        nota_eval = (
            "IMPORTANTE: Este es un sector de tipo SOURCE (red de transporte/captacion "
            "sin acometidas registradas). Las presiones aqui reflejadas se han evaluado "
            "sobre los nodos hidraulicos de la red (no sobre puntos de demanda final). "
            "Por tanto, los valores describen el estado hidraulico del transporte, no la "
            "calidad del servicio al usuario. Menciona esta consideracion en el analisis."
        )
    else:
        nota_eval = (
            "Las presiones se han evaluado en los puntos de demanda (acometidas/connecs) "
            "del sector, reflejando la calidad del servicio al usuario final."
        )

    return (f"Contexto general:\n{contexto}\n\n"
            f"Sector analizado: {nombre} (tipo: {sector_type})\n"
            f"Datos de presion del sector:\n{datos_sector}\n"
            f"{nota_eval}\n\n"
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
                             f"% alta vel={d.get('pct_alta_vel', '?')}%\n")
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
    """Envia un prompt a Claude y devuelve el texto generado.

    Si la respuesta se trunca por alcanzar max_tokens, avisa por consola
    para que el revisor sea consciente y pueda dar feedback (por ej.
    pedir un texto más corto o aumentar MAX_TOKENS).
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning(
                "Respuesta truncada por max_tokens=%d. "
                "El texto puede quedar a media frase. "
                "Considera dar feedback al modelo para acortar, "
                "o subir MAX_TOKENS en ai/generator.py.",
                MAX_TOKENS,
            )
        return message.content[0].text.strip()
    except Exception:
        logger.exception("Error al llamar a Claude API")
        return ""


# ---------------------------------------------------------------------------
# Revisión interactiva
# ---------------------------------------------------------------------------

def _bloque_directrices(directrices):
    """Construye el bloque de directrices acumuladas para inyectar al prompt."""
    if not directrices:
        return ""
    items = "\n".join(f"  - {d}" for d in directrices)
    return (
        "\n\n---\n"
        "INSTRUCCIONES Y DIRECTRICES DEL REVISOR\n"
        "(visión general e indicaciones aplicables a TODOS los textos del "
        "informe, no solo a este):\n"
        f"{items}\n"
        "Respétalas estrictamente.\n"
        "---\n"
    )


def _llamar_claude_con_directrices(prompt_base, directrices):
    """Inyecta las directrices acumuladas al prompt y llama a Claude."""
    return _llamar_claude(prompt_base + _bloque_directrices(directrices))


def _reescribir_con_feedback(prompt_original, feedback, directrices):
    """Reescribe el texto añadiendo el feedback puntual + las directrices acumuladas."""
    nuevo_prompt = (
        f"{prompt_original}\n\n"
        f"---\n"
        f"Nota del revisor sobre el texto anterior:\n{feedback}\n"
        f"Reescribe el parrafo teniendo en cuenta esta nota."
    )
    return _llamar_claude_con_directrices(nuevo_prompt, directrices)


def _print_separador(char="─", width=60):
    print(char * width)


def _revisar_iterativo(texto_inicial, prompt_original, etiqueta, directrices):
    """Muestra un texto, permite iterar con feedback hasta aceptar o saltar.

    `directrices` es una lista mutable: cuando el usuario da feedback y
    acepta la reescritura, ese feedback se AÑADE a la lista para que se
    aplique también a todos los textos posteriores.

    Returns: texto final aceptado (puede ser "" si se salta).
    """
    texto = texto_inicial
    feedbacks_de_este_texto = []  # ordenados, último primero al final
    while True:
        print(f"\n═══════ Revisando: {etiqueta} ═══════")
        print(texto if texto else "(sin texto)")
        _print_separador()
        respuesta = ask(
            "> [Enter]=aceptar · escribe feedback para reescribir · s=saltar: "
        ).strip()
        if not respuesta:
            print(f"✓ Aceptado.")
            # Las directrices que NO eran genéricas estaban solo en
            # feedbacks_de_este_texto. Las añadimos al pool global para
            # que también afecten a los textos siguientes.
            for fb in feedbacks_de_este_texto:
                if fb not in directrices:
                    directrices.append(fb)
            if feedbacks_de_este_texto:
                print(
                    f"  (Directrices acumuladas para textos siguientes: "
                    f"{len(directrices)})"
                )
            return texto
        if respuesta.lower() == "s":
            print(f"⊘ Saltado (bookmark quedará vacío).")
            return ""
        print(f"🔄 Reescribiendo {etiqueta.lower()} con tu feedback...")
        feedbacks_de_este_texto.append(respuesta)
        texto = _reescribir_con_feedback(prompt_original, respuesta, directrices)


def _revisar_sector(idx, datos_sectores, resultados, contexto, num_sectores, directrices):
    """Genera y revisa interactivamente los 3 textos de un sector."""
    nombre_sector = _nombre_sector(datos_sectores, idx)
    idx_1 = idx + 1
    sector_type = (datos_sectores[idx].get("sector_type") or "DISTRIBUTION").upper()

    print()
    _print_separador("═")
    print(f"  SECTOR {idx_1}/{num_sectores}: {nombre_sector}  [{sector_type}]")
    _print_separador("═")
    if directrices:
        print(f"  (Aplicando {len(directrices)} directriz/es acumulada/s del revisor)")

    # Genera los 3 textos del sector (3 llamadas a Claude), ya con las
    # directrices acumuladas inyectadas en el prompt.
    print(f"\n  Generando los 3 textos del sector con Claude...")
    prompt_p = _prompt_sector_presiones(contexto, datos_sectores, resultados, idx)
    prompt_v = _prompt_sector_velocidades(contexto, datos_sectores, resultados, idx)
    prompt_d = _prompt_sector_deposito(contexto, datos_sectores, resultados, idx)
    t_p = _llamar_claude_con_directrices(prompt_p, directrices)
    t_v = _llamar_claude_con_directrices(prompt_v, directrices)
    t_d = _llamar_claude_con_directrices(prompt_d, directrices)

    # Vista previa de los 3 juntos.
    print()
    _print_separador()
    print("[1] PRESIONES")
    _print_separador()
    print(t_p or "(sin texto)")
    print()
    _print_separador()
    print("[2] VELOCIDADES")
    _print_separador()
    print(t_v or "(sin texto)")
    print()
    _print_separador()
    print("[3] DEPÓSITO")
    _print_separador()
    print(t_d or "(sin texto)")
    print()
    _print_separador()
    accion = ask(
        "> ¿Aceptar los 3 textos tal cual? [Enter=sí / n=revisar uno a uno]: "
    ).strip().lower()

    if accion != "n":
        return {
            f"sector_{idx_1}_presiones":   t_p,
            f"sector_{idx_1}_velocidades": t_v,
            f"sector_{idx_1}_deposito":    t_d,
        }

    # Revisión iterativa por cada uno.
    t_p = _revisar_iterativo(t_p, prompt_p, f"sector {idx_1} · presiones", directrices)
    t_v = _revisar_iterativo(t_v, prompt_v, f"sector {idx_1} · velocidades", directrices)
    t_d = _revisar_iterativo(t_d, prompt_d, f"sector {idx_1} · deposito", directrices)
    return {
        f"sector_{idx_1}_presiones":   t_p,
        f"sector_{idx_1}_velocidades": t_v,
        f"sector_{idx_1}_deposito":    t_d,
    }


def _revisar_global(etiqueta, prompt_original, directrices):
    """Genera y revisa interactivamente un texto global. Returns: texto."""
    print()
    _print_separador("═")
    print(f"  GLOBAL: {etiqueta}")
    _print_separador("═")
    if directrices:
        print(f"  (Aplicando {len(directrices)} directriz/es acumulada/s del revisor)")
    print(f"\n  Generando con Claude...")
    texto = _llamar_claude_con_directrices(prompt_original, directrices)
    return _revisar_iterativo(texto, prompt_original, etiqueta, directrices)


def _pedir_instrucciones_generales(directrices):
    """Pide al usuario instrucciones generales para TODO el informe.

    Cada línea introducida se añade a `directrices`, de modo que se inyecta en
    todos los prompts de Claude (sectores, diagnósticos, conclusiones). Así el
    usuario transmite su visión general y las particularidades del informe
    ANTES de generar el primer texto.
    """
    print()
    _print_separador("═")
    print("  INSTRUCCIONES GENERALES PARA TODO EL INFORME")
    _print_separador("═")
    print("  Indica tu visión general y las particularidades que Claude debe")
    print("  tener en cuenta en TODOS los textos: tono, enfoque, terminología,")
    print("  aspectos a destacar o a evitar, etc.")
    print("  - Una instrucción por línea.")
    print("  - Línea vacía (Enter) para terminar.")
    print("  - Si no quieres añadir ninguna, pulsa Enter directamente.")
    n_inicial = len(directrices)
    while True:
        linea = ask(f"  [{len(directrices) - n_inicial + 1}] > ").strip()
        if not linea:
            break
        directrices.append(linea)
    añadidas = len(directrices) - n_inicial
    if añadidas:
        print(f"  ✓ {añadidas} instrucción/es general/es registrada/s; "
              f"se aplicarán a todos los textos.")
    else:
        print("  (Sin instrucciones generales; continúo.)")


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def generar_textos(params, datos_muni, datos_sectores, resultados):
    """Genera todos los textos narrativos del informe mediante Claude API.

    Flujo interactivo con APRENDIZAJE: cada feedback aceptado por el usuario
    se acumula como directriz de estilo y se inyecta en TODOS los prompts
    siguientes (otros sectores, conclusiones, etc.). De esta forma el modelo
    no repite los mismos defectos texto tras texto.

    Returns:
        dict: Mapa {nombre_marcador: texto_generado}. Saltados → "".
    """
    contexto = _resumen_contexto(params, datos_muni, datos_sectores, resultados)
    textos = {}
    # Lista mutable de directrices acumuladas. Se actualiza en cada revisión.
    directrices = []

    print()
    print("=" * 60)
    print("  REVISIÓN INTERACTIVA DE TEXTOS GENERADOS POR CLAUDE")
    print("=" * 60)
    print("  - Por cada sector verás los 3 textos juntos.")
    print("  - Pulsa Enter para aceptar tal cual, n para revisar uno a uno.")
    print("  - En cada texto: Enter=aceptar · feedback=reescribir · s=saltar.")
    print("  - Cada feedback que aceptes se acumula como directriz y se")
    print("    aplicará a TODOS los textos siguientes (otros sectores +")
    print("    diagnósticos + conclusiones).")

    # Instrucciones generales del usuario, antes de generar nada. Se precargan
    # como directrices para que se inyecten en todos los prompts.
    _pedir_instrucciones_generales(directrices)

    # Textos por sector
    num_sectores = len(datos_sectores) if datos_sectores else 0
    for i in range(num_sectores):
        textos.update(
            _revisar_sector(i, datos_sectores, resultados, contexto,
                            num_sectores, directrices)
        )

    # Bloque globales
    print()
    print("=" * 60)
    print("  TEXTOS GLOBALES DEL INFORME")
    print("=" * 60)

    textos["descripcion_sistema"]    = _revisar_global(
        "descripcion_sistema", _prompt_descripcion_sistema(contexto), directrices)
    textos["diagnostico_presiones"]  = _revisar_global(
        "diagnostico_presiones", _prompt_diagnostico(contexto, "presiones"), directrices)
    textos["diagnostico_velocidades"] = _revisar_global(
        "diagnostico_velocidades", _prompt_diagnostico(contexto, "velocidades"), directrices)
    textos["diagnostico_retencion"]  = _revisar_global(
        "diagnostico_retencion", _prompt_diagnostico(contexto, "retencion"), directrices)
    textos["diagnostico_autonomia"]  = _revisar_global(
        "diagnostico_autonomia", _prompt_diagnostico(contexto, "autonomia"), directrices)
    textos["diagnostico_global"]     = _revisar_global(
        "diagnostico_global", _prompt_diagnostico_global(contexto), directrices)
    textos["factores_condicionantes"] = _revisar_global(
        "factores_condicionantes", _prompt_factores_condicionantes(contexto), directrices)
    textos["puntos_vulnerables"]     = _revisar_global(
        "puntos_vulnerables", _prompt_puntos_vulnerables(contexto), directrices)
    textos["propuestas_mejora"]      = _revisar_global(
        "propuestas_mejora", _prompt_propuestas_mejora(contexto), directrices)
    textos["conclusiones"]           = _revisar_global(
        "conclusiones", _prompt_conclusiones(contexto), directrices)

    aceptados = sum(1 for t in textos.values() if t)
    print()
    print("=" * 60)
    print(f"  ✓ Generación completada: {aceptados} de {len(textos)} marcadores aceptados.")
    print(f"  ✓ Directrices acumuladas del revisor: {len(directrices)}.")
    print("=" * 60)
    return textos
