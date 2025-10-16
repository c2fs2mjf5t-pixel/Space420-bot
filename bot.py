# =====================================================
# bot.py — Space420 BOT (python-telegram-bot v21.4)
# - Benvenuto con immagine (da ENV o default)
# - Pulsanti inline che APRONO messaggi interni: Menù, Contatti
# - Salvataggio utenti (SQLite) + comandi admin (/list /export /backup_db /broadcast)
# - Backup automatico notturno (senza job_queue)
# =====================================================

import os
import sqlite3
import logging
import shutil
import asyncio as aio
import csv
from datetime import datetime, timezone, time as dtime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
import telegram.error as tgerr

VERSION = "Space420-1.2"

# ===== LOGGING =====
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("space420-bot")

# ===== CONFIG (ENV) =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # OBBLIGATORIO

DB_FILE = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")
BACKUP_TIME = os.environ.get("BACKUP_TIME", "03:00")  # HH:MM (UTC su Render)

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Immagine e testi (i testi devono essere contenuti leciti)
WELCOME_PHOTO_URL = os.environ.get(
    "WELCOME_PHOTO_URL",
    "https://i.postimg.cc/D0JhvYfw/1230-DD1-F-7504-4131-8-F96-FA4398-A29-B39.jpg"
).strip()

WELCOME_TITLE = os.environ.get(
    "WELCOME_TITLE",
    "BENVENUTO NEL CLUB SPACE OFFICIAL 🇮🇹🇲🇦🇺🇸🇪🇸"
)

# Inserisci in ENV contenuti leciti (descrizioni/programma/regole/link)
MENU_TEXT = os.environ.get(
    "MENU_TEXT",
    "📖 Menù — inserisci qui un testo lecito (descrizioni, regole, orari, novità)."
)

CONTACTS_TEXT = os.environ.get(
    "CONTACTS_TEXT",
    "📲 Contatti — inserisci qui i tuoi contatti leciti e link social (Telegram, Instagram, ecc.)."
)

# Etichette pulsanti
BTN_MENU = os.environ.get("BTN_MENU", "📖 Menù")
BTN_CONTACTS = os.environ.get("BTN_CONTACTS", "📲 Contatti")

# ===== DATABASE =====
def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_utc TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    logger.info("DB inizializzato: %s", DB_FILE)

def add_user_if_new(user):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id = ?", (user.id,))
    exists = cur.fetchone()
    if not exists:
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, joined_utc) VALUES (?, ?, ?, ?, ?)",
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        logger.info("Nuovo utente registrato: %s (@%s)", user.id, user.username)
    conn.close()

def count_users() -> int:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    (n,) = cur.fetchone()
    conn.close()
    return int(n)

# ===== HELPER =====
def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID

def build_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
            InlineKeyboardButton(BTN_CONTACTS, callback_data="open_contacts"),
        ]
    ]
    return InlineKeyboardMarkup(rows)

async def send_long_text(chat, text: str):
    # Telegram max ~4096 char. Se supera, spezza.
    MAX = 3900
    if len(text) <= MAX:
        await chat.send_message(text)
        return
    start = 0
    while start < len(text):
        await chat.send_message(text[start:start+MAX])
        start += MAX

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        add_user_if_new(user)

    caption = f"👋 {WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:"
    kb = build_main_keyboard()

    try:
        if WELCOME_PHOTO_URL:
            await update.effective_chat.send_photo(
                photo=WELCOME_PHOTO_URL,
                caption=caption,
                reply_markup=kb,
            )
        else:
            await update.effective_chat.send_message(
                text=caption, reply_markup=kb
            )
    except tgerr.TelegramError as e:
        logger.warning("Invio welcome fallito: %s", e)
        await update.effective_chat.send_message(text=caption, reply_markup=kb)

# ===== CALLBACK BUTTONS =====
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "open_menu":
        await send_long_text(q.message.chat, MENU_TEXT)
    elif q.data == "open_contacts":
        await send_long_text(q.message.chat, CONTACTS_TEXT)

# ===== COMMANDS (UTENTE) =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome(update, context)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🤖 Space420 — v{VERSION}\n"
        "Comandi:\n"
        "/start — Benvenuto e menu\n"
        "/menu — Apri Menù\n"
        "/contatti — Mostra Contatti\n"
        "/utenti — Numero registrati\n"
        "/status — Stato del bot\n"
        "\nAdmin: /list /export /backup_db /broadcast <msg>\n"
    )
    await update.message.reply_text(text)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long_text(update.effective_chat, MENU_TEXT)

async def cmd_contatti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long_text(update.effective_chat, CONTACTS_TEXT)

async def cmd_utenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = count_users()
    await update.message.reply_text(f"👥 Utenti registrati: {n}")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = count_users()
    tnow = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = (
        f"✅ Bot attivo (v{VERSION})\n"
        f"🗂 DB: {DB_FILE}\n"
        f"📦 Backup dir: {BACKUP_DIR} — Orario: {BACKUP_TIME}\n"
        f"👥 Utenti: {n}\n"
        f"⏱ Ora server: {tnow}"
    )
    await update.message.reply_text(text)

# ===== COMMANDS (ADMIN) =====
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, first_name, last_name, joined_utc "
        "FROM users ORDER BY joined_utc DESC LIMIT 100"
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nessun utente trovato.")
        return
    lines = ["Primi 100 utenti (ultimi iscritti):"]
    for uid, uname, fn, ln, joined in rows:
        nick = f"@{uname}" if uname else "(nessun username)"
        lines.append(f"- {uid} {nick} — {fn} {ln} — {joined}")
    await update.message.reply_text("\n".join(lines))

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, first_name, last_name, joined_utc "
        "FROM users ORDER BY joined_utc DESC"
    )
    rows = cur.fetchall()
    conn.close()

    export_path = Path(BACKUP_DIR) / f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(export_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "first_name", "last_name", "joined_utc"])
        writer.writerows(rows)

    await update.message.reply_document(
        document=InputFile(str(export_path)),
        filename=export_path.name,
        caption="Esportazione utenti (CSV)"
    )

async def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_dir) / f"users_backup_{ts}.db"
    shutil.copy2(src, dest)
    return dest

async def cmd_backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        p = await make_backup_copy(DB_FILE, BACKUP_DIR)
        await update.message.reply_document(
            document=InputFile(str(p)),
            filename=p.name,
            caption=f"Backup creato: {p.name}",
        )
    except Exception as e:
        await update.message.reply_text(f"Errore backup: {e}")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <messaggio>")
        return
    broadcast_text = " ".join(context.args)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()

    ok = 0
    ko = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text)
            ok += 1
            await aio.sleep(0.03)
        except Exception:
            ko += 1
            continue

    await update.message.reply_text(f"Broadcast completato. ✅ {ok} inviati • ❌ {ko} falliti.")

# ===== BACKUP NOTTURNO =====
def parse_hhmm(hhmm: str) -> dtime:
    try:
        h, m = hhmm.strip().split(":")
        return dtime(hour=int(h), minute=int(m))
    except Exception:
        return dtime(hour=3, minute=0)

async def nightly_backup_task():
    logger.info("Task backup automatico avviato. Orario target: %s", BACKUP_TIME)
    target_t = parse_hhmm(BACKUP_TIME)
    while True:
        now = datetime.now()
        today_target = datetime.combine(now.date(), target_t)
        if now >= today_target:
            today_target += timedelta(days=1)
        wait_s = (today_target - now).total_seconds()
        await aio.sleep(wait_s)
        try:
            p = await make_backup_copy(DB_FILE, BACKUP_DIR)
            logger.info("Backup notturno creato: %s", p)
        except Exception as e:
            logger.error("Backup notturno fallito: %s", e)
        await aio.sleep(60)  # evita doppio trigger

# ===== MAIN =====
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN non impostato nelle variabili d'ambiente.")
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Utente
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("contatti", cmd_contatti))
    app.add_handler(CommandHandler("utenti", cmd_utenti))
    app.add_handler(CommandHandler("status", cmd_status))

    # Admin
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Pulsanti inline
    app.add_handler(CallbackQueryHandler(on_button))

    # Se qualcuno scrive testo semplice, rimanda il menu
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), send_welcome))

    # Avvia il task di backup automatico
    aio.get_event_loop().create_task(nightly_backup_task())

    logger.info("Space420 avviato — modalità LONG POLLING")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()