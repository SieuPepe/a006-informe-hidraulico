"""
Insercion de textos narrativos en marcadores (bookmarks) de Word.

Localiza los bookmarkStart en el XML del documento y reemplaza el contenido
entre bookmarkStart y bookmarkEnd con los textos generados por la IA.
"""
import logging
from copy import deepcopy
from lxml import etree

from ai.generator import generar_textos

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Espacios de nombres XML
# ---------------------------------------------------------------------------
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP_W = {"w": NS_W}


# ---------------------------------------------------------------------------
# Funciones auxiliares XML
# ---------------------------------------------------------------------------

def _find_bookmarks(doc):
    """Devuelve un dict {nombre: elemento_bookmarkStart} de todos los bookmarks del documento."""
    bookmarks = {}
    body = doc.element.body
    for bm_start in body.iter(f"{{{NS_W}}}bookmarkStart"):
        name = bm_start.get(f"{{{NS_W}}}name")
        if name and name != "_GoBack":
            bookmarks[name] = bm_start
    return bookmarks


def _get_bookmark_id(bm_start):
    """Obtiene el id del bookmark (atributo w:id)."""
    return bm_start.get(f"{{{NS_W}}}id")


def _find_bookmark_end(parent, bm_id):
    """Busca el bookmarkEnd correspondiente a un bookmarkStart por su id."""
    for bm_end in parent.iter(f"{{{NS_W}}}bookmarkEnd"):
        if bm_end.get(f"{{{NS_W}}}id") == bm_id:
            return bm_end
    return None


def _remove_content_between(bm_start, bm_end):
    """Elimina los elementos (runs) entre bookmarkStart y bookmarkEnd.

    Los bookmarkStart/End pueden estar en el mismo parrafo o en parrafos
    distintos. En este modulo asumimos que estan en el mismo parrafo
    (caso habitual para marcadores de texto narrativo en plantillas).
    """
    parent = bm_start.getparent()
    if parent is None:
        return

    removing = False
    to_remove = []
    for child in list(parent):
        if child is bm_start:
            removing = True
            continue
        if child is bm_end:
            break
        if removing:
            to_remove.append(child)

    for elem in to_remove:
        parent.remove(elem)


def _get_run_properties_from_bookmark(bm_start):
    """Intenta extraer las propiedades de formato (rPr) del primer run
    dentro del bookmark, para preservar el estilo del texto original."""
    parent = bm_start.getparent()
    if parent is None:
        return None
    bm_id = _get_bookmark_id(bm_start)

    found_start = False
    for child in parent:
        if child is bm_start:
            found_start = True
            continue
        if found_start:
            if child.tag == f"{{{NS_W}}}bookmarkEnd" and child.get(f"{{{NS_W}}}id") == bm_id:
                break
            if child.tag == f"{{{NS_W}}}r":
                rpr = child.find(f"{{{NS_W}}}rPr")
                if rpr is not None:
                    return deepcopy(rpr)
    return None


def _create_run(text, rpr=None):
    """Crea un elemento <w:r><w:t>text</w:t></w:r> con formato opcional."""
    r = etree.SubElement(etree.Element("dummy"), f"{{{NS_W}}}r")
    r.getparent().remove(r)  # Crear elemento suelto

    if rpr is not None:
        r.append(deepcopy(rpr))

    t = etree.SubElement(r, f"{{{NS_W}}}t")
    t.text = text
    # Preservar espacios en blanco
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return r


def _insert_text_at_bookmark(bm_start, text):
    """Inserta texto en un bookmark, reemplazando cualquier contenido previo.

    Pasos:
    1. Captura el formato del texto existente dentro del bookmark.
    2. Elimina todo el contenido entre bookmarkStart y bookmarkEnd.
    3. Inserta nuevos runs con el texto proporcionado.
    """
    bm_id = _get_bookmark_id(bm_start)
    parent = bm_start.getparent()
    if parent is None:
        logger.warning("bookmarkStart sin padre, no se puede insertar texto.")
        return False

    # Buscar bookmarkEnd en el mismo padre o en todo el body
    bm_end = _find_bookmark_end(parent, bm_id)
    if bm_end is None:
        # Buscar en todo el documento (bookmarks que abarcan multiples parrafos)
        root = parent
        while root.getparent() is not None:
            root = root.getparent()
        bm_end = _find_bookmark_end(root, bm_id)

    # Capturar formato antes de borrar
    rpr = _get_run_properties_from_bookmark(bm_start)

    # Eliminar contenido existente entre start y end (solo si estan en el mismo parrafo)
    if bm_end is not None and bm_end.getparent() is parent:
        _remove_content_between(bm_start, bm_end)

    # Insertar nuevos runs despues del bookmarkStart
    # Dividir por lineas para respetar saltos de parrafo dentro del texto
    # (para simplificar, insertamos todo en un unico run)
    new_run = _create_run(text, rpr)

    # Insertar justo despues del bookmarkStart
    bm_index = list(parent).index(bm_start)
    parent.insert(bm_index + 1, new_run)

    return True


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def rellenar_marcadores(doc, params, datos_muni, datos_sectores, resultados):
    """Rellena los marcadores narrativos del documento Word.

    1. Inserta el texto de descripcion de sectores proporcionado por el usuario.
    2. Genera los textos narrativos con la API de Claude.
    3. Inserta cada texto en su marcador correspondiente.

    Args:
        doc: Objeto Document de python-docx.
        params: Diccionario con parametros del usuario. Debe contener
            'descripcion_sectores'.
        datos_muni: Diccionario con datos del municipio.
        datos_sectores: Lista de dicts con datos por sector.
        resultados: Diccionario con resultados de simulacion.
    """
    # Localizar todos los bookmarks del documento
    bookmarks = _find_bookmarks(doc)
    logger.info("Marcadores encontrados en el documento: %s",
                ", ".join(sorted(bookmarks.keys())))

    # 1. Insertar descripcion de sectores (texto del usuario)
    descripcion = params.get("descripcion_sectores", "")
    if descripcion and "descripcion_sectores" in bookmarks:
        logger.info("Insertando texto de descripcion de sectores...")
        _insert_text_at_bookmark(bookmarks["descripcion_sectores"], descripcion)
    elif descripcion:
        logger.warning("Marcador 'descripcion_sectores' no encontrado en el documento.")

    # 2. Generar textos con Claude
    logger.info("Llamando al generador de textos IA...")
    textos_ai = generar_textos(params, datos_muni, datos_sectores, resultados)

    # 3. Insertar cada texto generado en su marcador
    insertados = 0
    no_encontrados = []

    for nombre_marcador, texto in textos_ai.items():
        if not texto:
            logger.warning("Texto vacio para marcador '%s', omitido.", nombre_marcador)
            continue

        if nombre_marcador in bookmarks:
            ok = _insert_text_at_bookmark(bookmarks[nombre_marcador], texto)
            if ok:
                insertados += 1
                logger.debug("Texto insertado en marcador '%s'.", nombre_marcador)
            else:
                logger.warning("No se pudo insertar texto en marcador '%s'.",
                               nombre_marcador)
        else:
            no_encontrados.append(nombre_marcador)

    if no_encontrados:
        logger.warning("Marcadores no encontrados en el documento: %s",
                       ", ".join(no_encontrados))

    logger.info("Marcadores rellenados: %d de %d textos generados.",
                insertados, len(textos_ai))
