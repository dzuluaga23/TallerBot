"""Bot del taller - Sprint 2: registro de trabajos + consultas.

El mecanico envia un mensaje tipo:
    ABC123 cambio de aceite 45000
y el bot lo guarda en la base de datos y confirma con una ficha.

Comandos: /start, /ayuda, /historialdia, /ganancias, /buscar, /borrar.
"""
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from parser import (
    MOTIVO_DESCRIPCION,
    MOTIVO_PLACA,
    MOTIVO_PRECIO,
    MOTIVO_VACIO,
    MOTIVO_VARIAS_PLACAS,
    ParserError,
    parse,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import db

# Carga las variables del archivo .env (token, ids autorizados, etc.)
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Configura los logs: latido de cada mensaje y errores visibles
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # silencia el ruido de red
logger = logging.getLogger("taller-bot")

# Respuestas cuando el parser no entiende el mensaje (ticket S1-4)
MENSAJES_DE_ERROR = {
    MOTIVO_VACIO: "Wrote something, I'm listening 👀",
    MOTIVO_PLACA: (
        "No encontré la placa 🤔\n"
        "Agregué la placa del vehículo al mensaje.\n"
        "Ejemplos: <code>ABC123 cambio de aceite 45000</code> (carro) "
        "o <code>KGH12D cambio de tiras 38000</code> (moto)"
    ),
    MOTIVO_PRECIO: (
        "No encontré el precio 🤔\n"
        "Termina el mensaje con un valor.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_DESCRIPCION: (
        "No encontré el trabajo 🤔\n"
        "Soy un chatbot: necesito la placa, el trabajo y el precio.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_VARIAS_PLACAS: (
        "Encontré varias placas 🤔\n"
        "Deja solo la placa del vehículo que atendiste.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
}


def formatear_dinero(valor: float) -> str:
    """45000.0 -> '$45.000' con separador de miles estilo Colombia."""
    return f"$ {valor:,.0f}".replace(",", ".")


def formatear_fecha(mensaje_dt: datetime) -> str:
    """16/11/2026 2:45 p.m."""
    return mensaje_dt.strftime("%d/%m/%Y %I:%M %p").lower()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respuesta al comando /start."""
    await update.message.reply_text(
        "¡Hola! 🛠️ Soy el bot del taller.\n\n"
        "Para registrar un trabajo, mándame un solo mensaje con:\n"
        "<b>placa + trabajo + precio</b>\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>\n\n"
        "Mándalo así como esté: con $, con separadores y la placa "
        "al final también me sirven 😉\n"
        "Escribe <code>/ayuda</code> para ver todos los comandos."
    )
    logger.info("/start de %s", update.effective_user.username)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menú de comandos (ticket S2-5)."""
    await update.message.reply_text(
        "🛠️ <b>Bot del taller — comandos</b>\n\n"
        "📋 <b>Registrar (solo enviar un mensaje):</b>\n"
        "<code>ABC123 cambio de aceite 45000</code>\n\n"
        "🌅 <b>/historialdia</b> — lista de los trabajos de hoy con el total.\n"
        "📊 <b>/ganancias</b> — suma del día. También:\n"
        "    <code>/ganancias 7</code> últimos 7 días\n"
        "    <code>/ganancias mes</code> mes en curso\n"
        "🔍 <b>/buscar</b> <i>PLACA</i> — historial de un vehículo:\n"
        "    <code>/buscar ABC123</code>\n"
        "🗑️ <b>/borrar</b> <i>#</i> — anular un registro mal metido:\n"
        "    <code>/borrar 5</code>\n"
        "ℹ️ <b>/ayuda</b> — este menú."
    )


def _linea_trabajo(fila) -> str:
    """Una línea compacta por trabajo para las listas."""
    hora = datetime.fromisoformat(fila["fecha_hora"]).strftime("%I:%M %p").lower()
    return (
        f"#{fila['id']} {hora} · <b>{fila['placa']}</b> · "
        f"{fila['descripcion']} · {formatear_dinero(fila['precio'])}"
    )


async def historialdia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista los trabajos de hoy con total (ticket S2-1)."""
    filas = db.trabajos_hoy()
    if not filas:
        await update.message.reply_text(
            "😴 Todavía no hay trabajos registrados hoy.\n"
            "Cuando termines uno, manda el mensaje: "
            "<code>ABC123 cambio de aceite 45000</code>"
        )
        return
    total = sum(fila["precio"] for fila in filas)
    lista = "\n".join(_linea_trabajo(fila) for fila in filas)
    await update.message.reply_text(
        f"🌅 <b>Trabajos de hoy</b>\n{lista}\n\n"
        f"💰 <b>Total del día: {formatear_dinero(total)}</b> ({len(filas)} trabajos)"
    )


async def ganancias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Suma del periodo (ticket S2-2): hoy por defecto, /ganancias 7 o /ganancias mes."""
    arg = context.args[0].lower() if context.args else ""
    if arg in ("", "hoy", "dia"):
        etiqueta, cantidad, suma = db.resumen_periodo()
    elif arg == "mes":
        etiqueta, cantidad, suma = db.resumen_periodo(mes=True)
    elif arg.isdigit() and 1 <= int(arg) <= 365:
        etiqueta, cantidad, suma = db.resumen_periodo(dias=int(arg))
    else:
        await update.message.reply_text(
            "No entendí el periodo 🤔 Úsalo así:\n"
            "<code>/ganancias</code> (hoy)\n"
            "<code>/ganancias 7</code> (últimos 7 días)\n"
            "<code>/ganancias mes</code> (mes en curso)"
        )
        return
    if cantidad == 0:
        await update.message.reply_text(
            f"😌 No hay trabajos registrados en {etiqueta}."
        )
        return
    await update.message.reply_text(
        f"💼 <b>Ganancias de {etiqueta}</b>\n"
        f"💰 <b>{formatear_dinero(suma)}</b>\n"
        f"📋 {cantidad} trabajo{'s' if cantidad != 1 else ''}"
    )


async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Todo el historial de un vehículo (ticket S2-3)."""
    if not context.args:
        await update.message.reply_text(
            "Dime la placa 🤔\nEjemplo: <code>/buscar ABC123</code>"
        )
        return
    placa = context.args[0].upper()
    filas, cantidad, suma = db.historial_placa(placa)
    if cantidad == 0:
        await update.message.reply_text(
            f"🚘 No encontré trabajos para la placa <b>{placa}</b>.\n"
            "(revisa que esté bien escrita, ej: <code>ABC123</code>)"
        )
        return
    lista = "\n".join(_linea_trabajo(fila) for fila in filas)
    nota = f"\n…(+{cantidad - len(filas)} más antiguos)" if cantidad > len(filas) else ""
    await update.message.reply_text(
        f"🚘 <b>{placa}</b> — {cantidad} trabajo{'s' if cantidad != 1 else ''}\n"
        f"{lista}{nota}\n\n"
        f"💵 <b>Total histórico: {formatear_dinero(suma)}</b>"
    )


async def borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pide confirmación y anula un registro (ticket S2-4)."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Dime el número del trabajo 🤔\n"
            "Ejemplo: <code>/borrar 5</code>\n"
            "(el número sale en la confirmación: 'Trabajo #5')"
        )
        return
    trabajo_id = int(context.args[0])
    fila = db.trabajo_por_id(trabajo_id)
    if fila is None or fila["anulado"]:
        await update.message.reply_text(f"No encontré el trabajo #{trabajo_id} 🤷")
        return
    boton_si = InlineKeyboardButton(
        "🗑️ Sí, borrar", callback_data=f"borrar_si:{trabajo_id}"
    )
    boton_no = InlineKeyboardButton("❌ Cancelar", callback_data=f"borrar_no:{trabajo_id}")
    await update.message.reply_text(
        f"¿Seguro que quieres borrar este trabajo? 🤔\n\n{_linea_trabajo(fila)}",
        reply_markup=InlineKeyboardMarkup([[boton_si], [boton_no]]),
    )


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback: cualquier comando que no esté en la lista (S1-4 espíritu)."""
    comando = update.message.text.split()[0]
    await update.message.reply_text(
        f"No reconozco <code>{comando}</code> 🤔\n"
        "Escribe <code>/ayuda</code> para ver los comandos."
    )


async def confirmar_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acción al tocar los botones de /borrar."""
    query = update.callback_query
    accion, trabajo_id = query.data.split(":")

    if accion == "borrar_si":
        anulado = db.anular_trabajo(int(trabajo_id))
        if anulado:
            await query.edit_message_text(f"🗑️ Trabajo #{trabajo_id} anulado.")
        else:
            await query.edit_message_text(
                f"El trabajo #{trabajo_id} ya estaba anulado 🤷"
            )
        logger.info("Borrado trabajo #%s", trabajo_id)
    else:
        await query.edit_message_text(
            "😌 Listo, no quedó borrado nada."
        )
    await query.answer()


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda un trabajo desde un mensaje normal (no comando)."""
    texto = update.message.text
    try:
        resultado = parse(texto)
    except ParserError as error:
        await update.message.reply_text(
            MENSAJES_DE_ERROR.get(error.motivo, MENSAJES_DE_ERROR[MOTIVO_VACIO]),
            parse_mode="HTML",
        )
        return

    trabajo_id = db.agregar_trabajo(
        placa=resultado.placa,
        descripcion=resultado.descripcion,
        precio=resultado.precio,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(
        f"✅ <b>Trabajo #{trabajo_id} registrado</b>\n"
        f"🛻️ Placa: <b>{resultado.placa}</b>\n"
        f"🔧 Trabajo: {resultado.descripcion}\n"
        f"💰 Valor: {formatear_dinero(resultado.precio)}\n"
        f"🕒 {formatear_fecha(datetime.now())}"
    )
    logger.info(
        "Trabajo #%s: %s %s %.0f", trabajo_id, resultado.placa, resultado.descripcion, resultado.precio
    )


def main() -> None:
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "aqui_va_el_token":
        raise SystemExit(
            "Falta el token. Copia .env.example como .env y pega tu token de @BotFather."
        )
    db.init_db()  # crea taller.db si no existe

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    # Comandos de consulta (Sprint 2)
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("historialdia", historialdia))
    # Alias "ganancia" sin la s: para los dedos apurados del taller 😅
    app.add_handler(CommandHandler(["ganancias", "ganancia"], ganancias))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("borrar", borrar))
    # Botones de confirmacion del /borrar (S2-4)
    app.add_handler(CallbackQueryHandler(confirmar_borrar, pattern=r"^borrar_(si|no):"))
    # Cualquier otro comando desconocido (ej: /ganancia con otra falta):
    # SIEMPRE responde algo, nunca silencio
    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))
    # Todo texto que no sea comando es un registro (ticket S1-3)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar))

    logger.info("Bot iniciado. Presiona Ctrl+C para detener.")
    app.run_polling()  # long polling: sin dominio ni certificados


if __name__ == "__main__":
    main()
