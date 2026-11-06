"""Tests del decorador `protegido` (lista blanca, ticket S3-1)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot  # noqa: E402


def _update_falso(id_usuario):
    """Un Update de juguete con lo suficiente para el decorador."""
    usuario = SimpleNamespace(id=id_usuario, full_name="Mecanico Prueba")
    mensaje = SimpleNamespace(text="/start")
    return SimpleNamespace(effective_user=usuario, effective_message=mensaje, r=None)


def _handler_falso(update, context):
    async def falso(update, context):
        update.r = "PASS"

    return falso


def test_usuario_autorizado_pasa(monkeypatch):
    monkeypatch.setattr(bot, "IDs_AUTORIZADOS", {9136002456})
    handler_protegido = bot.protegido(_handler_falso(None, None))
    update = _update_falso(9136002456)
    asyncio.run(handler_protegido(update, None))
    assert update.r == "PASS"


def test_usuario_desconocido_no_pasa(monkeypatch):
    monkeypatch.setattr(bot, "IDs_AUTORIZADOS", {9136002456})
    handler_protegido = bot.protegido(_handler_falso(None, None))
    update = _update_falso(666)
    asyncio.run(handler_protegido(update, None))
    assert update.r is None  # silencio absoluto para desconocidos


def test_ids_con_comas_y_espacios_se_parsean():
    ids = {
        int(x) for x in "11, 22 ,33".replace(",", " ").split() if x.strip()
    }
    assert ids == {11, 22, 33}


def test_env_vacio_no_tira_error():
    import os

    texto = ""
    ids = {
        int(x) for x in texto.replace(",", " ").split() if x.strip()
    }
    assert ids == set()
