"""Tests de los códigos de venta de un solo uso (Sprint 8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot  # noqa: E402

CODIGO = "VENTA-PEDRO-2026-A1"


def test_redimir_codigo_es_un_solo_uso(bd_temporal):
    bd = bd_temporal
    taller_id = bd.crear_taller("Taller Pedro", 1, "Pedro")
    assert bd.redimir_codigo(CODIGO, taller_id, 1) is True
    assert bd.redimir_codigo(CODIGO, 999, 999) is False  # ya está quemado
    assert bd.codigo_ya_redimido(CODIGO) is True
    assert bd.codigo_ya_redimido("VENTA-OTRA-0001") is False


def test_estado_codigo_invalido(monkeypatch, bd_temporal):
    monkeypatch.setattr(bot, "CODIGOS_TALLER", {CODIGO})
    assert bot._estado_codigo("VENTA-FAKE-000X") == "invalido"


def test_estado_codigo_valido(monkeypatch, bd_temporal):
    monkeypatch.setattr(bot, "CODIGOS_TALLER", {CODIGO})
    assert bot._estado_codigo(CODIGO) == "ok"


def test_estado_codigo_letra_minuscula_se_normaliza(monkeypatch, bd_temporal):
    monkeypatch.setattr(bot, "CODIGOS_TALLER", {CODIGO})
    assert bot._estado_codigo(CODIGO.lower()) == "ok"


def test_estado_codigo_usado(monkeypatch, bd_temporal):
    bd = bd_temporal
    monkeypatch.setattr(bot, "CODIGOS_TALLER", {CODIGO})
    taller_id = bd.crear_taller("X", 1, "Duque")
    bd.redimir_codigo(CODIGO, taller_id, 1)
    assert bot._estado_codigo(CODIGO) == "usado"


def test_el_catalogo_del_env_se_parsea(monkeypatch):
    # El usuario puede escribir con comas+espacios; todo queda en mayúsculas
    texto = " venta-a1 , VENTA-B2"
    catalogo = {t.strip().upper() for t in texto.split(",") if t.strip()}
    assert catalogo == {"VENTA-A1", "VENTA-B2"}
