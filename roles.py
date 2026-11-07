"""Roles por taller, leidos de la BASE DE DATOS (Sprint 6).

El .env dejo de manejar roles: los duenos y mecanicos se gestionan desde
el propio bot con /nuevotaller y links de invitacion. Aki solo quedan los
helpers de consulta que usan los handlers.
"""
import db


def perfil(user_id: int | None) -> db.sqlite3.Row | None:
    """Fila del usuario activo en la BD, o None si no pertenece a nadie."""
    if user_id is None:
        return None
    return db.usuario_por_id(user_id)


def taller_de(user_id: int | None) -> int | None:
    fila = perfil(user_id)
    return fila["taller_id"] if fila else None


def rol_de(user_id: int | None) -> str | None:
    fila = perfil(user_id)
    return fila["rol"] if fila else None


def nombre_de(user_id: int | None) -> str | None:
    fila = perfil(user_id)
    return fila["nombre"] if fila else None


def es_dueno(user_id: int | None) -> bool:
    return rol_de(user_id) == db.ROL_DUENO


def es_autorizado(user_id: int | None) -> bool:
    """Duenos y mecanicos activos de cualquier taller."""
    return perfil(user_id) is not None
