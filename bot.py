# =====================================================
# SPACE420OFFICIAL BOT — python-telegram-bot v21.4
# =====================================================
# ✅ Benvenuto con immagine + pulsanti (Menù / Contatti)
# ✅ Testi lunghissimi (10.000+ caratteri) da variabili ENV
# ✅ "⬅️ Torna indietro" pulisce i messaggi
# ✅ Salvataggio utenti (SQLite)
# ✅ Admin-only in chat privata: status, backup, export (CSV/JSON/XLSX), list, broadcast
# ✅ Auto-backup giornaliero (UTC) + retention (pulizia backup vecchi)
# ✅ Anti-conflict (delete_webhook + polling retry)
# ✅ Anti-share: protect_content=True su tutti gli invii del bot
# ✅ Blocca media degli utenti (foto/video/file) se non admin
# ✅ /restore_db: ripristino DB rispondendo a un file .db
# =====================================================

import os
import csv
import json
import glob
import sqlite3
import logging
import asyncio as aio
from time import sleep
from datetime import datetime, timezone, time as dtime, timedelta
from pathlib import Path
from io import BytesIO
import shutil

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
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

# XLSX
from openpyxl import Workbook

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

# Auto-backup (UTC) + retention + notifica admin
BACKUP_TIME           = os.environ.get("BACKUP_TIME", "03:00")  # HH:MM (UTC)
BACKUP_NOTIFY_ADMIN   = os.environ.get("BACKUP_NOTIFY_ADMIN", "0")  # "1" per notificare
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "14"))

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

# ---------- BACKUP + RETENTION ----------
def make_backup_copy(src: str, dest_dir: str) -> Path:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_dir) / f"users_backup_{ts}.db"
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)  # copia consistente anche a caldo
    dst_conn.close(); src_conn.close()
    return dest

def cleanup_old_backups(dest_dir: str, retention_days: int):
    try:
        cutoff = datetime.now() - timedelta(days=retention_days)
        for path in glob.glob(str(Path(dest_dir) / "users_backup_*.db")):
            p = Path(path)
            if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                p.unlink(missing_ok=True)
        # anche csv/json/xlsx esportati vecchi
        for pattern in ["users_export_*.csv", "users_export_*.json", "users_export_*.xlsx"]:
            for path in glob.glob(str(Path(dest_dir) / pattern)):
                p = Path(path)
                if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                    p.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"cleanup_old_backups: {e}")

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
    await chat.send_photo(photo=WELCOME_PHOTO_URL, caption=caption, reply_markup=kb_home(), protect_content=True)

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
        m = await chat.send_message(p, protect_content=True)
        sent_ids.append(m.message_id)
    last = await chat.send_message(parts[-1], reply_markup=kb_back(), protect_content=True)
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
    await update.message.reply_text(f"👥 Utenti registrati: {n}", protect_content=True)

async def cmd_status(update, context):
    await update.message.reply_text("✅ Bot attivo", protect_content=True)

async def cmd_whoami(update, context):
    uid = update.effective_user.id
    await update.message.reply_text(f"ID: {uid}\nAdmin: {'SI' if is_admin(uid) else 'NO'}", protect_content=True)

# ---------- BLOCCO MEDIA UTENTI (non admin) ----------
async def block_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella foto/video/documenti/voice inviati da non-admin."""
    u = update.effective_user
    if u and is_admin(u.id):
        return
    chat = update.effective_chat
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=update.effective_message.id)
    except Exception:
        pass

# ---------- COMANDI ADMIN (solo privato) ----------
async def cmd_adminstatus(update, context):
    if not admin_only_private(update): return
    n = sqlite3.connect(DB_FILE).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(
        f"🔐 Admin Status\n"
        f"🗂 DB: {DB_FILE}\n"
        f"📦 Backup: {BACKUP_DIR}\n"
        f"⏰ Auto-backup (UTC): {BACKUP_TIME}\n"
        f"🧹 Retention: {BACKUP_RETENTION_DAYS} giorni\n"
        f"👥 Utenti: {n}",
        protect_content=True
    )

async def cmd_backup_db(update, context):
    if not admin_only_private(update): return
    p = make_backup_copy(DB_FILE, BACKUP_DIR)
    with open(p, "rb") as fh:
        await update.message.reply_document(document=fh, filename=p.name, caption=f"Backup creato: {p.name}", protect_content=True)

async def cmd_export(update, context):
    # CSV su disco + invio
    if not admin_only_private(update): return
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users")
        rows = cur.fetchall()
        conn.close()

        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = Path(BACKUP_DIR) / f"users_export_{ts}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["user_id","username","first_name","last_name","joined_utc"])
            w.writerows(rows)

        with open(csv_path, "rb") as fh:
            await update.message.reply_document(document=fh, filename=csv_path.name,
                                                caption=f"Esportazione utenti: {csv_path.name}",
                                                protect_content=True)
    except Exception as e:
        await update.message.reply_text(f"Errore export: {e}", protect_content=True)

async def cmd_export_json(update, context):
    if not admin_only_private(update): return
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users")
        rows = conn.cursor().fetchall() if False else rows  # placeholder per coerenza
        conn.close()

        data = [
            {"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3], "joined_utc": r[4]}
            for r in rows
        ]

        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = Path(BACKUP_DIR) / f"users_export_{ts}.json"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        with open(json_path, "rb") as fh:
            await update.message.reply_document(document=fh, filename=json_path.name,
                                                caption=f"Export JSON: {json_path.name}",
                                                protect_content=True)
    except Exception as e:
        await update.message.reply_text(f"Errore export JSON: {e}", protect_content=True)

async def cmd_export_xlsx(update, context):
    if not admin_only_private(update): return
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name, last_name, joined_utc FROM users")
        rows = cur.fetchall()
        conn.close()

        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_path = Path(BACKUP_DIR) / f"users_export_{ts}.xlsx"

        wb = Workbook()
        ws = wb.active
        ws.title = "Utenti"
        ws.append(["user_id","username","first_name","last_name","joined_utc"])
        for r in rows:
            ws.append(list(r))
        wb.save(xlsx_path)

        with open(xlsx_path, "rb") as fh:
            await update.message.reply_document(document=fh, filename=xlsx_path.name,
                                                caption=f"Export XLSX: {xlsx_path.name}",
                                                protect_content=True)
    except Exception as e:
        await update.message.reply_text(f"Errore export XLSX: {e}", protect_content=True)

async def cmd_list(update, context):
    if not admin_only_private(update): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name FROM users ORDER BY joined_utc DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nessun utente.", protect_content=True)
        return
    msg = "\n".join(f"• {fn or '-'} @{un or '-'} (ID: {uid})" for uid,un,fn in rows)
    for part in _chunks(msg,3800): await update.message.reply_text(part, protect_content=True)

async def cmd_broadcast(update, context):
    if not admin_only_private(update): return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <messaggio>", protect_content=True)
        return
    text = " ".join(context.args)
    conn = sqlite3.connect(DB_FILE)
    ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
    conn.close()
    ok=ko=0
    await update.message.reply_text(f"Invio a {len(ids)} utenti…", protect_content=True)
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text, protect_content=True)
            ok+=1
            await aio.sleep(0.03)  # rate limit dolce
        except:
            ko+=1
            await aio.sleep(0.03)
    await update.message.reply_text(f"Broadcast finito: ✅{ok} | ❌{ko}", protect_content=True)

# ---------- /restore_db (admin solo privato) ----------
async def cmd_restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only_private(update): return

    msg = update.effective_message
    if not msg or not msg.reply_to_message or not msg.reply_to_message.document:
        await update.message.reply_text(
            "📦 Per ripristinare:\n"
            "1) Invia un file **.db** al bot (come documento)\n"
            "2) Fai **Rispondi** a quel messaggio con `/restore_db`",
            protect_content=True
        )
        return

    doc = msg.reply_to_message.document
    if not (doc.file_name and doc.file_name.endswith(".db")):
        await update.message.reply_text("❌ Il file deve avere estensione .db", protect_content=True)
        return

    try:
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        tmp_path = Path(BACKUP_DIR) / f"restore_tmp_{doc.file_unique_id}.db"
        file = await doc.get_file()
        await file.download_to_drive(custom_path=str(tmp_path))
    except Exception as e:
        await update.message.reply_text(f"❌ Errore download file: {e}", protect_content=True)
        return

    try:
        safety_copy = Path(BACKUP_DIR) / f"pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak"
        if Path(DB_FILE).exists():
            shutil.copy2(DB_FILE, safety_copy)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore copia di sicurezza: {e}", protect_content=True)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return

    try:
        Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path, DB_FILE)
        await update.message.reply_text("✅ Database ripristinato con successo. Usa /adminstatus per verificare.", protect_content=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore ripristino DB: {e}", protect_content=True)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass

# ---------- AUTO-BACKUP GIORNALIERO ----------
def _parse_hhmm(s: str) -> dtime:
    try:
        h, m = s.split(":"); return dtime(hour=int(h), minute=int(m))
    except:
        return dtime(3, 0)  # default 03:00 UTC

async def nightly_backup_task(app: Application):
    target = _parse_hhmm(BACKUP_TIME)
    logger.info(f"Task auto-backup attivo — orario (UTC): {target.strftime('%H:%M')}")
    while True:
        now = datetime.utcnow()
        today_target = datetime.combine(now.date(), target)
        if now >= today_target:
            today_target += timedelta(days=1)
        wait_sec = (today_target - now).total_seconds()
        await aio.sleep(wait_sec)
        try:
            p = make_backup_copy(DB_FILE, BACKUP_DIR)
            cleanup_old_backups(BACKUP_DIR, BACKUP_RETENTION_DAYS)
            logger.info(f"Auto-backup creato: {p}")
            if BACKUP_NOTIFY_ADMIN == "1" and ADMIN_ID:
                try:
                    await app.bot.send_message(chat_id=ADMIN_ID, text=f"✅ Auto-backup creato: {p.name}", protect_content=True)
                except Exception as e:
                    logger.warning(f"Notify admin failed: {e}")
        except Exception as e:
            logger.error(f"Auto-backup errore: {e}")
        await aio.sleep(60)  # piccolo buffer

# ---------- ANTI-CONFLICT ----------
async def ensure_no_webhook(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook eliminato (anti-conflict).")
    except Exception as e:
        logger.warning(f"delete_webhook: {e}")

def run_polling_with_guard(app: Application):
    loop = aio.get_event_loop()
    # avvia task auto-backup
    loop.create_task(nightly_backup_task(app))
    # anti-conflict
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
    # admin (solo privato)
    app.add_handler(CommandHandler("adminstatus", cmd_adminstatus))
    app.add_handler(CommandHandler("backup_db", cmd_backup_db))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("export_json", cmd_export_json))
    app.add_handler(CommandHandler("export_xlsx", cmd_export_xlsx))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("restore_db", cmd_restore_db))
    # blocco media non-admin (foto/video/documenti/voice/sticker/audio/gif/video_note)
    media_filter = (
        filters.PHOTO
        | filters.VIDEO
        | filters.Document.ALL
        | filters.ANIMATION
        | filters.STICKER
        | filters.AUDIO
        | filters.VOICE
        | filters.VIDEO_NOTE
    )
    app.add_handler(MessageHandler(media_filter, block_media))
    # default (testi non comando → mostra home)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_start))
    logger.info("SPACE420OFFICIAL avviato — anti-conflict + auto-backup + protect_content + restore_db.")
    run_polling_with_guard(app)

if __name__ == "__main__":
    main()