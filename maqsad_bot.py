# ============================================================
# MAQSAD BOT — faqat "Maqsad eslatuvchi" + toʻliq Admin panel
# Kerakli kutubxona:
#   pip install "python-telegram-bot[job-queue]==20.7"
#
# Muhit oʻzgaruvchilari (Railway/PythonAnywhere "Variables" boʻlimida):
#   BOT_TOKEN=123456:ABC-...
#   ADMIN_IDS=7329434421,111111111   (bir nechta admin — vergul bilan)
# ============================================================

import logging
import sqlite3
import os
import html
import asyncio
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import RetryAfter, Forbidden, BadRequest, TelegramError

# ── SOZLAMALAR ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

BOT_USERNAME = "@SIZNING_BOT_USERNAME"   # <-- shu yerga oʻz bot usernamengizni yozing
BOT_FOOTER = f"\n\n🤖 {BOT_USERNAME}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DATABASE INIZIALIZATSIYASI ───────────────────────────────
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        joined_at TEXT,
        is_premium INTEGER DEFAULT 0,
        special_start_msg TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS broadcast_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message TEXT,
        sent_at TEXT,
        sent_by INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_actions (
        user_id INTEGER PRIMARY KEY,
        count INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS admin_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        message_text TEXT,
        sent_at TEXT,
        is_replied INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS video_codes (
        code TEXT PRIMARY KEY,
        file_id TEXT,
        label TEXT,
        is_premium INTEGER DEFAULT 0,
        added_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        name TEXT,
        target_count INTEGER,
        sent_count INTEGER DEFAULT 0,
        interval_minutes INTEGER,
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

# ── DB YORDAMCHI FUNKSIYALARI ───────────────────────────────
def get_setting(key, default=""):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def add_user(user_id, username, full_name):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("""INSERT INTO users (user_id, username, full_name, joined_at, is_premium)
                     VALUES (?,?,?,?,0)""",
                  (user_id, username, full_name, datetime.now().isoformat()))
        conn.commit()
    conn.close()

def is_premium(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT is_premium FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == 1

def set_premium(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_stats():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium=1")
    premium = c.fetchone()[0]
    conn.close()
    return total, premium

def log_broadcast(message, sent_by):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO broadcast_log (message, sent_at, sent_by) VALUES (?,?,?)",
              (message, datetime.now().isoformat(), sent_by))
    conn.commit()
    conn.close()

# ── MAQSAD (GOAL REMINDER) YORDAMCHI FUNKSIYALARI ────────────
def create_goal(user_id, chat_id, name, target_count, interval_minutes):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""INSERT INTO goals (user_id, chat_id, name, target_count, interval_minutes, created_at)
                 VALUES (?,?,?,?,?,?)""",
              (user_id, chat_id, name, target_count, interval_minutes, datetime.now().isoformat()))
    goal_id = c.lastrowid
    conn.commit()
    conn.close()
    return goal_id

def get_goal(goal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""SELECT id, user_id, chat_id, name, target_count, sent_count,
                 interval_minutes, is_active FROM goals WHERE id=?""", (goal_id,))
    row = c.fetchone()
    conn.close()
    return row

def increment_goal_sent(goal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE goals SET sent_count = sent_count + 1 WHERE id=?", (goal_id,))
    conn.commit()
    conn.close()

def deactivate_goal(goal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE goals SET is_active=0 WHERE id=?", (goal_id,))
    conn.commit()
    conn.close()

def get_active_goal_for_chat(chat_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""SELECT id, name, target_count, done_count, interval_minutes
                 FROM goals WHERE chat_id=? AND is_active=1
                 ORDER BY id DESC LIMIT 1""", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row

def increment_goal_done(goal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE goals SET done_count = done_count + 1 WHERE id=?", (goal_id,))
    conn.commit()
    c.execute("SELECT done_count FROM goals WHERE id=?", (goal_id,))
    new_count = c.fetchone()[0]
    conn.close()
    return new_count

# ── REKLAMA SANOQ TIZIMI (XAR 10 TA ISHLATILGANDA REKLAMA) ────
async def increment_action_and_check_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_actions (user_id, count) VALUES (?, 0)", (user_id,))
    c.execute("UPDATE user_actions SET count = count + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT count FROM user_actions WHERE user_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.commit()
    conn.close()

    if count > 0 and count % 10 == 0:
        ad_text = get_setting("ad_text", "🌟 Foydali tavsiya! Botimizni doʻstlaringizga ham ulashing!")
        ad_msg = f"📢 <b>E'LON</b>\n\n{html.escape(ad_text)}{BOT_FOOTER}"
        await context.bot.send_message(user_id, ad_msg, parse_mode="HTML")

# ── BARCHA FOYDALANUVCHILARGA TARQATISH (BROADCAST) ─────────
async def broadcast_copy_to_all(context: ContextTypes.DEFAULT_TYPE, from_chat_id: int, message_id: int) -> tuple[int, int]:
    users = get_all_users()
    success = 0
    for uid in users:
        for attempt in range(3):
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id
                )
                success += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except (Forbidden, BadRequest):
                break
            except TelegramError as e:
                logger.error(f"Broadcast xatosi ({uid}): {e}")
                break
            except Exception as e:
                logger.error(f"Broadcast kutilmagan xatosi ({uid}): {e}")
                break
        await asyncio.sleep(0.05)
    return success, len(users)

# ── MAJBURIY OBUNA CHEKLOVI ─────────────────────────────────
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    channel = get_setting("required_channel", "")
    if not channel:
        return True

    user_id = update.effective_user.id
    if user_id in ADMIN_IDS or is_premium(user_id):
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        logger.error(f"Subscription check error for {channel}: {e}")
        return True

    channel_clean = channel.replace("@", "")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanalga obuna boʻlish", url=f"https://t.me/{channel_clean}")],
        [InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")]
    ])
    msg = (
        f"⚠️ <b>Botdan foydalanish uchun rasmiy kanalimizga obuna boʻling!</b>\n\n"
        f"Kanal: {html.escape(channel)}\n\n"
        f"Obuna boʻlgach, '✅ Obunani tekshirish' tugmasini bosing."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return False

# ── MENYULAR ─────────────────────────────────────────────────
def main_menu_keyboard():
    keyboard = [[KeyboardButton("🎯 Maqsad")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def back_keyboard(callback="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data=callback)]])

def admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton("📢 Tarqatish", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📩 Kelgan xabarlar", callback_data="admin_messages_list"),
         InlineKeyboardButton("📢 Majburiy obuna", callback_data="admin_req_sub")],
        [InlineKeyboardButton("📣 Reklama sozlash", callback_data="admin_set_ad"),
         InlineKeyboardButton("👤 Foydalanuvchi topish", callback_data="admin_find_user")],
        [InlineKeyboardButton("✉️ Maxsus xabar", callback_data="admin_special_msg"),
         InlineKeyboardButton("🎬 Video kodi qoʻshish", callback_data="admin_add_video_code")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ── START COMMAND ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.full_name)

    if not await check_subscription(update, context):
        return

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT special_start_msg FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        await update.message.reply_text(row[0])

    welcome = (
        f"Salom, <b>{html.escape(user.first_name or '')}</b>!\n\n"
        f"🎯 <b>Maqsad Bot</b>ga xush kelibsiz!\n\n"
        f"Maqsad qoʻyish uchun /maqsad buyrugʻini yuboring yoki pastdagi tugmani bosing."
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=main_menu_keyboard())

# ── ADMIN: PREMIUM BERISH ─────────────────────────────────────
async def premium_oldi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        target_id = int(context.args[0])
        set_premium(target_id)
        await update.message.reply_text(f"✅ {target_id} ga premium berildi!")
        await context.bot.send_message(
            target_id,
            f"🎉 Sizga <b>Premium</b> berildi!{BOT_FOOTER}",
            parse_mode="HTML"
        )
    except Exception:
        await update.message.reply_text("❌ Format: /Premiumoldi userid")

# ── ADMIN PANEL ───────────────────────────────────────────────
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Ruxsat yoʻq!")
        return
    await update.message.reply_text(
        "👑 <b>Admin Panel</b>\n\nBarcha boshqaruv menyusi:",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )

# ── MAQSAD (GOAL REMINDER) BO'LIMI ──────────────────────────
async def maqsad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Maqsad o'rnatish", callback_data="maqsad_new")]
    ])
    await update.message.reply_text(
        "🎯 <b>Maqsad rejalashtiruvchi</b>\n\n"
        "Yangi maqsad qo'yish uchun tugmani bosing:",
        parse_mode="HTML",
        reply_markup=kb
    )

async def send_goal_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    goal_id = job.data["goal_id"]
    goal = get_goal(goal_id)
    if not goal or not goal[7]:          # is_active == 0 boʻlsa toʻxtatiladi
        job.schedule_removal()
        return

    _, user_id, chat_id, name, target_count, sent_count, interval_minutes, is_active = goal
    increment_goal_sent(goal_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"maqsad_cancel_{goal_id}")]
    ])
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT done_count FROM goals WHERE id=?", (goal_id,))
    done_count = c.fetchone()[0]
    conn.close()

    text = (
        f"🔔 <b>{html.escape(name)}</b>\n\n"
        f"Maqsadni bajarish kerak! Men eslatdim, seni vijdoningga havola.\n\n"
        f"📸 Bajarganingizga isbot sifatida <b>rasm yoki video</b> yuboring.\n"
        f"📊 Tasdiqlangan: {done_count}/{target_count}"
    )
    try:
        await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error(f"Maqsad eslatma xatosi: {e}")

async def process_goal_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Foydalanuvchi rasm/video yuborsa va faol maqsadi bo'lsa, tasdiqlaydi. True qaytarsa - ishlov berilgan."""
    chat_id = update.effective_chat.id
    goal = get_active_goal_for_chat(chat_id)
    if not goal:
        return False

    goal_id, name, target_count, done_count, interval_minutes = goal
    new_done = increment_goal_done(goal_id)

    if new_done >= target_count:
        deactivate_goal(goal_id)
        for job in context.job_queue.get_jobs_by_name(f"goal_{goal_id}"):
            job.schedule_removal()
        await update.message.reply_text(
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"🎯 \"{html.escape(name)}\" maqsadi <b>{target_count}/{target_count}</b> — toʻliq bajarildi!",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"✅ Tasdiqlandi! {new_done}/{target_count}\n\nDavom eting, bot eslatib turadi 💪"
        )
    return True

# ── VIDEO KOD ORQALI YUBORISH ─────────────────────────────────
async def send_video_by_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user_id = update.effective_user.id
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT file_id, label, is_premium FROM video_codes WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()

    if not row:
        return

    file_id, label, is_prem = row
    if is_prem and user_id not in ADMIN_IDS and not is_premium(user_id):
        await update.message.reply_text("👑 Bu video faqat Premium foydalanuvchilar uchun!")
        return

    await update.message.reply_video(
        file_id,
        caption=f"🎬 {html.escape(label or '')}{BOT_FOOTER}"
    )

# ── ODDIY XABARLAR (TEXT) ─────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if not await check_subscription(update, context):
        return

    if text == "🎯 Maqsad":
        await maqsad_command(update, context)

    elif state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast(text[:200], user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Xabar {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")

    elif state == "set_required_channel" and user_id in ADMIN_IDS:
        channel = text.strip()
        if not channel.startswith("@") and not channel.startswith("-100"):
            channel = "@" + channel
        set_setting("required_channel", channel)
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ Majburiy obuna kanali oʻrnatildi: {channel}")

    elif state == "set_ad_text" and user_id in ADMIN_IDS:
        set_setting("ad_text", text)
        context.user_data["state"] = None
        await update.message.reply_text("✅ Reklama matni muvaffaqiyatli saqlandi!")

    elif state and state.startswith("admin_reply_"):
        target_id = int(state.replace("admin_reply_", ""))
        try:
            await context.bot.send_message(
                target_id,
                f"📩 <b>Admin javobi:</b>\n\n{html.escape(text)}{BOT_FOOTER}",
                parse_mode="HTML"
            )
            await update.message.reply_text(f"✅ Javob foydalanuvchi <code>{target_id}</code> ga yuborildi!", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Javob yuborishda xatolik: {e}")
        context.user_data["state"] = None

    elif state and state.startswith("set_special_msg_"):
        target_id = int(state.replace("set_special_msg_", ""))
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET special_start_msg=? WHERE user_id=?", (text, target_id))
        conn.commit()
        conn.close()
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ {target_id} uchun maxsus xabar oʻrnatildi!")

    elif state == "admin_special_id" and user_id in ADMIN_IDS:
        try:
            target_id = int(text)
            context.user_data["state"] = f"set_special_msg_{target_id}"
            await update.message.reply_text(
                f"✅ ID topildi: <code>{target_id}</code>\n\nEndi maxsus xabarni yozing:",
                parse_mode="HTML"
            )
        except Exception:
            await update.message.reply_text("❌ Notoʻgʻri ID! Raqam kiriting.")

    elif state == "admin_find" and user_id in ADMIN_IDS:
        try:
            target_id = int(text)
            conn = sqlite3.connect("bot.db")
            c = conn.cursor()
            c.execute("SELECT user_id, username, full_name, joined_at, is_premium FROM users WHERE user_id=?", (target_id,))
            row = c.fetchone()
            conn.close()
            if row:
                uid, uname, fname, joined, prem = row
                await update.message.reply_text(
                    f"👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
                    f"🆔 ID: <code>{uid}</code>\n"
                    f"👤 Ism: {html.escape(fname or '')}\n"
                    f"📛 Username: @{html.escape(uname or 'yoq')}\n"
                    f"📅 Qoʻshilgan: {joined[:10]}\n"
                    f"👑 Premium: {'✅' if prem else '❌'}",
                    parse_mode="HTML",
                    reply_markup=back_keyboard("admin_back")
                )
            else:
                await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
        except Exception:
            await update.message.reply_text("❌ Notoʻgʻri ID!")
        context.user_data["state"] = None

    elif state == "admin_video_label" and user_id in ADMIN_IDS:
        context.user_data["temp_video_label"] = text
        context.user_data["state"] = "admin_video_type"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 Premium", callback_data="vtype_premium"),
             InlineKeyboardButton("🆓 Oddiy", callback_data="vtype_regular")]
        ])
        await update.message.reply_text("Bu video qanday turda boʻlsin?", reply_markup=kb)

    elif state == "admin_video_number" and user_id in ADMIN_IDS:
        code = text.strip()
        fid = context.user_data.get("temp_video_file_id")
        label = context.user_data.get("temp_video_label", "")
        is_prem = context.user_data.get("temp_video_premium", 0)
        if not fid:
            await update.message.reply_text("❌ Xatolik: video topilmadi, qaytadan boshlang.")
        else:
            conn = sqlite3.connect("bot.db")
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO video_codes (code, file_id, label, is_premium, added_at) VALUES (?,?,?,?,?)",
                      (code, fid, label, is_prem, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            await update.message.reply_text(
                f"✅ Video saqlandi!\n\n🔢 Kod: <code>{html.escape(code)}</code>\n🏷 Nom: {html.escape(label)}\n👑 Turi: {'Premium' if is_prem else 'Oddiy'}",
                parse_mode="HTML"
            )
        context.user_data["state"] = None
        context.user_data.pop("temp_video_file_id", None)
        context.user_data.pop("temp_video_label", None)
        context.user_data.pop("temp_video_premium", None)

    elif state == "maqsad_name_input":
        context.user_data["maqsad_name"] = text.strip()
        context.user_data["state"] = "maqsad_count_input"
        await update.message.reply_text(
            "🔢 Necha marta rasm/video bilan tasdiqlashingiz kerak? (1-100 oralig'ida son kiriting):"
        )

    elif state == "maqsad_count_input":
        try:
            count = int(text.strip())
            if not (1 <= count <= 100):
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ 1 dan 100 gacha son kiriting!")
            return
        context.user_data["maqsad_count"] = count
        context.user_data["state"] = "maqsad_interval_input"
        await update.message.reply_text("⏰ Necha daqiqadan keyin birinchi eslatma kelsin? (masalan: 30):")

    elif state == "maqsad_interval_input":
        try:
            interval = int(text.strip())
            if interval < 1:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ To'g'ri daqiqa kiriting (masalan: 30)!")
            return

        name = context.user_data.get("maqsad_name", "Maqsad")
        count = context.user_data.get("maqsad_count", 10)
        chat_id = update.message.chat_id

        goal_id = create_goal(user_id, chat_id, name, count, interval)
        context.job_queue.run_repeating(
            send_goal_reminder,
            interval=60,
            first=interval * 60,
            data={"goal_id": goal_id},
            name=f"goal_{goal_id}",
            chat_id=chat_id
        )

        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ Maqsad o'rnatildi!\n\n"
            f"🎯 Nomi: {html.escape(name)}\n"
            f"🔢 Tasdiqlash soni: {count} marta (rasm/video orqali)\n"
            f"⏰ Birinchi eslatma: {interval} daqiqadan keyin, keyin har daqiqada.\n\n"
            f"📸 Mashqni bajarganingizga isbot sifatida rasm yoki video yuboring — "
            f"{count} marta tasdiqlamaguningizcha bot eslatib turadi!",
            parse_mode="HTML"
        )
        await increment_action_and_check_ad(update, context)

    else:
        if text and text.strip().isdigit():
            await send_video_by_code(update, context, text.strip())

# ── CALLBACK (INLINE TUGMALAR) ────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "check_sub":
        if await check_subscription(update, context):
            await query.edit_message_text("✅ Rahmat! Obuna tasdiqlandi. Endi botdan foydalanishingiz mumkin.")
            await context.bot.send_message(user_id, "🏠 Asosiy menyu:", reply_markup=main_menu_keyboard())

    elif data == "back_main":
        context.user_data["state"] = None
        await query.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard())
        try:
            await query.message.delete()
        except Exception:
            pass

    elif data == "maqsad_new":
        context.user_data["state"] = "maqsad_name_input"
        await query.edit_message_text("📝 Maqsad nomini kiriting (masalan: 20 ta o'qish):")

    elif data.startswith("maqsad_cancel_"):
        goal_id = int(data.replace("maqsad_cancel_", ""))
        deactivate_goal(goal_id)
        for job in context.job_queue.get_jobs_by_name(f"goal_{goal_id}"):
            job.schedule_removal()
        await query.edit_message_text("🛑 Maqsad bekor qilindi. Eslatmalar toʻxtatildi.")

    elif data == "admin_stats" and user_id in ADMIN_IDS:
        total, premium = get_stats()
        await query.edit_message_text(
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"👑 Premium: {premium}\n"
            f"📢 Majburiy obuna kanali: <code>{html.escape(get_setting('required_channel', 'Yoq'))}</code>\n"
            f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_broadcast" and user_id in ADMIN_IDS:
        context.user_data["state"] = "broadcast"
        await query.edit_message_text(
            "📢 <b>Barcha foydalanuvchilarga tarqatish</b>\n\n"
            "Xabarni yuboring (Matn, rasm, video, GIF, stiker, audio, fayl). Bot uni barcha foydalanuvchilarga nusxalab yuboradi!",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_req_sub" and user_id in ADMIN_IDS:
        curr = get_setting("required_channel", "O'rnatilmagan")
        context.user_data["state"] = "set_required_channel"
        await query.edit_message_text(
            f"📢 <b>Majburiy Obuna Sozlanmasi</b>\n\nHozirgi kanal: <code>{html.escape(curr)}</code>\n\n"
            f"Yangi kanal username'ini yozing (Masalan: <code>@kanalim</code>):",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_set_ad" and user_id in ADMIN_IDS:
        curr_ad = get_setting("ad_text", "Standart")
        context.user_data["state"] = "set_ad_text"
        await query.edit_message_text(
            f"📣 <b>Reklama Matni Sozlanmasi</b>\n\nHozirgi reklama:\n<code>{html.escape(curr_ad)}</code>\n\n"
            f"Yangi reklama matnini kiriting:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_messages_list" and user_id in ADMIN_IDS:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("SELECT id, user_id, user_name, message_text, sent_at FROM admin_messages ORDER BY id DESC LIMIT 5")
        rows = c.fetchall()
        conn.close()

        if not rows:
            await query.edit_message_text("📭 Foydalanuvchilardan xabarlar kelmagan.", reply_markup=back_keyboard("admin_back"))
            return

        txt = "📩 <b>Oxirgi foydalanuvchi xabarlari:</b>\n\n"
        buttons = []
        for mid, uid, uname, mtext, sat in rows:
            safe_uname = html.escape(uname or "")
            safe_mtext = html.escape(mtext or "")
            txt += f"🆔 <code>{uid}</code> ({safe_uname}):\n\"{safe_mtext}\"\n📅 {sat[:16]}\n\n"
            buttons.append([InlineKeyboardButton(f"💬 Javob berish: {uname}", callback_data=f"reply_msg_{uid}")])
        buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])

        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("reply_msg_") and user_id in ADMIN_IDS:
        target_id = int(data.replace("reply_msg_", ""))
        context.user_data["state"] = f"admin_reply_{target_id}"
        await query.edit_message_text(
            f"💬 Foydalanuvchi <code>{target_id}</code> ga yuboriladigan javobingizni kiriting:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_find_user" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_find"
        await query.edit_message_text("🔍 Foydalanuvchi ID sini kiriting:", reply_markup=back_keyboard("admin_back"))

    elif data == "admin_special_msg" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_special_id"
        await query.edit_message_text(
            "✉️ <b>Maxsus start xabari</b>\n\nAvval foydalanuvchi ID sini kiriting:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_add_video_code" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_video_upload"
        await query.edit_message_text(
            "🎬 <b>Video kod qoʻshish</b>\n\nVideoni yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "vtype_premium" and user_id in ADMIN_IDS:
        context.user_data["temp_video_premium"] = 1
        context.user_data["state"] = "admin_video_number"
        await query.edit_message_text("🔢 Endi bu video uchun raqam (kod) kiriting:")

    elif data == "vtype_regular" and user_id in ADMIN_IDS:
        context.user_data["temp_video_premium"] = 0
        context.user_data["state"] = "admin_video_number"
        await query.edit_message_text("🔢 Endi bu video uchun raqam (kod) kiriting:")

    elif data == "admin_back" and user_id in ADMIN_IDS:
        await query.edit_message_text("👑 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=admin_menu_keyboard())

# ── MEDIA (RASM/VIDEO/BOSHQA) — FAQAT BROADCAST VA VIDEO-KOD UCHUN ──
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if not await check_subscription(update, context):
        return

    if state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast("[rasm]", user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Rasm {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")
        return

    await process_goal_proof(update, context)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if not await check_subscription(update, context):
        return

    if state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast("[video]", user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Video {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")
        return

    video_obj = update.message.video or update.message.video_note
    if not video_obj:
        return

    if state == "admin_video_upload" and user_id in ADMIN_IDS:
        context.user_data["temp_video_file_id"] = video_obj.file_id
        context.user_data["state"] = "admin_video_label"
        await update.message.reply_text("✅ Video qabul qilindi!\n\n📝 Endi bu video uchun nom (label) kiriting:")
        return

    await process_goal_proof(update, context)

async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if not await check_subscription(update, context):
        return

    if state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast("[media]", user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Media {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")

# ── MAIN FUNKSIYA ───────────────────────────────────────────
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("maqsad", maqsad_command))
    app.add_handler(CommandHandler("Premiumoldi", premium_oldi))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.ANIMATION | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.Sticker.ALL, handle_other_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Maqsad Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
