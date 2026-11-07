"""Bot del taller - Sprint 6: MULTI-TENANT.

Varios talleres conviven en un solo bot. Cada taller tiene dueno(s) y
mecanicos, gestionados desde el propio chat:

- /nuevotaller crea tu taller y quedas como su dueno.
- /invitar mecanico|dueno genera el link de invitacion.
- El candidato abre el link, pide unirse y el dueno acepta via botones.
- Todo lo demas (/historialdia, /ganancias...) muestra SOLO los datos
  del taller del usuario y respeta el rol.
"""
import csv
import io
import logging
import os
import threading
from datetime import datetime
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
import factura
import respaldo
import roles
from parser import (
    MOTIVO_DESCRIPCION,
    MOTIVO_PLACA,
    MOTIVO_PRECIO,
    MOTIVO_VACIO,
    MOTIVO_VARIAS_PLACAS,
    ParserError,
    parse,
)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Códigos de venta (Sprint 8): CATÁLOGO en el .env, ESTADO de uso en la BD.
# Cada código permite crear UN solo taller. Sepáralos por coma en el .env.
CODIGOS_TALLER: set[str] = {
    trozo.strip().upper()
    for trozo in os.getenv("CODIGOS_TALLER", "").split(",")
    if trozo.strip()
}


def _estado_codigo(codigo: str) -> str:
    """'ok' | 'invalido' | 'usado' — lógica de venta separada para poder probarla."""
    codigo = (codigo or "").strip().upper()
    if codigo not in CODIGOS_TALLER:
        return "invalido"
    if db.codigo_ya_redimido(codigo):
        return "usado"
    return "ok"

# ── Logs: consola + archivo rotativo ────────────────────────────────────
FORMATO_LOG = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
manejador_consola = logging.StreamHandler()
manejador_consola.setFormatter(logging.Formatter(FORMATO_LOG))
manejador_archivo = RotatingFileHandler(
    "taller-bot.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
)
manejador_archivo.setFormatter(logging.Formatter(FORMATO_LOG))
logging.basicConfig(
    format=FORMATO_LOG, level=logging.INFO,
    handlers=[manejador_consola, manejador_archivo],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("taller-bot")

# ── Cloud (Sprint 4 - Render) ───────────────────────────────────────────
# Render free: el servicio debe responder HTTP en su $PORT (si no, lo mata).
class _Salud(BaseHTTPRequestHandler):
    """GET /salud -> 200. Solo existe si la nube define PORT (local: nada)."""

    def do_GET(self) -> None:  # noqa: N802 (codigo del stdlib, no cambiar)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"tallerbot vivo")

    def log_message(self, *args) -> None:  # silencio: no embotella el log real
        pass


def _levantar_servidor_salud() -> None:
    puerto = int(os.getenv("PORT", "0"))
    if not puerto:
        return  # PC local / VM: no nube, no servidor de salud
    servidor = HTTPServer(("0.0.0.0", puerto), _Salud)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    logger.info("Servidor de salud en puerto %s (Render)", puerto)

EJEMPLO = "<code>ABC123 cambio de aceite 45000</code>"
MENSAJES_DE_ERROR = {
    MOTIVO_VACIO: "Escríbeme algo 👀",
    MOTIVO_PLACA: f"No vi la placa 🤔\nEj: {EJEMPLO}",
    MOTIVO_PRECIO: f"Falta el precio 🤔\nEj: {EJEMPLO}",
    MOTIVO_DESCRIPCION: f"Falta el trabajo 🤔\nEj: {EJEMPLO}",
    MOTIVO_VARIAS_PLACAS: f"Vi varias placas 🤔 déjame solo una.\nEj: {EJEMPLO}",
}


# ── Helpers de formato ──────────────────────────────────────────────────


def formatear_dinero(valor: float) -> str:
    """45000.0 -> '$ 45.000' (estilo Colombia)."""
    return f"$ {valor:,.0f}".replace(",", ".")


def formatear_fecha(mensaje_dt: datetime) -> str:
    return mensaje_dt.strftime("%d/%m/%Y %I:%M %p").lower()


async def responder(update: Update, texto: str, **extra) -> None:
    """ÚNICO canal de respuestas: SIEMPRE formato HTML."""
    await update.message.reply_text(texto, parse_mode="HTML", **extra)


def protegido(func):
    """Solo deja pasar a usuarios activos de algún taller (S3-1/S6)."""

    @wraps(func)
    async def envoltura(update, context, *args, **kwargs):
        usuario = update.effective_user.id if update.effective_user else None
        if not roles.es_autorizado(usuario):
            logger.warning("Acceso denegado: id=%s", usuario)
            return
        return await func(update, context, *args, **kwargs)

    return envoltura


def _linea_trabajo(fila, con_mecanico: bool = False) -> str:
    hora = datetime.fromisoformat(fila["fecha_hora"]).strftime("%I:%M %p").lower()
    mecanico = f" · {fila['mecanico'] or 'sin firmar'}" if con_mecanico else ""
    return (
        f"#{fila['id']} {hora} · <b>{fila['placa']}</b> · "
        f"{fila['descripcion']} · {formatear_dinero(fila['precio'])}{mecanico}"
    )


def _perfil(update: Update):
    """El perfil (taller_id, rol, nombre) del usuario que escribe."""
    return roles.perfil(update.effective_user.id)


# ── Onboarding multi-taller (comandos públicos) ─────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start normal, o con payload del deep link (?start=CODIGO)."""
    user = update.effective_user
    if context.args:
        await _procesar_link_invitacion(update, context, context.args[0])
        return
    perfil_usuario = roles.perfil(user.id)
    if perfil_usuario is None:
        await responder(
            update,
            "👋 Hola! Este bot es para talleres registrados.\n\n"
            "Si te invitaron a un taller, usa el link que te mandó tu dueño.\n"
            "Si quieres montar TU taller, necesitas un código del desarrollador:\n"
            "<code>/nuevotaller CODIGO NombreDelTaller</code>",
        )
        return
    nombre_taller = db.obtener_taller(perfil_usuario["taller_id"])["nombre"]
    await responder(
        update,
        f"🛠️ <b>{nombre_taller}</b> — hola {user.first_name}!\n"
        "Registra cada trabajo así: placa + trabajo + precio:\n"
        f"{EJEMPLO}\n/ayuda → todos los comandos",
    )


async def _procesar_link_invitacion(
    update: Update, context: ContextTypes.DEFAULT_TYPE, codigo: str
) -> None:
    """Abrió un link de invitación. Pública a propósito (no pertenecía antes)."""
    user = update.effective_user
    invitacion = db.invitacion_por_codigo(codigo)
    if invitacion is None or not invitacion["activa"]:
        await responder(update, "🔗 Este link ya no está vigente (caducó o fue revocado).")
        return
    perfil_usuario = roles.perfil(user.id)
    if perfil_usuario is not None:
        if perfil_usuario["taller_id"] == invitacion["taller_id"]:
            await responder(update, "🤗 Ya estás en este taller.")
        else:
            await responder(
                update,
                "🤔 Ya perteneces a otro taller.\n"
                "Para cambiarte, tienes que ser desvinculado del actual y volver a abrir el link.",
            )
        return
    taller = db.obtener_taller(invitacion["taller_id"])
    solicitud_id = db.crear_solicitud(
        codigo, user.id, user.full_name or user.first_name
    )
    if solicitud_id is None:
        await responder(update, "📨 Tu solicitud ya está en cola, esperando al dueño.")
        return
    await responder(
        update,
        f"🤝 Unirme a <b>{taller['nombre']}</b> como <b>{invitacion['rol']}</b>?\n"
        "La solicitud le va a llegar al dueño para que la acepte:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🤝 Solicitar unirme", callback_data=f"soli:{solicitud_id}")
        ]]),
    )
    logger.info("Solicitud #%s del user %s para invitación %s",
                solicitud_id, user.id, codigo)


async def nuevotaller(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/nuevotaller CODIGO [nombre] — crea el taller SOLO con código de venta (S8)."""
    user = update.effective_user
    perfil_usuario = roles.perfil(user.id)
    if perfil_usuario is not None:
        taller_actual = db.obtener_taller(perfil_usuario["taller_id"])
        await responder(
            update,
            f"🤔 Ya perteneces al taller <b>{taller_actual['nombre']}</b>.\n"
            "Si quieres otro taller, primero el dueño de ese te tiene que desvincular.",
        )
        return
    if not context.args:
        await responder(
            update,
            "🔒 Para usar el bot necesitas un <b>código de acceso</b> que te da el "
            "desarrollador del bot:\n\n"
            "<code>/nuevotaller CODIGO NombreDelTaller</code>\n\n"
            "Ejemplo: <code>/nuevotaller VENTA-PEDRO-2026 Taller Pedro Motores</code>",
        )
        return
    codigo = context.args[0].strip().upper()
    estado = _estado_codigo(codigo)
    if estado == "invalido":
        logger.warning("Código inválido: %r intento de %s", codigo, user.id)
        await responder(
            update,
            "❌ Ese código no es válido.\n"
            "Pídeselo al desarrollador del bot (es una palabra tipo "
            "VENTA-NOMBRE-2026) y vuelve a intentar.",
        )
        return
    if estado == "usado":
        await responder(
            update,
            "🚫 Ese código ya fue utilizado (son de un solo uso). "
            "Pide otro al desarrollador.",
        )
        return
    nombre = " ".join(context.args[1:]).strip() or f"Taller {user.first_name}"
    taller_id = db.crear_taller(nombre, user.id, user.full_name or user.first_name)
    redimido = db.redimir_codigo(codigo, taller_id, user.id)
    if not redimido:  # carrera rara: alguien lo quemó a la vez
        logger.warning("Código %s se quemó de lado al crear taller %s", codigo, taller_id)
    logger.info("Taller #%s '%s' creado por %s (código %s)",
                taller_id, nombre, user.id, codigo)
    await responder(
        update,
        f"🎉 <b>{nombre}</b> listo y ERES su dueño!\n\n"
        "Invita a tu gente:\n"
        "🔧 <code>/invitar mecanico</code>\n"
        "👑 <code>/invitar dueno</code>\n\n"
        "Y para registrar: placa + trabajo + precio\n"
        f"{EJEMPLO}",
    )


# ── Invitaciones y personal ─────────────────────────────────────────────


@protegido
async def invitar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/invitar mecanico|dueno -> link para compartir (S6-3)."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    rol = (context.args[0].strip().lower() if context.args else "")
    if rol not in (db.ROL_MECANICO, db.ROL_DUENO):
        await responder(
            update,
            "Indica el rol:\n<code>/invitar mecanico</code>\n<code>/invitar dueno</code>",
        )
        return
    taller_id = roles.taller_de(user.id)
    codigo = db.crear_invitacion(taller_id, rol, user.id)
    await responder(
        update,
        f"🔗 <b>Link de invitación</b> (rol: <b>{rol}</b>):\n\n"
        f"https://t.me/{context.bot.username}?start={codigo}\n\n"
        "Comparte ese link. Cuando abran el chat y toquen <b>🤝 Solicitar unirme</b>, "
        "te llega la solicitud para aceptar o rechazar.\n"
        "¿Ya no lo necesitas? <code>/revocar " + codigo + "</code>",
    )
    logger.info("Invitación %s (rol=%s) creada por %s", codigo, rol, user.id)


async def procesar_solicitud(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """El candidato toca '🤝 Solicitar unirme' → la pide al dueño (público)."""
    query = update.callback_query
    _, solicitud_id = query.data.split(":")
    solicitud = db.solicitud_por_id(int(solicitud_id))
    if solicitud is None or solicitud["estado"] != "pendiente":
        await query.answer("Solicitud ya procesada 👀", show_alert=True)
        return
    invitacion = db.invitacion_por_codigo(solicitud["codigo"])
    if invitacion is None or not invitacion["activa"]:
        await query.answer("Invitación no vigente 👀", show_alert=True)
        return
    nombre_taller = db.obtener_taller(invitacion["taller_id"])["nombre"]
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✅ Aceptar como {invitacion['rol']}",
            callback_data=f"inv_si:{invitacion['codigo']}:{solicitud_id}",
        ),
        InlineKeyboardButton(
            "❌ Rechazar",
            callback_data=f"inv_no:{invitacion['codigo']}:{solicitud_id}",
        ),
    ]])
    try:
        await context.bot.send_message(
            chat_id=invitacion["creada_por"],
            text=(
                f"🙋 <b>{solicitud['nombre']}</b> (ID {solicitud['user_id']}) "
                f"quiere unirse a <b>{nombre_taller}</b> como <b>{invitacion['rol']}</b>."
            ),
            reply_markup=teclado,
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("No pude avisar al dueno %s", invitacion["creada_por"])
        await query.edit_message_text("⚠️ No pude avisarle al dueño.")
        await query.answer()
        return
    await query.edit_message_text("📨 Solicitud enviada. Te contestamos aquí mismo.")
    await query.answer()


async def decidir_solicitud(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """El dueño toca ✅/❌ en la tarjeta de solicitud."""
    query = update.callback_query
    accion, codigo, solicitud_id = query.data.split(":")
    invitacion = db.invitacion_por_codigo(codigo)
    if invitacion is None or query.from_user.id != invitacion["creada_por"]:
        await query.answer("🤷 Solo quien generó el link puede decidir.", show_alert=True)
        return
    solicitud = db.solicitud_por_id(int(solicitud_id))
    if solicitud is None or solicitud["estado"] != "pendiente":
        await query.answer("Solicitud ya procesada 👀", show_alert=True)
        return
    if accion == "inv_si":
        db.agregar_usuario(
            solicitud["user_id"], invitacion["taller_id"],
            solicitud["nombre"], invitacion["rol"],
        )
        db.decidir_solicitud(solicitud["id"], True)
        nombre_taller = db.obtener_taller(invitacion["taller_id"])["nombre"]
        await query.edit_message_text(
            f"✅ <b>{solicitud['nombre']}</b> ahora es <b>{invitacion['rol']}</b> "
            f"de <b>{nombre_taller}</b>.",
            parse_mode="HTML",
        )
        try:
            await context.bot.send_message(
                solicitud["user_id"],
                f"🎉 ¡Bienvenido a <b>{nombre_taller}</b> como <b>{invitacion['rol']}</b>!\n"
                f"Registra: {EJEMPLO}",
                parse_mode="HTML",
            )
        except Exception:
            logger.warning("No pude saludar al user %s", solicitud["user_id"])
    else:
        db.decidir_solicitud(solicitud["id"], False)
        await query.edit_message_text("❌ Solicitud rechazada.")
        try:
            await context.bot.send_message(
                solicitud["user_id"], "❌ Tu solicitud fue rechazada."
            )
        except Exception:
            pass
    logger.info("Solicitud #%s %s por %s", solicitud["id"], accion, query.from_user.id)
    await query.answer()


@protegido
async def personal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/personal — lista del staff del propio taller (dueño)."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    personal_fila = db.personal_del_taller(roles.taller_de(user.id))
    dueños, mecanicos = [], []
    for fila in personal_fila:
        if not fila["activo"]:
            continue
        linea = f"▸ {fila['nombre']} (ID {fila['user_id']})"
        (dueños if fila["rol"] == db.ROL_DUENO else mecanicos).append(linea)
    texto = "👥 <b>Personal del taller</b>\n👑 Dueños:\n" + "\n".join(dueños)
    if mecanicos:
        texto += "\n🔧 Mecánicos:\n" + "\n".join(mecanicos)
    texto += (
        "\n\nManejo:\n"
        "<code>/rol ID mecanico|dueno</code>\n"
        "<code>/expulsar ID</code>\n"
        "<code>/invitar mecanico|dueno</code>"
    )
    await responder(update, texto)


@protegido
async def cambiar_rol_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rol ID mecanico|dueno — cambia el rol si es del mismo taller."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    if len(context.args) != 2 or not context.args[0].isdigit():
        await responder(update, "Así: <code>/rol 123456 mecanico</code>")
        return
    objetivo, rol = int(context.args[0]), context.args[1].lower()
    if rol not in (db.ROL_MECANICO, db.ROL_DUENO):
        await responder(update, "Roles válidos: mecanico o dueno.")
        return
    perfil_objetivo = roles.perfil(objetivo)
    if perfil_objetivo is None or perfil_objetivo["taller_id"] != roles.taller_de(user.id):
        await responder(update, f"No encontré a {objetivo} en este taller 🤷")
        return
    db.cambiar_rol(objetivo, rol, roles.taller_de(user.id))
    await responder(
        update,
        f"✅ {perfil_objetivo['nombre']} ahora es <b>{rol}</b>.",
    )
    logger.info("Rol de %s -> %s por %s", objetivo, rol, user.id)


@protegido
async def expulsar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/expulsar ID — desvincula al usuario del taller (puede volver con link)."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    if not context.args or not context.args[0].isdigit():
        await responder(update, "Así: <code>/expulsar 123456</code>")
        return
    objetivo = int(context.args[0])
    if objetivo == user.id:
        await responder(update, "🤔 No te puedes expulsar a ti mismo.")
        return
    perfil_objetivo = roles.perfil(objetivo)
    if perfil_objetivo is None or perfil_objetivo["taller_id"] != roles.taller_de(user.id):
        await responder(update, f"No encontré a {objetivo} en este taller 🤷")
        return
    db.expulsar_usuario(objetivo, roles.taller_de(user.id))
    await responder(update, f"🚪 {perfil_objetivo['nombre']} quedó desvinculado.")
    try:
        await context.bot.send_message(
            objetivo, "🚪 Fuiste desvinculado del taller."
        )
    except Exception:
        pass
    logger.info("Expulsado %s por %s", objetivo, user.id)


@protegido
async def revocar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/revocar CODIGO — mata un link de invitación."""
    if not roles.es_dueno(update.effective_user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    if not context.args:
        await responder(update, "Así: <code>/revocar CODIGO</code>")
        return
    revocado = db.revocar_invitacion(
        context.args[0].strip(), roles.taller_de(update.effective_user.id)
    )
    await responder(
        update,
        "🗑️ Link revocado." if revocado else "No encontré ese link 🤷",
    )


@protegido
async def datostaller(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/datostaller nombre=X nit=Y — datos del encabezado de la factura (S7)."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    taller_id = roles.taller_de(user.id)
    if not context.args:
        fila_taller = db.obtener_taller(taller_id)
        pendiente = [
            campo for campo in ("nit", "direccion", "telefono")
            if not fila_taller[campo]
        ]
        await responder(
            update,
            "🏢 <b>Datos del taller</b>\n"
            f"▸ Nombre: {fila_taller['nombre']}\n"
            f"▸ NIT: {fila_taller['nit'] or '—'}\n"
            f"▸ Dirección: {fila_taller['direccion'] or '—'}\n"
            f"▸ Teléfono: {fila_taller['telefono'] or '—'}\n"
            f"▸ Logo: {'🖼️' if fila_taller['logo'] else 'sin subir (manda una foto con /logo en el pie de foto)'}\n\n"
            "Editar (los valores admiten espacios):\n"
            "<code>/datostaller nombre=Taller Los Pistones</code>\n"
            "<code>/datostaller nit=900123-4 tel=3001112333 dir=Calle 45 #12-30</code>"
            + (f"\n\nFaltan: {', '.join(pendiente)}" if pendiente else ""),
        )
        return
    campos = _parsear_pares(context.args)
    sin_validar = campos.pop("tel", None)
    if sin_validar:  # alias amigable
        campos["telefono"] = sin_validar
    sin_validar = campos.pop("dir", None)
    if sin_validar:
        campos["direccion"] = sin_validar
    db.guardar_datos_taller(taller_id, campos)
    await responder(update, "✅ Datos guardados. Úsalos en la próxima factura 🧾")
    logger.info("Datos taller #%s actualizados por %s: %s",
                taller_id, user.id, list(campos))


def _parsear_pares(tokens: list[str]) -> dict[str, str]:
    """conj天涯ere ['nit=900123-4', 'dir...', 'Calle', '45'] -> {'nit': ..., 'dir': ...}
    Cada clave termina cuando aparece la siguiente con '='."""
    pares: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        if "=" not in tokens[i]:
            i += 1
            continue
        clave, valor = tokens[i].split("=", 1)
        i += 1
        extras = []
        while i < len(tokens) and "=" not in tokens[i]:
            extras.append(tokens[i])
            i += 1
        if extras:
            valor = " ".join([valor] + extras)
        if clave and valor.strip():
            pares[clave.strip().lower()] = valor.strip()
    return pares


@protegido
async def logo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/logo (con foto adjunta): guarda el logo del taller para el PDF (S7)."""
    user = update.effective_user
    if not roles.es_dueno(user.id):
        await responder(update, "🙅 Esto solo lo puede hacer un dueño.")
        return
    if not update.message.photo:
        await responder(
            update,
            "🖼️ Sube la imagen del logo y escribe /logo en el texto adjunto "
            "(caption) de la foto.",
        )
        return
    taller_id = roles.taller_de(user.id)
    Carpeta = "logos"
    os.makedirs(Carpeta, exist_ok=True)
    ruta = f"{Carpeta}/taller_{taller_id}.jpg"
    archivo = await update.message.photo[-1].get_file()
    contenido = await archivo.download_as_bytearray()
    with open(ruta, "wb") as flujo:
        flujo.write(contenido)
    db.guardar_logo(taller_id, ruta)
    await responder(update, "🖼️ Logo guardado. Se usará al tope de las facturas 🧾")
    logger.info("Logo del taller #%s guardado", taller_id)


@protegido
async def factura_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/factura PLACA — PDF con los trabajos de HOY de esa placa (S7)."""
    if not context.args:
        await responder(update, "Dime la placa 🤔\nEj: <code>/factura ABC123</code>")
        return
    placa = context.args[0].upper()
    perfil_usuario = _perfil(update)
    es_dueno = roles.es_dueno(update.effective_user.id)
    taller_id = perfil_usuario["taller_id"]
    filas_de_hoy = db.trabajos_hoy(
        taller_id,
        None if es_dueno else update.effective_user.id,
    )
    filas = [f for f in filas_de_hoy if f["placa"] == placa]
    if not filas:
        quien = (
            "sin facturación hoy para esa placa." if es_dueno
            else "sin trabajos tuyos hoy para esa placa."
        )
        await responder(
            update,
            f"🚘 No hay trabajos de hoy de <b>{placa}</b> — {quien}",
        )
        return
    fila_taller = db.obtener_taller(taller_id)
    contenido_pdf = factura.generar_pdf(
        nombre_taller=fila_taller["nombre"],
        nit=fila_taller["nit"],
        telefono=fila_taller["telefono"],
        direccion=fila_taller["direccion"],
        logo=fila_taller["logo"],
        placa=placa,
        items=filas,
    )
    fecha_doc = datetime.now().strftime("%Y-%m-%d")
    await update.message.reply_document(
        document=contenido_pdf,
        filename=f"factura_{placa}_{fecha_doc}.pdf",
        caption=(
            f"🧾 Factura simple de <b>{placa}</b> — {len(filas)} trabajo(s) · "
            f"{formatear_dinero(sum(f['precio'] for f in filas))} · (no fiscal)"
        ),
    )
    logger.info("Factura %s con %s items (taller %s)", placa, len(filas), taller_id)


# ── Comandos del día a día (verificados por taller y rol) ───────────────


@protegido
async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await responder(
        update,
        "🛠️ <b>Comandos</b>\n"
        f"📋 Registro: {EJEMPLO}\n"
        "🌅 /historialdia — trabajos de hoy\n"
        "📊 /ganancias [7 | mes] — resumen\n"
        "🙋 /misganancias — solo lo tuyo\n"
        "🔍 /buscar PLACA — historial de un vehículo\n"
        "🗑️ /borrar # — anular un registro\n"
        "📄 /exportar [7 | mes] — CSV (solo dueño)\n"
        "🧾 /factura PLACA — factura simple en PDF\n"
        "🏢 /datostaller — datos del taller (dueño)\n"
        "🖼️ /logo — sube el logo (foto adjunta, dueño)\n"
        "👥 /personal — staff (solo dueño)\n"
        "ℹ️ /ayuda",
    )


@protegido
async def historialdia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dueño: todos con nombre. Mecánico: solo los suyos."""
    perfil_usuario = _perfil(update)
    es_dueno = roles.es_dueno(update.effective_user.id)
    filas = db.trabajos_hoy(
        perfil_usuario["taller_id"],
        None if es_dueno else update.effective_user.id,
    )
    if not filas:
        await responder(update, "😌 Sin trabajos registrados hoy.")
        return
    total = sum(fila["precio"] for fila in filas)
    lista = "\n".join(_linea_trabajo(f, con_mecanico=es_dueno) for f in filas)
    titulo = "Trabajos de hoy" if es_dueno else "Tus trabajos de hoy"
    await responder(
        update,
        f"🌅 <b>{titulo}</b>\n{lista}\n\n"
        f"💰 <b>Total{' del día' if es_dueno else ''}: {formatear_dinero(total)}</b>"
        f" ({len(filas)} trabajo{'s' if len(filas) != 1 else ''})",
    )


@protegido
async def ganancias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reporte_ganancias(update, context, solo_propias=False)


@protegido
async def misganancias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reporte_ganancias(update, context, solo_propias=True)


async def _reporte_ganancias(
    update: Update, context: ContextTypes.DEFAULT_TYPE, solo_propias: bool
) -> None:
    arg = context.args[0].lower() if context.args else ""
    dias = None
    mes = False
    if arg == "mes":
        mes = True
    elif arg.isdigit() and 1 <= int(arg) <= 365:
        dias = int(arg)
    elif arg not in ("", "hoy", "dia"):
        await responder(
            update,
            "Periodo: <code>/ganancias</code> hoy · <code>/ganancias 7</code> · "
            "<code>/ganancias mes</code>",
        )
        return
    perfil_usuario = _perfil(update)
    taller_id = perfil_usuario["taller_id"]
    ver_todos = roles.es_dueno(update.effective_user.id) and not solo_propias

    if ver_todos:
        etiqueta, cantidad, suma = db.resumen_periodo(taller_id, dias=dias, mes=mes)
        texto = f"💼 <b>Ganancias de {etiqueta}</b>\n💰 <b>{formatear_dinero(suma)}</b>"
        _, desglose = db.desglose_mecanicos(taller_id, dias=dias, mes=mes)
        if desglose:
            lineas = "\n".join(
                f"👤 {nombre}: {formatear_dinero(suma_monto)} ({cantidad_personas})"
                for nombre, cantidad_personas, suma_monto in desglose
            )
            texto += f"\n\n<b>Por mecánico</b>:\n{lineas}"
        elif cantidad == 0:
            texto = f"😌 Sin trabajos en {etiqueta}."
    else:
        etiqueta, cantidad, suma = db.resumen_periodo(
            taller_id, dias=dias, mes=mes, mecanico_id=update.effective_user.id
        )
        if cantidad == 0:
            await responder(update, f"😌 Sin trabajos tuyos en {etiqueta}.")
            return
        texto = (
            f"💼 <b>Tus ganancias de {etiqueta}</b>\n"
            f"💰 <b>{formatear_dinero(suma)}</b>\n"
            f"📋 {cantidad} trabajo{'s' if cantidad != 1 else ''}"
        )
    await responder(update, texto)


@protegido
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dueño: historial completo. Mecánico: solo sus registros."""
    if not context.args:
        await responder(update, "Dime la placa 🤔\nEj: <code>/buscar ABC123</code>")
        return
    placa = context.args[0].upper()
    perfil_usuario = _perfil(update)
    es_dueno = roles.es_dueno(update.effective_user.id)
    filas, cantidad, suma = (
        db.historial_placa(placa, perfil_usuario["taller_id"])
        if es_dueno
        else db.historial_placa(placa, perfil_usuario["taller_id"],
                                usuario_id=update.effective_user.id)
    )
    if cantidad == 0:
        await responder(
            update,
            f"🚘 Sin trabajos para <b>{placa}</b>" + ("" if es_dueno else " tuyos") + ".",
        )
        return
    lista = "\n".join(_linea_trabajo(f, con_mecanico=es_dueno) for f in filas)
    nota = f"\n…(+{cantidad - len(filas)} más antiguos)" if cantidad > len(filas) else ""
    titulo = f"<b>{placa}</b>" if es_dueno else f"<b>{placa}</b> (tus registros)"
    await responder(
        update,
        f"🚘 {titulo} — {cantidad} trabajo{'s' if cantidad != 1 else ''}\n"
        f"{lista}{nota}\n\n💵 <b>Total: {formatear_dinero(suma)}</b>",
    )


@protegido
async def borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await responder(update, "Número 🤔 Ej: <code>/borrar 5</code>")
        return
    trabajo_id = int(context.args[0])
    taller_id = _perfil(update)["taller_id"]
    fila = db.trabajo_por_id(trabajo_id)
    if fila is None or fila["anulado"] or fila["taller_id"] != taller_id:
        await responder(update, f"No existe el trabajo #{trabajo_id} 🤷")
        return
    usuario_id = update.effective_user.id
    if not roles.es_dueno(usuario_id) and fila["usuario_id"] != usuario_id:
        await responder(update, "🙅 Solo puedes borrar tus propios trabajos.")
        return
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑️ Sí, borrar", callback_data=f"borrar_si:{trabajo_id}"),
        InlineKeyboardButton("❌ No", callback_data=f"borrar_no:{trabajo_id}"),
    ]])
    await responder(
        update,
        f"¿Borrar? {_linea_trabajo(fila)}",
        reply_markup=teclado,
    )


@protegido
async def confirmar_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    accion, trabajo_id = query.data.split(":")
    taller_id = roles.taller_de(query.from_user.id) or 0
    fila = db.trabajo_por_id(int(trabajo_id))
    puede = fila is not None and (
        fila["taller_id"] == taller_id
        and (roles.es_dueno(query.from_user.id)
             or fila["usuario_id"] == query.from_user.id)
    )
    if not puede:
        await query.answer("No tuyo 👀", show_alert=True)
        return
    if accion == "borrar_si":
        anulado = db.anular_trabajo(int(trabajo_id), taller_id)
        await query.edit_message_text(
            f"🗑️ #{trabajo_id} anulado." if anulado else f"#{trabajo_id} ya estaba anulado 🤷"
        )
        logger.info("Anulado #%s por %s", trabajo_id, query.from_user.id)
    else:
        await query.edit_message_text("😌 Quedó guardado.")
    await query.answer()


@protegido
async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    comando = (update.message.text or "/?").split()[0]
    await responder(update, f"No reconozco <code>{comando}</code> 🤔\nPrueba /ayuda")


@protegido
async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda el trabajo firmado y ligado al taller del usuario (S5-2/S6)."""
    try:
        resultado = parse(update.message.text)
    except ParserError as error:
        await responder(update, MENSAJES_DE_ERROR.get(error.motivo, "🤔"))
        return
    perfil_usuario = _perfil(update)
    firma = perfil_usuario["nombre"] or update.effective_user.first_name
    trabajo_id = db.agregar_trabajo(
        placa=resultado.placa,
        descripcion=resultado.descripcion,
        precio=resultado.precio,
        chat_id=update.effective_chat.id,
        taller_id=perfil_usuario["taller_id"],
        usuario_id=update.effective_user.id,
        mecanico=firma,
    )
    await responder(
        update,
        f"✅ <b>#{trabajo_id}</b> · <b>{resultado.placa}</b>\n"
        f"🔧 {resultado.descripcion}\n"
        f"💰 {formatear_dinero(resultado.precio)}\n"
        f"👤 {firma} · {formatear_fecha(datetime.now())}",
    )
    logger.info("Trabajo #%s: %s %s %.0f (por %s)", trabajo_id,
                resultado.placa, resultado.descripcion, resultado.precio, firma)


@protegido
async def exportar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """CSV del taller del usuario. Solo dueño (S5-5)."""
    if not roles.es_dueno(update.effective_user.id):
        await responder(update, "🙅 Esto solo lo puede hacer el dueño.")
        return
    arg = context.args[0].lower() if context.args else "mes"
    dias = None
    mes = True
    if arg.isdigit() and 1 <= int(arg) <= 365:
        dias, mes = int(arg), False
    elif arg == "hoy":
        dias, mes = None, False
    elif arg != "mes":
        await responder(
            update,
            "Periodo: <code>/exportar</code> (mes) · <code>/exportar 7</code> · "
            "<code>/exportar hoy</code>",
        )
        return
    taller_id = _perfil(update)["taller_id"]
    inicio, fin, etiqueta = db.rango_periodo(dias, mes)
    filas = db._trabajos_entre(inicio, fin, taller_id)
    if not filas:
        await responder(update, f"😌 Sin datos en {etiqueta}.")
        return
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(["id", "fecha", "hora", "placa", "trabajo", "precio", "mecanico"])
    for fila in filas:
        fecha_hora = datetime.fromisoformat(fila["fecha_hora"])
        escritor.writerow([
            fila["id"],
            fecha_hora.strftime("%Y-%m-%d"),
            fecha_hora.strftime("%H:%M"),
            fila["placa"],
            fila["descripcion"],
            int(fila["precio"]),
            fila["mecanico"] or "sin firmar",
        ])
    contenido = b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")  # BOM para Excel
    await update.message.reply_document(
        document=contenido,
        filename=f"taller_{inicio}_a_{fin}.csv",
        caption=f"📄 {etiqueta} — {len(filas)} trabajos",
    )


async def error_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Última linea de defensa: ningún handler tumba al bot (S3-2)."""
    logger.exception("Error no manejado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "😅 Algo salió mal de mi lado, intenta de nuevo."
            )
        except Exception:
            logger.exception("No pude avisar el error en el chat")


def _roles_antiguos() -> dict[int, str]:
    """Roles legados del .env (solo se leen UNA ves para migrar a la BD)."""
    salida: dict[int, str] = {}
    for texto, defecto in (
        (os.getenv("ADMIN_IDS", ""), "Dueño"),
        (os.getenv("MECHANICS", ""), "Mecánico"),
    ):
        for item in texto.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                id_texto, nombre = item.split(":", 1)
                salida[int(id_texto)] = nombre.strip() or defecto
            else:
                salida[int(item)] = defecto
    return salida


def main() -> None:
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "aqui_va_el_token":
        raise SystemExit("Falta el token en el .env (TELEGRAM_TOKEN).")
    db.init_db(duenos_antiguos=_roles_antiguos())  # migra si es necesario
    with db.conectar() as conn:
        n_talleres = conn.execute("SELECT COUNT(*) FROM talleres").fetchone()[0]
        n_usuarios = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE activo = 1"
        ).fetchone()[0]
    logger.info("Talleres: %s | usuarios activos: %s", n_talleres, n_usuarios)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers públicos (onboarding) SIEMPRE primero
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("nuevotaller", nuevotaller))
    # Gestión de personal
    app.add_handler(CommandHandler("invitar", invitar))
    app.add_handler(CommandHandler("personal", personal))
    app.add_handler(CommandHandler("rol", cambiar_rol_cmd))
    app.add_handler(CommandHandler("expulsar", expulsar_cmd))
    app.add_handler(CommandHandler("revocar", revocar_cmd))
    # Día a día
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("historialdia", historialdia))
    app.add_handler(CommandHandler(["ganancias", "ganancia"], ganancias))
    app.add_handler(CommandHandler("misganancias", misganancias))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("borrar", borrar))
    app.add_handler(CommandHandler("exportar", exportar))
    app.add_handler(CommandHandler("factura", factura_cmd))
    app.add_handler(CommandHandler("datostaller", datostaller))
    app.add_handler(CommandHandler("logo", logo))
    # La foto adjunta con caption /logo también dispara el guardado del logo
    app.add_handler(MessageHandler(filters.PHOTO, logo))
    # Callbacks de invitaciones (con verificación interna) y de borrado
    app.add_handler(CallbackQueryHandler(procesar_solicitud, pattern=r"^soli:"))
    app.add_handler(CallbackQueryHandler(decidir_solicitud, pattern=r"^inv_(si|no):"))
    app.add_handler(CallbackQueryHandler(confirmar_borrar, pattern=r"^borrar_(si|no):"))
    # Cualquier otro comando → siempre responde algo
    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))
    # Todo texto que no sea comando es un registro
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar))

    app.add_error_handler(error_global)

    _levantar_servidor_salud()
    if respaldo.disponible():
        restaurado = respaldo.restaurar_si_hace_falta()
        threading.Thread(target=respaldo.bucle, daemon=True).start()
        logger.info(
            "Respaldos a GitHub activos (cada %s min%s)",
            respaldo.minutos(), ", BD restaurada" if restaurado else "",
        )
    logger.info("Bot iniciado. Ctrl+C para detener.")
    app.run_polling()


if __name__ == "__main__":
    main()
