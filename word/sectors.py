"""
word/sectors.py — Replicacion del bloque de sector en el capitulo 5.3

La plantilla Word contiene un unico bloque "Sector [XXXX]" en el capitulo 5.3
que sirve como plantilla. Este modulo clona ese bloque para cada sector
hidraulico del municipio, actualizando encabezados, marcadores, campos REF
y marcadores de tablas.
"""
import copy
import re
import logging
from lxml import etree

logger = logging.getLogger(__name__)

# Namespace map for OpenXML word processing
NSMAP = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

# XPath helpers
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _qn(tag):
    """Build a qualified name in the w: namespace."""
    return f'{{{W}}}{tag}'


def _get_paragraph_style(paragraph_elem):
    """Return the style val of a <w:p> element, or None."""
    pPr = paragraph_elem.find(_qn('pPr'))
    if pPr is None:
        return None
    pStyle = pPr.find(_qn('pStyle'))
    if pStyle is None:
        return None
    return pStyle.get(_qn('val'))


def _heading_level(style_val):
    """
    Return the heading level (1-9) for a style like 'Heading3' or 'Ttulo3',
    or None if it is not a heading style.
    """
    if style_val is None:
        return None
    # Standard english names: Heading1, Heading2, ...
    m = re.match(r'(?:Heading|Ttulo|Titre|Titulo)\s*(\d)', style_val, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Also try the built-in style ids which python-docx may report
    m = re.match(r'heading\s*(\d)', style_val, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _paragraph_text(p_elem):
    """Extract concatenated text from all <w:t> elements in a paragraph."""
    texts = p_elem.findall(f'.//{_qn("t")}')
    return ''.join(t.text or '' for t in texts)


def _find_template_block(body):
    """
    Locate the template sector block inside the document body.

    The template block is the SUB-heading "5.3.1 Sector XXXX", NOT the
    parent heading "5.3. Análisis por sector hidráulico". We identify
    it by looking for a heading that contains both "Sector" AND "XXXX"
    (the placeholder text), or a heading matching "5.3.1".

    Returns (start_index, end_index) — indices into body's child elements.
    """
    children = list(body)
    start_idx = None
    template_level = None

    for i, elem in enumerate(children):
        if elem.tag != _qn('p'):
            continue
        style = _get_paragraph_style(elem)
        level = _heading_level(style)
        if level is None:
            continue

        # If we already found the start, a heading of same or higher level
        # (lower or equal number) marks the end of the block.
        if start_idx is not None and level <= template_level:
            return start_idx, i

        # Look for the TEMPLATE heading: must contain "XXXX" or "5.3.1"
        # This avoids matching "5.3. Análisis por sector hidráulico"
        if start_idx is None:
            text = _paragraph_text(elem)
            is_template = (
                'XXXX' in text
                or re.search(r'5\.3\.1', text)
                or (re.search(r'\bSector\b', text, re.IGNORECASE)
                    and level >= 3)  # Sub-heading level, not parent
            )
            if is_template:
                start_idx = i
                template_level = level

    # If block goes to the very end of the document
    if start_idx is not None:
        return start_idx, len(children)

    return None, None


def _collect_block_elements(body, start_idx, end_idx):
    """Return a list of XML elements in the block range."""
    children = list(body)
    return children[start_idx:end_idx]


def _get_max_bookmark_id(body):
    """Find the maximum bookmarkStart id in the document to avoid collisions."""
    max_id = 0
    for bm in body.iter(_qn('bookmarkStart')):
        try:
            val = int(bm.get(_qn('id'), '0'))
            if val > max_id:
                max_id = val
        except (ValueError, TypeError):
            pass
    return max_id


def _update_heading_text(p_elem, sector_number, sector_name):
    """
    Replace the text in the heading paragraph with '5.3.X. Sector NAME'.
    Preserves the first run's formatting and removes extra runs.
    """
    runs = p_elem.findall(f'.//{_qn("r")}')
    if not runs:
        return

    # No incluir numeración — el estilo Ttulo3 la genera automáticamente
    new_text = f'Sector {sector_name}'

    # Set the full text in the first run's <w:t> element
    first_run = runs[0]
    t_elem = first_run.find(_qn('t'))
    if t_elem is None:
        t_elem = etree.SubElement(first_run, _qn('t'))
    t_elem.text = new_text
    t_elem.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')

    # Remove any additional runs that carry text (to avoid duplicated text),
    # but keep runs that might carry field codes or other non-text content.
    for run in runs[1:]:
        t = run.find(_qn('t'))
        if t is not None:
            run.getparent().remove(run)


def _update_bookmarks(block_elements, sector_number, old_bookmark_id_map, next_bookmark_id):
    """
    Update bookmarkStart/bookmarkEnd elements in the cloned block.

    - The heading bookmark (e.g. _Ref226094431) gets a new unique name and id.
    - Narrative bookmarks (sector_x_presiones, etc.) are renumbered.

    Returns:
        (heading_bookmark_name, next_bookmark_id) — the new heading bookmark
        name and the next available bookmark id.
    """
    heading_bookmark_name = None

    # First pass: collect all bookmarkStart elements and plan renames
    bookmark_starts = []
    for elem in block_elements:
        for bs in elem.iter(_qn('bookmarkStart')):
            bookmark_starts.append(bs)

    id_remap = {}  # old_id -> new_id
    name_remap = {}  # old_name -> new_name

    for bs in bookmark_starts:
        old_id = bs.get(_qn('id'), '')
        old_name = bs.get(_qn('name'), '')

        new_id = str(next_bookmark_id)
        next_bookmark_id += 1
        id_remap[old_id] = new_id

        # Determine new name
        if old_name.startswith('_Ref') or old_name.startswith('_ref'):
            # Heading reference bookmark — generate a new unique one
            new_name = f'_Ref{900000 + sector_number}'
            heading_bookmark_name = new_name
        elif re.match(r'sector_\w+_presiones', old_name, re.IGNORECASE):
            new_name = f'sector_{sector_number}_presiones'
        elif re.match(r'sector_\w+_velocidades', old_name, re.IGNORECASE):
            new_name = f'sector_{sector_number}_velocidades'
        elif re.match(r'sector_\w+_deposito', old_name, re.IGNORECASE):
            new_name = f'sector_{sector_number}_deposito'
        else:
            # Generic: append sector number to avoid duplicates
            new_name = re.sub(
                r'_[xX]+|_\d+',
                f'_{sector_number}',
                old_name,
                count=1,
            )
            if new_name == old_name:
                new_name = f'{old_name}_{sector_number}'

        name_remap[old_name] = new_name

        bs.set(_qn('id'), new_id)
        bs.set(_qn('name'), new_name)

    # Update bookmarkEnd elements to match the remapped ids
    for elem in block_elements:
        for be in elem.iter(_qn('bookmarkEnd')):
            old_id = be.get(_qn('id'), '')
            if old_id in id_remap:
                be.set(_qn('id'), id_remap[old_id])

    return heading_bookmark_name, next_bookmark_id


def _update_ref_fields(block_elements, heading_bookmark_name):
    """
    Update REF field instructions in the cloned block to point to the new
    heading bookmark. This ensures table captions display the correct sector name.

    REF fields look like: <w:instrText> REF _Ref226094431 \\h </w:instrText>
    """
    if not heading_bookmark_name:
        return

    for elem in block_elements:
        for instr in elem.iter(_qn('instrText')):
            if instr.text and 'REF' in instr.text:
                # Replace the old _Ref... bookmark name with the new one
                instr.text = re.sub(
                    r'REF\s+\S+',
                    f'REF {heading_bookmark_name}',
                    instr.text,
                )


def _update_table_markers(block_elements, sector_number):
    """
    Update the table placeholder markers in the cloned block so each sector
    has unique markers. For example:
      {{TABLA_SECTOR_MEDIA}} -> {{TABLA_SECTOR_1_MEDIA}}

    Word often splits a literal like ``{{TABLA_SECTOR_MEDIA}}`` across
    several <w:t> runs (e.g. ``{{TABLA_``, ``SECTOR_``, ``MEDIA}}``).
    Iterating one <w:t> at a time would miss those split markers, so we
    aggregate text per paragraph (<w:p>), do the replacement on the full
    string, and write the new text back into the first <w:t>, blanking
    the rest. The marker fills its own paragraph in the template, so
    collapsing runs preserves visible formatting.
    """
    marker_map = {
        '{{TABLA_SECTOR_MEDIA}}':      f'{{{{TABLA_SECTOR_{sector_number}_MEDIA}}}}',
        '{{TABLA_SECTOR_MAXIMA}}':     f'{{{{TABLA_SECTOR_{sector_number}_MAXIMA}}}}',
        '{{TABLA_SECTOR_MINIMA}}':     f'{{{{TABLA_SECTOR_{sector_number}_MINIMA}}}}',
        '{{TABLA_SECTOR_DEPOSITOS}}':  f'{{{{TABLA_SECTOR_{sector_number}_DEPOSITOS}}}}',
    }

    replacements = 0
    for elem in block_elements:
        for p in elem.iter(_qn('p')):
            t_elements = p.findall(f'.//{_qn("t")}')
            if not t_elements:
                continue
            full_text = ''.join(t.text or '' for t in t_elements)

            new_text = full_text
            for old_marker, new_marker in marker_map.items():
                if old_marker in new_text:
                    new_text = new_text.replace(old_marker, new_marker)

            if new_text != full_text:
                t_elements[0].text = new_text
                t_elements[0].set(
                    '{http://www.w3.org/XML/1998/namespace}space', 'preserve'
                )
                for t in t_elements[1:]:
                    t.text = ''
                replacements += 1

    if replacements:
        logger.info(
            "_update_table_markers sector %d: %d marcadores reemplazados",
            sector_number, replacements,
        )
    else:
        logger.warning(
            "_update_table_markers sector %d: NO se reemplazó ningún marcador. "
            "Comprueba que el bloque plantilla contiene {{TABLA_SECTOR_MEDIA}} y similares.",
            sector_number,
        )


def _update_narrative_hidden_text(block_elements, sector_number):
    """
    Update hidden-text narrative placeholders that use sector_x or sector_X
    patterns in their text content.
    """
    for elem in block_elements:
        for t_elem in elem.iter(_qn('t')):
            if t_elem.text:
                t_elem.text = re.sub(
                    r'sector_[xX]+_',
                    f'sector_{sector_number}_',
                    t_elem.text,
                )


def replicar_sectores(doc, datos_sectores, resultados):
    """
    Replicate the template sector block in Chapter 5.3 for each hydraulic sector.

    Parameters
    ----------
    doc : docx.Document
        The python-docx Document loaded from the template.
    datos_sectores : list[dict]
        List of sector dicts, each with at least 'sector_id' and 'nombre_sector'.
    resultados : dict
        Simulation results dict with 'por_sector' and 'depositos_eps' keys.
    """
    if not datos_sectores:
        logger.warning("No hay sectores para replicar.")
        return

    body = doc.element.body

    start_idx, end_idx = _find_template_block(body)
    if start_idx is None:
        logger.error(
            "No se encontro el bloque de sector plantilla en el capitulo 5.3. "
            "Asegurese de que existe un encabezado con la palabra 'Sector'."
        )
        return

    logger.info(
        "Bloque plantilla encontrado: elementos %d a %d (%d elementos)",
        start_idx, end_idx, end_idx - start_idx,
    )

    # Collect the original template elements (before any modifications)
    template_elements = _collect_block_elements(body, start_idx, end_idx)

    # Determine insertion anchor: the element right after the template block,
    # or None if the block is at the end.
    children = list(body)
    if end_idx < len(children):
        insert_before = children[end_idx]
    else:
        insert_before = None

    # Track the next available bookmark id
    next_bm_id = _get_max_bookmark_id(body) + 1

    # Collect old bookmark id mapping from the template (for reference)
    old_bm_map = {}
    for elem in template_elements:
        for bs in elem.iter(_qn('bookmarkStart')):
            old_bm_map[bs.get(_qn('name'), '')] = bs.get(_qn('id'), '')

    # Generate cloned blocks for each sector
    for sector_number, sector_data in enumerate(datos_sectores, start=1):
        sector_name = sector_data.get('nombre_sector', sector_data.get('name', f'Sector {sector_number}'))

        logger.info("Generando bloque para sector %d: %s", sector_number, sector_name)

        # Deep-copy all template elements
        cloned_elements = [copy.deepcopy(elem) for elem in template_elements]

        # 1. Update heading text
        for elem in cloned_elements:
            if elem.tag == _qn('p'):
                style = _get_paragraph_style(elem)
                if _heading_level(style) is not None:
                    _update_heading_text(elem, sector_number, sector_name)
                    break

        # 2. Update bookmarks
        heading_bm_name, next_bm_id = _update_bookmarks(
            cloned_elements, sector_number, old_bm_map, next_bm_id
        )

        # 3. Update REF fields in captions
        _update_ref_fields(cloned_elements, heading_bm_name)

        # 4. Update table markers
        _update_table_markers(cloned_elements, sector_number)

        # 5. Update narrative hidden text placeholders
        _update_narrative_hidden_text(cloned_elements, sector_number)

        # Insert cloned elements into the body
        if insert_before is not None:
            for elem in cloned_elements:
                insert_before.addprevious(elem)
        else:
            for elem in cloned_elements:
                body.append(elem)

    # Remove the original template block
    for elem in template_elements:
        body.remove(elem)

    # Fill each sector's tables with its own data
    from word.tables import rellenar_tabla_sector
    for sector_number, sector_data in enumerate(datos_sectores, start=1):
        sid = sector_data.get('sector_id')
        rellenar_tabla_sector(doc, sector_data, sid, resultados, sector_number)

    logger.info(
        "Replicacion completada: %d bloques de sector generados.",
        len(datos_sectores),
    )
