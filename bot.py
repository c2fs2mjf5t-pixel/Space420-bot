# =====================================================
# bot.py — Space420 (python-telegram-bot v21.4)
# SQLite + Inline menu con "⬅️ Torna al menu"
# Admin blindati: /list /export /backup_db /broadcast (silenziosi per non-admin)
# Backup manuale + notturno, Anti-conflict (webhook cleanup & retry)
# =====================================================

import os
import csv
import sqlite3
import logging
import shutil
import asyncio as aio
import time as pytime
from datetime import datetime, timezone, time as dtime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import telegram.error as tgerr

VERSION = "Space420-BackNav-ADMINLOCK-1.0"

# ---------- LOG ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("space420")

# ---------- ENV ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # OBBLIGATORIO

DB_FILE = os.environ.get("DB_FILE", "./data/users.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backup")
BACKUP_TIME = os.environ.get("BACKUP_TIME", "03:00")   # HH:MM (UTC su Render)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

WELCOME_PHOTO_URL = os.environ.get(
    "WELCOME_PHOTO_URL",
    "https://i.postimg.cc/D0JhvYfw/1230-DD1-F-7504-4131-8-F96-FA4398-A29-B39.jpg",
).strip()
WELCOME_TITLE = os.environ.get(
    "WELCOME_TITLE",
    "BENVENUTO NEL CLUB SPACE OFFICIAL 🇮🇹🇲🇦🇺🇸🇪🇸",
)

# Testi (inserire contenuti leciti)
MENU_TEXT = os.environ.get(
    "MENU_TEXT",
    "📖 Menù — inserisci qui un testo lecito: descrizioni, regole, orari, novità."
)
CONTACTS_TEXT = os.environ.get(
    "CONTACTS_TEXT",
    "📲 Contatti — inserisci qui contatti e link social leciti."
)

# Etichette pulsanti
BTN_MENU = os.environ.get("BTN_MENU", "📖 Menù")
BTN_CONTACTS = os.environ.get("BTN_CONTACTS", "📲 Contatti")
BTN_BACK = os.environ.get("BTN_BACK", "⬅️ Torna al menu")

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
    log.info("DB pronto: %s", DB_FILE)

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
        log.info("Nuovo utente: %s @%s", user.id, user.username)
    conn.close()

def count_users() -> int:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    (n,) = cur.fetchone()
    conn.close()
    return int(n)

def is_admin(uid: int) -> bool:
    return ADMIN_ID and uid == ADMIN_ID

# ---------- UI ----------
def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
         InlineKeyboardButton(BTN_CONTACTS, callback_data="open_contacts")]
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BTN_BACK, callback_data="home")]])

async def send_long(chat, text: str):
    MAX = 3900
    if len(text) <= MAX:
        await chat.send_message(text)
        return
    for i in range(0, len(text), MAX):
        await chat.send_message(text[i:i+MAX])

async def show_home(chat):
    caption = f"👋 {WELCOME_TITLE}\n\nScegli una voce dal menu qui sotto:"
    if WELCOME_PHOTO_URL:
        await chat.send_photo(photo=WELCOME_PHOTO_URL, caption=caption, reply_markup=kb_home())
    else:
        await chat.send_message(text=caption, reply_markup=kb_home())

# ---------- CALLBACKS ----------
async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "open_menu":
        await send_long(q.message.chat, MENU_TEXT)
        await q.message.chat.send_message("—", reply_markup=kb_back())
    elif q.data == "open_contacts":
        await send_long(q.message.chat, CONTACTS_TEXT)
        await q.message.chat.send_message("—", reply_markup=kb_back())
    elif q.data == "home":
        await show_home(q.message.chat)

# ---------- USER COMMANDS ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        add_user_if_new(update.effective_user)
    await show_home(update.effective_chat)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long(update.effective_chat, MENU_TEXT)
    await update.effective_chat.send_message("—", reply_markup=kb_back())

async def cmd_contatti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_long(update.effective_chat, CONTACTS_TEXT)
    await update.effective_chat.send_message("—", reply_markup=kb_back())

async def cmd_utenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"👥 Utenti registrati: {count_users()}")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tnow = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.message.reply_text(
        f"✅ Space420 v{VERSION}\n"
        f"👥 Utenti: {count_users()}\n"
        f"🗂 DB: {DB_FILE}\n"
        f"📦 Backup dir: {BACKUP_DIR}\n"
        f"⏰ Backup time: {BACKUP_TIME}\n"
        f"🕓 Server UTC: {tnow}"
    )

# ---------- ADMIN GUARD (silenziosa) ----------
async def guard_admin(update: Update) -> bool:
    """Ritorna True se è admin; se NON è admin, non manda nulla e ritorna False."""
    uid = (update.effective_user.id if update and update.effective_user else None)
    return bool(uid and is_admin(uid))

# ---------- ADMIN ----------
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
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
    await send_long(update.effective_chat, "\n".join(lines))

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name, joined_utc "
                "FROM users ORDER BY joined_utc DESC")
    rows = cur.fetchall()
    conn.close()
    out = Path(BACKUP_DIR) / f"users_export_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "username", "first_name", "last_name", "joined_utc"])
        w.writerows(rows)
    await update.message.reply_document(InputFile(str(out)), filename=out.name,
                                        caption="Esportazione utenti (CSV)")

async def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    dest = Path(dest_dir) / f"users_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(src, dest)
    return dest

async def cmd_backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    try:
        p = await make_backup_copy(DB_FILE, BACKUP_DIR)
        await update.message.reply_document(InputFile(str(p)), filename=p.name,
                                            caption=f"Backup creato: {p.name}")
    except Exception as e:
        await update.message.reply_text(f"Errore backup: {e}")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update): return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <messaggio>")
        return
    text = " ".join(context.args)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    ok = ko = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, text)
            ok += 1
            await aio.sleep(0.03)
        except Exception:
            ko += 1
    await update.message.reply_text(f"Broadcast: ✅ {ok} • ❌ {ko}")

# ---------- HELP: mostra admin solo all'admin ----------
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    base = (
        "/start — Benvenuto e menu\n"
        "/menu — Apri Menù\n"
        "/contatti — Mostra Contatti\n"
        "/utenti — Numero registrati\n"
        "/status — Stato del bot\n"
    )
    admin = (
        "\nComandi admin:\n"
        "/list — Lista (ultimi 100)\n"
        "/export — Esporta CSV\n"
        "/backup_db — Backup immediato del DB\n"
        "/broadcast <msg> — Messaggio a tutti\n"
    )
    isadm = is_admin(update.effective_user.id) if update.effective_user else False
    await update.message.reply_text(base + (admin if isadm else ""))

# ---------- BACKUP NOTTURNO ----------
def parse_hhmm(s: str) -> dtime:
    try:
        h, m = s.split(":")
        return dtime(hour=int(h), minute=int(m))
    except Exception:
        return dtime(3, 0)

async def nightly_backup_task():
    log.info("Task backup attivo, orario: %s", BACKUP_TIME)
    target = parse_hhmm(BACKUP_TIME)
    while True:
        now = datetime.now()
        when = datetime.combine(now.date(), target)
        if now >= when:
            when += timedelta(days=1)
        await aio.sleep((when - now).total_seconds())
        try:
            p = await make_backup_copy(DB_FILE, BACKUP_DIR)
            log.info("Backup notturno: %s", p)
        except Exception as e:
            log.error("Backup notturno errore: %s", e)
        await aio.sleep(60)

# ---------- ANTI-CONFLICT (polling guard) ----------
def run_polling_with_guard(app):
    loop = aio.get_event_loop()
    try:
        loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
        log.info("Webhook eliminato. Avvio polling…")
    except Exception as e:
        log.warning("delete_webhook warning: %s", e)

    loop.create_task(nightly_backup_task())

    while True:
        try:
            app.run_polling(close_loop=False, drop_pending_updates=True)
            break
        except tgerr.Conflict as e:
            log.warning("Conflict getUpdates: %s — ritento tra 10s…", e)
            pytime.sleep(10)
            continue
        except Exception as e:
            log.error("Errore run_polling: %s — ritento tra 10s…", e)
            pytime.sleep(10)
            continue

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN non impostato nelle ENV.")
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("contatti", cmd_contatti))
    app.add_handler(CommandHandler("utenti", cmd_utenti))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))

    # Admin (blindati)
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Buttons + testo libero → mostra home
    app.add_handler(CallbackQueryHandler(on_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_start))

    log.info("Space420 pronto — LONG POLLING (admin blindati)")
    run_polling_with_guard(app)

if __name__ == "__main__":
    main()