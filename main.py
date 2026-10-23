import os
import io
import re
import json
import time
import html
import random
import asyncio
from datetime import datetime, timezone, timedelta

import aiohttp
from aiohttp import web
from urllib.parse import quote
from qparse import qz_parse_file, qz_shuffle_options, QZ_MAX_BYTES
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, PollAnswer, BotCommand, LinkPreviewOptions,
    KeyboardButtonPollType, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

# ======================= SOZLAMALAR =======================

TOKEN = "".join(os.environ["BOT_TOKEN"].split())
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
BOT_NAME = os.environ.get("BOT_NAME", "Quiz bot")      # post sarlavhasida ko'rinadi
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = "".join(os.environ.get("SUPABASE_KEY", "").split())
TZ = timezone(timedelta(hours=5))                      # Toshkent vaqti
BOT_USERNAME = ""                                      # ishga tushganda o'zi aniqlanadi
CONTACT = "@Demirbek_17_09"                            # "Aloqa" tugmasi shu akkauntga olib boradi

# Majburiy obuna kanallari: (tugma nomi, kanal username)
CHANNELS = [
    ("Kanal 1", "@TalabaMed_2025"),
    ("Kanal 2", "@oltinqalam_uz"),
    ("Kanal 3", "@Edits_foto"),
]

BTN_MAKE = "📝 Quiz tuzish"
BTN_FAST = "⚡ Tezkor quiz tuzish"
BTN_MY = "📂 Mening testlarim"
BTN_CONTACT = "📞 Aloqa"
BTN_FEEDBACK = "💬 Fikr bildirish"
BTN_DONE = "🏁 Tugatish"
BTN_CANCEL = "❌ Bekor qilish"

MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_MAKE), KeyboardButton(text=BTN_FAST)],
              [KeyboardButton(text=BTN_MY)],
              [KeyboardButton(text=BTN_CONTACT), KeyboardButton(text=BTN_FEEDBACK)]],
    resize_keyboard=True,
)

# Savol tuzish paneli (Telegramdagi Quiz Bot kabi: tugma tayyor viktorina oynasini ochadi)
POLL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Savol tuzish", request_poll=KeyboardButtonPollType(type="quiz"))],
              [KeyboardButton(text=BTN_DONE), KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)

SUB_TEXT = (
    "👋 Xush kelibsiz!\n\n"
    "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling. "
    "Obuna bo'lgach «✅ Tekshirish» tugmasini bosing, shundan keyin bot ishlaydi."
)

ABOUT_TEXT = (
    f"🧪 {BOT_NAME}: o'zingiz quiz tuzing, do'stlaringiz bilan yeching\n\n"
    "📝 Quiz tuzish: savollarni o'zingiz bittalab tuzasiz (Telegramdagi Quiz Bot kabi).\n"
    "⚡ Tezkor quiz tuzish: Word, Excel yoki txt faylni yuborasiz, bot uni tayyor quizga aylantiradi. "
    "Jami testni 10, 20, 30... talik qismlarga bo'lish yoki tasodifiy tanlash mumkin.\n"
    "📂 Mening testlarim: siz tuzgan hamma testlar shu yerda saqlanadi.\n\n"
    "Tayyor quizni do'stlaringizga yoki guruhga forward qilasiz, «Boshlash» ni bosgan kishi botda yechadi.\n\n"
    "👉 Boshlash uchun pastdagi ▦ menyu tugmasini bosing."
)

# ======================= OBUNA =======================

bot = Bot(TOKEN)
dp = Dispatcher()


async def not_subscribed(user_id):
    """Obuna bo'lmagan kanallar: [(tugma nomi, username)]"""
    result = []
    for name, username in CHANNELS:
        try:
            m = await bot.get_chat_member(username, user_id)
            if m.status in ("left", "kicked"):
                result.append((name, username))
            elif m.status == "restricted" and not getattr(m, "is_member", True):
                result.append((name, username))
        except Exception as e:
            # Odatda bot kanalda admin emas yoki username noto'g'ri
            print("Obuna tekshirish xatosi:", username, e)
            result.append((name, username))
    return result


def sub_keyboard(channels):
    rows = [[InlineKeyboardButton(text=n, url=f"https://t.me/{u[1:]}")] for n, u in channels]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def need_subscribe(msg: Message):
    left = await not_subscribed(msg.from_user.id)
    if left:
        await msg.answer(SUB_TEXT, reply_markup=sub_keyboard(left))
        return True
    return False


async def send_main(chat_id):
    await bot.send_message(chat_id, ABOUT_TEXT, reply_markup=MENU)


def _menu_texts():
    return {BTN_MAKE, BTN_FAST, BTN_MY, BTN_CONTACT, BTN_FEEDBACK, BTN_DONE, BTN_CANCEL}


# ======================= /start va tekshirish =======================

pending_qz = {}    # obuna bo'lgandan keyin ochiladigan havola
feedback_mode = {}   # user_id -> "choose" | "anon" | "named"
last_feedback = {}   # user_id -> oxirgi yuborilgan vaqt


@dp.message(CommandStart())
async def start(msg: Message, command: CommandObject):
    qz_w.pop(msg.from_user.id, None)
    feedback_mode.pop(msg.from_user.id, None)
    args = (command.args or "") if command else ""
    left = await not_subscribed(msg.from_user.id)
    if args.startswith("qz_"):
        if left:
            pending_qz[msg.from_user.id] = args
        else:
            await qz_deeplink(msg.chat.id, msg.from_user.id, args)
            return
    if left:
        await msg.answer(SUB_TEXT, reply_markup=sub_keyboard(left))
    else:
        await send_main(msg.chat.id)


@dp.message(Command("menu"))
async def menu_cmd(msg: Message):
    if await need_subscribe(msg):
        return
    await msg.answer("📋 Menyu pastda. Yopish uchun telefondagi orqaga tugmasini yoki ▦ ni bosing.", reply_markup=MENU)


@dp.callback_query(F.data == "check")
async def check(cb: CallbackQuery):
    left = await not_subscribed(cb.from_user.id)
    if left:
        await cb.answer("Hali hammasiga obuna bo'lmadingiz!", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=sub_keyboard(left))
        except Exception:
            pass
        return
    await cb.answer()
    try:
        await cb.message.delete()
    except Exception:
        pass
    pend = pending_qz.pop(cb.from_user.id, None)
    if pend:
        await qz_deeplink(cb.message.chat.id, cb.from_user.id, pend)
    else:
        await send_main(cb.message.chat.id)


# ======================= SOZLAMALAR: QUIZ =======================

QZ_TIMES = [15, 30, 45, 60, 90]
QZ_SIZES = [10, 20, 30, 40, 50]
QZ_COUNTS = [10, 20, 30, 50]
QZ_DAILY_LIMIT = 10
QZ_STATE_TTL = 1800

qz_w = {}          # yaratish jarayoni: user_id -> holat
qz_cache = {}      # test id -> (test, vaqt)
qz_sessions = {}   # ishlayotgan testlar: user_id -> sessiya
qz_daily = {}      # (sana, user_id) -> yaratilgan testlar soni

FAST_HELP = (
    "⚡ Tezkor quiz tuzish\n\n"
    "Savollar faylini yuboring: .xlsx (Excel), .docx (Word) yoki .txt, 5 MB gacha. "
    "Matnni oddiy xabar qilib yozib yuborsangiz ham bo'ladi.\n"
    "❗ PDF fayl o'qilmaydi. Uni Word yoki Excelga o'tkazib yuboring.\n\n"
    "Namuna (Word, txt yoki matn):\n"
    "1. Hujayraning energiya markazi qaysi?\n"
    "A) Yadro\nB) Mitoxondriya\nC) Ribosoma\nD) Goldji\n"
    "Javob: B\n\n"
    "To'g'ri javobni belgilash usullari: «Javob: B» qatori, variant oldiga yoki oxiriga * yoki +, "
    "yoki to'g'ri variantni qalin (bold) yozish.\n\n"
    "Excel: 1-ustun savol, keyingi ustunlar variantlar, oxirgi ustun to'g'ri javob (A, B, C yoki variantning o'zi).\n\n"
    "⚠️ Agar faylda to'g'ri javob umuman belgilanmagan bo'lsa, har savolning 1-varianti "
    "(Excelda savoldan keyingi 1-ustun) to'g'ri javob deb olinadi. Variantlar quizda aralashtiriladi.\n\n"
    "Bekor qilish: /bekor"
)

# ======================= BAZA (Supabase) =======================

def db_headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if extra:
        h.update(extra)
    return h


def _qz_kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def qz_pretty_title(name):
    t = re.sub(r"\.(docx|xlsx|txt)$", "", name or "", flags=re.I)
    t = re.sub(r"[_]+", " ", t).strip()
    return (t or "Test")[:60]


async def qz_save(qset):
    try:
        async with aiohttp.ClientSession() as ses:
            async with ses.post(
                f"{SUPABASE_URL}/rest/v1/quiz_sets",
                headers=db_headers({"Prefer": "return=minimal"}),
                json={"id": qset["id"], "owner": qset["owner"], "title": qset["title"],
                      "secs": qset["secs"], "parts": qset["parts"], "author": qset["by"]},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status >= 300:
                    print("quiz_sets yozish xato:", r.status, await r.text())
                    return False
                return True
    except Exception as e:
        print("quiz_sets yozish xatosi:", e)
        return False


async def qz_get(qid):
    hit = qz_cache.get(qid)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    try:
        async with aiohttp.ClientSession() as ses:
            async with ses.get(
                f"{SUPABASE_URL}/rest/v1/quiz_sets?select=*&id=eq.{quote(qid)}",
                headers=db_headers(), timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status >= 300:
                    print("quiz_sets o'qish xato:", r.status, await r.text())
                    return None
                rows = await r.json()
    except Exception as e:
        print("quiz_sets o'qish xatosi:", e)
        return None
    if not rows:
        return None
    row = rows[0]
    parts = row["parts"]
    if isinstance(parts, str):
        parts = json.loads(parts)
    qset = {"id": row["id"], "owner": row.get("owner"), "title": row.get("title") or "Test",
            "secs": row["secs"], "parts": parts, "by": row.get("author") or "",
            "desc": (parts[0].get("desc") or "") if parts else ""}
    qz_cache[qid] = (qset, time.time())
    if len(qz_cache) > 200:
        qz_cache.pop(next(iter(qz_cache)))
    return qset


async def qz_list_owner(uid):
    """Shu bot tuzgan testlar (id 'i' bilan boshlanadi), eng yangisi birinchi. Xato bo'lsa None."""
    base = f"{SUPABASE_URL}/rest/v1/quiz_sets?owner=eq.{uid}&id=like.i*&limit=300"
    attempts = [(base + "&select=id,title,created_at&order=created_at.desc", False),
                (base + "&select=id,title", True)]      # created_at ustuni bo'lmasa: qo'shilish tartibi
    for url, rev in attempts:
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get(url, headers=db_headers(), timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 400:
                        continue
                    if r.status >= 300:
                        print("quiz_sets ro'yxat xato:", r.status, await r.text())
                        return None
                    rows = await r.json()
                    return list(reversed(rows)) if rev else rows
        except Exception as e:
            print("quiz_sets ro'yxat xatosi:", e)
            return None
    return None


QZ_KIND_NAMES = {"a": "Jami", "r": "Tasodifiy", "m": "Qo'lda"}


def qz_group_tests(rows):
    """Bir xil nomli va bir xil turdagi testlar bitta hisoblanadi (eng yangisi qoladi)."""
    seen = {}
    for r in rows:                                   # rows: eng yangisi birinchi
        title = (r.get("title") or "Test").strip()
        kind = (r.get("id") or "")[1:2]
        key = (title.lower(), kind)
        if key not in seen:
            seen[key] = {"id": r["id"], "title": title, "kind": kind}
    return list(seen.values())


def qz_post_chunks(qset):
    """Ikkinchi rasmdagidek post: {1-30}  Boshlash ... (bir xabarda 80 tagacha havola)."""
    lines = []
    for i, part in enumerate(qset["parts"]):
        url = f"https://t.me/{BOT_USERNAME}?start=qz_{qset['id']}_{i}"
        lines.append(f"{{{html.escape(part['l'])}}}    <a href=\"{url}\">Boshlash</a>")
    desc = qset.get("desc") or ""
    head = (
        f"🧪 <b>{html.escape(BOT_NAME)}</b>\n"
        f"{html.escape(qset['title'])}\n"
        + (f"{html.escape(desc)}\n" if desc else "")
        + f"Tayyorladi: <b>{html.escape(qset.get('by') or '')}</b>\n"
        f"⏱ Har savolga {qset['secs']} soniya\n\n"
    )
    chunks = []
    for k in range(0, len(lines), 80):
        chunks.append((head if k == 0 else "") + "\n".join(lines[k:k + 80]))
    return chunks


async def qz_send_html(chat_id, text, **kw):
    return await bot.send_message(chat_id, text, parse_mode="HTML",
                                  link_preview_options=LinkPreviewOptions(is_disabled=True), **kw)


# ======================= YARATISH: UMUMIY =======================

def _qz_state(m, *steps):
    uid = m.from_user.id if m.from_user else None
    w = qz_w.get(uid) if uid else None
    return bool(w) and w["step"] in steps and time.time() - w["ts"] < QZ_STATE_TTL


def _qz_plain_text(m):
    return bool(m.text) and not m.text.startswith("/") and m.text not in _menu_texts()


async def _del_id(chat_id, mid):
    try:
        await bot.delete_message(chat_id, mid)
    except Exception:
        pass


async def _say(msg, w, text, **kw):
    """Xabar yuboradi va oldingi vaqtinchalik xabarni o'chiradi (chat toza qolsin)."""
    old = w.get("last")
    m = await msg.answer(text, **kw)
    w["last"] = m.message_id
    if old:
        await _del_id(msg.chat.id, old)
    return m


def _qz_time_kb():
    return _qz_kb([[(f"{t} soniya", f"qz:t:{t}") for t in QZ_TIMES[:3]],
                   [(f"{t} soniya", f"qz:t:{t}") for t in QZ_TIMES[3:]],
                   [("❌ Bekor qilish", "qz:x")]])


async def _ask_time(target, w):
    await _say(target, w, "Har bir savolga necha soniya vaqt beramiz?", reply_markup=_qz_time_kb())


@dp.message(Command("bekor"))
@dp.message(F.text == BTN_CANCEL)
async def cmd_bekor(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    w = qz_w.pop(msg.from_user.id, None)
    if w and w.get("last"):
        await _del_id(msg.chat.id, w["last"])
    await msg.answer("Bekor qilindi.", reply_markup=MENU)


# ======================= 1) QUIZ TUZISH (Quiz Bot kabi, bittalab) =======================

@dp.message(F.text == BTN_MAKE)
async def btn_make(msg: Message):
    if await need_subscribe(msg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    w = {"step": "m_title", "ts": time.time(), "mode": "manual", "qs": [], "desc": ""}
    qz_w[msg.from_user.id] = w
    await _say(
        msg, w,
        "Keling, yangi test tuzamiz. Dastlab, menga testingiz sarlavhasini "
        "(masalan: «Biologiya 1-mavzu» yoki «Anatomiya 20 ta savol») yuboring.\n\n"
        "Bekor qilish: /bekor",
        reply_markup=ReplyKeyboardRemove(),
    )


async def _ask_first_question(msg, w):
    w["step"] = "m_q"
    await _say(
        msg, w,
        "Yaxshi. Endi birinchi savolingiz bilan viktorina yuboring: pastdagi «Savol tuzish» tugmasini bosing, "
        "savol va variantlarni yozing, to'g'ri javobni belgilang va «Tuzish» ni bosing.\n\n"
        "Hamma savollar tayyor bo'lganda «🏁 Tugatish» ni bosing.",
        reply_markup=POLL_KB,
    )


@dp.message(Command("skip"), lambda m: _qz_state(m, "m_desc"))
async def make_skip(msg: Message):
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    await _ask_first_question(msg, w)


@dp.message(F.poll, lambda m: _qz_state(m, "m_q"))
async def make_poll(msg: Message):
    p = msg.poll
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    if p.type != "quiz" or p.correct_option_id is None:
        await msg.answer("Bu viktorina emas. Pastdagi «Savol tuzish» tugmasi orqali yuboring "
                         "(«To'g'ri javobni belgilash» yoqilgan bo'lishi kerak).")
        return
    expl = (getattr(p, "explanation", None) or "").strip()
    w["qs"].append({"q": p.question, "o": [o.text for o in p.options], "c": p.correct_option_id,
                    "e": expl[:200]})
    n = len(w["qs"])
    await _say(
        msg, w,
        f"✅ {n}-savol qo'shildi.\n\nKeyingi savol uchun «Savol tuzish» ni bosing, "
        f"tugatish uchun «🏁 Tugatish» ni bosing.",
        reply_markup=POLL_KB,
    )


@dp.message(Command("done"))
@dp.message(F.text == BTN_DONE)
async def make_done(msg: Message):
    w = qz_w.get(msg.from_user.id)
    if not w or w.get("mode") != "manual" or w["step"] != "m_q":
        await msg.answer("Hozir savol tuzish jarayoni yo'q.", reply_markup=MENU)
        return
    if not w["qs"]:
        await msg.answer("Hali birorta savol qo'shilmagan. «Savol tuzish» tugmasini bosing.")
        return
    w.update(step="time", ts=time.time())
    await _say(msg, w, f"🏁 Jami {len(w['qs'])} ta savol tayyor.", reply_markup=ReplyKeyboardRemove())
    await _ask_time(msg, w)


@dp.message(lambda m: _qz_state(m, "m_title", "m_desc", "m_q") and _qz_plain_text(m))
async def make_text(msg: Message):
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    t = msg.text.strip()
    if w["step"] == "m_title":
        w["title"] = t[:80]
        w["step"] = "m_desc"
        await _say(msg, w, "Yaxshi. Endi menga testingiz tavsifini yuboring. "
                           "Bu ixtiyoriy, bu bosqichni tashlab ketishingiz mumkin: /skip.")
    elif w["step"] == "m_desc":
        w["desc"] = t[:300]
        await _ask_first_question(msg, w)
    else:
        await msg.answer("Savolni pastdagi «Savol tuzish» tugmasi orqali yuboring.", reply_markup=POLL_KB)


# ======================= 2) TEZKOR QUIZ (fayldan) =======================

@dp.message(F.text == BTN_FAST)
async def btn_fast(msg: Message):
    if await need_subscribe(msg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    w = {"step": "file", "ts": time.time(), "mode": None}
    qz_w[msg.from_user.id] = w
    await _say(msg, w, FAST_HELP, reply_markup=MENU)


async def qz_after_parse(msg, name, data):
    uid = msg.from_user.id
    try:
        qs, notes = qz_parse_file(name, data)
    except ValueError as e:
        await msg.answer(f"❌ {e}\n\nNamunani qayta ko'rish uchun «{BTN_FAST}» tugmasini bosing.")
        return
    w = qz_w[uid]
    w.update(step="mode", qs=qs, title=qz_pretty_title(name), ts=time.time())
    text = f"✅ Jami {len(qs)} ta test topildi."
    if notes:
        text += "\n⚠️ " + "\n⚠️ ".join(notes)
    text += "\n\nJami testdan quiz qilaymi yoki son kiritasizmi?"
    await _say(msg, w, text, reply_markup=_qz_kb([
        [("📚 Jami testdan (qismlarga bo'lib)", "qz:m:all")],
        [("🔢 Son kiritaman (tasodifiy)", "qz:m:rnd")],
        [("❌ Bekor qilish", "qz:x")],
    ]))


@dp.message(F.document, lambda m: _qz_state(m, "file"))
async def fast_on_file(msg: Message):
    doc = msg.document
    name = doc.file_name or "test.txt"
    if name.lower().endswith(".pdf"):
        await msg.answer("❌ PDF fayl o'qilmaydi. Uni Word (.docx) yoki Excel (.xlsx) qilib yuboring.")
        return
    if doc.file_size and doc.file_size > QZ_MAX_BYTES:
        await msg.answer("Fayl juda katta (5 MB gacha).")
        return
    try:
        buf = await bot.download(doc, destination=io.BytesIO())
        data = buf.getvalue()
    except Exception as e:
        print("quiz fayl yuklash xatosi:", e)
        await msg.answer("Faylni yuklab bo'lmadi. Qayta yuboring.")
        return
    await qz_after_parse(msg, name, data)


@dp.message(lambda m: _qz_state(m, "file") and _qz_plain_text(m) and len(m.text) > 40)
async def fast_on_text(msg: Message):
    await qz_after_parse(msg, "test.txt", msg.text.encode("utf-8"))


@dp.message(lambda m: _qz_state(m, "count") and _qz_plain_text(m))
async def fast_on_count(msg: Message):
    w = qz_w[msg.from_user.id]
    n = len(w["qs"])
    t = msg.text.strip()
    if not t.isdigit() or not (1 <= int(t) <= n):
        await msg.answer(f"1 dan {n} gacha raqam yozing (jami {n} ta test bor).")
        return
    w.update(count=int(t), step="time", ts=time.time())
    await _ask_time(msg, w)


# ======================= 3) MENING TESTLARIM =======================

@dp.message(F.text == BTN_MY)
async def btn_my(msg: Message):
    if await need_subscribe(msg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    rows = await qz_list_owner(msg.from_user.id)
    if rows is None:
        await msg.answer("Testlar ro'yxatini olib bo'lmadi. Birozdan keyin qayta urinib ko'ring.")
        return
    if not rows:
        await msg.answer("Siz hali test tuzmagansiz. «📝 Quiz tuzish» yoki «⚡ Tezkor quiz tuzish» ni bosing.")
        return
    groups = qz_group_tests(rows)[:40]
    kb = [[(f"{i + 1}. {g['title'][:38]} · {QZ_KIND_NAMES.get(g['kind'], 'Test')}", f"qm:{g['id']}")]
          for i, g in enumerate(groups)]
    await msg.answer(f"📂 Sizning testlaringiz ({len(groups)} ta). Nomini bosing, yig'ilgan testlar yuboriladi:",
                     reply_markup=_qz_kb(kb))


@dp.callback_query(F.data.startswith("qm:"))
async def qz_my_cb(cb: CallbackQuery):
    qset = await qz_get(cb.data.split(":")[1])
    if not qset or (qset.get("owner") != cb.from_user.id and cb.from_user.id != ADMIN_ID):
        await cb.answer("Test topilmadi.", show_alert=True)
        return
    await cb.answer()
    for chunk in qz_post_chunks(qset):
        await qz_send_html(cb.message.chat.id, chunk)


# ======================= 4) ALOQA va FIKR BILDIRISH (eski botdan) =======================

@dp.message(F.text == BTN_CONTACT)
async def btn_contact(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✉️ Yozish", url=f"https://t.me/{CONTACT[1:]}")
    ]])
    await msg.answer(f"📞 Aloqa uchun: {CONTACT}", reply_markup=kb)


@dp.message(F.text == BTN_FEEDBACK)
async def btn_feedback(msg: Message):
    qz_w.pop(msg.from_user.id, None)
    feedback_mode[msg.from_user.id] = "choose"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕶 Anonim yuborish", callback_data="fb_anon")],
        [InlineKeyboardButton(text="👤 Ismim bilan yuborish", callback_data="fb_named")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fb_cancel")],
    ])
    await msg.answer(
        "💬 Bot haqida fikringizni bildiring.\n\n"
        "Anonim yuborsangiz, sizning ismingiz va akkauntingiz egasiga ko'rsatilmaydi. "
        "Qanday yuborasiz?",
        reply_markup=kb,
    )


@dp.callback_query(F.data.in_({"fb_anon", "fb_named", "fb_cancel"}))
async def fb_choice(cb: CallbackQuery):
    uid = cb.from_user.id
    if cb.data == "fb_cancel":
        feedback_mode.pop(uid, None)
        await cb.answer("Bekor qilindi")
        try:
            await cb.message.delete()
        except Exception:
            pass
        return
    feedback_mode[uid] = "anon" if cb.data == "fb_anon" else "named"
    await cb.answer()
    how = "anonim" if cb.data == "fb_anon" else "ismingiz bilan"
    try:
        await cb.message.edit_text(f"✍️ Fikringizni bitta xabar qilib yozing ({how} yuboriladi).\nBekor qilish uchun /bekor ni yuboring.")
    except Exception:
        pass


@dp.message(lambda m: feedback_mode.get(m.from_user.id) in ("anon", "named") and _qz_plain_text(m))
async def feedback_text(msg: Message):
    uid = msg.from_user.id
    mode = feedback_mode.get(uid)
    if not ADMIN_ID:
        feedback_mode.pop(uid, None)
        await msg.answer("Fikr qabul qilish hozircha ishlamayapti.")
        return
    now = time.time()
    if now - last_feedback.get(uid, 0) < 30:
        await msg.answer("Iltimos, biroz kutib, keyin yuboring.")
        return
    text = msg.text.strip()[:1500]
    if mode == "anon":
        head = "💬 Yangi fikr (anonim)"
    else:
        u = msg.from_user
        name = " ".join(x for x in [u.first_name, u.last_name] if x) or "Ism yo'q"
        uname = f" @{u.username}" if u.username else ""
        head = f"💬 Yangi fikr\n👤 {name}{uname} (ID: {u.id})"
    try:
        await bot.send_message(ADMIN_ID, f"{head}\n\n{text}")
    except Exception as e:
        print("Fikrni yuborishda xato:", e)
        await msg.answer("Yuborib bo'lmadi, keyinroq urinib ko'ring.")
        return
    last_feedback[uid] = now
    feedback_mode.pop(uid, None)
    await msg.answer("✅ Rahmat! Fikringiz yuborildi.")


# ======================= TUGMALAR (callback) =======================

@dp.callback_query(F.data.startswith("qz:"))
async def qz_on_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    parts = cb.data.split(":")
    kind = parts[1]
    w = qz_w.get(uid)
    if kind == "x":
        qz_w.pop(uid, None)
        await _del_id(cb.message.chat.id, cb.message.message_id)
        if w and w.get("last"):
            await _del_id(cb.message.chat.id, w["last"])
        await cb.message.answer("Bekor qilindi.", reply_markup=MENU)
        await cb.answer()
        return
    if not w or time.time() - w["ts"] > QZ_STATE_TTL:
        qz_w.pop(uid, None)
        await cb.answer("Jarayon eskirgan. Menyudan qaytadan boshlang.", show_alert=True)
        return
    w["ts"] = time.time()
    n = len(w.get("qs") or [])
    if kind == "m":
        w["mode"] = parts[2]
        if parts[2] == "all":
            sizes = [s for s in QZ_SIZES if s <= n] or [n]
            w["step"] = "size"
            await _say(
                cb.message, w,
                f"Jami {n} ta test. Har bir quizda nechta savol bo'lsin?\n"
                f"(Hammasi shu sondan bo'linib, ketma-ket quizlar yaratiladi.)",
                reply_markup=_qz_kb([[(str(s), f"qz:s:{s}") for s in sizes[:3]],
                                     [(str(s), f"qz:s:{s}") for s in sizes[3:]],
                                     [("❌ Bekor qilish", "qz:x")]]))
        else:
            counts = [c for c in QZ_COUNTS if c <= n] or [n]
            w["step"] = "count"
            await _say(
                cb.message, w,
                f"Jami {n} ta test bor. Nechta savollik quiz kerak?\n"
                f"1 dan {n} gacha son yozing yoki tugmani bosing. Savollar tasodifiy tanlanadi.",
                reply_markup=_qz_kb([[(str(c), f"qz:c:{c}") for c in counts],
                                     [("❌ Bekor qilish", "qz:x")]]))
    elif kind == "s":
        w["size"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message, w)
    elif kind == "c":
        w["count"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message, w)
    elif kind == "t":
        w["secs"] = max(5, min(int(parts[2]), 600))
        if w.get("last"):
            await _del_id(cb.message.chat.id, w["last"])
        await qz_create(cb, w)
        return
    await cb.answer()


async def qz_create(cb, w):
    uid = cb.from_user.id
    today = datetime.now(TZ).date().isoformat()
    if qz_daily.get((today, uid), 0) >= QZ_DAILY_LIMIT and uid != ADMIN_ID:
        await cb.answer(f"Kuniga {QZ_DAILY_LIMIT} tagacha quiz yaratish mumkin.", show_alert=True)
        return
    await cb.answer("Yaratilmoqda...")
    rnd = random.Random()
    if w["mode"] == "manual":
        qs = list(w["qs"])                      # qo'lda tuzilganda variantlar aralashtirilmaydi
        parts = [{"l": f"1-{len(qs)}", "qs": qs}]
        if w.get("desc"):
            parts[0]["desc"] = w["desc"]
    else:
        prepared = [qz_shuffle_options(q, rnd) for q in w["qs"]]
        n = len(prepared)
        if w["mode"] == "all":
            size = w["size"]
            parts = [{"l": f"{i + 1}-{min(i + size, n)}", "qs": prepared[i:i + size]} for i in range(0, n, size)]
        else:
            parts = [{"l": f"Tasodifiy {w['count']} ta", "qs": rnd.sample(prepared, w["count"])}]
    # id: "i" (shu botniki) + tur (a=jami, r=tasodifiy, m=qo'lda) + 5 ta tasodifiy belgi
    kind = {"manual": "m", "all": "a"}.get(w["mode"], "r")
    qid = "i" + kind + "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=5))
    qset = {"id": qid, "owner": uid, "by": (cb.from_user.first_name or "")[:30],
            "title": w.get("title") or "Test", "secs": w["secs"], "parts": parts,
            "desc": w.get("desc") or ""}
    if not await qz_save(qset):
        await cb.message.answer("Quizni saqlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.", reply_markup=MENU)
        return
    qz_daily[(today, uid)] = qz_daily.get((today, uid), 0) + 1
    qz_w.pop(uid, None)
    qz_cache[qid] = (qset, time.time())
    await cb.message.answer(
        f"✅ Tayyor! {len(parts)} ta quiz yaratildi. Quyidagi postni do'stlaringizga yoki guruhga yuboring (forward): "
        "«Boshlash» ni bosgan kishi quizni botda yechadi.\n\n"
        "Keyinroq «📂 Mening testlarim» orqali ham topasiz.",
        reply_markup=MENU,
    )
    for chunk in qz_post_chunks(qset):
        await qz_send_html(cb.message.chat.id, chunk)


# ======================= QUIZ O'TKAZISH =======================

async def qz_prep(chat_id, qset, p):
    part = qset["parts"][p]
    text = (
        f"🎲 “{qset['title']} {part['l']}” testiga tayyorlaning\n\n"
        f"🖊 {len(part['qs'])} ta savol\n"
        f"⏱ Har bir savol uchun {qset['secs']} soniya\n\n"
        "🏁 Tayyor bo'lganingizda quyidagi tugmani bosing.\n"
        "Uni to'xtatish uchun /stop buyrug'ini yuboring."
    )
    await bot.send_message(chat_id, text, reply_markup=_qz_kb([[("🏁 Boshlash", f"qs:{qset['id']}:{p}")]]))


async def qz_deeplink(chat_id, uid, args):
    m = re.fullmatch(r"qz_([a-z0-9]+)_(\d+)", args or "")
    qset = await qz_get(m.group(1)) if m else None
    if not qset or int(m.group(2)) >= len(qset["parts"]):
        await bot.send_message(chat_id, "Bu quiz topilmadi yoki o'chirilgan.")
        return
    await qz_prep(chat_id, qset, int(m.group(2)))


@dp.callback_query(F.data.startswith("qs:"))
async def qz_begin_cb(cb: CallbackQuery):
    _, qid, p = cb.data.split(":")
    uid = cb.from_user.id
    if await not_subscribed(uid):
        await cb.answer("Avval majburiy kanallarga obuna bo'ling (/start).", show_alert=True)
        return
    qset = await qz_get(qid)
    if not qset or int(p) >= len(qset["parts"]):
        await cb.answer("Quiz topilmadi.", show_alert=True)
        return
    old = qz_sessions.pop(uid, None)
    if old and old.get("task"):
        old["task"].cancel()
    part = qset["parts"][int(p)]
    qz_sessions[uid] = {"set": qid, "p": int(p), "title": qset["title"], "label": part["l"], "secs": qset["secs"],
                        "qs": part["qs"], "i": 0, "ok": 0, "bad": [], "poll_id": None, "mid": None,
                        "task": None, "chat": cb.message.chat.id, "t0": time.time()}
    await cb.answer()
    await qz_send(uid)


async def qz_send(uid):
    s = qz_sessions.get(uid)
    if not s:
        return
    if s["i"] >= len(s["qs"]):
        await qz_finish(uid)
        return
    q = s["qs"][s["i"]]
    head = f"[{s['i'] + 1}/{len(s['qs'])}]"
    letters = "ABCDEFGHIJ"
    try:
        if len(head) + 1 + len(q["q"]) > 300 or any(len(o) > 100 for o in q["o"]):
            text = f"{head} {q['q']}\n\n" + "\n".join(f"{letters[k]}) {o}" for k, o in enumerate(q["o"]))
            await bot.send_message(s["chat"], text[:4000])
            question, options = f"{head} Javobni tanlang", list(letters[:len(q["o"])])
        else:
            question, options = f"{head} {q['q']}", q["o"]
        extra = {"explanation": q["e"]} if q.get("e") else {}
        m = await bot.send_poll(s["chat"], question=question, options=options, type="quiz",
                                correct_option_id=q["c"], is_anonymous=False, open_period=s["secs"], **extra)
    except Exception as e:
        print("quiz savol yuborilmadi:", e)
        qz_sessions.pop(uid, None)
        try:
            await bot.send_message(s["chat"], "Savolni yuborib bo'lmadi. Quizni qaytadan boshlang.")
        except Exception:
            pass
        return
    s["poll_id"], s["mid"] = m.poll.id, m.message_id
    i = s["i"]
    s["task"] = asyncio.create_task(qz_timeout(uid, i, s["secs"]))


async def qz_timeout(uid, i, secs):
    try:
        await asyncio.sleep(secs + 2)
    except asyncio.CancelledError:
        return
    s = qz_sessions.get(uid)
    if s and s["i"] == i:
        s["bad"].append((i, None))
        s["i"] += 1
        s["poll_id"] = None
        await qz_send(uid)


@dp.poll_answer()
async def qz_on_answer(ev: PollAnswer):
    uid = ev.user.id
    s = qz_sessions.get(uid)
    if not s or ev.poll_id != s["poll_id"] or not ev.option_ids:
        return
    if s["task"]:
        s["task"].cancel()
    i = s["i"]
    if ev.option_ids[0] == s["qs"][i]["c"]:
        s["ok"] += 1
    else:
        s["bad"].append((i, ev.option_ids[0]))
    s["poll_id"] = None
    s["i"] += 1
    await asyncio.sleep(0.8)
    if qz_sessions.get(uid) is s:
        await qz_send(uid)


async def qz_finish(uid, early=False):
    s = qz_sessions.pop(uid, None)
    if not s:
        return
    if s["task"]:
        s["task"].cancel()
    if early and s.get("mid"):
        try:
            await bot.stop_poll(s["chat"], s["mid"])
        except Exception:
            pass
    n = len(s["qs"])
    wrong = [b for b in s["bad"] if b[1] is not None]
    answered = s["ok"] + len(wrong)
    skipped = n - answered
    secs = int(time.time() - s["t0"])
    lines = [
        f"🏁 Quiz {'to‘xtatildi' if early else 'yakunlandi'}: {s['title']} {s['label']}", "",
        f"✅ To'g'ri: {s['ok']} / {n} ({round(100 * s['ok'] / n)}%)",
        f"❌ Xato: {len(wrong)}",
        f"⏭ Javobsiz: {skipped}",
        f"⏱ Vaqt: {secs // 60} daq {secs % 60} soniya",
    ]
    if wrong:
        lines += ["", "Xato qilingan savollar:"]
        for i, _ in wrong[:10]:
            q = s["qs"][i]
            qt = q["q"] if len(q["q"]) <= 70 else q["q"][:67] + "..."
            lines.append(f"{i + 1}) {qt}\n   ➜ To'g'ri: {q['o'][q['c']][:80]}")
        if len(wrong) > 10:
            lines.append(f"... va yana {len(wrong) - 10} ta")
    await bot.send_message(s["chat"], "\n".join(lines), reply_markup=_qz_kb([
        [("🔁 Qayta boshlash", f"qs:{s['set']}:{s['p']}")],
        [("📋 Boshqa qismlar", f"qp:{s['set']}")],
    ]))


@dp.message(Command("stop"))
async def cmd_stop(msg: Message):
    if msg.from_user.id in qz_sessions:
        await qz_finish(msg.from_user.id, early=True)
    else:
        await msg.answer("Hozir faol quiz yo'q.")


@dp.callback_query(F.data.startswith("qp:"))
async def qz_parts_cb(cb: CallbackQuery):
    qset = await qz_get(cb.data.split(":")[1])
    await cb.answer()
    if qset:
        for chunk in qz_post_chunks(qset):
            await qz_send_html(cb.message.chat.id, chunk)


# ======================= ISHGA TUSHIRISH =======================

async def health(request):
    return web.Response(text="ok")


async def main():
    global BOT_USERNAME
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL va SUPABASE_KEY o'zgaruvchilari kiritilmagan.")
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print("Bot ishga tushdi: @" + BOT_USERNAME)
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands([
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="menu", description="Menyuni ochish"),
        BotCommand(command="stop", description="Ishlayotgan quizni to'xtatish"),
        BotCommand(command="bekor", description="Quiz tuzishni bekor qilish"),
    ])
    port = os.environ.get("PORT")
    if port:                                   # Render/Railway kabi hostinglar uchun
        app = web.Application()
        app.router.add_get("/", health)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
