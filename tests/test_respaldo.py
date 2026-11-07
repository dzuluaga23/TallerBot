"""Tests del respaldo de BD a GitHub (Sprint 4 - Render free)."""
import json
import sqlite3

import pytest

import respaldo  # noqa: E402  (sys.path ya lo pone conftest.py)


@pytest.fixture(autouse=True)
def nube_conectada(monkeypatch):
    """Env fake de GitHub para TODOS los tests de este modulo."""
    monkeypatch.setenv("GITHUB_RES_REPO", "dueno/respaldo-taller")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_falso")


def _bd_con_datos(ruta, talleres=1):
    """BD minima real (schema + talleres)."""
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE talleres (id INTEGER PRIMARY KEY, nombre TEXT)")
    for i in range(1, talleres + 1):
        con.execute("INSERT INTO talleres (id, nombre) VALUES (?, ?)", (i, f"T{i}"))
    con.commit()
    con.close()
    return ruta


def _bd_vacia(ruta):
    """BD real pero sin ningun taller (como init_db la deja)."""
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE talleres (id INTEGER PRIMARY KEY, nombre TEXT)")
    con.close()
    return ruta


# ------------------------------------------------------------- config ----


def test_disponible_con_config(nube_conectada):
    assert respaldo.disponible() is True


def test_disponible_sin_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_RES_REPO", raising=False)
    assert respaldo.disponible() is False


def test_minutos_default():
    assert respaldo.minutos() == 10


def test_bd_tiene_datos(tmp_path):
    assert respaldo._bd_tiene_datos(_bd_con_datos(tmp_path / "t.db")) is True
    assert respaldo._bd_tiene_datos(_bd_vacia(tmp_path / "v.db")) is False
    assert respaldo._bd_tiene_datos(tmp_path / "noexiste.db") is False
    corrupto = tmp_path / "r.db"
    corrupto.write_bytes(b"archivo...")
    assert respaldo._bd_tiene_datos(corrupto) is False


# ------------------------------------------------------------- subir ----


def test_respaldar_sube_bd_nueva(bd_temporal, monkeypatch, tmp_path):
    recibido = {}

    def falso_subir(bd_bytes, sha):
        recibido["bytes"], recibido["sha"] = bd_bytes, sha
        return True

    monkeypatch.setattr(respaldo, "_subir", falso_subir)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {})

    assert respaldo.respaldar_ahora(_bd_con_datos(tmp_path / "taller.db")) is True
    assert recibido["sha"] is None  # archivo nuevo en GitHub


def test_respaldar_actualiza_con_sha(bd_temporal, monkeypatch, tmp_path):
    recibido = {}

    def falso_subir(bd_bytes, sha):
        recibido["sha"] = sha
        return True

    monkeypatch.setattr(respaldo, "_subir", falso_subir)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {"sha": "abc123"})

    assert respaldo.respaldar_ahora(_bd_con_datos(tmp_path / "taller.db")) is True
    assert recibido["sha"] == "abc123"  # actualizacion del archivo existente


def test_respaldar_bd_sin_datos_no_sube(bd_temporal, monkeypatch, tmp_path):
    """REGLA CRITICA: una BD vacia NO puede machacar el respaldo bueno."""
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    ruta = _bd_vacia(tmp_path / "taller.db")
    assert respaldo.respaldar_ahora(ruta) is False


def test_respaldar_bd_corrupta_no_sube(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"octo")
    assert respaldo.respaldar_ahora(ruta) is False


def test_respaldar_sin_bd_local(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert respaldo.respaldar_ahora(tmp_path / "taller.db") is False


def test_respaldar_sin_config_falla_suave(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(respaldo, "_subir", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert respaldo.respaldar_ahora(_bd_con_datos(tmp_path / "taller.db")) is False


def test_respaldar_cuerpo_json_sano(bd_temporal, monkeypatch, tmp_path):
    """El PUT lleva un JSON valido con el contenido en base64."""
    import base64

    capturado = {}

    def falso_http(method, datos=None, accept=""):
        capturado["json"] = json.loads(datos)
        return 200, b"{}"

    monkeypatch.setattr(respaldo, "_http", falso_http)
    monkeypatch.setattr(respaldo, "_json_publicado", lambda: {})

    assert respaldo.respaldar_ahora(_bd_con_datos(tmp_path / "taller.db")) is True
    cuerpo = capturado["json"]
    assert cuerpo["branch"] == "main"
    assert base64.b64decode(cuerpo["content"])


# --------------------------------------------------------- restaurar ----


def test_restaurar_descarga_si_falta(bd_temporal, monkeypatch, tmp_path):
    def falso_http(method, datos=None, accept=""):
        assert method == "GET"
        assert accept == "application/vnd.github.raw"
        return 200, b"BD-DEL-RESPALDO"

    monkeypatch.setattr(respaldo, "_http", falso_http)
    ruta = tmp_path / "taller.db"

    assert respaldo.restaurar_si_hace_falta(ruta) is True
    assert ruta.read_bytes() == b"BD-DEL-RESPALDO"


def test_restaurar_no_toca_bd_con_datos(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    ruta = _bd_con_datos(tmp_path / "taller.db", talleres=2)

    assert respaldo.restaurar_si_hace_falta(ruta) is False  # respeta la BD viva


def test_restaurar_si_bd_vacia(bd_temporal, monkeypatch, tmp_path):
    """BD real pero 0 talleres = restaurar (caso DB default tras deploy)."""

    def falso_http(method, datos=None, accept=""):
        return 200, b"BD-BUENA"

    monkeypatch.setattr(respaldo, "_http", falso_http)
    ruta = _bd_vacia(tmp_path / "taller.db")

    assert respaldo.restaurar_si_hace_falta(ruta) is True
    assert ruta.read_bytes() == b"BD-BUENA"


def test_restaurar_si_bd_corrupta(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.setattr(respaldo, "_http", lambda m, datos=None, accept="": (200, b"BUENA"))
    ruta = tmp_path / "taller.db"
    ruta.write_bytes(b"octo")
    assert respaldo.restaurar_si_hace_falta(ruta) is True


def test_restaurar_sin_config_falla_suave(bd_temporal, monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(respaldo, "_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert respaldo.restaurar_si_hace_falta(tmp_path / "taller.db") is False


def test_restaurar_sin_respaldo_remoto(bd_temporal, monkeypatch, tmp_path):
    """404 en GitHub = aviso, no explota, BD local queda como esta."""
    monkeypatch.setattr(respaldo, "_http", lambda m, datos=None, accept="": (404, b""))
    ruta = _bd_vacia(tmp_path / "taller.db")
    antes = ruta.read_bytes()
    assert respaldo.restaurar_si_hace_falta(ruta) is False
    assert ruta.read_bytes() == antes  # intocada
