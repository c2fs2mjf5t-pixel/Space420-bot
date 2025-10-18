# =====================================================
# SPACE420OFFICIAL BOT — python-telegram-bot v21.4
# =====================================================
# ✅ Benvenuto con immagine + pulsanti (Menù / Contatti)
# ✅ Testi lunghissimi (10.000+ caratteri) da variabili ENV
# ✅ "⬅️ Torna indietro" pulisce i messaggi
# ✅ Salvataggio automatico utenti (SQLite)
# ✅ Comandi admin blindati in chat privata
# ✅ Backup + Export + List + Broadcast
# ✅ Anti-conflict (polling sicuro, retry automatico)
# =====================================================

import os
import csv
import sqlite3
import logging
import asyncio as aio
from time import sleep
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    Application,
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
BOT_TOKEN  = os.environ.get("BOT_TOKEN")
ADMIN_ID   = int(os.environ.get("ADMIN_ID", "0"))

DB_FILE    = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")

WELCOME_PHOTO_URL = (os.environ.get("WELCOME_PHOTO_URL") or
    "https://i.postimg.cc/D0JhvYfw/1230-DD1-F-7504-4131-8-F96-FA4398-A29-B39.jpg").strip()
WELCOME_TITLE = os.environ.get(
    "WELCOME_TITLE", "BENVENUTI NEL SPACE CLUB 🇺🇸🇪🇸🇲🇦🇮🇹🇳🇱"
)

# ---------- MENU / CONTATTI ----------
DEFAULT_MENU = "#MENU (default)\nImposta la variabile d'ambiente MENU_TEXT su Render."
DEFAULT_CONTACTS = "Contatti (default)\nImposta CONTACTS_TEXT su Render."
MENU_TEXT     = (os.environ.get("MENU_TEXT") or "").strip() or DEFAULT_MENU
CONTACTS_TEXT = (os.environ.get("CONTACTS_TEXT") or "").strip() or DEFAULT_CONTACTS

# ---------- LABEL BOTTONI ----------
BTN_MENU     = os.environ.get("BTN_MENU", "📖 Menù")
BTN_CONTACTS = os.environ.get("BTN_CONTACTS", "📲 Contatti")
BTN_BACK     = os.environ.get("BTN_BACK", "⬅️ Torna indietro")

OPEN_KEY = "open_msgs_ids"  # per ricordare messaggi aperti

# ---------- UTILITIES ----------
def is_admin(uid: int) -> bool:
    return uid != 0 and uid == ADMIN_ID

def is_private(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")

def admin_only_private(update: Update) -> bool:
    """True se è l’admin e scrive in chat privata."""
    user = update.effective_user
    return bool(user and is_admin(user.id) and is_private(update))

# ---------- DATABASE ----------
def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined_utc TEXT
    )""")
    conn.commit()
    conn.close()

def add_user_if_new(user):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=?", (user.id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    (user.id, user.username or "", user.first_name or "",
                     user.last_name or "", datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
    conn.close()

def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_dir) / f"users_backup_{ts}.db"
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close(); src_conn.close()
    return dest

# ---------- INTERFACCIA ----------
def kb_home():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
        InlineKeyboardButton(BTN_CONTACTS, callback_data="open_contacts"),
    ]])
def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton(BTN_BACK, callback_data="home")]])

async def show_home_with_photo(chat):
    caption = f"{WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:"
    await chat.send_photo(photo=WELCOME_PHOTO_URL, caption=caption, reply_markup=kb_home())

def _chunks(s: str, size: int = 3800):
    for i in range(0, len(s), size): yield s[i:i+size]

async def send_long_with_back(update_or_chat, context, text: str):
    if hasattr(update_or_chat, "effective_chat") and update_or_chat.effective_chat:
        chat = update_or_chat.effective_chat
    elif hasattr(update_or_chat, "message") and hasattr(update_or_chat.message, "chat"):
        chat = update_or_chat.message.chat
    else:
        chat = update_or_chat
    sent_ids = []
    parts = list(_chunks(text, 3800))
    if not parts: return
    for p in parts[:-1]:
        m = await chat.send_message(p)
        sent_ids.append(m.message_id)
    last = await chat.send_message(parts[-1], reply_markup=kb_back())
    sent_ids.append(last.message_id)
    context.user_data[OPEN_KEY] = sent_ids

async def delete_open_block(update, context):
    ids = context.user_data.get(OPEN_KEY, [])
    chat_id = update.effective_chat.id
    for mid in ids:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except: pass
    context.user_data[OPEN_KEY] = []

# ---------- CALLBACK ----------
async def on_buttons(update, context):
    q = update.callback_query
    await q.answer()
    try:
        if q.data == "open_menu":
            await send_long_with_back(update, context, MENU_TEXT)
        elif q.data == "open_contacts":
            await send_long_with_back(update, context, CONTACTS_TEXT)
        elif q.data == "home":
            await delete_open_block(update, context)
            try: await q.message.delete()
            except: pass
            await show_home_with_photo(q.message.chat)
    except Exception as e:
        logger.warning(f"on_buttons error: {e}")

# ---------- COMANDI BASE ----------
async def cmd_start(update, context):
    if update.effective_user: add_user_if_new(update.effective_user)
    await show_home_with_photo(update.effective_chat)

async def cmd_utenti(update, context):
    n = sqlite3.connect(DB_FILE).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"👥 Utenti registrati: {n}")

async def cmd_status(update, context):
    await update.message.reply_text("✅ Bot attivo")

async def cmd_whoami(update, context):
    uid = update.effective_user.id
    await update.message.reply_text(f"ID: {uid}\nAdmin: {'SI' if is_admin(uid) else 'NO'}")

# ---------- COMANDI ADMIN (solo privato) ----------
async def cmd_adminstatus(update, context):
    if not admin_only_private(update): return
    n = sqlite3.connect(DB_FILE).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"🔐 Admin Status\n🗂 DB: {DB_FILE}\n📦 Backup: {BACKUP_DIR}\n👥 Utenti: {n}")

async def cmd_backup_db(update, context):
    if not admin_only_private(update): return
    p = make_backup_copy(DB_FILE, BACKUP_DIR)
    with open(p, "rb") as fh:
        await update.message.reply_document(document=fh, filename=p.name, caption=f"Backup creato: {p.name}")

async def cmd_export(update, context):
    if not admin_only_private(update): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor(); cur.execute("SELECT * FROM users")
    rows = cur.fetchall(); conn.close()
    buf = BytesIO(); w = csv.writer(buf)
    w.writerow(["user_id","username","first_name","last_name","joined_utc"]); w.writerows(rows)
    buf.seek(0)
    await update.message.reply_document(document=buf, filename="users.csv", caption="Esportazione utenti")

async def cmd_list(update, context):
    if not admin_only_private(update): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name FROM users ORDER BY joined_utc DESC LIMIT 100")
    rows = cur.fetchall(); conn.close()
    if not rows: await update.message.reply_text("Nessun utente."); return
    msg = "\n".join(f"• {fn or '-'} @{un or '-'} (ID: {uid})" for uid,un,fn in rows)
    for part in _chunks(msg,3800): await update.message.reply_text(part)

async def cmd_broadcast(update, context):
    if not admin_only_private(update): return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <messaggio>")
        return
    text = " ".join(context.args)
    conn = sqlite3.connect(DB_FILE)
    ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
    conn.close()
    ok=ko=0
    await update.message.reply_text(f"Invio a {len(ids)} utenti…")
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            ok+=1
            await aio.sleep(0.03)
        except: ko+=1; await aio.sleep(0.03)
    await update.message.reply_text(f"Broadcast finito: ✅{ok} | ❌{ko}")

# ---------- ANTI-CONFLICT ----------
async def ensure_no_webhook(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook eliminato (anti-conflict).")
    except Exception as e:
        logger.warning(f"delete_webhook: {e}")

def run_polling_with_guard(app: Application):
    loop = aio.get_event_loop()
    loop.run_until_complete(ensure_no_webhook(app))
    while True:
        try:
            app.run_polling(close_loop=False, drop_pending_updates=True)
            break
        except tgerr.Conflict:
            logger.warning("Conflict: altro polling attivo — ritento tra 10s…")
            sleep(10)
        except Exception as e:
            logger.error(f"Errore polling: {e} — ritento tra 10s…")
            sleep(10)

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN non impostato.")
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # public
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_buttons))
    app.add_handler(CommandHandler("utenti", cmd_utenti))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    # admin
    app.add_handler(CommandHandler("adminstatus", cmd_adminstatus))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    # default
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_start))
    logger.info("SPACE420OFFICIAL avviato con anti-conflict.")
    run_polling_with_guard(app)

if __name__ == "__main__":
    main()