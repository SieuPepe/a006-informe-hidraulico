# Plantillas Word

Coloca aquí los archivos `.docx` de plantilla que el script `main.py` debe usar.

Los archivos `.docx` de esta carpeta están **versionados** (excepción al `.gitignore` global que ignora `*.docx`).

## Cómo añadir una plantilla nueva

### Opción A — Desde GitHub (web)

1. Entra al repo → carpeta `plantillas/`.
2. `Add file → Upload files`.
3. Arrastra el `.docx` y commit.

### Opción B — Desde local

```bash
cp "ruta/al/archivo.docx" plantillas/
git add plantillas/archivo.docx
git commit -m "feat: añadir plantilla X"
git push
```

## Uso

Al ejecutar `python main.py`, el script lista automáticamente los `.docx` que encuentre en esta carpeta y permite seleccionar uno por número. Si no hay ninguno, pide la ruta manual.
