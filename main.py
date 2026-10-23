import os
import io
import re
import json
import time
import html
import random
import asyncio
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import aiohttp
from aiohttp import web
from urllib.parse import quote
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, PollAnswer, BotCommand, LinkPreviewOptions,
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

# Majburiy obuna kanallari: (tugma nomi, kanal username)
CHANNELS = [
    ("Kanal 1", "@TalabaMed_2025"),
    ("Kanal 2", "@oltinqalam_uz"),
    ("Kanal 3", "@Edits_foto"),
]

BTN_MAKE = "📝 Quiz tuzish"
BTN_FAST = "⚡ Tezkor quiz tuzish"

MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_MAKE), KeyboardButton(text=BTN_FAST)]],
    resize_keyboard=True,
)

SUB_TEXT = (
    "👋 Xush kelibsiz!\n\n"
    "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling. "
    "Obuna bo'lgach «✅ Tekshirish» tugmasini bosing, shundan keyin bot ishlaydi."
)

ABOUT_TEXT = (
    f"🧪 {BOT_NAME}: o'zingiz quiz tuzing, do'stlaringiz bilan yeching\n\n"
    "📝 Quiz tuzish: savollarni o'zingiz bittalab kiritasiz (Telegramdagi Quiz Bot kabi).\n"
    "⚡ Tezkor quiz tuzish: Word, Excel yoki txt faylni yuborasiz, bot uni tayyor quizga aylantiradi. "
    "Jami testni 10, 20, 30... talik qismlarga bo'lish yoki tasodifiy tanlash mumkin.\n\n"
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
    return {BTN_MAKE, BTN_FAST}


# ======================= /start va tekshirish =======================

pending_qz = {}    # obuna bo'lgandan keyin ochiladigan havola


@dp.message(CommandStart())
async def start(msg: Message, command: CommandObject):
    qz_w.pop(msg.from_user.id, None)
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
      # ======================= FAYLDAN SAVOLLARNI O'QISH (eski botdan) =======================

QZ_MAX_Q = 1000
QZ_MAX_BYTES = 5 * 1024 * 1024
_QZ_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_QZ_ANS_RE = re.compile(r"^\s*(?:to['‘’ʻ`]?g['‘’ʻ`]?ri\s+)?(?:javob|answer|ans|kalit|key|ответ)\s*[:=\-–]\s*\(?([A-Ha-hА-Яа-я1-8])\)?\b", re.I)
_QZ_OPT_RE = re.compile(r"^\s*([*+#✅✔√]?)\s*\(?([A-Za-zА-Яа-я])\)?\s*[\.\)\]:]\s*(.*\S)\s*$")
_QZ_NUM_RE = re.compile(r"^\s*(?:savol|вопрос|question)?\s*№?\s*(\d{1,4})\s*[\.\)\-:]\s*", re.I)
_QZ_LOOK = {"А": 0, "В": 1, "С": 2, "Е": 4, "Н": 7}
_QZ_SEQ = {c: i for i, c in enumerate("АБВГДЕЖЗ")}
_QZ_NOSHUFFLE = re.compile(r"(hammasi|barcha|yuqoridagi|ikkalasi|hech biri|va\s+[a-h]\b|\b[a-h]\s+va\b|все|ни одно|оба)", re.I)


def _qz_idx(ch):
    ch = ch.upper()
    if "A" <= ch <= "H":
        return {ord(ch) - 65}
    c = set()
    if ch in _QZ_LOOK: c.add(_QZ_LOOK[ch])
    if ch in _QZ_SEQ: c.add(_QZ_SEQ[ch])
    return c


def qz_read_docx(data):
    """[(matn, qalin_mi)] : abzatslar (bo'sh abzatslar ham saqlanadi)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(_QZ_W + "p"):
        text, runs_bold = "", []
        for r in p.iter(_QZ_W + "r"):
            t = ""
            for n in r:
                if n.tag == _QZ_W + "t": t += n.text or ""
                elif n.tag == _QZ_W + "tab": t += " "
                elif n.tag == _QZ_W + "br": t += "\n"
            if not t.strip(): 
                text += t
                continue
            rp = r.find(_QZ_W + "rPr")
            b = rp.find(_QZ_W + "b") if rp is not None else None
            bold = b is not None and b.get(_QZ_W + "val") not in ("0", "false")
            text += t
            runs_bold.append(bold)
        allbold = bool(runs_bold) and all(runs_bold)
        for line in text.split("\n"):
            out.append((line, allbold and bool(line.strip())))
    return out


def qz_read_xlsx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        raise ValueError("Excel faylida varaq topilmadi.")
    rows = []
    for row in ET.fromstring(z.read(sheets[0])).iter(ns + "row"):
        cells = {}
        for c in row.iter(ns + "c"):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0):
                col = col * 26 + (ord(ch) - 64)
            t = c.get("t")
            if t == "s":
                v = c.find(ns + "v")
                val = shared[int(v.text)] if v is not None and v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(ns + "t"))
            else:
                v = c.find(ns + "v")
                val = (v.text or "") if v is not None else ""
            cells[col - 1] = val.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _qz_finish(qs, notes):
    """Tekshiruv va to'g'ri javobsiz savollarni hal qilish."""
    known = [q for q in qs if q["c"] is not None]
    if not qs:
        return [], notes
    if not known:   # hech bir savolda to'g'ri javob belgilanmagan: 1-variant to'g'ri deb olinadi
        for q in qs: q["c"] = 0
        notes.append("To'g'ri javob belgilanmagan edi: har savolning 1-varianti to'g'ri deb olindi.")
        return qs, notes
    miss = len(qs) - len(known)
    if miss:
        notes.append(f"{miss} ta savolda to'g'ri javob topilmadi, ular qo'shilmadi.")
    return known, notes


def _qz_clean_opt(t):
    t = re.sub(r"\s*(?:\(\s*(?:\+|to['‘’ʻ`]?g['‘’ʻ`]?ri)\s*\)|✅|✔|\*)\s*$", "", t, flags=re.I)
    return t.strip()


def qz_parse_block(text):
    """Savol / ==== / #to'g'ri / ==== / xato ... ++++ ko'rinishi."""
    notes, qs = [], []
    blocks = re.split(r"\n\s*\+{3,}\s*\n", "\n" + text + "\n")
    if len(blocks) == 1:
        blocks = re.split(r"\n\s*\n(?=[^\n]+\n\s*={3,})", "\n" + text + "\n")
    bad = 0
    for b in blocks:
        parts = [p.strip() for p in re.split(r"\n\s*={3,}\s*\n", b.strip())]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            if parts: bad += 1
            continue
        q = _QZ_NUM_RE.sub("", " ".join(parts[0].split("\n")), count=1).strip()
        opts, c, marks = [], None, 0
        for p in parts[1:]:
            p = " ".join(p.split("\n")).strip()
            if p[:1] in "#*+":
                marks += 1
                c = len(opts)
                p = p[1:].strip()
            opts.append(p)
        qs.append({"q": q, "o": opts, "c": c if marks == 1 else None})
    if bad: notes.append(f"{bad} ta blok tushunarsiz bo'lgani uchun o'tkazib yuborildi.")
    return _qz_finish(qs, notes)


def qz_parse_letter(lines):
    """lines: [(matn, qalin)]. Variantlar A) B) C) D) ko'rinishida."""
    notes, qs = [], []
    cur = None
    blank_after_opts = False

    def flush():
        nonlocal cur
        if cur and len(cur["o"]) >= 2:
            marks = [i for i, m in enumerate(cur["m"]) if m]
            c = None
            if len(marks) == 1: c = marks[0]
            elif not marks and cur.get("ans") is not None and cur["ans"] < len(cur["o"]): c = cur["ans"]
            else:
                bolds = [i for i, b in enumerate(cur["b"]) if b]
                if len(bolds) == 1 and len(cur["o"]) > 1: c = bolds[0]
            qs.append({"q": cur["q"].strip(), "o": cur["o"], "c": c})
        cur = None

    for raw, bold in lines:
        t = raw.strip()
        if not t:
            if cur and cur["o"]: blank_after_opts = True
            continue
        ma = _QZ_ANS_RE.match(t)
        if ma and cur and cur["o"]:
            ch = ma.group(1)
            if ch.isdigit(): idx = int(ch) - 1
            else:
                cand = _qz_idx(ch)
                idx = min(cand) if cand else None
            cur["ans"] = idx
            continue
        mo = _QZ_OPT_RE.match(t)
        if mo and cur is not None:
            mark, ch, body = mo.group(1), mo.group(2), mo.group(3)
            expect = len(cur["o"])
            if expect in _qz_idx(ch):
                trail = bool(re.search(r"(?:\(\s*(?:\+|to['‘’ʻ`]?g['‘’ʻ`]?ri)\s*\)|✅|✔|\*)\s*$", body, re.I))
                lead = body[:1] in "*+#✅✔√"
                if lead: body = body[1:].strip()
                cur["o"].append(_qz_clean_opt(body))
                cur["m"].append(bool(mark) or trail or lead)
                cur["b"].append(bold)
                blank_after_opts = False
                continue
        # variant bo'lmagan qator
        if cur is not None and cur["o"]:
            new_q = bool(_QZ_NUM_RE.match(t)) or blank_after_opts or len(cur["o"]) >= 2
            if not new_q:   # variantning davomi
                cur["o"][-1] += " " + t
                continue
            flush()
            blank_after_opts = False
        if cur is None:
            cur = {"q": "", "o": [], "m": [], "b": [], "ans": None}
        cur["q"] += (" " if cur["q"] else "") + _QZ_NUM_RE.sub("", t, count=1)
    flush()
    return _qz_finish(qs, notes)


def qz_parse_rows(rows):
    """Excel: Savol | A | B | C | D | To'g'ri javob."""
    notes, qs = [], []
    if not rows: return [], notes
    head = [c.lower() for c in rows[0]]
    has_head = any(len(c) <= 20 and "?" not in c and re.search(r"savol|question|вопрос", c) for c in head)
    ans_col = None
    if has_head:
        for i, c in enumerate(head):
            if re.search(r"to['‘’ʻ`]?g['‘’ʻ`]?ri|javob|answer|correct|key|ответ|kalit", c): ans_col = i
        q_col = next((i for i, c in enumerate(head) if re.search(r"savol|question|вопрос", c)), 0)
        body = rows[1:]
    else:
        q_col, body = 0, rows
        sample = [r[-1].strip().upper() for r in body[:20] if len(r) > 3 and r[-1].strip()]
        if sample and all(re.fullmatch(r"[A-H1-8]", x) for x in sample):
            ans_col = max(len(r) for r in body) - 1
    for r in body:
        r = r + [""] * 12
        q = r[q_col].strip()
        if not q: continue
        opt_idx = [i for i in range(len(r)) if i > q_col and i != ans_col and r[i].strip()]
        opts = [r[i].strip() for i in opt_idx]
        if len(opts) < 2: continue
        c = None
        if ans_col is not None and r[ans_col].strip():
            a = r[ans_col].strip()
            if re.fullmatch(r"[A-Ha-h]", a): c = ord(a.upper()) - 65
            elif re.fullmatch(r"[1-8]", a): c = int(a) - 1
            else:
                low = [o.lower() for o in opts]
                c = low.index(a.lower()) if a.lower() in low else None
            if c is not None and c >= len(opts): c = None
        qs.append({"q": q, "o": opts, "c": c})
    return _qz_finish(qs, notes)


def qz_parse_file(name, data):
    """(savollar, izohlar) qaytaradi yoki ValueError(xabar)."""
    if len(data) > QZ_MAX_BYTES:
        raise ValueError("Fayl juda katta (5 MB gacha).")
    low = name.lower()
    try:
        if low.endswith(".docx"):
            lines = qz_read_docx(data)
            text = "\n".join(t for t, _ in lines)
            qs, notes = qz_parse_block(text) if re.search(r"^\s*={3,}\s*$", text, re.M) else qz_parse_letter(lines)
        elif low.endswith(".xlsx"):
            qs, notes = qz_parse_rows(qz_read_xlsx(data))
        elif low.endswith(".txt"):
            text = None
            for enc in ("utf-8-sig", "cp1251", "latin-1"):
                try: text = data.decode(enc); break
                except Exception: pass
            qs, notes = qz_parse_block(text) if re.search(r"^\s*={3,}\s*$", text, re.M) else qz_parse_letter([(l, False) for l in text.split("\n")])
        else:
            raise ValueError("Faqat .docx, .xlsx yoki .txt fayllar qabul qilinadi.")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Faylni o'qib bo'lmadi. Fayl buzilmaganini tekshiring.")
    if not qs:
        raise ValueError("Fayldan savol topilmadi.")
    clean = []
    for q in qs:
        o = [x for x in q["o"] if x]
        if len(o) < 2 or len(o) > 10 or not q["q"] or q["c"] is None or q["c"] >= len(o):
            continue
        clean.append({"q": q["q"], "o": o, "c": q["c"]})
    if len(clean) > QZ_MAX_Q:
        notes.append(f"Faqat dastlabki {QZ_MAX_Q} ta savol olindi.")
        clean = clean[:QZ_MAX_Q]
    if not clean:
        raise ValueError("Savollar topildi, lekin hech birida to'g'ri javob aniqlanmadi.")
    return clean, notes


def qz_shuffle_options(q, rnd=random):
    """Variantlarni aralashtiradi ("hammasi", "A va B" kabi bog'liq variantlar bo'lsa, tegmaydi)."""
    if any(_QZ_NOSHUFFLE.search(o) for o in q["o"]):
        return q
    idx = list(range(len(q["o"])))
    rnd.shuffle(idx)
    return {"q": q["q"], "o": [q["o"][i] for i in idx], "c": idx.index(q["c"])}
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

MAKE_HELP = (
    "📝 Quiz tuzish\n\n"
    "Savollarni bittalab kiritamiz. 1-savolni yuboring:\n"
    "• savol matnini yozing, yoki\n"
    "• Telegramdagi tayyor quiz so'rovini (📎 ➜ So'rov ➜ Viktorina) yuboring.\n\n"
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
            "secs": row["secs"], "parts": parts, "by": row.get("author") or ""}
    qz_cache[qid] = (qset, time.time())
    if len(qz_cache) > 200:
        qz_cache.pop(next(iter(qz_cache)))
    return qset


def qz_post_chunks(qset):
    """Ikkinchi rasmdagidek post: {1-30}  Boshlash ... (bir xabarda 80 tagacha havola)."""
    lines = []
    for i, part in enumerate(qset["parts"]):
        url = f"https://t.me/{BOT_USERNAME}?start=qz_{qset['id']}_{i}"
        lines.append(f"{{{html.escape(part['l'])}}}    <a href=\"{url}\">Boshlash</a>")
    head = (
        f"🧪 <b>{html.escape(BOT_NAME)}</b>\n"
        f"{html.escape(qset['title'])}\n"
        f"Tayyorladi: <b>{html.escape(qset.get('by') or '')}</b>\n"
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


def _qz_time_kb():
    return _qz_kb([[(f"{t} soniya", f"qz:t:{t}") for t in QZ_TIMES[:3]],
                   [(f"{t} soniya", f"qz:t:{t}") for t in QZ_TIMES[3:]],
                   [("❌ Bekor qilish", "qz:x")]])


async def _ask_time(target):
    await target.answer("Har bir savolga necha soniya vaqt beramiz?", reply_markup=_qz_time_kb())


@dp.message(Command("bekor"))
async def cmd_bekor(msg: Message):
    if qz_w.pop(msg.from_user.id, None):
        await msg.answer("Bekor qilindi.")


# ======================= 1) QUIZ TUZISH (qo'lda, bittalab) =======================

@dp.message(F.text == BTN_MAKE)
async def btn_make(msg: Message):
    if await need_subscribe(msg):
        return
    qz_w[msg.from_user.id] = {"step": "m_q", "ts": time.time(), "mode": "manual", "qs": [], "cur": {}}
    await msg.answer(MAKE_HELP, reply_markup=_qz_kb([[("❌ Bekor qilish", "qz:x")]]))


def _added_kb():
    return _qz_kb([[("🏁 Tugatish", "qz:fin")],
                   [("↩️ Oxirgisini o'chirish", "qz:undo")],
                   [("❌ Bekor qilish", "qz:x")]])


async def _question_added(target, w, q, opts, c):
    w["qs"].append({"q": q, "o": opts, "c": c})
    w.update(step="m_q", cur={}, ts=time.time())
    n = len(w["qs"])
    await target.answer(
        f"✅ {n}-savol qo'shildi.\n\n{n + 1}-savolni yuboring (matn yoki quiz so'rovi), "
        f"yoki tugatish uchun «🏁 Tugatish» ni bosing.",
        reply_markup=_added_kb(),
    )


@dp.message(F.poll, lambda m: _qz_state(m, "m_q"))
async def make_poll(msg: Message):
    p = msg.poll
    w = qz_w[msg.from_user.id]
    if p.type != "quiz" or p.correct_option_id is None:
        await msg.answer("Bu oddiy so'rov. Iltimos, «Viktorina» (quiz) turidagi so'rov yuboring yoki savolni matn qilib yozing.")
        return
    opts = [o.text for o in p.options]
    await _question_added(msg, w, p.question, opts, p.correct_option_id)


@dp.message(lambda m: _qz_state(m, "m_q", "m_opts", "m_title") and _qz_plain_text(m))
async def make_text(msg: Message):
    uid = msg.from_user.id
    w = qz_w[uid]
    w["ts"] = time.time()
    t = msg.text.strip()
    step = w["step"]
    if step == "m_q":
        if len(t) > 1000:
            await msg.answer("Savol juda uzun (1000 belgigacha). Qisqartirib qayta yuboring.")
            return
        w["cur"] = {"q": t}
        w["step"] = "m_opts"
        await msg.answer(
            "Endi variantlarni yuboring: har bir variant yangi qatordan, 2 tadan 10 tagacha.\n\n"
            "Namuna:\nYadro\nMitoxondriya\nRibosoma\nGoldji",
            reply_markup=_qz_kb([[("❌ Bekor qilish", "qz:x")]]),
        )
    elif step == "m_opts":
        lines = [re.sub(r"^\(?[A-Ha-h]\)?[\.\)]\s+", "", l.strip()) for l in t.split("\n") if l.strip()]
        if len(lines) < 2 or len(lines) > 10:
            await msg.answer(f"Variantlar soni 2 dan 10 gacha bo'lishi kerak (siz {len(lines)} ta yubordingiz). Qayta yuboring.")
            return
        if any(len(x) > 300 for x in lines):
            await msg.answer("Variant juda uzun (300 belgigacha). Qisqartirib qayta yuboring.")
            return
        w["cur"]["o"] = lines
        w["step"] = "m_ans"
        letters = "ABCDEFGHIJ"
        text = "To'g'ri javobni tanlang:\n\n" + "\n".join(f"{letters[i]}) {o}" for i, o in enumerate(lines))
        rows = [[(letters[i], f"qz:a:{i}") for i in range(k, min(k + 5, len(lines)))] for k in range(0, len(lines), 5)]
        rows.append([("❌ Bekor qilish", "qz:x")])
        await msg.answer(text[:4000], reply_markup=_qz_kb(rows))
    elif step == "m_title":
        w["title"] = t[:60]
        w["step"] = "time"
        await _ask_time(msg)


# ======================= 2) TEZKOR QUIZ (fayldan) =======================

@dp.message(F.text == BTN_FAST)
async def btn_fast(msg: Message):
    if await need_subscribe(msg):
        return
    qz_w[msg.from_user.id] = {"step": "file", "ts": time.time(), "mode": None}
    await msg.answer(FAST_HELP)


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
    await msg.answer(text, reply_markup=_qz_kb([
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
    await _ask_time(msg)
  # ======================= TUGMALAR (callback) =======================

@dp.callback_query(F.data.startswith("qz:"))
async def qz_on_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    parts = cb.data.split(":")
    kind = parts[1]
    w = qz_w.get(uid)
    if kind == "x":
        qz_w.pop(uid, None)
        await cb.message.answer("Bekor qilindi.")
        await cb.answer()
        return
    if not w or time.time() - w["ts"] > QZ_STATE_TTL:
        qz_w.pop(uid, None)
        await cb.answer("Jarayon eskirgan. Menyudan qaytadan boshlang.", show_alert=True)
        return
    w["ts"] = time.time()

    # ---- qo'lda tuzish ----
    if kind == "a":                       # to'g'ri javob tanlandi
        cur = w.get("cur") or {}
        if w["step"] != "m_ans" or "o" not in cur:
            await cb.answer()
            return
        c = int(parts[2])
        await cb.answer()
        await _question_added(cb.message, w, cur["q"], cur["o"], c)
        return
    if kind == "undo":
        if w.get("qs"):
            w["qs"].pop()
            await cb.answer(f"Oxirgi savol o'chirildi. Hozir {len(w['qs'])} ta savol bor.", show_alert=True)
        else:
            await cb.answer("O'chiradigan savol yo'q.", show_alert=True)
        return
    if kind == "fin":
        if not w.get("qs"):
            await cb.answer("Hali birorta savol qo'shilmagan.", show_alert=True)
            return
        w["step"] = "m_title"
        await cb.answer()
        await cb.message.answer(
            f"Jami {len(w['qs'])} ta savol. Test nomini yozing (masalan: Biologiya 1-mavzu).",
            reply_markup=_qz_kb([[("⏭ Nomsiz davom etish", "qz:notitle")]]),
        )
        return
    if kind == "notitle":
        w["title"] = "Test"
        w["step"] = "time"
        await cb.answer()
        await _ask_time(cb.message)
        return

    # ---- fayldan ----
    n = len(w.get("qs") or [])
    if kind == "m":
        w["mode"] = parts[2]
        if parts[2] == "all":
            sizes = [s for s in QZ_SIZES if s <= n] or [n]
            w["step"] = "size"
            await cb.message.answer(
                f"Jami {n} ta test. Har bir quizda nechta savol bo'lsin?\n"
                f"(Hammasi shu sondan bo'linib, ketma-ket quizlar yaratiladi.)",
                reply_markup=_qz_kb([[(str(s), f"qz:s:{s}") for s in sizes[:3]],
                                     [(str(s), f"qz:s:{s}") for s in sizes[3:]],
                                     [("❌ Bekor qilish", "qz:x")]]))
        else:
            counts = [c for c in QZ_COUNTS if c <= n] or [n]
            w["step"] = "count"
            await cb.message.answer(
                f"Jami {n} ta test bor. Nechta savollik quiz kerak?\n"
                f"1 dan {n} gacha son yozing yoki tugmani bosing. Savollar tasodifiy tanlanadi.",
                reply_markup=_qz_kb([[(str(c), f"qz:c:{c}") for c in counts],
                                     [("❌ Bekor qilish", "qz:x")]]))
    elif kind == "s":
        w["size"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message)
    elif kind == "c":
        w["count"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message)
    elif kind == "t":
        w["secs"] = max(5, min(int(parts[2]), 600))
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
        qs = list(w["qs"])                      # qo'lda kiritilganda variantlar aralashtirilmaydi
        parts = [{"l": f"1-{len(qs)}", "qs": qs}]
    else:
        prepared = [qz_shuffle_options(q, rnd) for q in w["qs"]]
        n = len(prepared)
        if w["mode"] == "all":
            size = w["size"]
            parts = [{"l": f"{i + 1}-{min(i + size, n)}", "qs": prepared[i:i + size]} for i in range(0, n, size)]
        else:
            parts = [{"l": f"Tasodifiy {w['count']} ta", "qs": rnd.sample(prepared, w["count"])}]
    qid = "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=7))
    qset = {"id": qid, "owner": uid, "by": (cb.from_user.first_name or "")[:30],
            "title": w.get("title") or "Test", "secs": w["secs"], "parts": parts}
    if not await qz_save(qset):
        await cb.message.answer("Quizni saqlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.")
        return
    qz_daily[(today, uid)] = qz_daily.get((today, uid), 0) + 1
    qz_w.pop(uid, None)
    qz_cache[qid] = (qset, time.time())
    kb = _qz_kb([[("🏁 Hoziroq yechib ko'rish", f"qs:{qid}:0")]]) if len(parts) == 1 else None
    await cb.message.answer(
        f"✅ Tayyor! {len(parts)} ta quiz yaratildi. Quyidagi postni do'stlaringizga yoki guruhga yuboring (forward): "
        "«Boshlash» ni bosgan kishi quizni botda yechadi.",
        reply_markup=kb,
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
        m = await bot.send_poll(s["chat"], question=question, options=options, type="quiz",
                                correct_option_id=q["c"], is_anonymous=False, open_period=s["secs"])
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
