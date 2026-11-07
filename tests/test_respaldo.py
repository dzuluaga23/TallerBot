"""Tests del respaldo de BD a GitHub (Sprint 4 - Render free)."""
import json

import pytest  # noqa: F401 (pytest config da fixtures)

import respaldo  # noqa: E402  (sys.path ya lo pone conftest.py)


@pytest.fixture(autouse=True)
def nube_conectada(monkeypatch):
    """Env fake de GitHub para TODOS los tests de este modulo."""
    monkeypatch.setenv("GITHUB_RES_REPO", "dueno/respaldo-taller")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_falso")


def test_disponible_con_config(nube_conectada):
    assert respaldo.disponible() is True


def test_disponible_sin_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_RES_REPO", raising=False)
    assert respaldo.disponible() is False


def test_minutos_default():
    assert respaldo.minutos() == 10


def test_respaldar_sube_bd_nueva(bd_temporal, monkeypatch, tmp_path):
    recibido = {}

    def falso_subir(bd_bytes, sha):
        recibido["bytes"], recibido["sha"] = bd_bytes, sha
        return True

    monkeypatch.setattr(respaldo, "_subir", falso_subir)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {})

    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"BD-DE-PRUEBA")

    assert respaldo.respaldar_ahora(ruta) is True
    assert recibido["bytes"] == b"BD-DE-PRUEBA"
    assert recibido["sha"] is None  # archivo nuevo en GitHub


def test_respaldar_actualiza_con_sha(bd_temporal, monkeypatch, tmp_path):
    recibido = {}

    def falso_subir(bd_bytes, sha):
        recibido["sha"] = sha
        return True

    monkeypatch.setattr(respaldo, "_subir", falso_subir)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {"sha": "abc123"})

    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"x")

    assert respaldo.respaldar_ahora(ruta) is True
    assert recibido["sha"] == "abc123"  # actualizacion del archivo existente


def test_respaldar_sin_bd_local(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert respaldo.respaldar_ahora(tmp_path / "taller.db") is False


def test_respaldar_sin_config_falla_suave(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"x")
    assert respaldo.respaldar_ahora(ruta) is False  # fail-safe: no explota


def test_restaurar_descarga_si_falta(bd_temporal, monkeypatch, tmp_path):
    def falso_http(method, datos=None, accept=""):
        assert method == "GET"
        assert accept == "application/vnd.github.raw"
        return 200, b"BD-DEL-RESPALDO"

    monkeypatch.setattr(respaldo, "_http", falso_http)
    ruta = tmp_path / "taller.db"

    assert respaldo.restaurar_si_hace_falta(ruta) is True
    assert ruta.read_bytes() == b"BD-DEL-RESPALDO"


def test_restaurar_no_toca_db_viva(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"db real")

    assert respaldo.restaurar_si_hace_falta(ruta) is False  # respeta la BD existente


def test_respaldar_cuerpo_json_sano(bd_temporal, monkeypatch, tmp_path):
    """El PUT llevara un JSON valido con el contenido en base64."""
    import base64

    capturado = {}

    def falso_http(method, datos=None, accept=""):
        capturado["json"] = json.loads(datos)
        return 200, b"{}"

    monkeypatch.setattr(respaldo, "_http", falso_http)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {})

    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"MiBD")
    assert respaldo.respaldar_ahora(ruta) is True
    cuerpo = capturado["json"]
    assert cuerpo["branch"] == "main"
    assert base64.b64decode(cuerpo["content"]) == b"MiBD"
