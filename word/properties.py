"""
Escritura de campos DOCPROPERTY en documentos Word (.docx).

Actualiza tanto las propiedades personalizadas del documento (docProps/custom.xml)
como los valores mostrados en el cuerpo del documento (campos fldSimple y fldChar).
"""
import logging
from lxml import etree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Espacios de nombres XML
# ---------------------------------------------------------------------------
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
NS_VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

NSMAP_W = {"w": NS_W}

# ---------------------------------------------------------------------------
# Mapa de campos DOCPROPERTY -> claves del diccionario de valores
# ---------------------------------------------------------------------------
FIELD_MAP = {
    "Municipio": "municipio",
    "Habitantes": "habitantes",
    "LongitudRed": "longitud_red",
    "LongitudRedPrimaria": "longitud_primaria",
    "LongitudRedSecundaria": "longitud_secundaria",
    "Topografia": "topografia",
    "Cota_Min_msnm": "cota_min",
    "Cota_Max_msnm": "cota_max",
    "FuentesAbastecimiento": "fuentes_abastecimiento",
    "NumeroDepositos": "num_depositos",
    "VolumenDepositos": "volumen_depositos",
    "UbicacionDepositos": "ubicacion_depositos",
    "Num_Estaciones_Bombeo": "num_estaciones_bombeo",
    "Descripcion_bombeos": "descripcion_bombeos",
    "Num_Grupos_Presion": "num_grupos_presion",
    "Num_Reductoras": "num_reductoras",
    "NumeroAbonados": "num_abonados",
    "AbonadosDomesticos": "abonados_domesticos",
    "FactoresEstacionales": "factores_estacionales",
    "Num_Arcos": "num_arcos",
    "Num_Nodos": "num_nodos",
    "Num_Connecs": "num_connecs",
    "Periodo_Demanda": "periodo_demanda",
    "Demanda_Media_ls": "demanda_media_ls",
    "Demanda_Media_m3año": "demanda_media_m3ano",
    "Num_Sectores": "num_sectores",
    "Hora_Punta": "hora_punta",
    "Hora_Minimo": "hora_minimo",
    "multiplicador_demanda": "multiplicador_demanda",
}


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------

def _build_values(params, datos_muni, resultados):
    """Combina todas las fuentes de datos en un diccionario plano de valores."""
    values = {}

    # Datos del municipio (base de datos)
    if datos_muni:
        values.update(datos_muni)

    # Resultados de simulacion
    if resultados:
        for key in ("hora_punta", "hora_minimo", "demanda_media_ls",
                     "demanda_media_m3ano", "periodo_demanda"):
            if key in resultados:
                values[key] = resultados[key]

    # Parametros del usuario (mayor prioridad, sobreescriben si coinciden)
    if params:
        if params.get("municipio_nombre"):
            values["municipio"] = params["municipio_nombre"]
        if params.get("num_sectores") is not None:
            values["num_sectores"] = params["num_sectores"]
        # Campos manuales (sub-diccionario introducido por el usuario)
        campos_manuales = params.get("campos_manuales", {})
        for key, val in campos_manuales.items():
            if val:  # solo sobreescribir si el usuario introdujo algo
                values[key] = val

    # Horas de punta y minimo desde los timesteps de resultados
    if resultados and resultados.get("timesteps"):
        ts = resultados["timesteps"]
        if ts.get("punta"):
            values["hora_punta"] = ts["punta"]
        if ts.get("nocturno"):
            values["hora_minimo"] = ts["nocturno"]

    return values


def _format_value(value):
    """Convierte un valor a cadena adecuada para insertar en el documento."""
    if value is None:
        return ""
    if isinstance(value, float):
        # Eliminar decimales innecesarios (ej. 3.0 -> "3", 3.14 -> "3,14")
        if value == int(value):
            return str(int(value))
        return f"{value:g}".replace(".", ",")
    if isinstance(value, int):
        return str(value)
    return str(value)


def _extract_field_name(instr_text):
    """Extrae el nombre del campo de una instruccion DOCPROPERTY.

    Soporta formatos como:
        DOCPROPERTY "Municipio"  \\* MERGEFORMAT
        DOCPROPERTY Municipio
        DOCPROPERTY "Cota_Min_msnm"
    """
    if not instr_text:
        return None
    text = instr_text.strip()
    # Buscar DOCPROPERTY seguido del nombre del campo
    upper = text.upper()
    idx = upper.find("DOCPROPERTY")
    if idx == -1:
        return None
    rest = text[idx + len("DOCPROPERTY"):].strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end != -1:
            return rest[1:end]
    # Sin comillas: tomar la primera palabra
    parts = rest.split()
    if parts:
        return parts[0]
    return None


# ---------------------------------------------------------------------------
# Actualizacion de custom.xml (propiedades personalizadas del documento)
# ---------------------------------------------------------------------------

def _update_custom_properties(doc, field_values):
    """Actualiza las propiedades personalizadas en docProps/custom.xml.

    Si una propiedad ya existe, actualiza su valor.
    Si no existe, la crea.
    """
    custom_part = None
    for rel in doc.part.package.rels.values():
        if "custom-properties" in rel.reltype:
            custom_part = rel.target_part
            break

    if custom_part is None:
        logger.warning("No se encontro la parte custom-properties en el documento.")
        return

    root = etree.fromstring(custom_part.blob)

    existing = {}
    for prop in root.findall(f"{{{NS_CUSTOM}}}property"):
        name = prop.get("name")
        if name:
            existing[name] = prop

    next_pid = max(
        (int(p.get("pid", "1")) for p in root.findall(f"{{{NS_CUSTOM}}}property")),
        default=1,
    ) + 1

    for field_name, value_str in field_values.items():
        if field_name in existing:
            prop_elem = existing[field_name]
            # Actualizar el valor existente (buscar elemento vt:lpwstr o similar)
            vt_elem = prop_elem.find(f"{{{NS_VT}}}lpwstr")
            if vt_elem is None:
                # Puede ser otro tipo; limpiar hijos y crear lpwstr
                for child in list(prop_elem):
                    prop_elem.remove(child)
                vt_elem = etree.SubElement(prop_elem, f"{{{NS_VT}}}lpwstr")
            vt_elem.text = value_str
        else:
            # Crear nueva propiedad
            prop_elem = etree.SubElement(
                root,
                f"{{{NS_CUSTOM}}}property",
                fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
                pid=str(next_pid),
                name=field_name,
            )
            vt_elem = etree.SubElement(prop_elem, f"{{{NS_VT}}}lpwstr")
            vt_elem.text = value_str
            next_pid += 1

    custom_part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                        standalone=True)


# ---------------------------------------------------------------------------
# Actualizacion de campos en el cuerpo del documento
# ---------------------------------------------------------------------------

def _update_fld_simple_fields(body, field_values):
    """Actualiza campos fldSimple en el cuerpo del documento.

    Estructura:
        <w:fldSimple w:instr=' DOCPROPERTY "FieldName"  \\* MERGEFORMAT '>
            <w:r><w:t>valor</w:t></w:r>
        </w:fldSimple>
    """
    count = 0
    for fld in body.iter(f"{{{NS_W}}}fldSimple"):
        instr = fld.get(f"{{{NS_W}}}instr", "")
        field_name = _extract_field_name(instr)
        if field_name and field_name in field_values:
            # Buscar el primer w:t dentro de w:r
            for run in fld.iter(f"{{{NS_W}}}r"):
                t_elem = run.find(f"{{{NS_W}}}t")
                if t_elem is not None:
                    t_elem.text = field_values[field_name]
                    # Preservar espacios si el valor los tiene
                    if field_values[field_name].startswith(" ") or \
                       field_values[field_name].endswith(" "):
                        t_elem.set(
                            "{http://www.w3.org/XML/1998/namespace}space",
                            "preserve",
                        )
                    count += 1
                    break
    logger.debug("Actualizados %d campos fldSimple.", count)


def _update_fld_char_fields(body, field_values):
    """Actualiza campos fldChar (complejos) en el cuerpo del documento.

    Estructura tipica en un parrafo:
        <w:r><w:fldChar w:fldCharType="begin"/></w:r>
        <w:r><w:instrText> DOCPROPERTY "FieldName" \\* MERGEFORMAT </w:instrText></w:r>
        <w:r><w:fldChar w:fldCharType="separate"/></w:r>
        <w:r><w:t>valor mostrado</w:t></w:r>
        <w:r><w:fldChar w:fldCharType="end"/></w:r>

    El valor mostrado se encuentra en los runs entre "separate" y "end".
    """
    count = 0
    for paragraph in body.iter(f"{{{NS_W}}}p"):
        runs = list(paragraph.iter(f"{{{NS_W}}}r"))
        i = 0
        while i < len(runs):
            fld_char = runs[i].find(f"{{{NS_W}}}fldChar")
            if fld_char is not None and fld_char.get(f"{{{NS_W}}}fldCharType") == "begin":
                # Recoger la instruccion completa (puede estar en multiples runs)
                instr_text = ""
                sep_idx = None
                end_idx = None
                j = i + 1
                while j < len(runs):
                    fc = runs[j].find(f"{{{NS_W}}}fldChar")
                    if fc is not None:
                        ftype = fc.get(f"{{{NS_W}}}fldCharType")
                        if ftype == "separate":
                            sep_idx = j
                        elif ftype == "end":
                            end_idx = j
                            break
                    else:
                        instr_elem = runs[j].find(f"{{{NS_W}}}instrText")
                        if instr_elem is not None and sep_idx is None:
                            instr_text += (instr_elem.text or "")
                    j += 1

                field_name = _extract_field_name(instr_text)
                if field_name and field_name in field_values and \
                   sep_idx is not None and end_idx is not None:
                    value_str = field_values[field_name]
                    # Actualizar los runs entre separate y end
                    value_runs = runs[sep_idx + 1:end_idx]
                    if value_runs:
                        # Poner el valor en el primer run, vaciar el resto
                        first_t = value_runs[0].find(f"{{{NS_W}}}t")
                        if first_t is None:
                            first_t = etree.SubElement(value_runs[0], f"{{{NS_W}}}t")
                        first_t.text = value_str
                        if value_str.startswith(" ") or value_str.endswith(" "):
                            first_t.set(
                                "{http://www.w3.org/XML/1998/namespace}space",
                                "preserve",
                            )
                        for extra_run in value_runs[1:]:
                            t = extra_run.find(f"{{{NS_W}}}t")
                            if t is not None:
                                t.text = ""
                        count += 1
                    i = end_idx + 1
                    continue
            i += 1
    logger.debug("Actualizados %d campos fldChar.", count)


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def rellenar_docproperties(doc, params, datos_muni, resultados):
    """Rellena todos los campos DOCPROPERTY del documento Word.

    Actualiza tanto las propiedades personalizadas (docProps/custom.xml)
    como los valores mostrados en el cuerpo del documento.

    Args:
        doc: Objeto Document de python-docx.
        params: Diccionario con parametros del usuario (municipio_nombre,
            sector_ids, num_sectores, etc.).
        datos_muni: Diccionario con datos del municipio extraidos de la BD.
        resultados: Diccionario con resultados de simulacion.
    """
    # 1. Construir diccionario combinado de valores
    values = _build_values(params, datos_muni, resultados)

    # 2. Mapear nombres de campo DOCPROPERTY a sus valores formateados
    field_values = {}
    for field_name, data_key in FIELD_MAP.items():
        if data_key in values:
            field_values[field_name] = _format_value(values[data_key])

    if not field_values:
        logger.warning("No se encontraron valores para rellenar campos DOCPROPERTY.")
        return

    logger.info(
        "Rellenando %d campos DOCPROPERTY: %s",
        len(field_values),
        ", ".join(sorted(field_values.keys())),
    )

    # 3. Actualizar propiedades personalizadas en custom.xml
    _update_custom_properties(doc, field_values)

    # 4. Actualizar valores mostrados en el cuerpo del documento
    body = doc.element.body
    _update_fld_simple_fields(body, field_values)
    _update_fld_char_fields(body, field_values)

    # 5. Tambien buscar en headers y footers
    for section in doc.sections:
        for header in (section.header, section.first_page_header,
                       section.even_page_header):
            if header and header.is_linked_to_previous is False:
                _update_fld_simple_fields(header._element, field_values)
                _update_fld_char_fields(header._element, field_values)
        for footer in (section.footer, section.first_page_footer,
                       section.even_page_footer):
            if footer and footer.is_linked_to_previous is False:
                _update_fld_simple_fields(footer._element, field_values)
                _update_fld_char_fields(footer._element, field_values)

    logger.info("Campos DOCPROPERTY actualizados correctamente.")
