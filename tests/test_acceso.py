"""Tests del decorador `protegido` con roles por BD (S3-1/S6)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot  # noqa: E402
import roles  # noqa: E402


def _update_falso(id_usuario):
    usuario = SimpleNamespace(id=id_usuario, full_name="Mecanico Prueba")
    mensaje = SimpleNamespace(text="/start")
    return SimpleNamespace(effective_user=usuario, effective_message=mensaje, r=None)


def _handler_falso():
    async def falso(update, context):
        update.r = "PASS"

    return falso


def test_autorizado_pasa(monkeypatch):
    monkeypatch.setattr(roles, "es_autorizado", lambda uid: uid == 222)
    update = _update_falso(222)
    asyncio.run(bot.protegido(_handler_falso())(update, None))
    assert update.r == "PASS"


def test_desconocido_no_pasa(monkeypatch):
    monkeypatch.setattr(roles, "es_autorizado", lambda uid: uid == 222)
    update = _update_falso(666)
    asyncio.run(bot.protegido(_handler_falso())(update, None))
    assert update.r is None  # silencio absoluto para ajenos
