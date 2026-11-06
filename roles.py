"""Roles del bot: dueño (admin) y mecánicos.

Se configuran TODOS en el .env (sin tocar codigo nunca):

    # El/Los dueño(s) ven todo el taller. Si son varios se separan por coma.
    # Permite formato "ID" o "ID:Nombre" por si quieres etiquetar:
    ADMIN_IDS=9136002456

    # Mecánicos: OBLIGATORIO formato ID:Nombre (el nombre sale firmado en
    # los trabajo que registran y en los desgloses).
    MECHANICS=1122334455:Pedro,5566778899:Juan
"""
import os

from dotenv import load_dotenv

# El .env se carga aqui (antes de leer ADMIN_IDS/MECHANICS) porque el bot
# importa este modulo antes de cualquier otra cosa.
load_dotenv()


def _parsear(texto: str, etiqueta_por_defecto: str) -> dict[int, str]:
    """'111:Pedro, 222' -> {111: 'Pedro', 222: etiqueta_por_defecto}"""
    salida: dict[int, str] = {}
    for item in (texto or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            id_texto, nombre = item.split(":", 1)
            salida[int(id_texto)] = nombre.strip()
        else:
            salida[int(item)] = etiqueta_por_defecto
    return salida


# Se lee UNA vez al importar el modulo (al arrancar el bot)
ADMIN_IDS: dict[int, str] = _parsear(os.getenv("ADMIN_IDS", ""), "Dueño")
MECANICOS: dict[int, str] = _parsear(os.getenv("MECHANICS", ""), "Mecánico")


def es_admin(id_usuario: int) -> bool:
    return id_usuario in ADMIN_IDS


def es_autorizado(id_usuario: int) -> bool:
    """Duenos y mecanicos pueden usar el bot; nadie mas."""
    return id_usuario in ADMIN_IDS or id_usuario in MECANICOS


def nombre_de(id_usuario: int | None) -> str | None:
    """Etiqueta legible del usuario segun el .env, si existe."""
    if id_usuario is None:
        return None
    return ADMIN_IDS.get(id_usuario) or MECANICOS.get(id_usuario)
