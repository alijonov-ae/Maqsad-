# Universal Telegram Bot

Ko'p funksiyali Telegram bot: QR generator, matn→ovoz, stiker va premium emoji yaratish,
rasm siqish/4K kattalashtirish/fon o'chirish, videodan MP3 ajratish, dumaloq video,
parol saqlash, referal tizimi, kanalga avto-reaksiya va admin panel.

## O'rnatish

```bash
pip install -r requirements.txt
apt-get install -y ffmpeg        # MAJBURIY - pastdagi izohga qarang
cp .env.example .env             # va qiymatlarni to'ldiring
python bot_fixed.py
```

### ffmpeg majburiy

Quyidagi bo'limlar `ffmpeg`/`ffprobe` ga tayanadi va u o'rnatilmagan bo'lsa **ishlamaydi**:

- 🎥 Dumaloq video qilish
- 🎬 Videodan ovoz ajratish (MP3)
- 🎞 WEBP emoji yaratish

Bot ishga tushganda ffmpeg topilmasa jurnalga ogohlantirish yozadi.
Railway'da `nixpacks.toml` fayli buni avtomatik o'rnatadi.

## Muhit o'zgaruvchilari

| O'zgaruvchi | Majburiy | Izoh |
|---|---|---|
| `BOT_TOKEN` | ✅ | @BotFather dan olingan token. Bo'lmasa bot ishga tushmaydi. |
| `ADMIN_IDS` | ✅ | Admin ID lari, vergul bilan. Bo'sh bo'lsa admin panel va "Admin bilan bog'lanish" ishlamaydi. |
| `DB_DIR` | ❌ | Baza papkasi. Railway Volume uchun `/data`. Standart: `/data`. |
| `BYTEZ_API_KEY` | ❌ | AI chat uchun. Bo'lmasa "AI bilan suhbat" o'chadi. |
| `GEMINI_API_KEY` | ❌ | Google Gemini uchun. |
| `REMBG_API_KEY` | ❌ | Fon o'chirish API si uchun. |

## Ma'lumotlar bazasi

SQLite (`bot.db`). `init_db()` barcha jadvallarni ishga tushishda avtomatik yaratadi,
shuning uchun bo'sh papkadan boshlash ham mumkin. `DB_DIR` ichida baza bo'lmasa,
repo bilan kelgan `bot.db` bir marta ko'chiriladi.

## ⚠️ Muhim xavfsizlik eslatmalari

1. **`bot.db` ochiq repoda turibdi** va ichida ~235 real foydalanuvchi ma'lumoti hamda
   14 ta ochiq (shifrlanmagan) parol bor. Uni git tarixidan olib tashlash tavsiya etiladi.
2. **Bytez API kaliti** avval kod ichida ochiq yozilgan edi. Endi `BYTEZ_API_KEY`
   muhit o'zgaruvchisidan o'qiladi, lekin **eski kalit tarixda qolgan** — uni Bytez
   panelida bekor qilib (rotate) yangisini olish kerak.
3. `passwords` jadvali parollarni ochiq matnda saqlaydi — shifrlash tavsiya etiladi.
