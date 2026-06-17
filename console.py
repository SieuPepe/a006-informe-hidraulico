"""Utilidades de consola para entrada interactiva robusta.

El problema que resuelve: cuando se encadenan muchos prompts, un Enter (u otra
tecla) pulsado ANTES de que aparezca la pregunta se queda en el buffer de stdin
(type-ahead) y lo consume el siguiente input(), devolviendo vacío. Eso desplaza
toda la secuencia un paso: tu respuesta real cae en el prompt siguiente y parece
que el programa "se salta" pasos.

La solución es descartar lo que haya pendiente en stdin justo antes de leer cada
respuesta, de modo que solo cuente lo que tecleas DESPUÉS de ver el prompt.
"""
import sys


def flush_input():
    """Descarta la entrada pendiente en stdin (type-ahead) si es una terminal.

    No hace nada si stdin está redirigido (tubería/fichero), para no romper la
    ejecución automatizada o no interactiva.
    """
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return
    except (ValueError, OSError):
        return

    # POSIX (Linux / macOS)
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
        return
    except (ImportError, OSError, ValueError):
        pass

    # Windows
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    except (ImportError, OSError):
        pass


def ask(prompt=""):
    """Como input(), pero descarta primero cualquier type-ahead pendiente.

    Así un Enter tecleado de más en un prompt anterior no se cuela en este.
    """
    flush_input()
    return input(prompt)
