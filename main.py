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
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, PollAnswer, BotCommand, LinkPreviewOptions, ChatMemberUpdated,
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

# Majburiy obuna kanallari: (kanal username)
CHANNELS = ["@TalabaMed_2025", "@oltinqalam_uz", "@Edits_foto"]

QZ_TIMES = [15, 30, 45, 60, 90]
QZ_SIZES = [10, 20, 30, 40, 50]
QZ_COUNTS = [10, 20, 30, 50]
QZ_DAILY_LIMIT = 30          # bir foydalanuvchi kuniga nechta quiz yaratishi mumkin
QZ_STATE_TTL = 1800

# ======================= TILLAR (uz / en / ru) =======================

LANGS = ("uz", "en", "ru")
LI = {"uz": 0, "en": 1, "ru": 2}
BTN_LANG = "🌐 Til / Language / Язык"
CHOOSE_LANG = "🌐 Tilni tanlang / Choose your language / Выберите язык"

TR = {
    # --- tugmalar ---
    "b_make": ("📝 Quiz tuzish", "📝 Create quiz", "📝 Создать квиз"),
    "b_fast": ("⚡ Tezkor quiz tuzish", "⚡ Quick quiz from file", "⚡ Быстрый квиз из файла"),
    "b_my": ("📂 Mening testlarim", "📂 My quizzes", "📂 Мои квизы"),
    "b_contact": ("📞 Aloqa", "📞 Contact", "📞 Связь"),
    "b_fb": ("💬 Fikr bildirish", "💬 Feedback", "💬 Отзыв"),
    "b_done": ("🏁 Tugatish", "🏁 Finish", "🏁 Завершить"),
    "b_cancel": ("❌ Bekor qilish", "❌ Cancel", "❌ Отмена"),
    "b_poll": ("Savol tuzish", "Create a question", "Создать вопрос"),
    "b_check": ("✅ Tekshirish", "✅ Check", "✅ Проверить"),
    "b_chan": ("Kanal {n}", "Channel {n}", "Канал {n}"),
    "b_sec": ("{t} soniya", "{t} sec", "{t} сек"),
    "b_all": ("📚 Jami testdan (qismlarga bo'lib)", "📚 Whole test (split into parts)", "📚 Весь тест (по частям)"),
    "b_rnd": ("🔢 Son kiritaman (tasodifiy)", "🔢 Enter a number (random)", "🔢 Ввести число (случайно)"),
    "b_nomore": ("⏭ Nomsiz davom etish", "⏭ Continue without a title", "⏭ Продолжить без названия"),
    "b_start": ("🏁 Boshlash", "🏁 Start", "🏁 Начать"),
    "b_again": ("🔁 Qayta boshlash", "🔁 Restart", "🔁 Заново"),
    "b_parts": ("📋 Boshqa qismlar", "📋 Other parts", "📋 Другие части"),
    "b_write": ("✉️ Yozish", "✉️ Write", "✉️ Написать"),
    "b_anon": ("🕶 Anonim yuborish", "🕶 Send anonymously", "🕶 Отправить анонимно"),
    "b_named": ("👤 Ismim bilan yuborish", "👤 Send with my name", "👤 Отправить с моим именем"),
    "l_start": ("Boshlash", "Start", "Начать"),
    "l_group": ("Guruhda", "In a group", "В группе"),
    "k_all": ("Jami", "Whole", "Весь"),
    "k_rnd": ("Tasodifiy", "Random", "Случайный"),
    "k_man": ("Qo'lda", "Manual", "Вручную"),
    # --- obuna / start ---
    "sub_text": (
        "👋 Xush kelibsiz!\n\nBotdan foydalanish uchun quyidagi kanallarga obuna bo'ling. "
        "Obuna bo'lgach «✅ Tekshirish» tugmasini bosing, shundan keyin bot ishlaydi.",
        "👋 Welcome!\n\nTo use the bot, please subscribe to the channels below. "
        "After subscribing, press «✅ Check» and the bot will start working.",
        "👋 Добро пожаловать!\n\nЧтобы пользоваться ботом, подпишитесь на каналы ниже. "
        "После подписки нажмите «✅ Проверить», и бот заработает."),
    "sub_alert": ("Hali hammasiga obuna bo'lmadingiz!", "You haven't subscribed to all channels yet!",
                  "Вы ещё не подписались на все каналы!"),
    "sub_need": ("Avval majburiy kanallarga obuna bo'ling (/start).",
                 "Please subscribe to the required channels first (/start).",
                 "Сначала подпишитесь на обязательные каналы (/start)."),
    "about": (
        "🧪 {name}: o'zingiz quiz tuzing, do'stlaringiz bilan yeching\n\n"
        "📝 Quiz tuzish: savollarni o'zingiz bittalab tuzasiz (Telegramdagi Quiz Bot kabi).\n"
        "⚡ Tezkor quiz tuzish: Word, Excel yoki txt faylni yuborasiz, bot uni tayyor quizga aylantiradi. "
        "Jami testni 10, 20, 30... talik qismlarga bo'lish yoki tasodifiy tanlash mumkin.\n"
        "📂 Mening testlarim: siz tuzgan hamma testlar shu yerda saqlanadi.\n\n"
        "Tayyor quizni do'stlaringizga yoki guruhga forward qiling: «Boshlash» ni bosgan kishi botda yechadi, "
        "«Guruhda» ni bossangiz guruhdagi hamma birga o'ynaydi.\n\n"
        "👉 Boshlash uchun pastdagi ▦ menyu tugmasini bosing.",
        "🧪 {name}: create quizzes and take them with friends\n\n"
        "📝 Create quiz: build questions one by one (like Telegram's Quiz Bot).\n"
        "⚡ Quick quiz from file: send a Word, Excel or txt file and the bot turns it into a ready quiz. "
        "You can split the whole test into parts of 10, 20, 30... or pick random questions.\n"
        "📂 My quizzes: every quiz you created is saved here.\n\n"
        "Forward the finished quiz to friends or a group: whoever taps «Start» takes it in the bot, "
        "and «In a group» lets everyone in the group play together.\n\n"
        "👉 Press the ▦ menu button below to begin.",
        "🧪 {name}: создавайте квизы и проходите их с друзьями\n\n"
        "📝 Создать квиз: добавляйте вопросы по одному (как в Telegram Quiz Bot).\n"
        "⚡ Быстрый квиз из файла: отправьте файл Word, Excel или txt, и бот превратит его в готовый квиз. "
        "Весь тест можно разбить на части по 10, 20, 30... или выбрать случайные вопросы.\n"
        "📂 Мои квизы: все созданные вами квизы хранятся здесь.\n\n"
        "Перешлите готовый квиз друзьям или в группу: кто нажмёт «Начать», пройдёт его в боте, "
        "а «В группе» позволит играть всем участникам группы вместе.\n\n"
        "👉 Чтобы начать, нажмите кнопку меню ▦ внизу."),
    "menu_open": ("📋 Menyu pastda. Yopish uchun telefondagi orqaga tugmasini yoki ▦ ni bosing.",
                  "📋 The menu is below. To close it, press the phone's back button or ▦.",
                  "📋 Меню внизу. Чтобы закрыть, нажмите «назад» на телефоне или ▦."),
    "lang_set": ("✅ Til: O'zbekcha", "✅ Language: English", "✅ Язык: Русский"),
    "cancelled": ("Bekor qilindi.", "Cancelled.", "Отменено."),
    "expired": ("Jarayon eskirgan. Menyudan qaytadan boshlang.",
                "This session has expired. Please start again from the menu.",
                "Сессия устарела. Начните заново из меню."),
    # --- quiz tuzish (qo'lda) ---
    "make_title": (
        "Keling, yangi test tuzamiz. Dastlab, menga testingiz sarlavhasini (masalan: «Biologiya 1-mavzu» "
        "yoki «Anatomiya 20 ta savol») yuboring.\n\nBekor qilish: /bekor",
        "Let's create a new quiz. First, send me the quiz title (for example: «Biology topic 1» "
        "or «Anatomy 20 questions»).\n\nTo cancel: /bekor",
        "Давайте создадим новый квиз. Сначала отправьте название (например: «Биология, тема 1» "
        "или «Анатомия, 20 вопросов»).\n\nОтмена: /bekor"),
    "make_desc": ("Yaxshi. Endi menga testingiz tavsifini yuboring. Bu ixtiyoriy, bu bosqichni tashlab ketishingiz mumkin: /skip.",
                  "Good. Now send me a description of your quiz. It's optional, you can skip this step: /skip.",
                  "Хорошо. Теперь отправьте описание квиза. Это необязательно, можно пропустить: /skip."),
    "make_q": (
        "Yaxshi. Endi birinchi savolingiz bilan viktorina yuboring: pastdagi «Savol tuzish» tugmasini bosing, "
        "savol va variantlarni yozing, to'g'ri javobni belgilang va «Tuzish» ni bosing.\n\n"
        "Hamma savollar tayyor bo'lganda «🏁 Tugatish» ni bosing.",
        "Great. Now send your first question as a quiz: press the «Create a question» button below, "
        "write the question and options, mark the correct answer and press «Create».\n\n"
        "When all questions are ready, press «🏁 Finish».",
        "Отлично. Теперь отправьте первый вопрос как викторину: нажмите кнопку «Создать вопрос» внизу, "
        "напишите вопрос и варианты, отметьте правильный ответ и нажмите «Создать».\n\n"
        "Когда все вопросы готовы, нажмите «🏁 Завершить»."),
    "poll_bad": (
        "Bu viktorina emas. Pastdagi «Savol tuzish» tugmasi orqali yuboring («To'g'ri javobni belgilash» yoqilgan bo'lishi kerak).",
        "This is not a quiz poll. Please send it with the «Create a question» button below (the «Quiz mode» / correct answer option must be on).",
        "Это не викторина. Отправьте вопрос через кнопку «Создать вопрос» внизу (должен быть включён режим «Викторина» с правильным ответом)."),
    "q_added": ("✅ {n}-savol qo'shildi.\n\nKeyingi savol uchun «Savol tuzish» ni bosing, tugatish uchun «🏁 Tugatish» ni bosing.",
                "✅ Question {n} added.\n\nPress «Create a question» for the next one, or «🏁 Finish» to finish.",
                "✅ Вопрос {n} добавлен.\n\nНажмите «Создать вопрос» для следующего или «🏁 Завершить», чтобы закончить."),
    "no_q_yet": ("Hali birorta savol qo'shilmagan. «Savol tuzish» tugmasini bosing.",
                 "No questions added yet. Press «Create a question».",
                 "Вопросов пока нет. Нажмите «Создать вопрос»."),
    "no_process": ("Hozir savol tuzish jarayoni yo'q.", "There is no quiz being created right now.",
                   "Сейчас нет создаваемого квиза."),
    "n_ready": ("🏁 Jami {n} ta savol tayyor.", "🏁 {n} questions are ready.", "🏁 Готово вопросов: {n}."),
    "ask_time": ("Har bir savolga necha soniya vaqt beramiz?", "How many seconds per question?",
                 "Сколько секунд даём на каждый вопрос?"),
    "use_poll_btn": ("Savolni pastdagi «Savol tuzish» tugmasi orqali yuboring.",
                     "Please send the question with the «Create a question» button below.",
                     "Отправьте вопрос через кнопку «Создать вопрос» внизу."),
    # --- tezkor quiz ---
    "fast_help": (
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
        "Bekor qilish: /bekor",
        "⚡ Quick quiz from file\n\n"
        "Send a file with questions: .xlsx (Excel), .docx (Word) or .txt, up to 5 MB. "
        "You can also just paste the text as a message.\n"
        "❗ PDF files cannot be read. Please convert them to Word or Excel first.\n\n"
        "Example (Word, txt or text):\n"
        "1. What is the energy center of the cell?\n"
        "A) Nucleus\nB) Mitochondria\nC) Ribosome\nD) Golgi\n"
        "Answer: B\n\n"
        "Ways to mark the correct answer: an «Answer: B» line, a * or + before or after the option, "
        "or make the correct option bold.\n\n"
        "Excel: column 1 is the question, the next columns are options, the last column is the correct answer "
        "(A, B, C or the option text).\n\n"
        "⚠️ If no correct answer is marked anywhere in the file, the 1st option of every question "
        "(in Excel, the 1st column after the question) is taken as correct. Options are shuffled in the quiz.\n\n"
        "To cancel: /bekor",
        "⚡ Быстрый квиз из файла\n\n"
        "Отправьте файл с вопросами: .xlsx (Excel), .docx (Word) или .txt, до 5 МБ. "
        "Можно просто вставить текст в сообщение.\n"
        "❗ PDF-файлы не читаются. Сначала преобразуйте их в Word или Excel.\n\n"
        "Пример (Word, txt или текст):\n"
        "1. Что является энергетическим центром клетки?\n"
        "A) Ядро\nB) Митохондрия\nC) Рибосома\nD) Гольджи\n"
        "Ответ: B\n\n"
        "Как отметить правильный ответ: строка «Ответ: B», знак * или + перед или после варианта, "
        "либо выделите правильный вариант жирным.\n\n"
        "Excel: 1-й столбец — вопрос, следующие — варианты, последний — правильный ответ "
        "(A, B, C или текст варианта).\n\n"
        "⚠️ Если правильные ответы нигде не отмечены, правильным считается 1-й вариант каждого вопроса "
        "(в Excel — 1-й столбец после вопроса). В квизе варианты перемешиваются.\n\n"
        "Отмена: /bekor"),
    "pdf_no": ("❌ PDF fayl o'qilmaydi. Uni Word (.docx) yoki Excel (.xlsx) qilib yuboring.",
               "❌ PDF files cannot be read. Please send it as Word (.docx) or Excel (.xlsx).",
               "❌ PDF не читается. Отправьте файл в формате Word (.docx) или Excel (.xlsx)."),
    "too_big": ("Fayl juda katta (5 MB gacha).", "The file is too large (up to 5 MB).", "Файл слишком большой (до 5 МБ)."),
    "dl_fail": ("Faylni yuklab bo'lmadi. Qayta yuboring.", "Couldn't download the file. Please send it again.",
                "Не удалось загрузить файл. Отправьте ещё раз."),
    "parse_err": ("❌ {e}\n\nNamunani qayta ko'rish uchun «{b}» tugmasini bosing.",
                  "❌ {e}\n\nPress «{b}» to see the example again.",
                  "❌ {e}\n\nНажмите «{b}», чтобы снова увидеть пример."),
    "pe_no_sheet": ("Excel faylida varaq topilmadi.", "No sheet found in the Excel file.", "В файле Excel не найден лист."),
    "pe_big": ("Fayl juda katta (5 MB gacha).", "The file is too large (up to 5 MB).", "Файл слишком большой (до 5 МБ)."),
    "pe_fmt": ("Faqat .docx, .xlsx yoki .txt fayllar qabul qilinadi.", "Only .docx, .xlsx or .txt files are accepted.",
               "Принимаются только файлы .docx, .xlsx или .txt."),
    "pe_unreadable": ("Faylni o'qib bo'lmadi. Fayl buzilmaganini tekshiring.", "Couldn't read the file. Check that it isn't corrupted.",
                      "Не удалось прочитать файл. Проверьте, что он не повреждён."),
    "pe_empty": ("Fayldan savol topilmadi.", "No questions found in the file.", "В файле не найдено вопросов."),
    "pe_noans": ("Savollar topildi, lekin hech birida to'g'ri javob aniqlanmadi.",
                 "Questions were found, but no correct answer could be determined for any of them.",
                 "Вопросы найдены, но ни для одного не удалось определить правильный ответ."),
    "pn_first": ("To'g'ri javob belgilanmagan edi: har savolning 1-varianti to'g'ri deb olindi.",
                 "No correct answers were marked: the 1st option of each question was taken as correct.",
                 "Правильные ответы не были отмечены: правильным считается 1-й вариант каждого вопроса."),
    "pn_miss": ("{n} ta savolda to'g'ri javob topilmadi, ular qo'shilmadi.",
                "{n} questions had no correct answer and were not added.",
                "У {n} вопросов не найден правильный ответ, они не добавлены."),
    "pn_badblock": ("{n} ta blok tushunarsiz bo'lgani uchun o'tkazib yuborildi.",
                    "{n} blocks were skipped because they were unclear.",
                    "{n} блоков пропущено, так как они непонятны."),
    "pn_cut": ("Faqat dastlabki {n} ta savol olindi.", "Only the first {n} questions were taken.",
               "Взяты только первые {n} вопросов."),
    "found": ("✅ Jami {n} ta test topildi.", "✅ Found {n} questions in total.", "✅ Всего найдено вопросов: {n}."),
    "mode_q": ("Jami testdan quiz qilaymi yoki son kiritasizmi?",
               "Should I make quizzes from the whole test, or will you enter a number?",
               "Сделать квизы из всего теста или вы введёте число?"),
    "size_q": ("Jami {n} ta test. Har bir quizda nechta savol bo'lsin?\n(Hammasi shu sondan bo'linib, ketma-ket quizlar yaratiladi.)",
               "{n} questions in total. How many questions per quiz?\n(Everything will be split into consecutive quizzes of this size.)",
               "Всего вопросов: {n}. Сколько вопросов в одном квизе?\n(Всё будет разбито на последовательные квизы такого размера.)"),
    "count_q": ("Jami {n} ta test bor. Nechta savollik quiz kerak?\n1 dan {n} gacha son yozing yoki tugmani bosing. Savollar tasodifiy tanlanadi.",
                "There are {n} questions in total. How many questions should the quiz have?\nType a number from 1 to {n} or press a button. Questions are picked randomly.",
                "Всего вопросов: {n}. Сколько вопросов должно быть в квизе?\nНапишите число от 1 до {n} или нажмите кнопку. Вопросы выбираются случайно."),
    "count_bad": ("1 dan {n} gacha raqam yozing (jami {n} ta test bor).", "Type a number from 1 to {n} ({n} questions in total).",
                  "Напишите число от 1 до {n} (всего вопросов: {n})."),
    # --- mening testlarim ---
    "my_fail": ("Testlar ro'yxatini olib bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
                "Couldn't load your quizzes. Please try again in a moment.",
                "Не удалось загрузить список квизов. Попробуйте чуть позже."),
    "my_empty": ("Siz hali test tuzmagansiz. «{a}» yoki «{b}» ni bosing.",
                 "You haven't created any quizzes yet. Press «{a}» or «{b}».",
                 "Вы ещё не создали ни одного квиза. Нажмите «{a}» или «{b}»."),
    "my_head": ("📂 Sizning testlaringiz ({n} ta). Nomini bosing, yig'ilgan testlar yuboriladi:",
                "📂 Your quizzes ({n}). Tap a name to get the finished quiz post:",
                "📂 Ваши квизы ({n}). Нажмите на название, чтобы получить готовый пост:"),
    "not_found": ("Test topilmadi.", "Quiz not found.", "Квиз не найден."),
    # --- yaratish natijasi ---
    "limit": ("Kuniga {n} tagacha quiz yaratish mumkin.", "You can create up to {n} quizzes per day.",
              "В день можно создать до {n} квизов."),
    "creating": ("Yaratilmoqda...", "Creating...", "Создаём..."),
    "save_fail": ("Quizni saqlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
                  "Couldn't save the quiz. Please try again in a moment.",
                  "Не удалось сохранить квиз. Попробуйте чуть позже."),
    "done_msg": (
        "✅ Tayyor! {n} ta quiz yaratildi. Quyidagi postni do'stlaringizga yoki guruhga yuboring (forward): "
        "«Boshlash» ni bosgan kishi quizni botda yechadi. «Guruhda» ni bossangiz, quiz guruhdagi hamma bilan birga o'ynaladi.\n\n"
        "Keyinroq «{b}» orqali ham topasiz.",
        "✅ Done! {n} quiz(zes) created. Forward the post below to friends or a group: "
        "whoever taps «Start» takes the quiz in the bot. «In a group» lets everyone in the group play together.\n\n"
        "You can also find it later in «{b}».",
        "✅ Готово! Создано квизов: {n}. Перешлите пост ниже друзьям или в группу: "
        "кто нажмёт «Начать», пройдёт квиз в боте. «В группе» позволяет играть всем участникам вместе.\n\n"
        "Позже его можно найти в «{b}»."),
    "post_by": ("Tayyorladi", "Created by", "Автор"),
    "post_topic": ("Guruh mavzusi (topic) ichida:", "Inside a group topic:", "Внутри темы группы:"),
    "post_secs": ("⏱ Har savolga {s} soniya", "⏱ {s} seconds per question", "⏱ {s} сек на вопрос"),
    # --- quiz o'tkazish (shaxsiy) ---
    "prep": (
        "🎲 “{title} {label}” testiga tayyorlaning\n\n🖊 {n} ta savol\n⏱ Har bir savol uchun {s} soniya\n\n"
        "🏁 Tayyor bo'lganingizda quyidagi tugmani bosing.\nUni to'xtatish uchun /stop buyrug'ini yuboring.",
        "🎲 Get ready for “{title} {label}”\n\n🖊 {n} questions\n⏱ {s} seconds per question\n\n"
        "🏁 Press the button below when you're ready.\nSend /stop to stop it.",
        "🎲 Приготовьтесь к тесту «{title} {label}»\n\n🖊 Вопросов: {n}\n⏱ {s} сек на каждый вопрос\n\n"
        "🏁 Когда будете готовы, нажмите кнопку ниже.\nЧтобы остановить, отправьте /stop."),
    "quiz_nf": ("Bu quiz topilmadi yoki o'chirilgan.", "This quiz was not found or has been deleted.",
                "Этот квиз не найден или удалён."),
    "pick": ("{h} Javobni tanlang", "{h} Choose the answer", "{h} Выберите ответ"),
    "send_fail": ("Savolni yuborib bo'lmadi. Quizni qaytadan boshlang.", "Couldn't send the question. Please restart the quiz.",
                  "Не удалось отправить вопрос. Начните квиз заново."),
    "fin_head": ("🏁 Quiz {st}: {title} {label}", "🏁 Quiz {st}: {title} {label}", "🏁 Квиз {st}: {title} {label}"),
    "st_done": ("yakunlandi", "finished", "завершён"),
    "st_stop": ("to'xtatildi", "stopped", "остановлен"),
    "fin_ok": ("✅ To'g'ri: {ok} / {n} ({p}%)", "✅ Correct: {ok} / {n} ({p}%)", "✅ Верно: {ok} / {n} ({p}%)"),
    "fin_bad": ("❌ Xato: {n}", "❌ Wrong: {n}", "❌ Неверно: {n}"),
    "fin_skip": ("⏭ Javobsiz: {n}", "⏭ Unanswered: {n}", "⏭ Без ответа: {n}"),
    "fin_time": ("⏱ Vaqt: {m} daq {s} soniya", "⏱ Time: {m} min {s} sec", "⏱ Время: {m} мин {s} сек"),
    "fin_wrong": ("Xato qilingan savollar:", "Questions you got wrong:", "Вопросы с ошибками:"),
    "fin_right": ("➜ To'g'ri: {a}", "➜ Correct: {a}", "➜ Правильно: {a}"),
    "fin_more": ("... va yana {n} ta", "... and {n} more", "... и ещё {n}"),
    "no_active": ("Hozir faol quiz yo'q.", "There is no active quiz right now.", "Сейчас нет активного квиза."),
    # --- guruh ---
    "g_prep": ("👥 Guruhda quiz: “{title} {label}”\n\n🖊 {n} ta savol\n⏱ Har savolga {s} soniya\n\n"
               "Guruhdagi hamma ishtirok etishi mumkin. «Boshlash» ni quizni boshlagan kishi yoki guruh admini bosadi.",
               "👥 Group quiz: “{title} {label}”\n\n🖊 {n} questions\n⏱ {s} seconds per question\n\n"
               "Everyone in the group can take part. «Start» is pressed by whoever launched the quiz or a group admin.",
               "👥 Квиз в группе: «{title} {label}»\n\n🖊 Вопросов: {n}\n⏱ {s} сек на вопрос\n\n"
               "Участвовать может любой участник группы. Кнопку «Начать» нажимает тот, кто запустил квиз, или админ группы."),
    "g_only": ("Faqat quizni boshlagan kishi yoki guruh admini buni qila oladi.",
               "Only the person who launched the quiz or a group admin can do this.",
               "Это может сделать только тот, кто запустил квиз, или админ группы."),
    "g_busy": ("Guruhda quiz allaqachon davom etyapti. To'xtatish: /stop",
               "A quiz is already running in this group. To stop it: /stop",
               "В группе уже идёт квиз. Остановить: /stop"),
    "g_info": ("Quiz tuzish uchun menga shaxsiy xabar yozing 👇", "To create quizzes, message me privately 👇",
               "Чтобы создавать квизы, напишите мне в личные сообщения 👇"),
    "g_results": ("🏆 {title} {label}: natijalar", "🏆 {title} {label}: results", "🏆 {title} {label}: результаты"),
    "g_warn": ("🔴 {n} soniya qoldi!", "🔴 {n} seconds left!", "🔴 Осталось {n} сек!"),
    "unsub_warn": (
        "⚠️ Siz kanaldan chiqib ketdingiz: {ch}\n\nBotdan foydalanishda davom etish uchun qayta obuna bo'ling va «✅ Tekshirish» ni bosing.",
        "⚠️ You left the channel: {ch}\n\nTo keep using the bot, please subscribe again and press «✅ Check».",
        "⚠️ Вы вышли из канала: {ch}\n\nЧтобы продолжить пользоваться ботом, подпишитесь снова и нажмите «✅ Проверить»."),
    "g_none": ("Hech kim qatnashmadi.", "Nobody took part.", "Никто не участвовал."),
    "g_fail": ("Savolni yuborib bo'lmadi. Botga guruhda xabar va so'rov yuborish ruxsatini bering.",
               "Couldn't send the question. Please allow the bot to send messages and polls in this group.",
               "Не удалось отправить вопрос. Разрешите боту отправлять сообщения и опросы в этой группе."),
    # --- aloqa / fikr ---
    "contact_txt": ("📞 Aloqa uchun: {c}", "📞 Contact: {c}", "📞 Связь: {c}"),
    "fb_choose": ("💬 Bot haqida fikringizni bildiring.\n\nAnonim yuborsangiz, sizning ismingiz va akkauntingiz egasiga ko'rsatilmaydi. Qanday yuborasiz?",
                  "💬 Share your feedback about the bot.\n\nIf you send it anonymously, your name and account won't be shown to the owner. How would you like to send it?",
                  "💬 Поделитесь мнением о боте.\n\nЕсли отправите анонимно, ваше имя и аккаунт не будут показаны владельцу. Как отправить?"),
    "fb_write": ("✍️ Fikringizni bitta xabar qilib yozing ({how} yuboriladi).\nBekor qilish uchun /bekor ni yuboring.",
                 "✍️ Write your feedback in one message (it will be sent {how}).\nTo cancel, send /bekor.",
                 "✍️ Напишите отзыв одним сообщением (будет отправлен {how}).\nДля отмены отправьте /bekor."),
    "how_anon": ("anonim", "anonymously", "анонимно"),
    "how_named": ("ismingiz bilan", "with your name", "с вашим именем"),
    "fb_off": ("Fikr qabul qilish hozircha ishlamayapti.", "Feedback is not available right now.",
               "Приём отзывов сейчас недоступен."),
    "fb_wait": ("Iltimos, biroz kutib, keyin yuboring.", "Please wait a bit before sending again.",
                "Пожалуйста, подождите немного и отправьте снова."),
    "fb_err": ("Yuborib bo'lmadi, keyinroq urinib ko'ring.", "Couldn't send it, please try again later.",
               "Не удалось отправить, попробуйте позже."),
    "fb_thanks": ("✅ Rahmat! Fikringiz yuborildi.", "✅ Thank you! Your feedback was sent.", "✅ Спасибо! Ваш отзыв отправлен."),
}


def tr(lang, key, **kw):
    s = TR[key][LI.get(lang, 0)]
    return s.format(**kw) if kw else s


# Barcha tillardagi tugma matnlari (tugma bosilganini tilidan qat'i nazar aniqlash uchun)
BTN_ALL = {k: {TR[k][i] for i in range(3)} for k in
           ("b_make", "b_fast", "b_my", "b_contact", "b_fb", "b_done", "b_cancel")}


def _menu_texts():
    out = {BTN_LANG}
    for v in BTN_ALL.values():
        out |= v
    return out


def is_btn(key):
    return lambda m: bool(m.text) and m.text in BTN_ALL[key]


def guess_lang(code):
    c = (code or "").lower()
    return "ru" if c.startswith("ru") else "uz" if c.startswith("uz") else "en"


def menu_kb(lg):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=tr(lg, "b_make")), KeyboardButton(text=tr(lg, "b_fast"))],
                  [KeyboardButton(text=tr(lg, "b_my"))],
                  [KeyboardButton(text=tr(lg, "b_contact")), KeyboardButton(text=tr(lg, "b_fb"))],
                  [KeyboardButton(text=BTN_LANG)]],
        resize_keyboard=True,
    )


def poll_kb(lg):
    # Telegramdagi Quiz Bot kabi: tugma tayyor viktorina oynasini ochadi
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=tr(lg, "b_poll"), request_poll=KeyboardButtonPollType(type="quiz"))],
                  [KeyboardButton(text=tr(lg, "b_done")), KeyboardButton(text=tr(lg, "b_cancel"))]],
        resize_keyboard=True,
    )


bot = Bot(TOKEN)
dp = Dispatcher()

pending_qz = {}      # obuna bo'lgandan keyin ochiladigan havola
pending_start = {}   # til tanlangandan keyin davom ettiriladigan /start parametri
feedback_mode = {}   # user_id -> "anon" | "named"
last_feedback = {}   # user_id -> oxirgi yuborilgan vaqt
qz_w = {}            # yaratish jarayoni: user_id -> holat
qz_cache = {}        # test id -> (test, vaqt)
qz_sessions = {}     # shaxsiy chatda ishlayotgan testlar: user_id -> sessiya
qz_daily = {}        # (sana, user_id) -> yaratilgan testlar soni
g_sessions = {}      # guruhda ishlayotgan testlar: chat_id -> sessiya
poll_chat = {}       # poll_id -> chat_id (guruh so'rovlari)
lang_cache = {}      # user_id -> til
lang_miss = {}       # user_id -> tilni bazadan oxirgi qidirgan vaqt (topilmadi)
sub_cache = {}       # user_id -> hammasiga obuna bo'lgan vaqt
_last = {}           # user_id -> oxirgi so'rov vaqti (spamdan himoya)
parse_sem = asyncio.Semaphore(2)   # bir vaqtda 2 tadan ortiq fayl o'qilmaydi


# ======================= BAZA (Supabase) =======================

def db_headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if extra:
        h.update(extra)
    return h


_http = None


def http():
    """Hamma Supabase so'rovlari uchun bitta umumiy ulanish (ko'p foydalanuvchida tez va yengil)."""
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=60, ttl_dns_cache=300))
    return _http


async def _sb(method, path, **kw):
    """Supabase REST so'rovi: (status, json|None)."""
    try:
        async with http().request(method, f"{SUPABASE_URL}/rest/v1/{path}",
                                  timeout=aiohttp.ClientTimeout(total=25), **kw) as r:
            data = None
            try:
                data = await r.json()
            except Exception:
                pass
            if r.status >= 300:
                print("Supabase xato:", method, path[:60], r.status, str(data)[:200])
            return r.status, data
    except Exception as e:
        print("Supabase xatosi:", e)
        return 0, None


async def lang_saved(uid):
    """Foydalanuvchi tanlagan til (yo'q bo'lsa None)."""
    if uid in lang_cache:
        return lang_cache[uid]
    if time.time() - lang_miss.get(uid, 0) < 30:          # yaqinda so'ralgan va topilmagan
        return None
    st, data = await _sb("GET", f"quiz_users?select=lang&user_id=eq.{uid}", headers=db_headers())
    if st == 200 and data:
        lang_cache[uid] = data[0].get("lang")
        return lang_cache[uid]
    lang_miss[uid] = time.time()
    return None


async def lang_of(user):
    return (await lang_saved(user.id)) or guess_lang(getattr(user, "language_code", None))


async def set_lang(uid, lg):
    lang_cache[uid] = lg
    await _sb("POST", "quiz_users?on_conflict=user_id",
              headers=db_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
              json={"user_id": uid, "lang": lg})


async def qz_save(qset):
    st, _ = await _sb("POST", "quiz_sets", headers=db_headers({"Prefer": "return=minimal"}),
                      json={"id": qset["id"], "owner": qset["owner"], "title": qset["title"],
                            "secs": qset["secs"], "parts": qset["parts"], "author": qset["by"]})
    return 0 < st < 300


async def qz_get(qid):
    hit = qz_cache.get(qid)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    st, rows = await _sb("GET", f"quiz_sets?select=*&id=eq.{quote(qid)}", headers=db_headers())
    if st != 200 or not rows:
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
    base = f"quiz_sets?owner=eq.{uid}&id=like.i*&limit=300"
    st, rows = await _sb("GET", base + "&select=id,title,created_at&order=created_at.desc", headers=db_headers())
    if st == 200:
        return rows or []
    st, rows = await _sb("GET", base + "&select=id,title", headers=db_headers())
    if st == 200:
        return list(reversed(rows or []))
    return None


def qz_group_tests(rows):
    """Bir xil nomli va bir xil turdagi testlar bitta hisoblanadi (eng yangisi qoladi)."""
    seen = {}
    for r in rows:
        title = (r.get("title") or "Test").strip()
        kind = (r.get("id") or "")[1:2]
        key = (title.lower(), kind)
        if key not in seen:
            seen[key] = {"id": r["id"], "title": title, "kind": kind}
    return list(seen.values())


KIND_KEY = {"a": "k_all", "r": "k_rnd", "m": "k_man"}


def qz_post_chunks(qset, lg):
    """Post: {1-30}  Boshlash · Guruhda (bir xabarda 60 tagacha qator)."""
    lines = []
    for i, part in enumerate(qset["parts"]):
        u1 = f"https://t.me/{BOT_USERNAME}?start=qz_{qset['id']}_{i}"
        u2 = f"https://t.me/{BOT_USERNAME}?startgroup=qz_{qset['id']}_{i}"
        lines.append(f"{{{html.escape(part['l'])}}}    <a href=\"{u1}\">{tr(lg, 'l_start')}</a>"
                     f" · <a href=\"{u2}\">👥 {tr(lg, 'l_group')}</a>")
    desc = qset.get("desc") or ""
    head = (f"🧪 <b>{html.escape(BOT_NAME)}</b>\n{html.escape(qset['title'])}\n"
            + (f"{html.escape(desc)}\n" if desc else "")
            + f"{tr(lg, 'post_by')}: <b>{html.escape(qset.get('by') or '')}</b>\n"
            + tr(lg, "post_secs", s=qset["secs"]) + "\n"
            + f"{tr(lg, 'post_topic')} <code>/quiz {qset['id']} 1</code>\n\n")
    chunks = []
    for k in range(0, len(lines), 60):
        chunks.append((head if k == 0 else "") + "\n".join(lines[k:k + 60]))
    return chunks


async def qz_send_html(chat_id, text, **kw):
    return await bot.send_message(chat_id, text, parse_mode="HTML",
                                  link_preview_options=LinkPreviewOptions(is_disabled=True), **kw)


def _qz_kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def qz_pretty_title(name):
    t = re.sub(r"\.(docx|xlsx|txt)$", "", name or "", flags=re.I)
    t = re.sub(r"[_]+", " ", t).strip()
    return (t or "Test")[:60]


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


def _is_group(chat):
    return chat.type in ("group", "supergroup")


# ======================= /start, til, obuna =======================

def lang_kb():
    return _qz_kb([[("🇬🇧 English", "lg:en")], [("🇷🇺 Русский", "lg:ru")], [("🇺🇿 O'zbek", "lg:uz")]])


async def not_subscribed(user_id, force=False):
    """Obuna bo'lmagan kanallar: [(raqam, username)]. Obuna bo'lganlar 5 daqiqa eslab qolinadi."""
    if not force and time.time() - sub_cache.get(user_id, 0) < 300:
        return []
    result = []
    for i, username in enumerate(CHANNELS, 1):
        try:
            m = await bot.get_chat_member(username, user_id)
            if m.status in ("left", "kicked"):
                result.append((i, username))
            elif m.status == "restricted" and not getattr(m, "is_member", True):
                result.append((i, username))
        except Exception as e:
            print("Obuna tekshirish xatosi:", username, e)     # odatda bot kanalda admin emas
            result.append((i, username))
    if not result:
        sub_cache[user_id] = time.time()
    else:
        sub_cache.pop(user_id, None)
    return result


def sub_keyboard(channels, lg):
    rows = [[InlineKeyboardButton(text=tr(lg, "b_chan", n=i), url=f"https://t.me/{u[1:]}")] for i, u in channels]
    rows.append([InlineKeyboardButton(text=tr(lg, "b_check"), callback_data="check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def need_subscribe(msg: Message, lg):
    left = await not_subscribed(msg.from_user.id)
    if left:
        await msg.answer(tr(lg, "sub_text"), reply_markup=sub_keyboard(left, lg))
        return True
    return False


async def send_main(chat_id, lg):
    await bot.send_message(chat_id, tr(lg, "about", name=BOT_NAME), reply_markup=menu_kb(lg))


async def proceed(chat_id, uid, args, lg):
    left = await not_subscribed(uid)
    if args.startswith("qz_"):
        if left:
            pending_qz[uid] = args
        else:
            await qz_deeplink(chat_id, args, lg)
            return
    if left:
        await bot.send_message(chat_id, tr(lg, "sub_text"), reply_markup=sub_keyboard(left, lg))
    else:
        await send_main(chat_id, lg)


@dp.message(CommandStart())
async def start(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    args = (command.args or "") if command else ""
    if _is_group(msg.chat):                                   # guruhda
        lg = await lang_of(msg.from_user)
        if args.startswith("qz_"):
            await qz_group_prep(msg.chat.id, uid, args, lg, _thread(msg))
        else:
            await msg.answer(tr(lg, "g_info") + f"\nhttps://t.me/{BOT_USERNAME}")
        return
    qz_w.pop(uid, None)
    feedback_mode.pop(uid, None)
    saved = await lang_saved(uid)
    if not saved:                                             # birinchi marta: tilni so'raymiz
        pending_start[uid] = args
        await msg.answer(CHOOSE_LANG, reply_markup=lang_kb())
        return
    await proceed(msg.chat.id, uid, args, saved)


@dp.message(Command("lang"))
@dp.message(F.text == BTN_LANG)
async def cmd_lang(msg: Message):
    await msg.answer(CHOOSE_LANG, reply_markup=lang_kb())


@dp.callback_query(F.data.startswith("lg:"))
async def lang_choice(cb: CallbackQuery):
    lg = cb.data.split(":")[1]
    if lg not in LANGS:
        await cb.answer()
        return
    uid = cb.from_user.id
    await set_lang(uid, lg)
    await cb.answer(tr(lg, "lang_set"))
    try:
        await cb.message.delete()
    except Exception:
        pass
    await proceed(cb.message.chat.id, uid, pending_start.pop(uid, ""), lg)


@dp.message(Command("menu"))
async def menu_cmd(msg: Message):
    lg = await lang_of(msg.from_user)
    if await need_subscribe(msg, lg):
        return
    await msg.answer(tr(lg, "menu_open"), reply_markup=menu_kb(lg))


@dp.callback_query(F.data == "check")
async def check(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    left = await not_subscribed(cb.from_user.id, force=True)
    if left:
        await cb.answer(tr(lg, "sub_alert"), show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=sub_keyboard(left, lg))
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
        await qz_deeplink(cb.message.chat.id, pend, lg)
    else:
        await send_main(cb.message.chat.id, lg)


# ======================= YARATISH: UMUMIY =======================

def _qz_state(m, *steps):
    uid = m.from_user.id if m.from_user else None
    w = qz_w.get(uid) if uid else None
    return bool(w) and w["step"] in steps and time.time() - w["ts"] < QZ_STATE_TTL


def _qz_plain_text(m):
    return bool(m.text) and not m.text.startswith("/") and m.text not in _menu_texts()


def _qz_time_kb(lg):
    return _qz_kb([[(tr(lg, "b_sec", t=t), f"qz:t:{t}") for t in QZ_TIMES[:3]],
                   [(tr(lg, "b_sec", t=t), f"qz:t:{t}") for t in QZ_TIMES[3:]],
                   [(tr(lg, "b_cancel"), "qz:x")]])


async def _ask_time(target, w, lg):
    await _say(target, w, tr(lg, "ask_time"), reply_markup=_qz_time_kb(lg))


@dp.message(Command("bekor"))
@dp.message(is_btn("b_cancel"))
async def cmd_bekor(msg: Message):
    lg = await lang_of(msg.from_user)
    feedback_mode.pop(msg.from_user.id, None)
    w = qz_w.pop(msg.from_user.id, None)
    if w and w.get("last"):
        await _del_id(msg.chat.id, w["last"])
    await msg.answer(tr(lg, "cancelled"), reply_markup=menu_kb(lg))


# ======================= 1) QUIZ TUZISH (Quiz Bot kabi, bittalab) =======================

@dp.message(is_btn("b_make"))
async def btn_make(msg: Message):
    lg = await lang_of(msg.from_user)
    if await need_subscribe(msg, lg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    w = {"step": "m_title", "ts": time.time(), "mode": "manual", "qs": [], "desc": ""}
    qz_w[msg.from_user.id] = w
    await _say(msg, w, tr(lg, "make_title"), reply_markup=ReplyKeyboardRemove())


async def _ask_first_question(msg, w, lg):
    w["step"] = "m_q"
    await _say(msg, w, tr(lg, "make_q"), reply_markup=poll_kb(lg))


@dp.message(Command("skip"), lambda m: _qz_state(m, "m_desc"))
async def make_skip(msg: Message):
    lg = await lang_of(msg.from_user)
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    await _ask_first_question(msg, w, lg)


@dp.message(F.poll, lambda m: _qz_state(m, "m_q"))
async def make_poll(msg: Message):
    lg = await lang_of(msg.from_user)
    p = msg.poll
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    if p.type != "quiz" or p.correct_option_id is None:
        await msg.answer(tr(lg, "poll_bad"))
        return
    expl = (getattr(p, "explanation", None) or "").strip()
    w["qs"].append({"q": p.question, "o": [o.text for o in p.options], "c": p.correct_option_id,
                    "e": expl[:200]})
    await _say(msg, w, tr(lg, "q_added", n=len(w["qs"])), reply_markup=poll_kb(lg))


@dp.message(Command("done"))
@dp.message(is_btn("b_done"))
async def make_done(msg: Message):
    lg = await lang_of(msg.from_user)
    w = qz_w.get(msg.from_user.id)
    if not w or w.get("mode") != "manual" or w["step"] != "m_q":
        await msg.answer(tr(lg, "no_process"), reply_markup=menu_kb(lg))
        return
    if not w["qs"]:
        await msg.answer(tr(lg, "no_q_yet"))
        return
    w.update(step="time", ts=time.time())
    await _say(msg, w, tr(lg, "n_ready", n=len(w["qs"])), reply_markup=ReplyKeyboardRemove())
    await _ask_time(msg, w, lg)


@dp.message(lambda m: _qz_state(m, "m_title", "m_desc", "m_q") and _qz_plain_text(m))
async def make_text(msg: Message):
    lg = await lang_of(msg.from_user)
    w = qz_w[msg.from_user.id]
    w["ts"] = time.time()
    t = msg.text.strip()
    if w["step"] == "m_title":
        w["title"] = t[:80]
        w["step"] = "m_desc"
        await _say(msg, w, tr(lg, "make_desc"))
    elif w["step"] == "m_desc":
        w["desc"] = t[:300]
        await _ask_first_question(msg, w, lg)
    else:
        await msg.answer(tr(lg, "use_poll_btn"), reply_markup=poll_kb(lg))


# ======================= 2) TEZKOR QUIZ (fayldan) =======================

@dp.message(is_btn("b_fast"))
async def btn_fast(msg: Message):
    lg = await lang_of(msg.from_user)
    if await need_subscribe(msg, lg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    w = {"step": "file", "ts": time.time(), "mode": None}
    qz_w[msg.from_user.id] = w
    await _say(msg, w, tr(lg, "fast_help"), reply_markup=menu_kb(lg))


async def qz_after_parse(msg, name, data, lg):
    uid = msg.from_user.id
    try:
        async with parse_sem:                                   # og'ir ishni alohida oqimda bajaramiz: bot qotmaydi
            qs, notes = await asyncio.to_thread(qz_parse_file, name, data)
    except ValueError as e:
        key = e.args[0][0] if e.args and isinstance(e.args[0], tuple) else "pe_unreadable"
        await msg.answer(tr(lg, "parse_err", e=tr(lg, key), b=tr(lg, "b_fast")))
        return
    w = qz_w[uid]
    w.update(step="mode", qs=qs, title=qz_pretty_title(name), ts=time.time())
    text = tr(lg, "found", n=len(qs))
    if notes:
        text += "".join("\n⚠️ " + tr(lg, k, n=n) for k, n in notes)
    text += "\n\n" + tr(lg, "mode_q")
    await _say(msg, w, text, reply_markup=_qz_kb([
        [(tr(lg, "b_all"), "qz:m:all")], [(tr(lg, "b_rnd"), "qz:m:rnd")], [(tr(lg, "b_cancel"), "qz:x")]]))


@dp.message(F.document, lambda m: _qz_state(m, "file"))
async def fast_on_file(msg: Message):
    lg = await lang_of(msg.from_user)
    doc = msg.document
    name = doc.file_name or "test.txt"
    if name.lower().endswith(".pdf"):
        await msg.answer(tr(lg, "pdf_no"))
        return
    if doc.file_size and doc.file_size > QZ_MAX_BYTES:
        await msg.answer(tr(lg, "too_big"))
        return
    try:
        buf = await bot.download(doc, destination=io.BytesIO())
        data = buf.getvalue()
    except Exception as e:
        print("quiz fayl yuklash xatosi:", e)
        await msg.answer(tr(lg, "dl_fail"))
        return
    await qz_after_parse(msg, name, data, lg)


@dp.message(lambda m: _qz_state(m, "file") and _qz_plain_text(m) and len(m.text) > 40)
async def fast_on_text(msg: Message):
    lg = await lang_of(msg.from_user)
    await qz_after_parse(msg, "test.txt", msg.text.encode("utf-8"), lg)


@dp.message(lambda m: _qz_state(m, "count") and _qz_plain_text(m))
async def fast_on_count(msg: Message):
    lg = await lang_of(msg.from_user)
    w = qz_w[msg.from_user.id]
    n = len(w["qs"])
    t = msg.text.strip()
    if not t.isdigit() or not (1 <= int(t) <= n):
        await msg.answer(tr(lg, "count_bad", n=n))
        return
    w.update(count=int(t), step="time", ts=time.time())
    await _ask_time(msg, w, lg)


# ======================= 3) MENING TESTLARIM =======================

@dp.message(is_btn("b_my"))
async def btn_my(msg: Message):
    lg = await lang_of(msg.from_user)
    if await need_subscribe(msg, lg):
        return
    feedback_mode.pop(msg.from_user.id, None)
    rows = await qz_list_owner(msg.from_user.id)
    if rows is None:
        await msg.answer(tr(lg, "my_fail"))
        return
    if not rows:
        await msg.answer(tr(lg, "my_empty", a=tr(lg, "b_make"), b=tr(lg, "b_fast")))
        return
    groups = qz_group_tests(rows)[:40]
    kb = [[(f"{i + 1}. {g['title'][:38]} · {tr(lg, KIND_KEY.get(g['kind'], 'k_man'))}", f"qm:{g['id']}")]
          for i, g in enumerate(groups)]
    await msg.answer(tr(lg, "my_head", n=len(groups)), reply_markup=_qz_kb(kb))


@dp.callback_query(F.data.startswith("qm:"))
async def qz_my_cb(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    qset = await qz_get(cb.data.split(":")[1])
    if not qset or (qset.get("owner") != cb.from_user.id and cb.from_user.id != ADMIN_ID):
        await cb.answer(tr(lg, "not_found"), show_alert=True)
        return
    await cb.answer()
    for chunk in qz_post_chunks(qset, lg):
        await qz_send_html(cb.message.chat.id, chunk)


# ======================= 4) ALOQA va FIKR BILDIRISH =======================

@dp.message(is_btn("b_contact"))
async def btn_contact(msg: Message):
    lg = await lang_of(msg.from_user)
    feedback_mode.pop(msg.from_user.id, None)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tr(lg, "b_write"), url=f"https://t.me/{CONTACT[1:]}")]])
    await msg.answer(tr(lg, "contact_txt", c=CONTACT), reply_markup=kb)


@dp.message(is_btn("b_fb"))
async def btn_feedback(msg: Message):
    lg = await lang_of(msg.from_user)
    qz_w.pop(msg.from_user.id, None)
    feedback_mode[msg.from_user.id] = "choose"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lg, "b_anon"), callback_data="fb_anon")],
        [InlineKeyboardButton(text=tr(lg, "b_named"), callback_data="fb_named")],
        [InlineKeyboardButton(text=tr(lg, "b_cancel"), callback_data="fb_cancel")]])
    await msg.answer(tr(lg, "fb_choose"), reply_markup=kb)


@dp.callback_query(F.data.in_({"fb_anon", "fb_named", "fb_cancel"}))
async def fb_choice(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    uid = cb.from_user.id
    if cb.data == "fb_cancel":
        feedback_mode.pop(uid, None)
        await cb.answer(tr(lg, "cancelled"))
        try:
            await cb.message.delete()
        except Exception:
            pass
        return
    feedback_mode[uid] = "anon" if cb.data == "fb_anon" else "named"
    await cb.answer()
    how = tr(lg, "how_anon" if cb.data == "fb_anon" else "how_named")
    try:
        await cb.message.edit_text(tr(lg, "fb_write", how=how))
    except Exception:
        pass


@dp.message(lambda m: feedback_mode.get(m.from_user.id) in ("anon", "named") and _qz_plain_text(m))
async def feedback_text(msg: Message):
    lg = await lang_of(msg.from_user)
    uid = msg.from_user.id
    mode = feedback_mode.get(uid)
    if not ADMIN_ID:
        feedback_mode.pop(uid, None)
        await msg.answer(tr(lg, "fb_off"))
        return
    now = time.time()
    if now - last_feedback.get(uid, 0) < 30:
        await msg.answer(tr(lg, "fb_wait"))
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
        await msg.answer(tr(lg, "fb_err"))
        return
    last_feedback[uid] = now
    feedback_mode.pop(uid, None)
    await msg.answer(tr(lg, "fb_thanks"))


# ======================= TUGMALAR (callback) va YARATISH =======================

@dp.callback_query(F.data.startswith("qz:"))
async def qz_on_cb(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    uid = cb.from_user.id
    parts = cb.data.split(":")
    kind = parts[1]
    w = qz_w.get(uid)
    if kind == "x":
        qz_w.pop(uid, None)
        await _del_id(cb.message.chat.id, cb.message.message_id)
        if w and w.get("last"):
            await _del_id(cb.message.chat.id, w["last"])
        await cb.message.answer(tr(lg, "cancelled"), reply_markup=menu_kb(lg))
        await cb.answer()
        return
    if not w or time.time() - w["ts"] > QZ_STATE_TTL:
        qz_w.pop(uid, None)
        await cb.answer(tr(lg, "expired"), show_alert=True)
        return
    w["ts"] = time.time()
    n = len(w.get("qs") or [])
    if kind == "m":
        w["mode"] = parts[2]
        if parts[2] == "all":
            sizes = [s for s in QZ_SIZES if s <= n] or [n]
            w["step"] = "size"
            await _say(cb.message, w, tr(lg, "size_q", n=n),
                       reply_markup=_qz_kb([[(str(s), f"qz:s:{s}") for s in sizes[:3]],
                                            [(str(s), f"qz:s:{s}") for s in sizes[3:]],
                                            [(tr(lg, "b_cancel"), "qz:x")]]))
        else:
            counts = [c for c in QZ_COUNTS if c <= n] or [n]
            w["step"] = "count"
            await _say(cb.message, w, tr(lg, "count_q", n=n),
                       reply_markup=_qz_kb([[(str(c), f"qz:c:{c}") for c in counts],
                                            [(tr(lg, "b_cancel"), "qz:x")]]))
    elif kind == "s":
        w["size"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message, w, lg)
    elif kind == "c":
        w["count"] = max(1, min(int(parts[2]), n))
        w["step"] = "time"
        await _ask_time(cb.message, w, lg)
    elif kind == "t":
        w["secs"] = max(5, min(int(parts[2]), 600))
        if w.get("last"):
            await _del_id(cb.message.chat.id, w["last"])
        await qz_create(cb, w, lg)
        return
    await cb.answer()


async def qz_create(cb, w, lg):
    uid = cb.from_user.id
    today = datetime.now(TZ).date().isoformat()
    if qz_daily.get((today, uid), 0) >= QZ_DAILY_LIMIT and uid != ADMIN_ID:
        await cb.answer(tr(lg, "limit", n=QZ_DAILY_LIMIT), show_alert=True)
        return
    await cb.answer(tr(lg, "creating"))
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
            parts = [{"l": f"🎲 {w['count']}", "qs": rnd.sample(prepared, w["count"])}]
    # id: "i" (shu botniki) + tur (a=jami, r=tasodifiy, m=qo'lda) + 5 ta tasodifiy belgi
    kind = {"manual": "m", "all": "a"}.get(w["mode"], "r")
    qid = "i" + kind + "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=5))
    qset = {"id": qid, "owner": uid, "by": (cb.from_user.first_name or "")[:30],
            "title": w.get("title") or "Test", "secs": w["secs"], "parts": parts,
            "desc": w.get("desc") or ""}
    if not await qz_save(qset):
        await cb.message.answer(tr(lg, "save_fail"), reply_markup=menu_kb(lg))
        return
    qz_daily[(today, uid)] = qz_daily.get((today, uid), 0) + 1
    qz_w.pop(uid, None)
    qz_cache[qid] = (qset, time.time())
    await cb.message.answer(tr(lg, "done_msg", n=len(parts), b=tr(lg, "b_my")), reply_markup=menu_kb(lg))
    for chunk in qz_post_chunks(qset, lg):
        await qz_send_html(cb.message.chat.id, chunk)


# ======================= QUIZ O'TKAZISH: umumiy =======================

def _cancel_other(task):
    """Taymer vazifasini bekor qiladi, lekin o'zini emas (aks holda natija xabari yuborilmay qoladi)."""
    if task and task is not asyncio.current_task():
        task.cancel()


async def send_poll_safe(*a, **kw):
    """Telegram 'juda tez' (flood) desa, kutib qayta urinadi."""
    for _ in range(3):
        try:
            return await bot.send_poll(*a, **kw)
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after, 30) + 0.5)
    return await bot.send_poll(*a, **kw)


def _poll_args(q, head, lg):
    """Savol matni uzun bo'lsa alohida xabar, so'rovda esa harflar. (extra_text, question, options)"""
    letters = "ABCDEFGHIJ"
    if len(head) + 1 + len(q["q"]) > 300 or any(len(o) > 100 for o in q["o"]):
        text = f"{head} {q['q']}\n\n" + "\n".join(f"{letters[k]}) {o}" for k, o in enumerate(q["o"]))
        return text[:4000], tr(lg, "pick", h=head), list(letters[:len(q["o"])])
    return None, f"{head} {q['q']}", q["o"]


async def qz_deeplink(chat_id, args, lg):
    m = re.fullmatch(r"qz_([a-z0-9]+)_(\d+)", args or "")
    qset = await qz_get(m.group(1)) if m else None
    if not qset or int(m.group(2)) >= len(qset["parts"]):
        await bot.send_message(chat_id, tr(lg, "quiz_nf"))
        return
    p = int(m.group(2))
    part = qset["parts"][p]
    await bot.send_message(
        chat_id, tr(lg, "prep", title=qset["title"], label=part["l"], n=len(part["qs"]), s=qset["secs"]),
        reply_markup=_qz_kb([[(tr(lg, "b_start"), f"qs:{qset['id']}:{p}")]]))


# ======================= shaxsiy chatda o'ynash =======================

@dp.callback_query(F.data.startswith("qs:"))
async def qz_begin_cb(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    _, qid, p = cb.data.split(":")
    uid = cb.from_user.id
    if await not_subscribed(uid):
        await cb.answer(tr(lg, "sub_need"), show_alert=True)
        return
    qset = await qz_get(qid)
    if not qset or int(p) >= len(qset["parts"]):
        await cb.answer(tr(lg, "quiz_nf"), show_alert=True)
        return
    old = qz_sessions.pop(uid, None)
    if old and old.get("task"):
        old["task"].cancel()
    part = qset["parts"][int(p)]
    qz_sessions[uid] = {"set": qid, "p": int(p), "title": qset["title"], "label": part["l"], "secs": qset["secs"],
                        "qs": part["qs"], "i": 0, "ok": 0, "bad": [], "poll_id": None, "mid": None, "lg": lg,
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
    try:
        extra_text, question, options = _poll_args(q, head, s["lg"])
        if extra_text:
            await bot.send_message(s["chat"], extra_text)
        extra = {"explanation": q["e"]} if q.get("e") else {}
        m = await send_poll_safe(s["chat"], question=question, options=options, type="quiz",
                                correct_option_id=q["c"], is_anonymous=False, open_period=s["secs"], **extra)
    except Exception as e:
        print("quiz savol yuborilmadi:", e)
        qz_sessions.pop(uid, None)
        try:
            await bot.send_message(s["chat"], tr(s["lg"], "send_fail"))
        except Exception:
            pass
        return
    s["poll_id"], s["mid"] = m.poll.id, m.message_id
    s["task"] = asyncio.create_task(qz_timeout(uid, s["i"], s["secs"]))


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


async def qz_finish(uid, early=False):
    s = qz_sessions.pop(uid, None)
    if not s:
        return
    lg = s["lg"]
    _cancel_other(s["task"])
    if early and s.get("mid"):
        try:
            await bot.stop_poll(s["chat"], s["mid"])
        except Exception:
            pass
    n = len(s["qs"])
    wrong = [b for b in s["bad"] if b[1] is not None]
    skipped = n - s["ok"] - len(wrong)
    secs = int(time.time() - s["t0"])
    lines = [
        tr(lg, "fin_head", st=tr(lg, "st_stop" if early else "st_done"), title=s["title"], label=s["label"]), "",
        tr(lg, "fin_ok", ok=s["ok"], n=n, p=round(100 * s["ok"] / n)),
        tr(lg, "fin_bad", n=len(wrong)),
        tr(lg, "fin_skip", n=skipped),
        tr(lg, "fin_time", m=secs // 60, s=secs % 60),
    ]
    if wrong:
        lines += ["", tr(lg, "fin_wrong")]
        for i, _ in wrong[:10]:
            q = s["qs"][i]
            qt = q["q"] if len(q["q"]) <= 70 else q["q"][:67] + "..."
            lines.append(f"{i + 1}) {qt}\n   " + tr(lg, "fin_right", a=q["o"][q["c"]][:80]))
        if len(wrong) > 10:
            lines.append(tr(lg, "fin_more", n=len(wrong) - 10))
    await bot.send_message(s["chat"], "\n".join(lines), reply_markup=_qz_kb([
        [(tr(lg, "b_again"), f"qs:{s['set']}:{s['p']}")],
        [(tr(lg, "b_parts"), f"qp:{s['set']}")],
    ]))


@dp.callback_query(F.data.startswith("qp:"))
async def qz_parts_cb(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    qset = await qz_get(cb.data.split(":")[1])
    await cb.answer()
    if qset:
        for chunk in qz_post_chunks(qset, lg):
            await qz_send_html(cb.message.chat.id, chunk)


# ======================= GURUHDA O'YNASH (hamma birga, mavzular (topic) alohida) =======================

def _thread(msg):
    """Forum guruhdagi mavzu (topic) raqami; oddiy guruhda None."""
    return msg.message_thread_id if getattr(msg, "is_topic_message", False) else None


def _tkw(thread):
    return {"message_thread_id": thread} if thread else {}


async def _is_chat_admin(chat_id, uid):
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in ("creator", "administrator")
    except Exception:
        return False


async def qz_group_prep(chat_id, uid, args, lg, thread=None):
    m = re.fullmatch(r"qz_([a-z0-9]+)_(\d+)", args or "")
    qset = await qz_get(m.group(1)) if m else None
    if not qset or int(m.group(2)) >= len(qset["parts"]):
        await bot.send_message(chat_id, tr(lg, "quiz_nf"), **_tkw(thread))
        return
    p = int(m.group(2))
    part = qset["parts"][p]
    await bot.send_message(
        chat_id, tr(lg, "g_prep", title=qset["title"], label=part["l"], n=len(part["qs"]), s=qset["secs"]),
        reply_markup=_qz_kb([[(tr(lg, "b_start"), f"qg:{qset['id']}:{p}:{uid}")]]), **_tkw(thread))


@dp.message(Command("quiz"))
async def cmd_quiz(msg: Message, command: CommandObject):
    """Guruh mavzusi (topic) ichida quizni boshlash: /quiz KOD [qism raqami]."""
    lg = await lang_of(msg.from_user)
    if not _is_group(msg.chat):
        await msg.answer(tr(lg, "g_info"))
        return
    parts = (command.args or "").split()
    if not parts:
        await msg.answer(tr(lg, "g_info") + f"\nhttps://t.me/{BOT_USERNAME}")
        return
    qid = parts[0].replace("qz_", "").split("_")[0].lower()
    p = int(parts[1]) - 1 if len(parts) > 1 and parts[1].isdigit() else 0
    await qz_group_prep(msg.chat.id, msg.from_user.id, f"qz_{qid}_{max(p, 0)}", lg, _thread(msg))


@dp.callback_query(F.data.startswith("qg:"))
async def qz_group_begin(cb: CallbackQuery):
    lg = await lang_of(cb.from_user)
    _, qid, p, starter = cb.data.split(":")
    chat_id = cb.message.chat.id
    thread = _thread(cb.message)
    key = (chat_id, thread or 0)
    uid = cb.from_user.id
    if uid != int(starter) and not await _is_chat_admin(chat_id, uid):
        await cb.answer(tr(lg, "g_only"), show_alert=True)
        return
    if key in g_sessions:
        await cb.answer(tr(lg, "g_busy"), show_alert=True)
        return
    qset = await qz_get(qid)
    if not qset or int(p) >= len(qset["parts"]):
        await cb.answer(tr(lg, "quiz_nf"), show_alert=True)
        return
    part = qset["parts"][int(p)]
    g_sessions[key] = {"chat": chat_id, "thread": thread, "title": qset["title"], "label": part["l"],
                       "secs": qset["secs"], "qs": part["qs"], "i": 0, "starter": uid, "lg": lg,
                       "scores": {}, "answered": set(), "warn": None,
                       "poll_id": None, "mid": None, "task": None, "q_t0": 0.0, "polls": []}
    await cb.answer()
    await _del_id(chat_id, cb.message.message_id)
    await g_send(key)


async def g_send(key):
    g = g_sessions.get(key)
    if not g:
        return
    if g["i"] >= len(g["qs"]):
        await g_finish(key)
        return
    if g.get("warn"):
        await _del_id(g["chat"], g["warn"])
        g["warn"] = None
    q = g["qs"][g["i"]]
    head = f"[{g['i'] + 1}/{len(g['qs'])}]"
    kw = _tkw(g["thread"])
    try:
        extra_text, question, options = _poll_args(q, head, g["lg"])
        if extra_text:
            await bot.send_message(g["chat"], extra_text, **kw)
        extra = {"explanation": q["e"]} if q.get("e") else {}
        m = await send_poll_safe(g["chat"], question=question, options=options, type="quiz",
                                correct_option_id=q["c"], is_anonymous=False, open_period=g["secs"],
                                **kw, **extra)
    except Exception as e:
        print("guruh savoli yuborilmadi:", e)
        g_sessions.pop(key, None)
        try:
            await bot.send_message(g["chat"], tr(g["lg"], "g_fail"), **kw)
        except Exception:
            pass
        return
    g["poll_id"], g["mid"] = m.poll.id, m.message_id
    g["answered"] = set()
    g["q_t0"] = time.time()
    g["polls"].append(m.poll.id)
    poll_chat[m.poll.id] = key
    g["task"] = asyncio.create_task(g_timeout(key, g["i"], g["secs"]))


async def g_timeout(key, i, secs):
    """Vaqt tugaguncha kutadi (hamma javob bergan bo'lsa ham). 10 soniya qolganda qizil ogohlantirish chiqaradi."""
    try:
        if secs > 12:
            await asyncio.sleep(secs - 10)
            g = g_sessions.get(key)
            if not g or g["i"] != i:
                return
            try:
                m = await bot.send_message(g["chat"], tr(g["lg"], "g_warn", n=10), **_tkw(g["thread"]))
                g["warn"] = m.message_id
            except Exception:
                pass
            await asyncio.sleep(5)
            g = g_sessions.get(key)
            if g and g["i"] == i and g.get("warn"):
                try:
                    await bot.edit_message_text(tr(g["lg"], "g_warn", n=5), chat_id=g["chat"], message_id=g["warn"])
                except Exception:
                    pass
            await asyncio.sleep(6)
        else:
            await asyncio.sleep(secs + 1)
    except asyncio.CancelledError:
        return
    g = g_sessions.get(key)
    if g and g["i"] == i:
        g["i"] += 1
        g["poll_id"] = None
        await g_send(key)


async def g_finish(key, early=False):
    g = g_sessions.pop(key, None)
    if not g:
        return
    lg = g["lg"]
    _cancel_other(g["task"])
    if g.get("warn"):
        await _del_id(g["chat"], g["warn"])
    if early and g.get("mid"):
        try:
            await bot.stop_poll(g["chat"], g["mid"])
        except Exception:
            pass
    for pid in g["polls"]:
        poll_chat.pop(pid, None)
    n = len(g["qs"])
    ranking = sorted(g["scores"].values(), key=lambda x: (-x["ok"], x["t"]))
    lines = [f"<b>{html.escape(tr(lg, 'g_results', title=g['title'], label=g['label']))}</b>", ""]
    if not ranking:
        lines.append(tr(lg, "g_none"))
    medals = ["🥇", "🥈", "🥉"]
    for k, sc in enumerate(ranking[:20]):
        mark = medals[k] if k < 3 else f"{k + 1}."
        lines.append(f"{mark} {html.escape(sc['name'])} — {sc['ok']}/{n} ({int(sc['t']) // 60}:{int(sc['t']) % 60:02d})")
    await qz_send_html(g["chat"], "\n".join(lines), **_tkw(g["thread"]))


async def g_on_answer(ev: PollAnswer, key):
    g = g_sessions.get(key)
    if not g or g["poll_id"] != ev.poll_id or not ev.option_ids:
        return
    uid = ev.user.id
    if uid in g["answered"]:
        return
    g["answered"].add(uid)
    sc = g["scores"].setdefault(uid, {"name": ev.user.full_name or "?", "ok": 0, "t": 0.0})
    if ev.option_ids[0] == g["qs"][g["i"]]["c"]:
        sc["ok"] += 1
        sc["t"] += time.time() - g["q_t0"]


@dp.poll_answer()
async def qz_on_answer(ev: PollAnswer):
    key = poll_chat.get(ev.poll_id)
    if key is not None:
        await g_on_answer(ev, key)
        return
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


@dp.message(Command("stop"))
async def cmd_stop(msg: Message):
    lg = await lang_of(msg.from_user)
    if _is_group(msg.chat):
        key = (msg.chat.id, _thread(msg) or 0)
        g = g_sessions.get(key)
        if not g:
            await msg.answer(tr(lg, "no_active"))
            return
        if msg.from_user.id != g["starter"] and not await _is_chat_admin(msg.chat.id, msg.from_user.id):
            await msg.answer(tr(lg, "g_only"))
            return
        await g_finish(key, early=True)
        return
    if msg.from_user.id in qz_sessions:
        await qz_finish(msg.from_user.id, early=True)
    else:
        await msg.answer(tr(lg, "no_active"))


# ======================= XATOLAR, UYG'OQ TURISH, ISHGA TUSHIRISH =======================

warned = {}     # user_id -> kanaldan chiqqani haqida oxirgi ogohlantirish vaqti


@dp.chat_member()
async def on_member_change(ev: ChatMemberUpdated):
    """Majburiy kanaldan chiqib ketgan foydalanuvchiga darrov ogohlantirish yuboradi.
    Ishlashi uchun bot kanalda admin bo'lishi kerak."""
    names = [c.lower() for c in CHANNELS]
    uname = ("@" + (ev.chat.username or "")).lower()
    if uname not in names or ev.new_chat_member.status not in ("left", "kicked"):
        return
    user = ev.new_chat_member.user
    if user.is_bot:
        return
    sub_cache.pop(user.id, None)
    if time.time() - warned.get(user.id, 0) < 3600:
        return
    lg = await lang_saved(user.id)
    if not lg:                                    # botdan foydalanmagan odamga yozmaymiz
        return
    warned[user.id] = time.time()
    idx = names.index(uname) + 1
    ch = f"{tr(lg, 'b_chan', n=idx)} ({CHANNELS[idx - 1]})"
    try:
        await bot.send_message(user.id, tr(lg, "unsub_warn", ch=ch),
                               reply_markup=sub_keyboard([(idx, CHANNELS[idx - 1])], lg))
    except Exception as e:
        print("Ogohlantirish yuborilmadi:", user.id, e)


class Throttle(BaseMiddleware):
    """Bitta foydalanuvchidan juda tez ketma-ket kelgan so'rovlarni tashlab yuboradi (spamdan himoya)."""
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            now = time.monotonic()
            if now - _last.get(user.id, 0) < 0.3:
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None
            _last[user.id] = now
        return await handler(event, data)


dp.message.outer_middleware(Throttle())
dp.callback_query.outer_middleware(Throttle())


async def cleanup_loop():
    """Har 10 daqiqada eskirgan ma'lumotlarni xotiradan tozalaydi (xotira to'lib qotmasligi uchun)."""
    while True:
        await asyncio.sleep(600)
        try:
            now, mono = time.time(), time.monotonic()
            for uid in [u for u, w in qz_w.items() if now - w.get("ts", 0) > QZ_STATE_TTL * 2]:
                qz_w.pop(uid, None)
            for uid in [u for u, t in last_feedback.items() if now - t > 3600]:
                last_feedback.pop(uid, None)
            for uid in [u for u, t in sub_cache.items() if now - t > 600]:
                sub_cache.pop(uid, None)
            for uid in [u for u, t in lang_miss.items() if now - t > 600]:
                lang_miss.pop(uid, None)
            for uid in [u for u, t in warned.items() if now - t > 7200]:
                warned.pop(uid, None)
            for uid in [u for u, t in _last.items() if mono - t > 600]:
                _last.pop(uid, None)
            today = datetime.now(TZ).date().isoformat()
            for k in [k for k in qz_daily if k[0] != today]:
                qz_daily.pop(k, None)
            for uid in [u for u, s_ in qz_sessions.items() if now - s_.get("t0", now) > 10800]:
                s_ = qz_sessions.pop(uid, None)
                if s_ and s_.get("task"):
                    s_["task"].cancel()
            for key in [k for k, g in g_sessions.items() if g.get("q_t0") and now - g["q_t0"] > 10800]:
                await g_finish(key, early=True)
            if len(lang_cache) > 100000:
                lang_cache.clear()
            if len(pending_qz) > 5000:
                pending_qz.clear()
            if len(pending_start) > 5000:
                pending_start.clear()
        except Exception as e:
            print("cleanup xato:", e)


@dp.error()
async def on_error(event):
    print("XATO:", repr(event.exception))
    return True


async def health(request):
    return web.Response(text="ok")


async def keepalive():
    """Render bepul rejasi uxlab qolmasligi uchun o'ziga har 8 daqiqada so'rov yuboradi."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        await asyncio.sleep(480)
        try:
            async with aiohttp.ClientSession() as ses:
                await ses.get(url, timeout=aiohttp.ClientTimeout(total=20))
        except Exception as e:
            print("keepalive xato:", e)


async def main():
    global BOT_USERNAME
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL va SUPABASE_KEY o'zgaruvchilari kiritilmagan.")
    me = await bot.get_me()
    BOT_USERNAME = me.username
    print("Bot ishga tushdi: @" + BOT_USERNAME)
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands([
        BotCommand(command="start", description="Start / Старт"),
        BotCommand(command="menu", description="Menu / Меню"),
        BotCommand(command="lang", description="Til / Language / Язык"),
        BotCommand(command="stop", description="Stop quiz"),
        BotCommand(command="bekor", description="Cancel"),
    ])
    port = os.environ.get("PORT")
    if port:                                   # Render/Railway kabi hostinglar uchun
        app = web.Application()
        app.router.add_get("/", health)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    asyncio.create_task(keepalive())
    asyncio.create_task(cleanup_loop())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
