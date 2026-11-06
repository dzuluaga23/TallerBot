"""Tests del decorador `protegido` y del modulo de roles (S3-1/S5-1)."""
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


def _handler_falso(update, context):
    async def falso(update, context):
        update.r = "PASS"

    return falso


def test_usuario_autorizado_pasa(monkeypatch):
    monkeypatch.setattr(roles, "ADMIN_IDS", {9136002456: "Dueño"})
    monkeypatch.setattr(roles, "MECANICOS", {})
    update = _update_falso(9136002456)
    asyncio.run(bot.protegido(_handler_falso(None, None))(update, None))
    assert update.r == "PASS"


def test_mecanico_autorizado_pasa(monkeypatch):
    monkeypatch.setattr(roles, "ADMIN_IDS", {})
    monkeypatch.setattr(roles, "MECANICOS", {222: "Pedro"})
    update = _update_falso(222)
    asyncio.run(bot.protegido(_handler_falso(None, None))(update, None))
    assert update.r == "PASS"


def test_desconocido_no_pasa(monkeypatch):
    monkeypatch.setattr(roles, "ADMIN_IDS", {1: "Dueño"})
    monkeypatch.setattr(roles, "MECANICOS", {2: "Pedro"})
    update = _update_falso(666)
    asyncio.run(bot.protegido(_handler_falso(None, None))(update, None))
    assert update.r is None  # silencio absoluto


def test_parseo_de_ids():
    assert roles._parsear("111:Pedro, 222", "X") == {111: "Pedro", 222: "X"}
    assert roles._parsear("", "X") == {}
    assert roles._parsear("333", "Dueño") == {333: "Dueño"}


def test_es_admin_y_nombre(monkeypatch):
    monkeypatch.setattr(roles, "ADMIN_IDS", {1: "Duque"})
    monkeypatch.setattr(roles, "MECANICOS", {2: "Pedro"})
    assert roles.es_admin(1) and not roles.es_admin(2)
    assert roles.nombre_de(1) == "Duque"
    assert roles.nombre_de(2) == "Pedro"
    assert roles.nombre_de(999) is None
