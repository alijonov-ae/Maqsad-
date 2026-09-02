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
| `GEMINI_API_KEY` | ⚠️ | **AI chat uchun asosiy provayder.** [aistudio.google.com/apikey](https://aistudio.google.com/apikey) dan bepul olinadi. Bo'lmasa "AI bilan suhbat" ishlamaydi. |
| `BYTEZ_API_KEY` | ❌ | AI chat uchun zaxira provayder. Gemini javob bermasa ishlatiladi. |
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

## Ikkinchi bosqich tuzatishlari (AI va premium emoji)

Foydalanuvchi "AI funksiyalari va premium emoji ishlamayapti" deb xabar bergandan
so'ng quyidagi asosiy nosozliklar aniqlanib tuzatildi.

### 1. Premium emoji pack HECH QACHON yaratilmagan

`create_new_sticker_set()` ga `sticker_format="static"` argumenti berilardi. Bu argument
`python-telegram-bot` 21.0 dan boshlab (Bot API 7.2) **olib tashlangan** — natijada har bir
urinish `TypeError: got an unexpected keyword argument 'sticker_format'` bilan qulardi va
foydalanuvchi faqat "❌ Pack yaratishda xatolik yuz berdi" xabarini ko'rardi.
Format endi faqat `InputSticker(format=...)` ichida beriladi.

### 2. WEBP fayl yuborilganda bot jim turardi

Emoji manbasi sifatida faqat `message.photo` o'qilardi va `premium_emoji_collect` holati
faqat `handle_photo` ichida yo'naltirilgan edi. Foydalanuvchi WEBP/PNG faylni **hujjat
(document)** sifatida yuborsa yoki GIF/video yuborsa, `handle_other_media` /
`handle_video` bu holatni umuman tekshirmasdi — bot hech qanday javob bermasdi.
Endi rasm, hujjat, GIF, video, video-note va stiker qabul qilinadi.

### 3. Animatsion emoji noto'g'ri formatda tayyorlanardi

Telegram animatsion custom-emoji uchun **VP9 kodekli WEBM** talab qiladi, animatsion WEBP'ni
qabul qilmaydi. Yangi `convert_to_webm_emoji()` qo'shildi: 100x100, 3 soniyagacha,
shaffoflik saqlanadi va fayl 64 KB ga sig'guncha sifat bosqichma-bosqich pasaytiriladi.
Manba animatsion ekanligi `_is_animated_bytes()` bilan avtomatik aniqlanadi.

### 4. Pack sarlavhasi endi bot nomi bilan

Sarlavha `<tanlangan ism> • @kerakli_boladi_bot` ko'rinishida yasaladi
(`build_pack_title()`). Telegram 64 belgi cheklovi bor, shuning uchun foydalanuvchi
kiritgan qism kerak bo'lsa qisqartiriladi — aks holda Telegram xato qaytarardi.

### 5. Aralash formatli pack

Telegram bitta pack ichida statik va animatsion emojini aralashtirishga ruxsat bermaydi.
Bazaga `custom_emoji_packs.sticker_format` ustuni qo'shildi (avtomatik migratsiya bilan) —
mos kelmagan fayl endi tushunarli xabar bilan rad etiladi.

### 6. Yakunlashda takrorlangan kod

`premium_emoji_finalize()` ichida limit tekshiruvi va "⏳ tayyorlanmoqda" xabari **ikki marta**
takrorlangan edi: foydalanuvchiga ikkita kutish xabari chiqardi va birinchisi hech qachon
o'chirilmasdi. Takror olib tashlandi.

### 7. Pack nomlari to'qnashuvi

Nom faqat soniya aniqligidagi vaqtdan yasalardi, shuning uchun bir soniya ichida yaratilgan
ikki pack bir xil nom olib, bazada biri ikkinchisini o'chirib yuborardi. Endi nomga tasodifiy
qo'shimcha qo'shiladi.

### 8. AI umuman ishlamagan

Kodda `gemini_model` sozlangan, lekin **hech qayerda ishlatilmagan** edi. AI faqat Bytez'ga
tayanardi, Bytez'dagi barcha model ID'lari esa HTTP 404 qaytaradi (akkaunt model katalogi
bo'sh):

```
google/gemini-2.0-flash -> 404 "Model does not exist or has yet to be added to the Bytez catalog"
openai/gpt-4o-mini      -> 404 (xuddi shunday)
```

Endi **Gemini asosiy provayder**, Bytez esa zaxira. Ishlatish uchun `GEMINI_API_KEY` ni
qo'yish kifoya. Hech biri ishlamasa, foydalanuvchiga sababi ko'rsatiladi.

### 9. Uzun AI javoblari yo'qolib ketardi

Telegram bitta xabarga 4096 belgi ruxsat beradi. Undan uzun javob "Message is too long"
xatosi bilan yo'qolardi. Yangi `_split_for_telegram()` javobni qator/so'z chegarasidan
bo'laklab yuboradi.

### 10. Telegram xatolari tushunarli tilda

`create_new_sticker_set` xatolari (`STICKER_SET_NAME_OCCUPIED`, `PEER_ID_INVALID`,
`STICKER_VIDEO_BIG`, `STICKERS_TOO_MUCH` va boshqalar) endi o'zbek tilida, nima qilish
kerakligi bilan tushuntiriladi.

### Nima tekshirildi

- `py_compile`, `pyflakes`, `ruff` — toza
- Statik emoji: WEBP, 100x100, shaffof
- Animatsion emoji: `ffprobe` → `vp9, 100x100, 3.0s`, ~11.6 KB (64 KB limitidan past)
- Sarlavha: barcha holatlarda ≤64 belgi, `Ism • @kerakli_boladi_bot`
- Baza migratsiyasi haqiqiy `bot.db` ustida sinaldi, `init_db()` qayta-qayta ishlatilsa ham xato bermaydi
- To'liq oqim mocklar bilan: WEBP hujjat → emoji tanlash → pack yaratish → havola
- Mavjud pack'ga qo'shish, aralash format rad etilishi, bo'sh yakunlash, noto'g'ri fayl turi
- AI: Gemini qisqa/uzun javob, Gemini xato → Bytez zaxira, ikkisi ham xato → sabab ko'rsatilishi
