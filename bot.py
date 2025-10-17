# =====================================================
# bot.py — SPACE420 BOT (python-telegram-bot v21+)
# Backup automatico + Blindato admin + Navigazione corretta
# =====================================================

import os
import sqlite3
import logging
import shutil
import csv
from datetime import datetime, timezone, time as dtime
from pathlib import Path
from io import BytesIO

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import telegram.error as tgerr

# ===== LOGGING =====
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("space420")

# ===== ENV CONFIG =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DB_FILE = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")
BACKUP_TIME = os.environ.get("BACKUP_TIME", "03:00")
WELCOME_PHOTO_URL = os.environ.get(
    "WELCOME_PHOTO_URL",
    "https://i.postimg.cc/D0JhvYfw/1230-DD1-F-7504-4131-8-F96-FA4398-A29-B39.jpg",
)
WELCOME_TITLE = "BENVENUTO NEL SPACE CLUB OFFICIAL 🇮🇹🇲🇦🇺🇸🇪🇸"

# ===== BUTTON LABELS =====
BTN_MENU = "📖 Menù"
BTN_CONTACTS = "📲 Contatti"
BTN_BACK = "⬅️ Torna indietro"

# ===== DATABASE INIT =====
def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined TIMESTAMP
    )"""
    )
    conn.commit()
    conn.close()


def add_user_if_new(user):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, joined) VALUES (?, ?, ?, ?, ?)",
            (
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                datetime.now(timezone.utc),
            ),
        )
        conn.commit()
    conn.close()


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


# ===== BACKUP FUNCTION =====
def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_dir) / f"users_backup_{ts}.db"

    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return dest


# ===== UI =====
def kb_home():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
                InlineKeyboardButton(BTN_CONTACTS, callback_data="open_contacts"),
            ]
        ]
    )


def kb_back():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(BTN_BACK, callback_data="home")]]
    )


HOME_TEXT = f"👋 {WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:"


async def show_home_with_photo(chat):
    if WELCOME_PHOTO_URL:
        await chat.send_photo(photo=WELCOME_PHOTO_URL, caption=WELCOME_TITLE)
    await chat.send_message(text=HOME_TEXT, reply_markup=kb_home())


async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        if q.data == "open_menu":
            await q.message.edit_text(MENU_TEXT, reply_markup=kb_back())
        elif q.data == "open_contacts":
            await q.message.edit_text(CONTACTS_TEXT, reply_markup=kb_back())
        elif q.data == "home":
            await q.message.edit_text(HOME_TEXT, reply_markup=kb_home())
    except tgerr.BadRequest:
        # se non può editare (vecchio messaggio), ne crea uno nuovo
        if q.data == "open_menu":
            await q.message.chat.send_message(MENU_TEXT, reply_markup=kb_back())
        elif q.data == "open_contacts":
            await q.message.chat.send_message(CONTACTS_TEXT, reply_markup=kb_back())
        elif q.data == "home":
            await q.message.chat.send_message(HOME_TEXT, reply_markup=kb_home())


# ====== TEXTI DELLE PAGINE ======
MENU_TEXT = """#MENU🥇✅💯💣

✅✅✅✅✅✅✅✅✅✅

   🛸🛸SPACE.CLUB🛸🛸
      
⛓️🏴 C'È CHI DICE E C'È CHI FA🏴⛓️

🥇🛸VI PORTIAMO NELLO SPAZIO🛸🥇

🛸THE_BEST_CLUB_IN_THE_CITY_🛸

🐀⚔️5 PAGINE BANNATE ⚔️🐀

EX-🥊T.P.2.0🥊


🔝🔝🔝SOLO MATERIALE DI ALTA QUALITÀ PER VERI INTENDITORI🇺🇸🍭💣🔝
"""

CONTACTS_TEXT = """•UNICI CONTATTI 📲📲📲

•CANALE TELEGRAM-
https://t.me/+C1YZrzdjfAE1OGM0

•INSTAGRAM -
https://www.instagram.com/space.club.csc?igsh=emM2NW1ya2g4bTd0

•CANALE POTATO -
https://doudlj.org/joinchat/ZjoVT0QWt7cH0-B0AGpV7Q

•CONTATTO POTATO -
https://doudlj.org/TysonPlug

•CANALE SIGNAL-
https://signal.group/#CjQKIN_UntxiqbKdVUCt83cl0AS06BS_nhlvw3eJETmfCIK_EhBYgXg1vvdcSDiCUSVoMRha

✅🛸MEET-UP SEMPRE ATTIVO🛸✅
✅OPERATIVI TUTTI I GIORNI ✅
💶DALLE 9:00 ALLE 2:00💶
"""

# ===== COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        add_user_if_new(update.effective_user)
    await show_home_with_photo(update.effective_chat)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(
        f"ID: {uid}\nAdmin: {'SI' if is_admin(uid) else 'NO'}"
    )


async def cmd_utenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"👥 Utenti registrati: {count}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 SPACE420 STATUS\n\nDB: {DB_FILE}\nBackup: {BACKUP_DIR}\nBackup Time (UTC): {BACKUP_TIME}"
    )


# ===== ADMIN COMMANDS =====
async def cmd_backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    backup_file = make_backup_copy(DB_FILE, BACKUP_DIR)
    await update.message.reply_document(
        InputFile(backup_file), caption=f"Backup creato: {backup_file.name}"
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    conn.close()

    output = BytesIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "first_name", "last_name", "joined"])
    writer.writerows(rows)
    output.seek(0)

    await update.message.reply_document(
        InputFile(output, filename="users_export.csv"), caption="Esportazione utenti"
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name FROM users ORDER BY joined DESC LIMIT 50")
    rows = cur.fetchall()
    conn.close()

    text = "📜 Ultimi utenti registrati:\n\n" + "\n".join(
        [f"{r[2]} @{r[1]} (ID: {r[0]})" for r in rows]
    )
    await update.message.reply_text(text or "Nessun utente trovato.")


# ===== MAIN =====
def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # HANDLERS
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_buttons))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("utenti", cmd_utenti))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_start))

    logger.info("SPACE420 avviato — modalità polling.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


if __name__ == "__main__":
    main()