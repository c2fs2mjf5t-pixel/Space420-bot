# =====================================================
# SPACE420OFFICIAL BOT — python-telegram-bot v21.4
# - Benvenuto: una sola immagine con testo e bottoni
# - Menu/Contatti: supporto 10.000+ caratteri (spezzamento automatico)
# - "⬅️ Torna indietro": cancella l'intero blocco e torna al benvenuto
# - SQLite utenti, comandi admin blindati, backup manuale robusto
# =====================================================

import os
import csv
import sqlite3
import logging
from datetime import datetime, timezone
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

# ---------- LOG ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("space420")

# ---------- ENV ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")           # obbligatorio
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))   # tuo ID numerico

DB_FILE = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")

# Immagine e testi (puoi cambiarli via ENV se vuoi)
WELCOME_PHOTO_URL = os.environ.get(
    "WELCOME_PHOTO_URL",
    "https://i.postimg.cc/D0JhvYfw/1230-DD1-F-7504-4131-8-F96-FA4398-A29-B39.jpg"
).strip()

WELCOME_TITLE = os.environ.get(
    "WELCOME_TITLE",
    "BENVENUTI NEL SPACE CLUB 🇺🇸🇪🇸🇲🇦🇮🇹🇳🇱"
)

# Testi del menu/contatti (puoi metterli anche da ENV; supporta 10k+ char)
MENU_TEXT = os.environ.get("MENU_TEXT", "#MENU qui il tuo testo lungo…")
CONTACTS_TEXT = os.environ.get("CONTACTS_TEXT", "Contatti e link…")

# Etichette pulsanti
BTN_MENU = os.environ.get("BTN_MENU", "📖 Menù")
BTN_CONTACTS = os.environ.get("BTN_CONTACTS", "📲 Contatti")
BTN_BACK = os.environ.get("BTN_BACK", "⬅️ Torna indietro")

# Key per tracciare i messaggi aperti per utente
OPEN_KEY = "open_msgs_ids"

# ---------- DB ----------
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

def add_user_if_new(user):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=?", (user.id,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    conn.close()

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID and uid != 0

# ---------- BACKUP (robusto via API SQLite) ----------
def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_dir) / f"users_backup_{ts}.db"
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)  # copia consistente anche a caldo
    finally:
        dst_conn.close()
        src_conn.close()
    return dest

# ---------- UI ----------
def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
            InlineKeyboardButton(BTN_CONTACTS, callback_data="open_contacts"),
        ]]
    )

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BTN_BACK, callback_data="home")]])

async def show_home_with_photo(chat):
    """Mostra una sola immagine con la scritta e i pulsanti sotto (nessun doppio messaggio)."""
    if WELCOME_PHOTO_URL:
        await chat.send_photo(
            photo=WELCOME_PHOTO_URL,
            caption=f"{WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:",
            reply_markup=kb_home(),
        )
    else:
        await chat.send_message(
            text=f"{WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:",
            reply_markup=kb_home(),
        )

# ---------- Text chunking (10k+ caratteri) ----------
def _chunks(s: str, size: int = 3800):
    """Spezzetta il testo in blocchi sotto il limite Telegram (~4096)."""
    i = 0
    n = len(s)
    while i < n:
        yield s[i:i+size]
        i += size

async def send_long_with_back(update_or_chat, context, text: str):
    """Invia testo lunghissimo a pezzi e salva gli ID per cancellarli al 'Back'."""
    # ricava chat e user_data
    if hasattr(update_or_chat, "effective_chat"):
        chat = update_or_chat.effective_chat
        user_data = context.user_data
    else:
        chat = update_or_chat
        user_data = context.user_data

    sent_ids = []
    parts = list(_chunks(text, 3800))
    if not parts:
        return

    for p in parts[:-1]:
        m = await chat.send_message(p)
        sent_ids.append(m.message_id)

    last = await chat.send_message(parts[-1], reply_markup=kb_back())
    sent_ids.append(last.message_id)

    user_data[OPEN_KEY] = sent_ids

async def delete_open_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella tutti i messaggi del blocco aperto (menù/contatti)."""
    ids = context.user_data.get(OPEN_KEY, [])
    chat_id = update.effective_chat.id
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    context.user_data[OPEN_KEY] = []

# ---------- CALLBACKS ----------
async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        if q.data == "open_menu":
            await send_long_with_back(q, context, MENU_TEXT)
        elif q.data == "open_contacts":
            await send_long_with_back(q, context, CONTACTS_TEXT)
        elif q.data == "home":
            # cancella tutto il blocco aperto e torna al benvenuto
            await delete_open_block(update, context)
            try:
                await q.message.delete()
            except Exception:
                pass
            await show_home_with_photo(q.message.chat)
    except Exception as e:
        logger.warning(f"on_buttons error: {e}")

# ---------- COMMANDS (UTENTE) ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        add_user_if_new(update.effective_user)
    await show_home_with_photo(update.effective_chat)

async def cmd_utenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    (n,) = cur.fetchone()
    conn.close()
    await update.message.reply_text(f"👥 Utenti registrati: {n}")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✅ Bot attivo\n🗂 DB: {DB_FILE}\n📦 Backup dir: {BACKUP_DIR}"
    )

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"ID: {uid}\nAdmin: {'SI' if is_admin(uid) else 'NO'}")

# ---------- COMMANDS (ADMIN — blindati) ----------
async def cmd_backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    p = make_backup_copy(DB_FILE, BACKUP_DIR)
    await update.message.reply_document(InputFile(p), caption=f"Backup creato: {p.name}")

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users")
    rows = cur.fetchall()
    conn.close()
    buf = BytesIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "username", "first_name", "last_name", "joined_utc"])
    w.writerows(rows)
    buf.seek(0)
    await update.message.reply_document(
        InputFile(buf, filename="users_export.csv"),
        caption="Esportazione utenti (CSV)"
    )

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name, joined_utc "
                "FROM users ORDER BY joined_utc DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nessun utente.")
        return
    lines = ["Ultimi 100 iscritti:"]
    for uid, un, fn, ln, ts in rows:
        lines.append(f"- {uid} @{un or '-'} — {fn or ''} {ln or ''} — {ts}")
    # spezza anche la lista se lunghissima
    for part in _chunks("\n".join(lines), 3800):
        await update.message.reply_text(part)

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN non impostato.")
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("utenti", cmd_utenti))

    # Admin (blindati)
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("list", cmd_list))

    # Pulsanti
    app.add_handler(CallbackQueryHandler(on_buttons))

    # Testo libero → torna al benvenuto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_start))

    logger.info("SPACE420OFFICIAL pronto — polling.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)

if __name__ == "__main__":
    main()