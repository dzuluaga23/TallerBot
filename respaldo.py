"""Respaldo de la BD en un repo de GitHub (Sprint 4 - Render free).

Render free NO tiene disco persistente: en cada restart/redeploy la zona
temporal se borra. Este modulo usa un repo privado de GitHub como almacen:

- respaldar_ahora(): sube taller.db (via API Contents, sin necesidad de git).
- restaurar_si_hace_falta(): si la BD no existe o esta vacia, la baja.
- bucle(): hilo daemon que restaura al inicio y respalda cada RESPALDO_MINUTOS.

Config en variables de entorno (Render > Environment > Add):
  GITHUB_RES_REPO = usuario/repo-respaldo   (repo privado, solo para la BD)
  GITHUB_TOKEN    = token con permiso contents:write sobre ese repo
  RESPALDO_MINUTOS = cada cuanto respalda (default 10)

Todo es fail-safe: si falta config o falla la red, el bot sigue andando
(y lo deja escrito en el log).
"""
import base64
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

import db

logger = logging.getLogger("taller-bot.respaldo")

RUTA_REMOTA = "respaldo/taller.db"
INTERVALO_DEFAULT = 10

API = "https://api.github.com"


def repo() -> str:
    """'usuario/repo' del respaldo, o '' si no esta configurado."""
    return os.getenv("GITHUB_RES_REPO", "").strip()


def disponible() -> bool:
    """True si hay repo Y token: solo entonces el respaldo esta activo."""
    return bool(repo()) and bool(os.getenv("GITHUB_TOKEN", "").strip())


def minutos() -> int:
    try:
        n = int(os.getenv("RESPALDO_MINUTOS", str(INTERVALO_DEFAULT)))
        return n if n > 0 else INTERVALO_DEFAULT
    except ValueError:
        return INTERVALO_DEFAULT


# ---------------------------------------------------------------- HTTP ----


def _http(method: str, datos: bytes | str | None = None, accept: str = "") -> tuple[int, bytes]:
    """Peticion a la API de GitHub. Devuelve (codigo, cuerpo). Nunca lanza."""
    url = f"{API}/repos/{repo()}/contents/{RUTA_REMOTA}"
    encabezados = {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "TallerBot",
    }
    if accept:
        encabezados["Accept"] = accept
    cuerpo = None
    if datos is not None:
        if isinstance(datos, str):
            datos = datos.encode("utf-8")
        cuerpo = datos
        encabezados["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=cuerpo, method=method, headers=encabezados)
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return respuesta.status, respuesta.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except Exception as exc:  # red caida, timeout, DNS...
        logger.warning("Respaldos %s fallo: %s", method, exc)
        return 0, b""


def _json_publicado() -> dict:
    """El JSON del archivo remoto tal como esta en GitHub (o {})."""
    codigo, cuerpo = _http("GET", accept="application/json")
    if codigo == 200:
        try:
            return json.loads(cuerpo)
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------- helpers ----


def _bd_tiene_datos(ruta: Path) -> bool:
    """¿La BD tiene talleres? Archivo borrado / corrupto / 0 talleres = sin datos."""
    if not ruta.exists():
        return False
    try:
        con = sqlite3.connect(ruta)
        try:
            return con.execute("SELECT COUNT(*) FROM talleres").fetchone()[0] > 0
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False  # archivo corrupto o sin esquema: no hay datos utiles


# ---------------------------------------------------------------- put ----


def _cuerpo_subida(bd_bytes: bytes, sha: str | None) -> str:
    return json.dumps({
        "message": f"respaldo automatico {time.strftime('%Y-%m-%d %H:%M')}",
        "branch": "main",
        "sha": sha,
        "content": base64.b64encode(bd_bytes).decode("ascii"),
    })


def _subir(bd_bytes: bytes, sha: str | None) -> bool:
    """PUT del archivo. True si GitHub lo acepto."""
    codigo, cuerpo = _http("PUT", datos=_cuerpo_subida(bd_bytes, sha))
    if codigo in (200, 201):
        return True
    logger.warning("Respaldos: subir fallo (HTTP %s) %s", codigo, cuerpo[:200])
    return False


def respaldar_ahora(ruta_bd: Path | None = None) -> bool:
    """Sube la BD actual al repo. False si no hay config o fallo.

    PROTECCION: nunca sube una BD sin talleres — evita que un deploy con la
    BD fresca machaque el respaldo anterior si la restauracion fallo.
    """
    if not disponible():
        return False
    ruta = Path(ruta_bd or db.DB_PATH)
    if not _bd_tiene_datos(ruta):
        logger.info("Respaldos: BD sin talleres; no subo (protejo el respaldo previo)")
        return False
    sha = _json_publicado().get("sha")  # None = primeras subida (archivo nuevo)
    return _subir(Path(ruta).read_bytes(), sha)


# ---------------------------------------------------------------- get ----


def restaurar_si_hace_falta(ruta_bd: Path | None = None) -> bool:
    """Descarga el respaldo si la BD local NO tiene datos (falta, vacia o rota).

    True = restauro. La BD default que init_db crea vacia TAMBIEN se
    reemplaza: los datos no viven en el disco de Render (free).
    """
    if not disponible():
        return False
    ruta = Path(ruta_bd or db.DB_PATH)
    if _bd_tiene_datos(ruta):
        return False  # BD local con datos vivos: nada que restaurar
    codigo, cuerpo = _http("GET", accept="application/vnd.github.raw")
    if codigo != 200 or not cuerpo:
        logger.warning("Respaldos: no hay respaldo disponible (HTTP %s)", codigo)
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(cuerpo)
    logger.info("Respaldos: BD restaurada desde GitHub (%s bytes)", len(cuerpo))
    return True


# ---------------------------------------------------------------- loop ----


def bucle(intervalo_min: int | None = None, ruta_bd: Path | None = None) -> None:
    """Lazo para un hilo daemon: respaldo periodico. Idealmente nunca lanza."""
    cada = (intervalo_min or minutos()) * 60
    ruta = ruta_bd or db.DB_PATH
    # primer respaldo rapido tras arrancar
    time.sleep(20)
    while True:
        try:
            if respaldar_ahora(ruta):
                logger.info("Respaldos: BD subida a GitHub")
        except Exception as exc:  # jamas debe tumbar el hilo del bot
            logger.warning("Respaldos: error inesperado: %s", exc)
        time.sleep(cada)
