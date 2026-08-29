# ============================================================
# UNIVERSAL TELEGRAM BOT - TO'LIQ VA YANGILANGAN 
# Kerakli kutubxonalar:
# pip install python-telegram-bot==20.7 Pillow qrcode[pil] gtts
# ============================================================

import logging
import sqlite3
import os
import io
import html
import asyncio
import random
import tempfile
import subprocess
from datetime import datetime
import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InputSticker,
    ReactionTypeEmoji
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ChatMemberHandler, ContextTypes, filters
)
from telegram.error import RetryAfter, Forbidden, BadRequest, TelegramError
import qrcode
from openai import OpenAI as BytezOpenAI
from gtts import gTTS
from PIL import Image
import google.generativeai as genai

# ── SOZLAMALAR ──────────────────────────────────────────────
# Token va Admin ID lar endi muhit o'zgaruvchilaridan (environment variables) o'qiladi.
# Railway/PythonAnywhere kabi platformalarda "Variables" bo'limiga quyidagilarni qo'shing:
#   BOT_TOKEN=123456:ABC-...
#   ADMIN_IDS=7329434421,111111111   (bir nechta admin bo'lsa vergul bilan ajrating)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# Railway Volume mount path'i (masalan "/data") + baza fayli nomi.
# Agar DB_DIR o'zgaruvchisi berilmasa, joriy papkada ("bot.db") ishlatiladi.
DB_DIR = os.environ.get("DB_DIR", "/data")
DB_PATH = os.path.join(DB_DIR, "bot.db")
# Papka mavjud bo'lmasa (Volume ulanmagan yoki bo'sh bo'lsa ham), xatolik bermasligi uchun yaratib qo'yamiz.
try:
    os.makedirs(DB_DIR, exist_ok=True)
except Exception as _e:
    logging.warning(f"DB_DIR ({DB_DIR}) yaratib bo'lmadi: {_e}")

# BIR MARTALIK KO'CHIRISH: agar Volume ichida hali bazasi bo'lmasa, lekin repo bilan
# birga yuklangan eski bot.db mavjud bo'lsa — uni Volume'ga ko'chiramiz.
# Ko'chirilgandan keyin Volume'dagi fayl saqlanib qoladi, keyingi deploy'larda qayta ko'chirilmaydi.
_BUNDLED_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
if not os.path.exists(DB_PATH) and os.path.exists(_BUNDLED_DB_PATH):
    try:
        import shutil
        shutil.copy2(_BUNDLED_DB_PATH, DB_PATH)
        logging.info(f"Eski bot.db muvaffaqiyatli ko'chirildi: {_BUNDLED_DB_PATH} -> {DB_PATH}")
    except Exception as _e:
        logging.warning(f"Eski bot.db'ni ko'chirib bo'lmadi: {_e}")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
REMBG_API_KEY = os.environ.get("REMBG_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.5-flash")
else:
    gemini_model = None
BYTEZ_API_KEY = "9f212dbd7879edfd0850f9610a28178b"

PROVIDER_KEYS = {
    "openai": None,
    "anthropic": None,
    "google": None,
    "mistral": None,
    "cohere": None,
}

AI_MODELS = [
    ("google", "google/gemini-2.0-flash"),
    ("openai", "openai/gpt-4o-mini"),
    ("mistral", "mistralai/mistral-small-latest"),
    ("cohere", "cohere/command-r"),
    ("anthropic", "anthropic/claude-3-5-haiku-latest"),
]

bytez_client = BytezOpenAI(
    api_key=BYTEZ_API_KEY,
    base_url="https://api.bytez.com/models/v2/openai/v1"
)
ADMIN_USERNAME = "@alijonov_ff"
BOT_USERNAME = "@kerakli_boladi_bot"
BOT_FOOTER = f"\n\n🤖 {BOT_USERNAME}"

# Kanalga avto-reaksiya uchun standart emoji ro'yxati
DEFAULT_REACTION_EMOJIS = ["👍", "❤️", "🔥", "🎉", "😁", "🤔", "😍", "👏", "🥳", "💯"]

# Limitlar
LIMITS = {
    "password": 7,
    "qr": 10,
    "tts": 10,
    "compress": 10,
    "convert": 10,
    "audio_extract": 10,
    "sticker": 15,
    "circle_video": 10,
    "bg_remove": 10,
    "upscale_4k": 10,
}

REFERRAL_BONUS = {
    "password": (5, 5),
    "qr":       (5, 5),
    "tts":      (5, 10),
    "compress": (5, 10),
    "convert":  (5, 10),
    "audio_extract": (5, 5),
    "sticker":  (5, 10),
    "circle_video": (5, 5),
    "bg_remove": (5, 5),
    "upscale_4k": (5, 5),
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DATABASE INIZIALIZATSIYASI ───────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        joined_at TEXT,
        referred_by INTEGER,
        referral_count INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0,
        special_start_msg TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS passwords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        label TEXT,
        password TEXT,
        created_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS usage_stats (
        user_id INTEGER,
        feature TEXT,
        used_today INTEGER DEFAULT 0,
        last_reset TEXT,
        PRIMARY KEY (user_id, feature)
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

    c.execute("""CREATE TABLE IF NOT EXISTS user_stickers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_id TEXT,
        created_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS video_codes (
        code TEXT PRIMARY KEY,
        file_id TEXT,
        label TEXT,
        is_premium INTEGER DEFAULT 0,
        added_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS bot_channels (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        username TEXT,
        added_by INTEGER,
        added_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS word_files (
        word TEXT PRIMARY KEY,
        file_id TEXT,
        file_type TEXT,
        label TEXT,
        added_at TEXT
    )""")
    conn.commit()
    conn.close()

# ── BOT QO'SHILGAN KANALLAR ──────────────────────────────────
def add_bot_channel(chat_id, title, username, added_by):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_channels (chat_id, title, username, added_by, added_at) VALUES (?,?,?,?,?)",
              (chat_id, title, username, added_by, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_bot_channel(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bot_channels WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

def get_bot_channels():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, title, username FROM bot_channels")
    rows = c.fetchall()
    conn.close()
    return rows

def is_bot_channel(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM bot_channels WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return bool(row)

def get_bot_channels_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM bot_channels")
    n = c.fetchone()[0]
    conn.close()
    return n

# ── SO'Z BILAN FAYL YUBORISH ──────────────────────────────────
def save_word_file(word, file_id, file_type, label=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO word_files (word, file_id, file_type, label, added_at) VALUES (?,?,?,?,?)",
              (word.lower().strip(), file_id, file_type, label, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_word_file(word):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT file_id, file_type, label FROM word_files WHERE word=?", (word.lower().strip(),))
    row = c.fetchone()
    conn.close()
    return row

async def send_file_by_word(update: Update, context: ContextTypes.DEFAULT_TYPE, word: str):
    row = get_word_file(word)
    if not row:
        return
    file_id, file_type, label = row
    caption = f"📁 {html.escape(label)}{BOT_FOOTER}" if label else BOT_FOOTER
    try:
        if file_type == "photo":
            await update.message.reply_photo(file_id, caption=caption, parse_mode="HTML")
        elif file_type == "video":
            await update.message.reply_video(file_id, caption=caption, parse_mode="HTML")
        elif file_type == "audio":
            await update.message.reply_audio(file_id, caption=caption, parse_mode="HTML")
        elif file_type == "voice":
            await update.message.reply_voice(file_id, caption=caption, parse_mode="HTML")
        elif file_type == "animation":
            await update.message.reply_animation(file_id, caption=caption, parse_mode="HTML")
        elif file_type == "sticker":
            await update.message.reply_sticker(file_id)
        else:
            await update.message.reply_document(file_id, caption=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"So'z bilan fayl yuborish xatosi: {e}")

# ── KANALLARGA REKLAMA (FORWARD, NUSXALAMASDAN) ──────────────
async def broadcast_forward_to_channels(context: ContextTypes.DEFAULT_TYPE, from_chat_id: int, message_id: int) -> tuple[int, int]:
    channels = get_bot_channels()
    success = 0
    for chat_id, title, username in channels:
        for attempt in range(3):
            try:
                await context.bot.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
                success += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except (Forbidden, BadRequest):
                break
            except TelegramError as e:
                logger.error(f"Kanalga reklama xatosi ({chat_id}): {e}")
                break
            except Exception as e:
                logger.error(f"Kanalga reklama kutilmagan xatosi ({chat_id}): {e}")
                break
        await asyncio.sleep(0.05)
    return success, len(channels)

# ── DB YORDAMCHI FUNKSIYALARI ───────────────────────────────
def get_setting(key, default=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def add_user(user_id, username, full_name, referred_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("""INSERT INTO users
            (user_id, username, full_name, joined_at, referred_by, referral_count, is_premium)
            VALUES (?,?,?,?,?,0,0)""",
            (user_id, username, full_name, datetime.now().isoformat(), referred_by))
        conn.commit()
        if referred_by:
            c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?",
                      (referred_by,))
            conn.commit()
    conn.close()

def is_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_premium FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == 1

def set_premium(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium=1")
    premium = c.fetchone()[0]
    conn.close()
    return total, premium

def log_broadcast(message, sent_by):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO broadcast_log (message, sent_at, sent_by) VALUES (?,?,?)",
              (message, datetime.now().isoformat(), sent_by))
    conn.commit()
    conn.close()

def get_referral_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT referral_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_limit(user_id, feature):
    base = LIMITS.get(feature, 5)
    if is_premium(user_id):
        return 9999
    ref_count = get_referral_count(user_id)
    needed, bonus = REFERRAL_BONUS.get(feature, (5, 0))
    extra = (ref_count // needed) * bonus
    return base + extra

def get_used_today(user_id, feature):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT used_today, last_reset FROM usage_stats WHERE user_id=? AND feature=?",
              (user_id, feature))
    row = c.fetchone()
    if not row or row[1] != today:
        c.execute("""INSERT OR REPLACE INTO usage_stats (user_id, feature, used_today, last_reset)
                     VALUES (?,?,0,?)""", (user_id, feature, today))
        conn.commit()
        conn.close()
        return 0
    conn.close()
    return row[0]

def increment_usage(user_id, feature):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""INSERT OR REPLACE INTO usage_stats (user_id, feature, used_today, last_reset)
                 VALUES (?,?, COALESCE((SELECT used_today FROM usage_stats
                 WHERE user_id=? AND feature=? AND last_reset=?),0)+1, ?)""",
              (user_id, feature, user_id, feature, today, today))
    conn.commit()
    conn.close()

def check_limit(user_id, feature):
    used = get_used_today(user_id, feature)
    limit = get_limit(user_id, feature)
    return used >= limit

# ── REKLAMA SANOQ TIZIMI (XAR 10 TA ISHLATILGANDA REKLAMA) ────
async def increment_action_and_check_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_actions (user_id, count) VALUES (?, 0)", (user_id,))
    c.execute("UPDATE user_actions SET count = count + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT count FROM user_actions WHERE user_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.commit()
    conn.close()

    if count > 0 and count % 10 == 0:
        ad_text = get_setting("ad_text", "🌟 Foydali tavsiya! Botimizni do'stlaringizga ham ulashing va limitlarni bepul oshiring!")
        ad_msg = f"📢 <b>E'LON  </b>\n\n{html.escape(ad_text)}{BOT_FOOTER}"
        await context.bot.send_message(user_id, ad_msg, parse_mode="HTML")

# ── BARCHA FOYDALANUVCHILARGA TARQATISH (BROADCAST) ─────────
async def broadcast_copy_to_all(context: ContextTypes.DEFAULT_TYPE, from_chat_id: int, message_id: int) -> tuple[int, int]:
    """Berilgan xabarni barcha foydalanuvchilarga nusxalab yuboradi.

    Avvalgi kodda xatolik sabab (bare except) Telegramning flood-control
    (RetryAfter) javobi jimgina yutilib, ko'p foydalanuvchiga xabar yetib
    bormas edi. Bu funksiya:
      - RetryAfter kelsa, ko'rsatilgan vaqt kutib, o'sha foydalanuvchiga
        qayta urinadi (xabar tashlab yuborilmaydi);
      - botni bloklagan/faylni topa olmagan foydalanuvchilarni (Forbidden/
        BadRequest) xato sifatida emas, kutilgan holat sifatida o'tkazib
        yuboradi;
      - har bir yuborishdan keyin qisqa pauza qo'yib, Telegramning
        umumiy tezlik limitiga (~30 xabar/soniya) tushib qolmaslikni
        ta'minlaydi.
    """
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
        [InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{channel_clean}")],
        [InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")]
    ])
    msg = (
        f"⚠️ <b>Botdan foydalanish uchun rasmiy kanalimizga obuna bo'ling!</b>\n\n"
        f"Kanal: {html.escape(channel)}\n\n"
        f"Obuna bo'lgach, '✅ Obunani tekshirish' tugmasini bosing."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
    return False

# ── MENYULAR ─────────────────────────────────────────────────
def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🛠 Foydali botlar"), KeyboardButton("🎬 Videodan ovoz")],
        [KeyboardButton("🎥 Dumaloq video"), KeyboardButton("🖼 Stiker yaratish")],
        [KeyboardButton("🔐 Parollar"), KeyboardButton("👥 Do'stlarni taklif")],
        [KeyboardButton("📊 Mening hisobim")],
        [KeyboardButton("🤖 AI Yordamchi")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main_menu_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("🛠 Foydali botlar", callback_data="menu_useful_bots"),
         InlineKeyboardButton("🎬 Videodan ovoz", callback_data="menu_audio_extract")],
        [InlineKeyboardButton("🎥 Dumaloq video", callback_data="menu_circle_video"),
         InlineKeyboardButton("🖼 Stiker yaratish", callback_data="menu_sticker")],
        [InlineKeyboardButton("🔐 Parollar", callback_data="menu_passwords"),
         InlineKeyboardButton("👥 Do'stlarni taklif", callback_data="menu_referral")],
        [InlineKeyboardButton("📊 Mening hisobim", callback_data="menu_account")],
        [InlineKeyboardButton("🤖 AI Yordamchi", callback_data="menu_ai")],
    ]
    return InlineKeyboardMarkup(keyboard)

def useful_bots_keyboard():
    keyboard = [
        [InlineKeyboardButton("📷 QR Generator", callback_data="qr_gen"),
         InlineKeyboardButton("🔊 Matn → Tovush", callback_data="tts")],
        [InlineKeyboardButton("🗜 Rasm siqish", callback_data="compress"),
         InlineKeyboardButton("🔄 Fayl konvertor", callback_data="convert")],
        [InlineKeyboardButton("📩 Admin bilan bog'lanish", callback_data="contact_admin")],
        [InlineKeyboardButton("🪄 Fon o'chirish", callback_data="bg_remove"),
         InlineKeyboardButton("📐 4K rasm", callback_data="upscale_4k")],
        [InlineKeyboardButton("🔥 Kanalga avto-reaksiya", callback_data="info_avto_reaction")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard(callback="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data=callback)]])

async def _reply_or_edit(update, text, reply_markup=None, parse_mode="HTML"):
    if update.message:
        await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)

async def show_useful_bots_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    await _reply_or_edit(
        update,
        "🛠 <b>Foydali botlar</b>\n\nBo'limni tanlang:",
        reply_markup=useful_bots_keyboard()
    )

async def start_audio_extract_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["state"] = "audio_extract_input"
    used = get_used_today(user_id, "audio_extract")
    limit = get_limit(user_id, "audio_extract")
    await _reply_or_edit(
        update,
        f"🎬 <b>Videodan ovozni ajratish</b>\n\n"
        f"📊 Bugungi: {used}/{limit}\n\n"
        f"Ovozini ajratib olmoqchi bo'lgan videongizni yuboring (Video yoki Video Note):",
        reply_markup=back_keyboard("back_main")
    )

async def start_circle_video_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["state"] = "circle_video_input"
    used = get_used_today(user_id, "circle_video")
    limit = get_limit(user_id, "circle_video")
    await _reply_or_edit(
        update,
        f"🎥 <b>Dumaloq video (Video Note) yaratish</b>\n\n"
        f"📊 Bugungi: {used}/{limit}\n\n"
        f"Dumaloq ko'rinishga keltirmoqchi bo'lgan videongizni yuboring:",
        reply_markup=back_keyboard("back_main")
    )

async def show_sticker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Oddiy stiker (bitta)", callback_data="sticker_single")],
        [InlineKeyboardButton("📦 Stiker Pack (to'plam yig'ish)", callback_data="sticker_pack")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")]
    ])
    await _reply_or_edit(
        update,
        "🖼 <b>Stiker Yaratish Bo'limi</b>\n\nQaysi usulda stiker yaratmoqchisiz?",
        reply_markup=kb
    )

async def start_ai_chat_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "ai_chat"
    await _reply_or_edit(update, "🤖 Savolingizni yozing!", reply_markup=None)

# ── START COMMAND ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0].replace("ref_", ""))
            if referred_by == user.id:
                referred_by = None
        except Exception:
            referred_by = None

    add_user(user.id, user.username, user.full_name, referred_by)

    # Obunani tekshirish
    if not await check_subscription(update, context):
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT special_start_msg FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()

    special_msg = row[0] if row and row[0] else None

    if special_msg:
        await update.message.reply_text(special_msg)

    welcome = (
        f" Salom , <b>{html.escape(user.first_name or '')}</b>!\n\n"
        f"🤖 <b> Yordamchi Bot</b>ga xush kelibsiz!\n\n"
        f"📌 Kerakli bo'limni tanlang:"
    )
    await update.message.reply_text(
        welcome,
        parse_mode="HTML",
        reply_markup=main_menu_inline_keyboard()
    )
    await update.message.reply_text(
        "🚀 Mini App orqali barcha xaridlar tarixi va statistikani ko'rishingiz mumkin:",
        reply_markup=get_mini_app_keyboard()
    )
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Asosiy menyu:\n\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=main_menu_inline_keyboard()
    )
# ── PREMIUM COMMAND ───────────────────────────────────────────
async def premium_oldi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        target_id = int(context.args[0])
        set_premium(target_id)
        await update.message.reply_text(f"✅ {target_id} ga premium berildi!")
        await context.bot.send_message(
            target_id,
            f"🎉 Sizga <b>Premium</b> berildi! Barcha limitlar ochildi!{BOT_FOOTER}",
            parse_mode="HTML"
        )
    except Exception:
        await update.message.reply_text("❌ Format: /Premiumoldi userid")
async def mini_app_premium_tasdiqla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        res= requests.post(f"{MINI_APP_URL}/api/bot/grant-premium", json={
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "item_title": "VIP Premium (Mini App orqali)"
        })
        await update.message.reply_text(
            f"🎉 Tabriklaymiz, {user.first_name}! Sizga VIP Premium maqomi faollashtirildi!"
        )
    except Exception as e:
        await update.message.reply_text("Xatolik: Mini App bilan bog'lanib bo'lmadi.")

# ── HISOBIM ───────────────────────────────────────────────────
async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ref_count = get_referral_count(user_id)
    premium_status = "✅ Premium" if is_premium(user_id) else "❌ Oddiy"
    ref_link = f"https://t.me/{BOT_USERNAME.replace('@', '')}?start=ref_{user_id}"

    text = (
        f"📊 <b>Mening hisobim</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👑 Status: {premium_status}\n"
        f"👥 Taklif qilganlar: {ref_count} ta\n\n"
        f"🔗 Mening havolam:\n<code>{html.escape(ref_link)}</code>{BOT_FOOTER}"
    )
    await _reply_or_edit(update, text, reply_markup=back_keyboard("back_main"))

# ── RASMNI 4K'GA KATTALASHTIRISH ─────────────────────────────
def upscale_image_to_4k(image_bytes: bytes) -> tuple[bytes, tuple[int, int], tuple[int, int]]:
    """Rasmni Lanczos interpolatsiyasi bilan uzun tomoni ~3840px bo'lguncha kattalashtiradi.
    Eslatma: bu chinakam AI-detallashtirish emas, silliq kattalashtirish (upscale)."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")
    w, h = img.size
    target_long_side = 3840
    long_side = max(w, h)

    if long_side >= target_long_side:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=95)
        out.seek(0)
        return out.getvalue(), (w, h), (w, h)

    scale = target_long_side / long_side
    new_size = (int(w * scale), int(h * scale))
    upscaled = img.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    upscaled.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.getvalue(), (w, h), new_size

# ── STIKER YARATISH FUNKSIYALARI ──────────────────────────────
def create_sticker_from_image_bytes(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGBA")

    max_size = 512
    w, h = img.size
    if w > h:
        new_w = max_size
        new_h = int(h * (max_size / w))
    else:
        new_h = max_size
        new_w = int(w * (max_size / h))

    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    offset = ((512 - new_w) // 2, (512 - new_h) // 2)
    canvas.paste(img, offset, img)

    out = io.BytesIO()
    canvas.save(out, format="WEBP")
    out.seek(0)
    return out.getvalue()

# ── DUMALOQ VIDEO YASASH FUNKSIYASI (FFmpeg, progress bar bilan) ─
async def _get_video_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def make_progress_bar(percent: int) -> str:
    filled = min(10, max(0, percent // 10))
    unfilled = 10 - filled
    bar = "█" * filled + "░" * unfilled
    return f"{percent}% {bar}"

async def remove_background(image_bytes: bytes, progress_cb=None) -> bytes:
    if progress_cb:
        await progress_cb(10, "Rasm yuklanmoqda...")

    def _do_request():
        resp = requests.post(
            "https://api.rembg.com/rmbg",
            headers={"x-api-key": REMBG_API_KEY},
            files={"image": ("photo.jpg", image_bytes)},
            data={"format": "png"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.content

    task = asyncio.create_task(asyncio.to_thread(_do_request))

    percent = 15
    while not task.done():
        await asyncio.sleep(1.2)
        if percent < 85:
            percent += 12
            if progress_cb:
                await progress_cb(min(percent, 85), "Fon o'chirilmoqda...")

    result = await task
    if progress_cb:
        await progress_cb(100, "Tayyor!")
    return result

# ── DUMALOQ VIDEO YASASH FUNKSIYASI (FFmpeg) ─────────────────
async def convert_to_circle_video(video_bytes: bytes, progress_cb=None) -> bytes:
    if progress_cb:
        await progress_cb(20, "Vaqtincha xotiraga yozilmoqda...")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + "_circle.mp4"

    try:
        if progress_cb:
            await progress_cb(30, "Format tahlil qilinmoqda...")

        # FFmpeg: Har qanday video formatni 1:1 kvadrat kesish, yuv420p va Telegram Video Note formatiga keltirish
        cmd = [
            "ffmpeg", "-y",
            "-i", tmp_in_path,
            "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=512:512,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-t", "60",
            tmp_out_path
        ]

        if progress_cb:
            await progress_cb(40, "Kadrlar 1:1 kadrga kesilmoqda...")

        async def run_progress_ticks():
            steps = [
                (50, "Dumaloq shaklga keltirilmoqda..."),
                (60, "Kadrlar ishlanmoqda..."),
                (70, "Ovoz va video birlashtirilmoqda..."),
                (80, "Optimal sifatga keltirilmoqda...")
            ]
            for pct, lbl in steps:
                await asyncio.sleep(0.4)
                if progress_cb:
                    await progress_cb(pct, lbl)

        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        prog_task = asyncio.create_task(run_progress_ticks())
        await proc.communicate()
        prog_task.cancel()

        if progress_cb:
            await progress_cb(90, "Fayl tayyorlanmoqda...")

        with open(tmp_out_path, "rb") as f:
            circle_bytes = f.read()

        if progress_cb:
            await progress_cb(100, "Tayyor!")

        return circle_bytes
    finally:
        if os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)

# ── VIDEODAN OVOZ AJRATISH FUNKSIYASI (FFmpeg) ────────────────
def _run_audio_extract_sync(video_bytes: bytes) -> bytes:
    """Bloklovchi FFmpeg va fayl operatsiyalari uchun yordamchi funksiya —
    asyncio.to_thread orqali alohida oqimda chaqiriladi."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".mp3"

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", tmp_in_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            tmp_out_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        with open(tmp_out_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)


async def extract_audio_from_video(video_bytes: bytes) -> bytes:
    return await asyncio.to_thread(_run_audio_extract_sync, video_bytes)

# ── KANALGA AVTO-REAKSIYA (o'z-o'zidan ro'yxatga qo'shiluvchi) ─
REACTION_COOLDOWN_SECONDS = 300  # 5 daqiqa

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot biror kanalga admin qilib qo'shilganda yoki olib tashlanganda ishga tushadi."""
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    if chat.type != "channel":
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    added_by = result.from_user

    if new_status == "administrator" and old_status != "administrator":
        add_bot_channel(chat.id, chat.title, chat.username, added_by.id if added_by else None)
        if added_by:
            try:
                await context.bot.send_message(
                    added_by.id,
                    f"✅ Botni <b>{html.escape(chat.title or '')}</b> kanaliga administrator qilib qo'shdingiz!\n\n"
                    f"Endi bu kanaldagi yangi postlarga avtomatik ravishda tasodifiy 1 ta emoji bilan reaksiya bildiriladi "
                    f"(har {REACTION_COOLDOWN_SECONDS // 60} daqiqada bir marta).{BOT_FOOTER}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Kanal admin xabari yuborilmadi: {e}")
    elif new_status in ("left", "kicked", "member") and old_status == "administrator":
        remove_bot_channel(chat.id)

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post:
        return

    if get_setting("avto_reaction_enabled", "1") != "1":
        return

    if not is_bot_channel(post.chat.id):
        return

    cooldown_key = f"last_reaction_at:{post.chat.id}"
    last_at = get_setting(cooldown_key, "")
    if last_at:
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_at)).total_seconds()
            if elapsed < REACTION_COOLDOWN_SECONDS:
                return
        except Exception:
            pass

    emojis_raw = get_setting("reaction_emojis", ",".join(DEFAULT_REACTION_EMOJIS))
    emoji_list = [e.strip() for e in emojis_raw.split(",") if e.strip()] or DEFAULT_REACTION_EMOJIS
    chosen = random.choice(emoji_list)

    try:
        await context.bot.set_message_reaction(
            chat_id=post.chat.id,
            message_id=post.message_id,
            reaction=[ReactionTypeEmoji(chosen)]
        )
        set_setting(cooldown_key, datetime.now().isoformat())
    except Exception as e:
        logger.error(f"Avto-reaksiya xatosi: {e}")

# ── XABARLARNI QAYTA ISHLASH (HANDLE MESSAGE) ───────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    # Obunani tekshirish
    if not await check_subscription(update, context):
        return

    if text == "🛠 Foydali botlar":
        await show_useful_bots_menu(update, context)

    elif text == "🎬 Videodan ovoz":
        await start_audio_extract_flow(update, context)

    elif text == "🎥 Dumaloq video":
        await start_circle_video_flow(update, context)

    elif text == "🖼 Stiker yaratish":
        await show_sticker_menu(update, context)

    elif text == "🔐 Parollar":
        await show_password_menu(update, context)

    elif text == "👥 Do'stlarni taklif":
        await show_referral_menu(update, context)

    elif text == "📊 Mening hisobim":
        await my_account(update, context)

    elif text == "🤖 AI Yordamchi":
        await start_ai_chat_flow(update, context)

    elif state == "ai_chat":
        await ask_universal_ai(update, context, text)

    elif state == "contact_admin":
        user = update.effective_user
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO admin_messages (user_id, user_name, message_text, sent_at) VALUES (?,?,?,?)",
                  (user.id, user.full_name, text, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        safe_full_name = html.escape(user.full_name or "")
        safe_username = html.escape(user.username or "yoq")
        safe_text = html.escape(text)

        for admin_id in ADMIN_IDS:
            try:
                msg = (
                    f"📩 <b>Yangi foydalanuvchi xabari!</b>\n\n"
                    f"👤 Ism: {safe_full_name}\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"📛 Username: @{safe_username}\n\n"
                    f"📝 Xabar:\n{safe_text}"
                )
                await context.bot.send_message(admin_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed sending admin notification: {e}")

        await update.message.reply_text(
            f"✅ Xabaringiz adminga yuborildi! Adminlarimiz tez orada javob berishadi.{BOT_FOOTER}",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_main")
        )
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "save_pass_label":
        context.user_data["pass_label"] = text
        context.user_data["state"] = "save_pass_value"
        await update.message.reply_text("🔑 Parolni kiriting:")

    elif state == "save_pass_value":
        label = context.user_data.get("pass_label", "Nomsiz")
        password = text

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM passwords WHERE user_id=?", (user_id,))
        count = c.fetchone()[0]
        limit = get_limit(user_id, "password")

        if count >= limit:
            conn.close()
            await update.message.reply_text(
                f"❌ Parol limiti {limit} ta!\n"
                "Ko'proq joy uchun do'stlarni taklif qiling 👥"
            )
            context.user_data["state"] = None
            return

        c.execute("INSERT INTO passwords (user_id, label, password, created_at) VALUES (?,?,?,?)",
                  (user_id, label, password, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ Parol saqlandi!\n\n🏷 Nom: <b>{html.escape(label)}</b>{BOT_FOOTER}",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_passwords")
        )
        await increment_action_and_check_ad(update, context)

    elif state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast(text[:200], user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Xabar {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")

    elif state == "channel_ad_broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Kanallarga yuborilmoqda...")
        success, total = await broadcast_forward_to_channels(context, update.message.chat_id, update.message.message_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Reklama {success}/{total} kanalga yuborildi!")

    elif state == "admin_wordfile_word" and user_id in ADMIN_IDS:
        word = text.strip()
        fid = context.user_data.get("temp_wordfile_id")
        ftype = context.user_data.get("temp_wordfile_type", "document")
        if not fid:
            await update.message.reply_text("❌ Xatolik: fayl topilmadi, qaytadan boshlang.")
        else:
            save_word_file(word, fid, ftype)
            await update.message.reply_text(
                f"✅ Fayl saqlandi!\n\n🔤 So'z: <code>{html.escape(word)}</code>\n\n"
                f"Endi foydalanuvchi shu so'zni yozsa, fayl avtomatik yuboriladi.",
                parse_mode="HTML",
                reply_markup=back_keyboard("admin_back")
            )
        context.user_data["state"] = None
        context.user_data.pop("temp_wordfile_id", None)
        context.user_data.pop("temp_wordfile_type", None)

    elif state == "set_required_channel" and user_id in ADMIN_IDS:
        channel = text.strip()
        if not channel.startswith("@") and not channel.startswith("-100"):
            channel = "@" + channel
        set_setting("required_channel", channel)
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ Majburiy obuna kanali o'rnatildi: {channel}")

    elif state == "set_ad_text" and user_id in ADMIN_IDS:
        set_setting("ad_text", text)
        context.user_data["state"] = None
        await update.message.reply_text("✅ Reklama matni muvaffaqiyatli saqlandi!")

    elif state == "avtoreact_add_channel_input" and user_id in ADMIN_IDS:
        context.user_data["state"] = None
        channel_input = text.strip()
        if channel_input.lstrip("-").isdigit():
            chat_ref = int(channel_input)
        elif channel_input.startswith("@"):
            chat_ref = channel_input
        else:
            chat_ref = "@" + channel_input

        try:
            chat = await context.bot.get_chat(chat_ref)
            member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)
            if member.status != "administrator":
                await update.message.reply_text(
                    f"❌ Bot <b>{html.escape(chat.title or '')}</b> kanalida admin emas.\n\n"
                    f"Avval botni shu kanalga <b>administrator</b> qilib qo'shing, so'ng qayta urinib ko'ring.",
                    parse_mode="HTML",
                    reply_markup=back_keyboard("admin_avto_reaction")
                )
            else:
                add_bot_channel(chat.id, chat.title, chat.username, user_id)
                await update.message.reply_text(
                    f"✅ <b>{html.escape(chat.title or '')}</b> kanali avto-reaksiya ro'yxatiga qo'shildi!",
                    parse_mode="HTML",
                    reply_markup=back_keyboard("admin_avto_reaction")
                )
        except Exception as e:
            logger.error(f"Kanal qo'shish xatosi: {e}")
            await update.message.reply_text(
                "❌ Kanal topilmadi yoki bot unga kira olmayapti. Username/ID to'g'riligini tekshiring va "
                "botni kanalga admin qilib qo'shganingizga ishonch hosil qiling.",
                reply_markup=back_keyboard("admin_avto_reaction")
            )

    elif state == "set_reaction_emojis" and user_id in ADMIN_IDS:
        emojis = text.strip()
        set_setting("reaction_emojis", emojis)
        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ Emojilar yangilandi: {emojis}",
            reply_markup=back_keyboard("admin_avto_reaction")
        )

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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET special_start_msg=? WHERE user_id=?", (text, target_id))
        conn.commit()
        conn.close()
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ {target_id} uchun maxsus xabar o'rnatildi!")

    elif state == "admin_special_id" and user_id in ADMIN_IDS:
        try:
            target_id = int(text)
            context.user_data["state"] = f"set_special_msg_{target_id}"
            await update.message.reply_text(
                f"✅ ID topildi: <code>{target_id}</code>\n\nEndi maxsus xabarni yozing:",
                parse_mode="HTML"
            )
        except Exception:
            await update.message.reply_text("❌ Noto'g'ri ID! Raqam kiriting.")

    elif state == "admin_find" and user_id in ADMIN_IDS:
        try:
            target_id = int(text)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, username, full_name, joined_at, referral_count, is_premium FROM users WHERE user_id=?", (target_id,))
            row = c.fetchone()
            conn.close()
            if row:
                uid, uname, fname, joined, refs, prem = row
                await update.message.reply_text(
                    f"👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
                    f"🆔 ID: <code>{uid}</code>\n"
                    f"👤 Ism: {html.escape(fname or '')}\n"
                    f"📛 Username: @{html.escape(uname or 'yoq')}\n"
                    f"📅 Qo'shilgan: {joined[:10]}\n"
                    f"👥 Takliflar: {refs}\n"
                    f"👑 Premium: {'✅' if prem else '❌'}",
                    parse_mode="HTML",
                    reply_markup=back_keyboard("admin_back")
                )
            else:
                await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
        except Exception:
            await update.message.reply_text("❌ Noto'g'ri ID!")
        context.user_data["state"] = None

    elif state == "admin_video_label" and user_id in ADMIN_IDS:
        context.user_data["temp_video_label"] = text
        context.user_data["state"] = "admin_video_type"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 Premium", callback_data="vtype_premium"),
             InlineKeyboardButton("🆓 Oddiy", callback_data="vtype_regular")]
        ])
        await update.message.reply_text("Bu video qanday turda bo'lsin?", reply_markup=kb)

    elif state == "admin_video_number" and user_id in ADMIN_IDS:
        code = text.strip()
        fid = context.user_data.get("temp_video_file_id")
        label = context.user_data.get("temp_video_label", "")
        is_prem = context.user_data.get("temp_video_premium", 0)
        if not fid:
            await update.message.reply_text("❌ Xatolik: video topilmadi, qaytadan boshlang.")
        else:
            conn = sqlite3.connect(DB_PATH)
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

    elif state == "qr_input":
        await generate_qr(update, context, text)

    elif state == "tts_input":
        await text_to_speech(update, context, text)

    else:
        if text and text.strip().isdigit():
            await send_video_by_code(update, context, text.strip())
        elif text and text.strip():
            await send_file_by_word(update, context, text.strip())

# ── QR VA TTS FUNKSIYALARI ───────────────────────────────────
async def generate_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if check_limit(user_id, "qr"):
        limit = get_limit(user_id, "qr")
        await update.message.reply_text(
            f"❌ QR limit tugadi! (Kunlik {limit} ta)\n"
            "5 ta do'st taklif qiling — 5 ta qo'shimcha limit oling! 👥"
        )
        return
    increment_usage(user_id, "qr")
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Yana QR", callback_data="qr_gen"),
         InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
    ])
    await update.message.reply_photo(
        buf,
        caption=f"✅ QR kod tayyor!\n\n📝 Matn: <code>{html.escape(text)}</code>{BOT_FOOTER}",
        parse_mode="HTML",
        reply_markup=kb
    )
    context.user_data["state"] = None
    await increment_action_and_check_ad(update, context)

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id

    if len(text.strip()) < 3:
        await update.message.reply_text("❌ Matn juda qisqa! Kamida 3 ta belgi kiriting.")
        return

    if check_limit(user_id, "tts"):
        await update.message.reply_text(
            "❌ Limit tugadi! 5 ta do'st taklif qiling — 10+ qo'shimcha! 👥"
        )
        return
    try:
        tts = gTTS(text=text, lang="ru")
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        buf.name = "audio.mp3"
        increment_usage(user_id, "tts")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Yana", callback_data="tts"),
             InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
        ])
        await update.message.reply_voice(
            buf,
            caption=f"🔊 Matn ovozga aylantirildi!\n\n📝 Matn: <code>{html.escape(text)}</code>{BOT_FOOTER}",
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"TTS error: {e}")
        await update.message.reply_text("❌ Tovush yaratishda xatolik yuz berdi! Qayta urinib ko'ring.")
    context.user_data["state"] = None
    await increment_action_and_check_ad(update, context)

async def send_video_by_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT file_id, label, is_premium FROM video_codes WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()

    if not row:
        return

    file_id, label, is_prem = row
    if is_prem and user_id not in ADMIN_IDS and not is_premium(user_id):
        await update.message.reply_text(
            "👑 Bu video faqat Premium foydalanuvchilar uchun!",
            reply_markup=get_mini_app_keyboard()
        )
        return

    await update.message.reply_video(
        video=file_id,
        caption=f"🎬 {html.escape(label)}{BOT_FOOTER}" if label else BOT_FOOTER,
        parse_mode="HTML"
    )

async def show_password_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT label, password, created_at FROM passwords WHERE user_id=?", (user_id,))
    passwords = c.fetchall()
    conn.close()
    limit = get_limit(user_id, "password")
    text = f"🔐 <b>Parollar</b> ({len(passwords)}/{limit})\n\n"
    if passwords:
        for i, (label, pwd, created) in enumerate(passwords, 1):
            safe_label = html.escape(label)
            safe_pwd = html.escape(pwd)
            text += f"{i}. 🏷 <b>{safe_label}</b>\n<code>{safe_pwd}</code>\n\n"
    else:
        text += "📭 Hali parol saqlanmagan\n\n"
    text += BOT_FOOTER
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yangi parol saqlash", callback_data="add_password")],
        [InlineKeyboardButton("🗑 Barchasini o'chirish", callback_data="clear_passwords")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ])
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

async def show_referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ref_count = get_referral_count(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME.replace('@', '')}?start=ref_{user_id}"

    text = (
        f"👥 <b>Do'stlarni taklif qilish</b>\n\n"
        f"📊 Taklif qilganlar: <b>{ref_count}</b> ta\n\n"
        f"🎁 <b>Bonuslar:</b>\n"
        f"• 5 ta taklif → Parol: +5 joy\n"
        f"• 5 ta taklif → QR: +5 ta\n"
        f"• 5 ta taklif → TTS: +10 ta\n"
        f"• 5 ta taklif → Rasm siqish: +10 ta\n"
        f"• 5 ta taklif → Videodan ovoz: +5 ta\n"
        f"• 5 ta taklif → Stiker yaratish: +10 ta\n"
        f"• 5 ta taklif → Dumaloq video: +5 ta\n\n"
        f"🔗 Sizning havolangiz:\n<code>{html.escape(ref_link)}</code>\n\n"
        f"<i>(Bosib nusxa olish)</i>{BOT_FOOTER}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Havolani ulashish",
                              url=f"https://t.me/share/url?url={ref_link}&text=Bu%20foydali%20botga%20qo%27shiling!")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ])
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

# ── ADMIN PANEL VA CALLBACK HANDLER ─────────────────────────
def admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton("📢 Tarqatish", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📩 Kelgan xabarlar", callback_data="admin_messages_list"),
         InlineKeyboardButton("📢 Majburiy obuna", callback_data="admin_req_sub")],
        [InlineKeyboardButton("📣 Reklama sozlash", callback_data="admin_set_ad"),
         InlineKeyboardButton("👤 Foydalanuvchi topish", callback_data="admin_find_user")],
        [InlineKeyboardButton("✉️ Maxsus xabar", callback_data="admin_special_msg"),
         InlineKeyboardButton("🎬 Video kodi qo'shish", callback_data="admin_add_video_code")],
        [InlineKeyboardButton("🔥 Avto-reaksiya", callback_data="admin_avto_reaction"),
         InlineKeyboardButton("📣 Kanallarga reklama", callback_data="admin_channel_ad")],
        [InlineKeyboardButton("📁 Fayl qo'shish (so'z)", callback_data="admin_add_word_file")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def avto_reaction_menu_keyboard():
    enabled = get_setting("avto_reaction_enabled", "1") == "1"
    toggle_label = "🔴 O'chirish" if enabled else "🟢 Yoqish"
    keyboard = [
        [InlineKeyboardButton(toggle_label, callback_data="avtoreact_toggle")],
        [InlineKeyboardButton("➕ Kanal qo'shish", callback_data="avtoreact_add_channel")],
        [InlineKeyboardButton("😊 Emojilarni sozlash", callback_data="avtoreact_set_emojis")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_avto_reaction_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enabled = get_setting("avto_reaction_enabled", "1") == "1"
    emojis = get_setting("reaction_emojis", ",".join(DEFAULT_REACTION_EMOJIS))
    channel_count = get_bot_channels_count()
    status_str = "✅ Yoniq" if enabled else ("❌ O'" + "chiq")
    text = (
        f"🔥 <b>Kanalga avto-reaksiya</b>\n\n"
        f"Holati: {status_str}\n"
        f"Ulangan kanallar: <b>{channel_count}</b> ta\n"
        f"Emojilar: {html.escape(emojis)}\n\n"
        f"ℹ️ Botni istalgan kanalga <b>admin</b> qilib qo'shsangiz, u avtomatik ravishda ro'yxatga qo'shiladi "
        f"va yangi postlarga tasodifiy 1 ta emoji bilan reaksiya bildiriladi (har {REACTION_COOLDOWN_SECONDS // 60} daqiqada 1 marta)."
    )
    await _reply_or_edit(update, text, reply_markup=avto_reaction_menu_keyboard())

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Ruxsat yo'q!")
        return
    await update.message.reply_text(
        "👑 <b>Admin Panel</b>\n\nBarcha boshqaruv menyusi:",
        parse_mode="HTML",
        reply_markup=admin_menu_keyboard()
    )

async def ask_universal_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    wait_msg = await update.message.reply_text("⏳ O'ylanmoqda...")
    answer = None
    for provider, model_id in AI_MODELS:
        try:
            extra_headers = {}
            if PROVIDER_KEYS.get(provider):
                extra_headers["provider-key"] = PROVIDER_KEYS[provider]

            response = await asyncio.to_thread(
                bytez_client.chat.completions.create,
                model=model_id,
                messages=[{"role": "user", "content": text}],
                extra_headers=extra_headers or None,
            )
            answer = response.choices[0].message.content
            break
        except Exception as e:
            logger.error(f"{provider} ({model_id}) xato: {e}")
            continue

    await wait_msg.delete()
    if answer:
        await update.message.reply_text(answer)
    else:
        await update.message.reply_text("❌ Kechirasiz, hozircha AI xizmatlari ishlamayapti.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "check_sub":
        if await check_subscription(update, context):
            await query.edit_message_text("✅ Rahmat! Obuna tasdiqlandi. Endi botdan foydalanishingiz mumkin.")
            await context.bot.send_message(
                user_id,
                "🏠 Asosiy menyu:\n\nKerakli bo'limni tanlang:",
                parse_mode="HTML",
                reply_markup=main_menu_inline_keyboard()
            )

    elif data == "back_main":
        context.user_data["state"] = None
        try:
            await query.edit_message_text(
                "🏠 Asosiy menyu:\n\nKerakli bo'limni tanlang:",
                parse_mode="HTML",
                reply_markup=main_menu_inline_keyboard()
            )
        except Exception:
            await query.message.reply_text(
                "🏠 Asosiy menyu:\n\nKerakli bo'limni tanlang:",
                parse_mode="HTML",
                reply_markup=main_menu_inline_keyboard()
            )

    elif data == "menu_useful_bots":
        await show_useful_bots_menu(update, context)

    elif data == "menu_audio_extract":
        await start_audio_extract_flow(update, context)

    elif data == "menu_circle_video":
        await start_circle_video_flow(update, context)

    elif data == "menu_sticker":
        await show_sticker_menu(update, context)

    elif data == "menu_passwords":
        await show_password_menu(update, context)

    elif data == "menu_referral":
        await show_referral_menu(update, context)

    elif data == "menu_account":
        await my_account(update, context)

    elif data == "menu_ai":
        await start_ai_chat_flow(update, context)

    elif data == "info_avto_reaction":
        await query.edit_message_text(
            "🔥 <b>Kanalga avto-reaksiya</b>\n\n"
            "Botni istalgan kanalingizga <b>administrator</b> qilib qo'shing — "
            "yangi postlaringizga avtomatik ravishda tasodifiy emoji bilan reaksiya bildiriladi "
            "(har 5 daqiqada bir marta).",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "back_useful":
        context.user_data["state"] = None
        await query.edit_message_text(
            "🛠 <b>Foydali botlar</b>\n\nBo'limni tanlang:",
            parse_mode="HTML",
            reply_markup=useful_bots_keyboard()
        )

    elif data == "back_passwords":
        context.user_data["state"] = None
        await show_password_menu(update, context)

    elif data == "sticker_single":
        context.user_data["state"] = "sticker_single_input"
        used = get_used_today(user_id, "sticker")
        limit = get_limit(user_id, "sticker")
        await query.edit_message_text(
            f"🖼 <b>Oddiy Stiker Yaratish</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Stikerga aylantirmoqchi bo'lgan rasmingizni yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_main")
        )

    elif data == "sticker_pack":
        context.user_data["state"] = "sticker_pack_input"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_stickers WHERE user_id=?", (user_id,))
        count = c.fetchone()[0]
        conn.close()

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Pack yaratish (havola olish)", callback_data="finalize_sticker_pack")],
            [InlineKeyboardButton("📄 TXT sifatida yuklash", callback_data="export_sticker_txt")],
            [InlineKeyboardButton("🗑 To'plamni tozalash", callback_data="clear_sticker_pack")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")]
        ])
        await query.edit_message_text(
            f"📦 <b>Stiker Pack Yaratish</b>\n\n"
            f"Hozircha yig'ilgan stikerlar: <b>{count}</b> ta\n\n"
            f"Rasmlarni ketma-ket yuboring, bot ularni saqlaydi! Tayyor bo'lgach TXT fayl ko'rinishida yuklab olishingiz mumkin.{BOT_FOOTER}",
            parse_mode="HTML",
            reply_markup=kb
        )

    elif data == "export_sticker_txt":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT file_id, created_at FROM user_stickers WHERE user_id=?", (user_id,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            await query.answer("📭 Hali hech qanday stiker yig'ilmadi!", show_alert=True)
            return

        txt_content = f"STICKER PACK EXPORT - {BOT_USERNAME}\n"
        txt_content += f"Pack Name: StickerPack_{user_id}_{BOT_USERNAME}\n"
        txt_content += "----------------------------------------\n\n"
        for idx, (fid, dt) in enumerate(rows, 1):
            txt_content += f"Sticker {idx}: File_ID = {fid} (Date: {dt})\n"

        buf = io.BytesIO(txt_content.encode("utf-8"))
        buf.name = f"StickerPack_{user_id}.txt"

        await query.message.reply_document(
            document=buf,
            caption=f"📦 Stiker pack TXT ma'lumoti tayyor!\n\nPack nomi: <code>StickerPack_{user_id}_{html.escape(BOT_USERNAME)}</code>{BOT_FOOTER}",
            parse_mode="HTML"
        )

    elif data == "clear_sticker_pack":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM user_stickers WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.answer("✅ To'plam tozalandi!", show_alert=True)
        await query.edit_message_text("✅ Stikerlar to'plami tozalandi!", reply_markup=back_keyboard("back_main"))
    elif data == "finalize_sticker_pack":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT file_id FROM user_stickers WHERE user_id=?", (user_id,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            await query.answer("📭 Hali hech qanday rasm yig'ilmagan!", show_alert=True)
            return

        await query.answer("⏳ Stiker pack yaratilmoqda...")
        wait_msg = await query.message.reply_text("⏳ Stiker pack yaratilmoqda, biroz kuting...")

        pack_name = f"pack{user_id}_by_{BOT_USERNAME.lstrip('@')}"
        pack_title = "Mening Stiker To'plamim"

        try:
            stickers_input = []
            for (fid,) in rows[:120]:
                file = await context.bot.get_file(fid)
                buf = io.BytesIO()
                await file.download_to_memory(buf)
                webp_bytes = create_sticker_from_image_bytes(buf.getvalue())
                stickers_input.append(InputSticker(sticker=webp_bytes, emoji_list=["😀"]))

            try:
                await context.bot.create_new_sticker_set(
                    user_id=user_id,
                    name=pack_name,
                    title=pack_title,
                    stickers=stickers_input,
                    sticker_format="static"
                )
            except BadRequest as e:
                if "occupied" not in str(e).lower():
                    raise

            link = f"https://t.me/addstickers/{pack_name}"
            await wait_msg.delete()
            await query.message.reply_text(
                f"✅ Stiker pack tayyor!\n\n🔗 Havola: {link}\n\nHavolani bosib, stikerlarni Telegramga qo'shib oling!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Sticker pack creation error: {e}")
            await wait_msg.edit_text("❌ Stiker pack yaratishda xatolik yuz berdi.")

    elif data == "qr_gen":
        if check_limit(user_id, "qr"):
            limit = get_limit(user_id, "qr")
            await query.edit_message_text(
                f"❌ QR limit tugadi! (Kunlik {limit} ta)\n"
                "5 ta do'st taklif qiling — 5 ta qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "qr_input"
        used = get_used_today(user_id, "qr")
        limit = get_limit(user_id, "qr")
        await query.edit_message_text(
            f"📷 <b>QR Generator</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"QR kodga aylantirish uchun matn yuboring",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "tts":
        if check_limit(user_id, "tts"):
            await query.edit_message_text(
                "❌ Limit tugadi! 5 ta do'st taklif qiling — 10+ qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "tts_input"
        used = get_used_today(user_id, "tts")
        limit = get_limit(user_id, "tts")
        await query.edit_message_text(
            f"🔊 <b>Matn → Tovush</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Tovushga aylantirish uchun matn yuboring (Kamida 3 ta belgi):",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "compress":
        if check_limit(user_id, "compress"):
            await query.edit_message_text(
                "❌ Limit tugadi! 5 ta do'st taklif qiling — 10+ qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "compress_input"
        used = get_used_today(user_id, "compress")
        limit = get_limit(user_id, "compress")
        await query.edit_message_text(
            f"🗜 <b>Rasm siqish</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Siqmoqchi bo'lgan rasmni yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "convert":
        if check_limit(user_id, "convert"):
            await query.edit_message_text(
                "❌ Limit tugadi! 5 ta do'st taklif qiling — 10+ qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "convert_input"
        used = get_used_today(user_id, "convert")
        limit = get_limit(user_id, "convert")
        await query.edit_message_text(
            f"🔄 <b>Fayl konvertor</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Formatini PNG o'tkazmoqchi bo'lgan rasmingizni yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "bg_remove":
        if check_limit(user_id, "bg_remove"):
            await query.edit_message_text(
                "❌ Limit tugadi! 5 ta do'st taklif qiling — 10+ qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "bg_remove_input"
        used = get_used_today(user_id, "bg_remove")
        limit = get_limit(user_id, "bg_remove")
        await query.edit_message_text(
            f"🪄 <b>Fonni o'chirish</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Fonini olib tashlamoqchi bo'lgan rasmni yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "upscale_4k":
        if check_limit(user_id, "upscale_4k"):
            await query.edit_message_text(
                "❌ Limit tugadi! 5 ta do'st taklif qiling — 5 ta qo'shimcha! 👥",
                reply_markup=back_keyboard("back_useful")
            )
            return
        context.user_data["state"] = "upscale_4k_input"
        used = get_used_today(user_id, "upscale_4k")
        limit = get_limit(user_id, "upscale_4k")
        await query.edit_message_text(
            f"📐 <b>4K rasm</b>\n\n"
            f"📊 Bugungi: {used}/{limit}\n\n"
            f"Kattalashtirmoqchi bo'lgan rasmni yuboring (uzun tomoni ~3840px gacha silliq kattalashtiriladi):",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "contact_admin":
        context.user_data["state"] = "contact_admin"
        await query.edit_message_text(
            f"📩 <b>Admin bilan bog'lanish</b>\n\n"
            f"Xabaringizni yozib yuboring (matn, rasm yoki audio):",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_useful")
        )

    elif data == "add_password":
        context.user_data["state"] = "save_pass_label"
        await query.edit_message_text(
            "🏷 Parol uchun nom kiriting:\nMisol: <code>Instagram</code>",
            parse_mode="HTML",
            reply_markup=back_keyboard("back_passwords")
        )

    elif data == "clear_passwords":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM passwords WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ Barcha parollar o'chirildi!",
            reply_markup=back_keyboard("back_main")
        )

    elif data == "admin_stats" and user_id in ADMIN_IDS:
        total, premium = get_stats()
        await query.edit_message_text(
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"👑 Premium: {premium}\n"
            f"📢 Majburiy obuna kanali: <code>{html.escape(get_setting('required_channel', 'Yoq'))}</code>\n"
            f"🔥 Avto-reaksiya ulangan kanallar: <b>{get_bot_channels_count()}</b>\n"
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
        conn = sqlite3.connect(DB_PATH)
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

    elif data == "circle_video_direct":
        file_id = context.user_data.get("last_video_file_id")
        if not file_id:
            await query.answer("❌ Video topilmadi! Iltimos, videoni qayta yuboring.", show_alert=True)
            return

        if check_limit(user_id, "circle_video"):
            await query.answer("❌ Dumaloq video yaratish limiti tugadi!", show_alert=True)
            return

        msg = await query.message.reply_text("⏳ *Video yuklanmoqda...*\n\n`10% █░░░░░░░░░`", parse_mode="Markdown")

        async def progress_cb(percent, label="Dumaloq video tayyorlanmoqda..."):
            try:
                p_str = make_progress_bar(percent)
                await msg.edit_text(f"⏳ *{label}*\n\n`{p_str}`", parse_mode="Markdown")
            except Exception:
                pass

        try:
            file = await context.bot.get_file(file_id)
            buf = io.BytesIO()
            await file.download_to_memory(buf)

            circle_bytes = await convert_to_circle_video(buf.getvalue(), progress_cb=progress_cb)
            circle_file = io.BytesIO(circle_bytes)
            circle_file.name = "circle.mp4"

            increment_usage(user_id, "circle_video")
            await msg.delete()
            await query.message.reply_video_note(video_note=circle_file)
            await query.message.reply_text(
                f"✅ Dumaloq video tayyor!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Circle video error: {e}")
            await msg.edit_text("❌ Videoni dumaloq qilishda xatolik yuz berdi.")
        await increment_action_and_check_ad(update, context)

    elif data == "audio_extract_direct":
        file_id = context.user_data.get("last_video_file_id")
        if not file_id:
            await query.answer("❌ Video topilmadi! Iltimos, videoni qayta yuboring.", show_alert=True)
            return

        if check_limit(user_id, "audio_extract"):
            await query.answer("❌ Videodan ovoz ajratish limiti tugadi!", show_alert=True)
            return

        msg = await query.message.reply_text("⏳ Videodan MP3 ovoz ajratib olinmoqda...")
        try:
            file = await context.bot.get_file(file_id)
            buf = io.BytesIO()
            await file.download_to_memory(buf)

            audio_bytes = await extract_audio_from_video(buf.getvalue())
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.mp3"

            increment_usage(user_id, "audio_extract")
            await msg.delete()
            await query.message.reply_audio(
                audio=audio_file,
                caption=f"🎵 Videodan ajratib olingan MP3 audio!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Audio extract error: {e}")
            await msg.edit_text("❌ Videodan ovoz ajratishda xatolik yuz berdi.")
        await increment_action_and_check_ad(update, context)

    elif data == "admin_find_user" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_find"
        await query.edit_message_text(
            "🔍 Foydalanuvchi ID sini kiriting:",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_special_msg" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_special_id"
        await query.edit_message_text(
            "✉️ <b>Maxsus start xabari</b>\n\n"
            "Avval foydalanuvchi ID sini kiriting:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_add_video_code" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_video_upload"
        await query.edit_message_text(
            "🎬 <b>Video kod qo'shish</b>\n\nVideoni yuboring:",
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

    elif data == "admin_avto_reaction" and user_id in ADMIN_IDS:
        context.user_data["state"] = None
        await show_avto_reaction_menu(update, context)

    elif data == "avtoreact_toggle" and user_id in ADMIN_IDS:
        current = get_setting("avto_reaction_enabled", "1")
        set_setting("avto_reaction_enabled", "0" if current == "1" else "1")
        await show_avto_reaction_menu(update, context)

    elif data == "avtoreact_add_channel" and user_id in ADMIN_IDS:
        context.user_data["state"] = "avtoreact_add_channel_input"
        await query.edit_message_text(
            "➕ <b>Kanal qo'shish</b>\n\n"
            "Kanal username'ini (masalan: <code>@mychannel</code>) yoki ID raqamini yuboring.\n\n"
            "⚠️ Botni bu kanalga oldindan <b>administrator</b> qilib qo'shgan bo'lishingiz kerak, "
            "aks holda kanal qo'shilmaydi.",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_avto_reaction")
        )

    elif data == "avtoreact_set_emojis" and user_id in ADMIN_IDS:
        context.user_data["state"] = "set_reaction_emojis"
        await query.edit_message_text(
            "😊 Reaksiya uchun emojilarni vergul bilan ajratib yuboring\n"
            "(Masalan: <code>👍,❤️,🔥,🎉</code>):",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_avto_reaction")
        )

    elif data == "admin_channel_ad" and user_id in ADMIN_IDS:
        context.user_data["state"] = "channel_ad_broadcast"
        count = get_bot_channels_count()
        await query.edit_message_text(
            f"📣 <b>Kanallarga reklama tarqatish</b>\n\n"
            f"Ulangan kanallar: <b>{count}</b> ta\n\n"
            f"Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video — istalgan turda). "
            f"Bot uni nusxalamasdan, to'g'ridan-to'g'ri barcha ulangan kanallarga forward qiladi.",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_add_word_file" and user_id in ADMIN_IDS:
        context.user_data["state"] = "admin_wordfile_upload"
        await query.edit_message_text(
            "📁 <b>Fayl qo'shish (so'z bilan)</b>\n\nFaylni (hujjat, rasm, video, audio) yuboring:",
            parse_mode="HTML",
            reply_markup=back_keyboard("admin_back")
        )

    elif data == "admin_back" and user_id in ADMIN_IDS:
        context.user_data["state"] = None
        await query.edit_message_text(
            "👑 <b>Admin Panel</b>",
            parse_mode="HTML",
            reply_markup=admin_menu_keyboard()
        )

# ── RASM, VIDEO VA FAYLLARNI QAYTA ISHLASH (HANDLE MEDIA) ──────
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

    if state == "channel_ad_broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Kanallarga yuborilmoqda...")
        success, total = await broadcast_forward_to_channels(context, update.message.chat_id, update.message.message_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Reklama {success}/{total} kanalga yuborildi!")
        return

    if state == "admin_wordfile_upload" and user_id in ADMIN_IDS:
        context.user_data["temp_wordfile_id"] = update.message.photo[-1].file_id
        context.user_data["temp_wordfile_type"] = "photo"
        context.user_data["state"] = "admin_wordfile_word"
        await update.message.reply_text("✅ Rasm qabul qilindi!\n\n🔤 Endi bu fayl uchun so'z (kalit so'z) kiriting:")
        return

    if state == "contact_admin":
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"📩 <b>Yangi foydalanuvchi rasmi!</b> (ID: <code>{user_id}</code>):", parse_mode="HTML")
                await context.bot.copy_message(chat_id=admin_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            except Exception:
                pass
        await update.message.reply_text(f"✅ Rasmingiz adminga yuborildi!{BOT_FOOTER}", parse_mode="HTML", reply_markup=back_keyboard("back_main"))
        context.user_data["state"] = None
        return

    if state == "compress_input":
        if check_limit(user_id, "compress"):
            await update.message.reply_text("❌ Limit tugadi!")
            return
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        img = Image.open(buf)
        out = io.BytesIO()
        img = img.convert("RGB")
        img.save(out, format="JPEG", quality=40, optimize=True)
        original_size = len(buf.getvalue())
        compressed_size = len(out.getvalue())
        out.seek(0)
        out.name = "compressed.jpg"
        increment_usage(user_id, "compress")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Yana siqish", callback_data="compress"),
             InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
        ])
        await update.message.reply_document(
            out,
            caption=(f"✅ Rasm siqildi!\n\n"
                     f"📦 Asl: {original_size//1024} KB\n"
                     f"📦 Siqilgan: {compressed_size//1024} KB\n"
                     f"📉 Tejam: {max(0, 100 - int(compressed_size / max(original_size, 1) * 100))}%{BOT_FOOTER}"),
            reply_markup=kb
        )
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "convert_input":
        if check_limit(user_id, "convert"):
            await update.message.reply_text("❌ Limit tugadi!")
            return
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        img = Image.open(buf)

        png_out = io.BytesIO()
        img.save(png_out, format="PNG")
        png_out.seek(0)
        png_out.name = "converted_image.png"

        increment_usage(user_id, "convert")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Yana konvertatsiya", callback_data="convert"),
             InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
        ])
        await update.message.reply_document(
            png_out,
            caption=f"✅ Rasm PNG formatga o'tkazildi!{BOT_FOOTER}",
            reply_markup=kb
        )
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "bg_remove_input":
        if check_limit(user_id, "bg_remove"):
            await update.message.reply_text("❌ Limit tugadi!")
            return

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)

        msg = await update.message.reply_text("⏳ *Fon o'chirilmoqda...*\n\n`10% █░░░░░░░░░`", parse_mode="Markdown")

        async def progress_cb(percent, label="Fon o'chirilmoqda..."):
            try:
                p_str = make_progress_bar(percent)
                await msg.edit_text(f"⏳ *{label}*\n\n`{p_str}`", parse_mode="Markdown")
            except Exception:
                pass

        try:
            result_bytes = await remove_background(buf.getvalue(), progress_cb=progress_cb)
            result_file = io.BytesIO(result_bytes)
            result_file.name = "no_bg.png"

            increment_usage(user_id, "bg_remove")
            await msg.delete()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🪄 Yana fon o'chirish", callback_data="bg_remove"),
                 InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
            ])
            await update.message.reply_document(
                result_file,
                caption=f"✅ Fon muvaffaqiyatli o'chirildi!{BOT_FOOTER}",
                reply_markup=kb
            )
        except Exception as e:
            logger.error(f"BG remove error: {e}")
            await msg.edit_text(f"❌ Xatolik: {e}")
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "upscale_4k_input":
        if check_limit(user_id, "upscale_4k"):
            await update.message.reply_text("❌ Limit tugadi!")
            return

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)

        msg = await update.message.reply_text("⏳ Rasm kattalashtirilmoqda...")
        try:
            result_bytes, old_size, new_size = upscale_image_to_4k(buf.getvalue())
            result_file = io.BytesIO(result_bytes)
            result_file.name = "4k.jpg"

            increment_usage(user_id, "upscale_4k")
            await msg.delete()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📐 Yana 4K rasm", callback_data="upscale_4k"),
                 InlineKeyboardButton("🔙 Orqaga", callback_data="back_useful")]
            ])
            await update.message.reply_document(
                result_file,
                caption=(f"✅ Rasm kattalashtirildi!\n\n"
                         f"📏 Avval: {old_size[0]}x{old_size[1]}\n"
                         f"📏 Endi: {new_size[0]}x{new_size[1]}{BOT_FOOTER}"),
                reply_markup=kb
            )
        except Exception as e:
            logger.error(f"4K upscale error: {e}")
            await msg.edit_text("❌ Rasmni kattalashtirishda xatolik yuz berdi.")
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "sticker_single_input" or state == "sticker_input":
        if check_limit(user_id, "sticker"):
            await update.message.reply_text("❌ Stiker yaratish limiti tugadi!")
            return

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)

        msg = await update.message.reply_text("⏳ Stiker tayyorlanmoqda...")
        try:
            sticker_bytes = create_sticker_from_image_bytes(buf.getvalue())
            increment_usage(user_id, "sticker")
            await msg.delete()
            await update.message.reply_sticker(sticker=sticker_bytes)
            await update.message.reply_text(
                f"✅ Stiker yaratildi!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Sticker creation error: {e}")
            await msg.edit_text("❌ Stiker yaratishda xatolik yuz berdi.")
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "sticker_pack_input":
        photo = update.message.photo[-1]
        file_id = photo.file_id

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO user_stickers (user_id, file_id, created_at) VALUES (?,?,?)",
                  (user_id, file_id, datetime.now().isoformat()))
        c.execute("SELECT COUNT(*) FROM user_stickers WHERE user_id=?", (user_id,))
        count = c.fetchone()[0]
        conn.commit()
        conn.close()

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Pack yaratish (havola olish)", callback_data="finalize_sticker_pack")],
            [InlineKeyboardButton("📄 TXT sifatida yuklash", callback_data="export_sticker_txt")],
            [InlineKeyboardButton("🗑 To'plamni tozalash", callback_data="clear_sticker_pack")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")]
        ])
        await update.message.reply_text(
            f"✅ Rasm to'plamga saqlandi! (Jami: <b>{count}</b> ta)\n\nYana rasm yuborishingiz yoki TXT fayl ko'rinishida yuklab olishingiz mumkin.{BOT_FOOTER}",
            parse_mode="HTML",
            reply_markup=kb
        )

    else:
        # Standart holatda rasm yuborilganda menyu chiqarish
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼 Stikerga aylantirish", callback_data="sticker_single")],
            [InlineKeyboardButton("🗜 Siqish (Compress)", callback_data="compress")],
            [InlineKeyboardButton("🔄 PNG ga o'tkazish", callback_data="convert")]
        ])
        await update.message.reply_text(
            f"📷 Rasm qabul qilindi. Nima qilmoqchisiz?{BOT_FOOTER}",
            reply_markup=kb
        )

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

    if state == "channel_ad_broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Kanallarga yuborilmoqda...")
        success, total = await broadcast_forward_to_channels(context, update.message.chat_id, update.message.message_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Reklama {success}/{total} kanalga yuborildi!")
        return

    if state == "admin_wordfile_upload" and user_id in ADMIN_IDS:
        vobj = update.message.video or update.message.video_note
        context.user_data["temp_wordfile_id"] = vobj.file_id
        context.user_data["temp_wordfile_type"] = "video"
        context.user_data["state"] = "admin_wordfile_word"
        await update.message.reply_text("✅ Video qabul qilindi!\n\n🔤 Endi bu fayl uchun so'z (kalit so'z) kiriting:")
        return

    if state == "contact_admin":
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"📩 <b>Yangi foydalanuvchi videosi!</b> (ID: <code>{user_id}</code>):", parse_mode="HTML")
                await context.bot.copy_message(chat_id=admin_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            except Exception:
                pass
        await update.message.reply_text(f"✅ Videongiz adminga yuborildi!{BOT_FOOTER}", parse_mode="HTML", reply_markup=back_keyboard("back_main"))
        context.user_data["state"] = None
        return

    video_obj = update.message.video or update.message.video_note
    if not video_obj:
        return

    context.user_data["last_video_file_id"] = video_obj.file_id

    if state == "admin_video_upload" and user_id in ADMIN_IDS:
        context.user_data["temp_video_file_id"] = video_obj.file_id
        context.user_data["state"] = "admin_video_label"
        await update.message.reply_text("✅ Video qabul qilindi!\n\n📝 Endi bu video uchun nom (label) kiriting:")
        return

    if state == "circle_video_input" and (update.message.video or update.message.video_note):
        if check_limit(user_id, "circle_video"):
            await update.message.reply_text("❌ Dumaloq video yaratish limiti tugadi!")
            return

        msg = await update.message.reply_text("⏳ *Video yuklanmoqda...*\n\n`10% █░░░░░░░░░`", parse_mode="Markdown")

        async def progress_cb(percent, label="Dumaloq video tayyorlanmoqda..."):
            try:
                p_str = make_progress_bar(percent)
                await msg.edit_text(f"⏳ *{label}*\n\n`{p_str}`", parse_mode="Markdown")
            except Exception:
                pass

        try:
            video_obj = update.message.video or update.message.video_note
            file = await context.bot.get_file(video_obj.file_id)
            buf = io.BytesIO()
            await file.download_to_memory(buf)

            circle_bytes = await convert_to_circle_video(buf.getvalue(), progress_cb=progress_cb)
            circle_file = io.BytesIO(circle_bytes)
            circle_file.name = "circle.mp4"

            increment_usage(user_id, "circle_video")
            await msg.delete()
            await update.message.reply_video_note(video_note=circle_file)
            await update.message.reply_text(
                f"✅ Dumaloq video tayyor!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Circle video error: {e}")
            await msg.edit_text("❌ Videoni dumaloq qilishda xatolik yuz berdi.")
        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    elif state == "audio_extract_input":
        if check_limit(user_id, "audio_extract"):
            await update.message.reply_text("❌ Videodan ovoz ajratish limiti tugadi!")
            return

        msg = await update.message.reply_text("⏳ Videodan MP3 ovoz ajratib olinmoqda...")
        try:
            file = await context.bot.get_file(video_obj.file_id)
            buf = io.BytesIO()
            await file.download_to_memory(buf)

            audio_bytes = await extract_audio_from_video(buf.getvalue())
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.mp3"

            increment_usage(user_id, "audio_extract")
            await msg.delete()
            await update.message.reply_audio(
                audio=audio_file,
                caption=f"🎵 Videodan ajratib olingan MP3 audio!{BOT_FOOTER}",
                reply_markup=back_keyboard("back_main")
            )
        except Exception as e:
            logger.error(f"Audio extract error: {e}")
            await msg.edit_text("❌ Videodan ovoz ajratishda xatolik yuz berdi.")

        context.user_data["state"] = None
        await increment_action_and_check_ad(update, context)

    else:
        # Standart holatda video kelganda tanlov menyusi
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎥 Dumaloq video qilish", callback_data="circle_video_direct")],
            [InlineKeyboardButton("🎬 Ovozini ajratib olish (MP3)", callback_data="audio_extract_direct")]
        ])
        await update.message.reply_text(
            f"📹 Video qabul qilindi. Ushbu video ustida nima bajarmoqchisiz?{BOT_FOOTER}",
            reply_markup=kb
        )

# ── BARCHA BOSHQA MEDIA XABARLAR ─────────────────────────────
async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if state == "broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Tarqatilmoqda, iltimos kuting...")
        success, total = await broadcast_copy_to_all(context, update.message.chat_id, update.message.message_id)
        log_broadcast("[media]", user_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Media {success}/{total} foydalanuvchiga muvaffaqiyatli tarqatildi!")
        return

    if state == "channel_ad_broadcast" and user_id in ADMIN_IDS:
        wait_msg = await update.message.reply_text("⏳ Kanallarga yuborilmoqda...")
        success, total = await broadcast_forward_to_channels(context, update.message.chat_id, update.message.message_id)
        context.user_data["state"] = None
        await wait_msg.edit_text(f"✅ Reklama {success}/{total} kanalga yuborildi!")
        return

    if state == "admin_wordfile_upload" and user_id in ADMIN_IDS:
        m = update.message
        if m.animation:
            fid, ftype = m.animation.file_id, "animation"
        elif m.audio:
            fid, ftype = m.audio.file_id, "audio"
        elif m.voice:
            fid, ftype = m.voice.file_id, "voice"
        elif m.document:
            fid, ftype = m.document.file_id, "document"
        elif m.sticker:
            fid, ftype = m.sticker.file_id, "sticker"
        else:
            fid, ftype = None, None
        if fid:
            context.user_data["temp_wordfile_id"] = fid
            context.user_data["temp_wordfile_type"] = ftype
            context.user_data["state"] = "admin_wordfile_word"
            await update.message.reply_text("✅ Fayl qabul qilindi!\n\n🔤 Endi bu fayl uchun so'z (kalit so'z) kiriting:")
        return

    if state == "contact_admin":
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"📩 <b>Yangi foydalanuvchi fayli/mediasi!</b> (ID: <code>{user_id}</code>):", parse_mode="HTML")
                await context.bot.copy_message(chat_id=admin_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            except Exception:
                pass
        await update.message.reply_text(f"✅ Yuborgan faylingiz adminga yetkazildi!{BOT_FOOTER}", parse_mode="HTML", reply_markup=back_keyboard("back_main"))
        context.user_data["state"] = None
        return

# ── MAIN FUNKSIYA ───────────────────────────────────────────
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Buyruqlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("Premiumoldi", premium_oldi))
    app.add_handler(CommandHandler("miniapppremium", mini_app_premium_tasdiqla))
    app.add_handler(CommandHandler("menu", menu_command))
    # Callbacklar
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Kanalga avto-reaksiya (bot kanalda admin bo'lgan holatda yangi postlarga ishlaydi)
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_channel_post))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Media handlerlar (kanal postlari bu handlerlarga tushmasligi uchun ~CHANNEL_POST bilan cheklanadi)
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.UpdateType.CHANNEL_POST, handle_photo))
    app.add_handler(MessageHandler((filters.VIDEO | filters.VIDEO_NOTE) & ~filters.UpdateType.CHANNEL_POST, handle_video))
    app.add_handler(MessageHandler((filters.ANIMATION | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.Sticker.ALL) & ~filters.UpdateType.CHANNEL_POST, handle_other_media))

    # Text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.CHANNEL_POST, handle_message))

    print("✅ Telegram Bot barcha tuzatishlar bilan muvaffaqiyatli ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
