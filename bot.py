"""Bot del taller - Sprint 5: roles (dueño/mecánicos), firma y textos limpios.

- El mecánico envía: ABC123 cambio de aceite 45000 → queda firmado con su nombre.
- Mecánico: solo ve SUS trabajos/ganancias. Dueño (ADMIN_IDS): ve todo + desglose.
- Todas las respuestas van con parse_mode=HTML via responder() (nada de '<b>' literal).
"""
import csv
import io
import logging
import os
from datetime import datetime
from functools import wraps
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

# ── Logs: consola + archivo rotativo (S3-3) ─────────────────────────────
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

# ── Errores del parser (cortos, S1-4/S5-6) ──────────────────────────────
MENSAJES_DE_ERROR = {
    MOTIVO_VACIO: "Escríbeme algo 👀",
    MOTIVO_PLACA: (
        "No vi la placa 🤔\nEj: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_PRECIO: (
        "Falta el precio 🤔\nEj: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_DESCRIPCION: (
        "Falta el trabajo 🤔\nEj: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_VARIAS_PLACAS: (
        "Vi varias placas 🤔 déjame solo una.\n"
        "Ej: <code>ABC123 cambio de aceite 45000</code>"
    ),
}

EJEMPLO = "<code>ABC123 cambio de aceite 45000</code>"


# ── Helpers de formato ──────────────────────────────────────────────────

def formatear_dinero(valor: float) -> str:
    """45000.0 -> '$ 45.000' (estilo Colombia)."""
    return f"$ {valor:,.0f}".replace(",", ".")


def formatear_fecha(mensaje_dt: datetime) -> str:
    """16/11/2026 02:45 pm."""
    return mensaje_dt.strftime("%d/%m/%Y %I:%M %p").lower()


async def responder(update: Update, texto: str, **extra) -> None:
    """ÚNICO canal de respuestas: SIEMPRE lleva formato HTML (fix S5-6)."""
    await update.message.reply_text(texto, parse_mode="HTML", **extra)


def protegido(func):
    """Solo deja pasar a admins y mecánicos del .env (S3-1)."""

    @wraps(func)
    async def envoltura(update, context, *args, **kwargs):
        usuario = update.effective_user.id if update.effective_user else None
        if not roles.es_autorizado(usuario):
            logger.warning(
                "Acceso denegado: id=%s nombre=%r mensaje=%r",
                usuario,
                update.effective_user.full_name if update.effective_user else "?",
                update.effective_message.text if update.effective_message else "?",
            )
            return
        return await func(update, context, *args, **kwargs)

    return envoltura


def _linea_trabajo(fila, con_mecanico: bool = False) -> str:
    """Línea compacta: #7 09:15 · ABC123 · descripcion · $ x [· nombre]"""
    hora = datetime.fromisoformat(fila["fecha_hora"]).strftime("%I:%M %p").lower()
    mecanico = f" · {fila['mecanico'] or 'sin firmar'}" if con_mecanico else ""
    return (
        f"#{fila['id']} {hora} · <b>{fila['placa']}</b> · "
        f"{fila['descripcion']} · {formatear_dinero(fila['precio'])}{mecanico}"
    )


# ── Comandos ────────────────────────────────────────────────────────────

@protegido
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await responder(
        update,
        "🛠️ <b>Bot del taller</b>\n"
        "Mándame un mensaje con <b>placa + trabajo + precio</b>:\n"
        f"{EJEMPLO}\n/ayuda → comandos",
    )


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
        "ℹ️ /ayuda",
    )


@protegido
async def historialdia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dueño: todos con nombre. Mecánico: solo los suyos (S5-3)."""
    usuario_solicita = update.effective_user.id
    es_admin = roles.es_admin(usuario_solicita)
    filas = (
        db.trabajos_hoy() if es_admin else db.trabajos_hoy(usuario_id=usuario_solicita)
    )
    if not filas:
        await responder(update, "😌 Sin trabajos registrados hoy.")
        return
    total = sum(fila["precio"] for fila in filas)
    lista = "\n".join(
        _linea_trabajo(fila, con_mecanico=es_admin) for fila in filas
    )
    quien = "Trabajos de hoy" if es_admin else "Tus trabajos de hoy"
    await responder(
        update,
        f"🌅 <b>{quien}</b>\n{lista}\n\n"
        f"💰 <b>Total{' del día' if es_admin else ''}: {formatear_dinero(total)}</b>"
        f" ({len(filas)} trabajo{'s' if len(filas) != 1 else ''})",
    )


@protegido
async def ganancias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dueño: total del taller + desglose. Mecánico: solo lo suyo."""
    await _reporte_ganancias(update, context, solo_propias=False)


@protegido
async def misganancias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias claro: SIEMPRE lo propio (aunque quien lo mande sea el dueño)."""
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
    usuario_solicita = update.effective_user.id
    solo_del_dueno = roles.es_admin(usuario_solicita) and not solo_propias

    if solo_del_dueno:
        etiqueta, cantidad, suma = db.resumen_periodo(dias=dias, mes=mes)
        texto = f"💼 <b>Ganancias de {etiqueta}</b>\n💰 <b>{formatear_dinero(suma)}</b>"
        # Desglose por mecánico (S5-3)
        etiqueta2, desglose = db.desglose_mecanicos(dias=dias, mes=mes)
        if desglose:
            lineas = "\n".join(
                f"👤 {nombre}: {formatear_dinero(suma_monto)} ({cantidad}) "
                for nombre, cantidad, suma_monto in desglose
            )
            texto += f"\n\n<b>Por mecánico</b>:\n{lineas}"
        elif cantidad == 0:
            texto = f"😌 Sin trabajos en {etiqueta}."
    else:
        etiqueta, cantidad, suma = db.resumen_periodo(
            dias=dias, mes=mes, mecanico_id=usuario_solicita
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
    """Dueño: historial completo del vehículo. Mecánico: solo sus registros."""
    if not context.args:
        await responder(update, "Dime la placa 🤔\nEj: <code>/buscar ABC123</code>")
        return
    placa = context.args[0].upper()
    usuario_solicita = update.effective_user.id
    es_admin = roles.es_admin(usuario_solicita)
    filas, cantidad, suma = (
        db.historial_placa(placa)
        if es_admin
        else db.historial_placa(placa, usuario_id=usuario_solicita)
    )
    if cantidad == 0:
        await responder(
            update,
            f"🚘 Sin trabajos para <b>{placa}</b>"
            + ("" if es_admin else " tuyos") + ".",
        )
        return
    lista = "\n".join(
        _linea_trabajo(fila, con_mecanico=es_admin) for fila in filas
    )
    nota = (
        f"\n…(+{cantidad - len(filas)} más antiguos)"
        if cantidad > len(filas) else ""
    )
    titulo = f"<b>{placa}</b>" if es_admin else f"<b>{placa}</b> (tus registros)"
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
    fila = db.trabajo_por_id(trabajo_id)
    if fila is None or fila["anulado"]:
        await responder(update, f"No existe el trabajo #{trabajo_id} 🤷")
        return
    usuario_solicita = update.effective_user.id
    if not roles.es_admin(usuario_solicita) and fila["usuario_id"] != usuario_solicita:
        # S5-4: cada mecánico solo puede borrar lo suyo
        await responder(update, "🙅 Solo puedes borrar tus propios trabajos.")
        return
    botones = [
        [
            InlineKeyboardButton("🗑️ Sí, borrar", callback_data=f"borrar_si:{trabajo_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"borrar_no:{trabajo_id}"),
        ]
    ]
    await responder(
        update,
        f"¿Borrar? {_linea_trabajo(fila)}",
        reply_markup=InlineKeyboardMarkup(botones),
    )


@protegido
async def confirmar_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    accion, trabajo_id = query.data.split(":")
    fila = db.trabajo_por_id(int(trabajo_id))
    usuario_solicita = update.effective_user.id
    puede = fila is not None and (
        roles.es_admin(usuario_solicita) or fila["usuario_id"] == usuario_solicita
    )
    if not puede:
        await query.answer("No tuyo 👀", show_alert=True)
        return
    if accion == "borrar_si":
        anulado = db.anular_trabajo(int(trabajo_id))
        await query.edit_message_text(
            f"🗑️ #{trabajo_id} anulado." if anulado else f"#{trabajo_id} ya estaba anulado 🤷",
        )
        logger.info("Anulado #%s por %s", trabajo_id, usuario_solicita)
    else:
        await query.edit_message_text("😌 Quedó guardado.")
    await query.answer()


@protegido
async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    comando = (update.message.text or "/?").split()[0]
    await responder(
        update, f"No reconozco <code>{comando}</code> 🤔\nPrueba /ayuda"
    )


@protegido
async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda el trabajo firmado con quien lo registro (S5-2)."""
    try:
        resultado = parse(update.message.text)
    except ParserError as error:
        await responder(update, MENSAJES_DE_ERROR.get(error.motivo, "🤔"))
        return
    usuario_solicita = update.effective_user.id
    firma = (
        roles.nombre_de(usuario_solicita)
        or update.effective_user.first_name  # si no está etiquetado en .env
    )
    trabajo_id = db.agregar_trabajo(
        placa=resultado.placa,
        descripcion=resultado.descripcion,
        precio=resultado.precio,
        chat_id=update.effective_chat.id,
        usuario_id=usuario_solicita,
        mecanico=firma,
    )
    await responder(
        update,
        f"✅ <b>#{trabajo_id}</b> · <b>{resultado.placa}</b>\n"
        f"🔧 {resultado.descripcion}\n"
        f"💰 {formatear_dinero(resultado.precio)}\n"
        f"👤 {firma} · {formatear_fecha(datetime.now())}",
    )
    logger.info("Trabajo #%s: %s %s %.0f (por %s)",
                trabajo_id, resultado.placa, resultado.descripcion,
                resultado.precio, firma)


@protegido
async def exportar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """CSV con los trabajos del periodo. Solo el dueño (S5-5)."""
    if not roles.es_admin(update.effective_user.id):
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
        await responder(update, "Periodo: <code>/exportar</code> (mes) · <code>/exportar 7</code> · <code>/exportar hoy</code>")
        return
    inicio, fin, etiqueta = db.rango_periodo(dias, mes)
    filas = db._trabajos_entre(inicio, fin)
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
            fila["mecanico"] or roles.nombre_de(fila["usuario_id"]) or "sin firmar",
        ])
    contenido = b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")  # BOM p/ Excel
    nombre_archivo = f"taller_{inicio}_a_{fin}.csv"
    await update.message.reply_document(
        document=contenido,  # bytes van directo en PTB 22+
        filename=nombre_archivo,
        caption=f"📄 {etiqueta} — {len(filas)} trabajos",
    )


async def error_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Última línea de defensa: ningún handler tumba al bot (S3-2)."""
    logger.exception("Error no manejado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "😅 Algo salió mal de mi lado, intenta de nuevo."
            )
        except Exception:
            logger.exception("No pude avisar el error en el chat")


def main() -> None:
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "aqui_va_el_token":
        raise SystemExit("Falta el token en el .env (TELEGRAM_TOKEN).")
    if not roles.ADMIN_IDS:
        raise SystemExit(
            "Define quién es dueño en .env:\n  ADMIN_IDS=9136002456"
        )
    logger.info(
        "Roles: %s admin(s): %s, %s mecánico(s): %s",
        len(roles.ADMIN_IDS), list(roles.ADMIN_IDS.values()),
        len(roles.MECANICOS), list(roles.MECANICOS.values()) or "—",
    )
    db.init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("historialdia", historialdia))
    app.add_handler(CommandHandler(["ganancias", "ganancia"], ganancias))
    app.add_handler(CommandHandler("misganancias", misganancias))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("borrar", borrar))
    app.add_handler(CommandHandler("exportar", exportar))
    app.add_handler(CallbackQueryHandler(confirmar_borrar, pattern=r"^borrar_(si|no):"))
    # Cualquier otro comando → siempre responde algo (nunca silencio)
    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))
    # Todo texto que no sea comando es un registro
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar))

    app.add_error_handler(error_global)
    logger.info("Bot iniciado. Ctrl+C para detener.")
    app.run_polling()


if __name__ == "__main__":
    main()
