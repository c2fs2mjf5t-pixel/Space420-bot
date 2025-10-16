# =====================================================
# bot.py — Space420 BOT (python-telegram-bot v21+)
# Salvataggio utenti (SQLite) + pulsanti menu
# Admin: /list /export /broadcast /backup_db /status
# Backup automatico notturno (orario da ENV BACKUP_TIME)
# Modalità: LONG POLLING (perfetta per Render Background Worker)
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
    filters,
)
import telegram.error as tgerr

VERSION = "Space420-1.0"

# ===== LOGGING =====
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("space420-bot")

# ===== CONFIG (ENV) =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")

DB_FILE = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")
BACKUP_TIME = os.environ.get("BACKUP_TIME", "03:00")  # formato HH:MM (server time, UTC su Render)

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

WELCOME_PHOTO_URL = os.environ.get("WELCOME_PHOTO_URL", "").strip()

# Pulsanti (URL)
MENU_URL = os.environ.get("MENU_URL", "https://t.me/")
SPAIN_URL = os.environ.get("SPAIN_URL", "https://t.me/")
REVIEWS_URL = os.environ.get("REVIEWS_URL", "https://t.me/")
CONTACTS_URL = os.environ.get("CONTACTS_URL", "https://t.me/")

# Pulsanti (etichette) — modificabili da ENV, con default
BTN_MENU = os.environ.get("BTN_MENU", "📖Menù")
BTN_SPAIN = os.environ.get("BTN_SPAIN", "🇪🇸Spagna")
BTN_REVIEWS = os.environ.get("BTN_REVIEWS", "🎇Recensioni")
BTN_CONTACTS = os.environ.get("BTN_CONTACTS", "📲Contatti")

# ===== DATABASE =====
def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
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
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
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
        logger.info("Nuovo utente registrato: %s (%s)", user.id, user.username)
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

def build_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(BTN_MENU, url=MENU_URL),
            InlineKeyboardButton(BTN_SPAIN, url=SPAIN_URL),
        ],
        [
            InlineKeyboardButton(BTN_REVIEWS, url=REVIEWS_URL),
            InlineKeyboardButton(BTN_CONTACTS, url=CONTACTS_URL),
        ],
    ]
    return InlineKeyboardMarkup(rows)

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    add_user_if_new(user)

    text = (
        "👋 Benvenuto nel bot **Space420**!\n"
        "Serietà e rispetto. Qui si cresce con impegno e determinazione.\n\n"
        "Scegli una voce dal menu qui sotto:"
    )
    kb = build_menu_keyboard()

    try:
        if WELCOME_PHOTO_URL:
            await update.effective_chat.send_photo(
                photo=WELCOME_PHOTO_URL,
                caption=text,
                reply_markup=kb,
                parse_mode="Markdown",
            )
        else:
            await update.effective_chat.send_message(
                text=text, reply_markup=kb, parse_mode="Markdown"
            )
    except tgerr.TelegramError as e:
        logger.warning("Invio welcome fallito: %s", e)
        await update.effective_chat.send_message(text=text, reply_markup=kb, parse_mode="Markdown")

# ===== COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome(update, context)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🤖 *Space420* — v{VERSION}\n"
        "Comandi utente:\n"
        "/start — Benvenuto e menu\n"
        "/utenti — Numero totale utenti\n"
        "/status — Stato del bot\n\n"
        "Comandi admin:\n"
        "/list — Lista utenti (primi 100)\n"
        "/export — Esporta CSV completo\n"
        "/broadcast <testo> — Invia a tutti gli utenti\n"
        "/backup_db — Backup immediato del DB\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_utenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = count_users()
    await update.message.reply_text(f"👥 Utenti registrati: *{n}*", parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = count_users()
    tnow = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = (
        f"✅ Bot attivo (v{VERSION})\n"
        f"🗂 DB: `{DB_FILE}`\n"
        f"📦 Backup dir: `{BACKUP_DIR}` — Orario: {BACKUP_TIME}\n"
        f"👥 Utenti: {n}\n"
        f"⏱ Ora server: {tnow}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users ORDER BY joined_utc DESC LIMIT 100")
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
    # crea CSV in memoria
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users ORDER BY joined_utc DESC")
    rows = cur.fetchall()
    conn.close()

    csv_path = Path(BACKUP_DIR) / f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "first_name", "last_name", "joined_utc"])
        writer.writerows(rows)

    await update.message.reply_document(document=InputFile(str(csv_path)), filename=csv_path.name, caption="Esportazione utenti (CSV)")

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
    text = " ".join(context.args)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()

    ok = 0
    ko = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            ok += 1
            await aio.sleep(0.03)  # throtte leggero
        except Exception:
            ko += 1
            continue

    await update.message.reply_text(f"Broadcast completato. ✅ {ok} inviati • ❌ {ko} falliti.")

# ===== SCHEDULER BACKUP NOTTURNO =====
def parse_hhmm(hhmm: str) -> dtime:
    try:
        h, m = hhmm.strip().split(":")
        return dtime(hour=int(h), minute=int(m))
    except Exception:
        return dtime(hour=3, minute=0)

async def nightly_backup_task():
    logger.info("Task backup automatico avviato. Orario: %s", BACKUP_TIME)
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
        # attende un minuto per evitare doppio trigger in edge cases
        await aio.sleep(60)

# ===== MAIN =====
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN non impostato nelle variabili d'ambiente.")
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Utente
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("utenti", cmd_utenti))
    app.add_handler(CommandHandler("status", cmd_status))

    # Admin
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Facoltativo: se qualcuno scrive senza comandi, rimanda il menu
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), send_welcome))

    # Avvia task di backup automatico
    app.job_queue.run_repeating(lambda ctx: None, interval=3600, first=0)  # job_queue keepalive
    aio.create_task(nightly_backup_task())

    logger.info("Space420 avviato — modalità LONG POLLING")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
