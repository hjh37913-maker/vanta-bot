import asyncio
import io
import json
import logging
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import quote

import httpx
from openai import AsyncOpenAI
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vanta")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "flux")
# Telegram ID через запятую. Пусто = бот открыт всем (и тратит твой баланс!)
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}
HISTORY_LIMIT = 24
DATA_FILE = Path(os.getenv("DATA_FILE", "data.json"))
BANNERS = Path(__file__).parent / "banners"

client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

# ---------- характер ----------
CORE = (
    "Тебя зовут Vanta. Ты не обычный чат-бот, а острый, уверенный ум с сухим юмором. "
    "Говоришь коротко, точно и по делу, как гениальный друг, который уважает время собеседника. "
    "Никакой лести, воды, канцелярита и лишних извинений. Не читай лекций, если не просили. "
    "Если собеседник неправ, спокойно и с аргументами скажи об этом. Если вопрос расплывчатый, задай один уточняющий вопрос. "
    "Иногда уместна короткая остроумная фраза, но смысл всегда важнее шутки. "
    "Отвечай на языке собеседника. Никогда не используй эмодзи и смайлики. "
    "Форматирование: короткие абзацы, списки только когда они реально помогают, код всегда в блоках тройных кавычек."
)
MODES = {
    "vanta": ("Vanta", CORE),
    "mentor": ("Наставник", CORE + " Сейчас ты наставник: объясняешь сложное просто, по шагам, с яркими аналогиями, и проверяешь понимание коротким вопросом в конце."),
    "coder": ("Кодер", CORE + " Сейчас ты senior-разработчик: даёшь рабочий, чистый код, сразу указываешь на подводные камни и предлагаешь лучший способ, а не первый попавшийся."),
    "strategist": ("Стратег", CORE + " Сейчас ты стратег: разбираешь задачу как консультант, показываешь варианты, риски и даёшь чёткую рекомендацию с первым шагом."),
    "editor": ("Редактор", CORE + " Сейчас ты редактор и копирайтер: улучшаешь тексты, делаешь их живыми и сильными, объясняешь правки одной строкой."),
    "translator": ("Переводчик", CORE + " Сейчас ты переводчик: переводишь присланный текст с сохранением смысла, тона и стиля. Русский и английский друг в друга, если язык не указан."),
    "critic": ("Разнос", CORE + " Сейчас ты беспощадный критик-аналитик. Оцениваешь присланную идею, текст, код, проект или план строго по фактам. Находишь каждую слабость, ошибку, риск и логическую дыру и называешь прямо, без смягчений, без вежливых прокладок и без оговорок там, где есть факт. Не щади чувства, но ничего не выдумывай: каждое замечание конкретно, обосновано, с объяснением, в чём проблема и как её исправить. Критикуй работу, а не личность: никаких оскорблений человека и пустой грубости, только факты. Если что-то действительно сильное, скажи об этом прямо и с обоснованием, без восторгов и без похвалы из вежливости. Если данных мало для оценки, назови, чего не хватает. Формат ответа: вердикт одной строкой с оценкой из 10, затем провалы, затем что работает, затем что исправить в порядке приоритета."),
    "sarcasm": ("Дерзкий", CORE + " Сейчас ты в режиме едкого остроумия: отвечай с иронией и подколами, но по-доброму, без оскорблений личности. Ответ по существу при этом всегда верный."),
}

# ---------- хранилище ----------
state = {}


def new_user():
    return {"mode": "vanta", "history": [], "await_image": False, "last_image": "", "last_kb_msg": None}


def user(uid):
    return state.setdefault(uid, new_user())


def load():
    if DATA_FILE.exists():
        try:
            for k, v in json.loads(DATA_FILE.read_text()).items():
                u = new_user()
                u["mode"] = v.get("mode", "vanta") if v.get("mode") in MODES else "vanta"
                u["history"] = v.get("history", [])
                state[int(k)] = u
        except Exception:
            log.exception("load failed")


def save():
    try:
        DATA_FILE.write_text(json.dumps({k: {"mode": v["mode"], "history": v["history"]} for k, v in state.items()}, ensure_ascii=False))
    except Exception:
        log.exception("save failed")


# ---------- интерфейс ----------
def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Новый чат", callback_data="new"), InlineKeyboardButton("Режимы", callback_data="modes")],
        [InlineKeyboardButton("Нарисовать", callback_data="image"), InlineKeyboardButton("О Vanta", callback_data="about")],
        [InlineKeyboardButton("Справка", callback_data="help")],
    ])


def modes_kb(current):
    rows, row = [], []
    for key, (name, _) in MODES.items():
        row.append(InlineKeyboardButton(f"> {name}" if key == current else name, callback_data=f"mode:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Назад", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]])


def answer_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Короче", callback_data="re:short"),
        InlineKeyboardButton("Подробнее", callback_data="re:long"),
        InlineKeyboardButton("Заново", callback_data="re:again"),
    ]])


def image_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Ещё вариант", callback_data="img:again"),
        InlineKeyboardButton("Меню", callback_data="menu"),
    ]])


def caption(name, first=""):
    c = {
        "menu": (f"{first}, на связи Vanta. Пиши вопрос или выбирай действие." if first else "На связи Vanta. Пиши вопрос или выбирай действие."),
        "modes": "Выбери характер. Активный режим отмечен знаком >.",
        "image": "Опиши картинку одним сообщением. Чем точнее, тем лучше.",
        "help": "Просто пиши. Vanta помнит контекст разговора.\n\n/new  сбросить диалог\n/mode  сменить характер\n/image  нарисовать\n/about  о боте",
        "about": "Vanta: личный ИИ без воды и пафоса. Восемь характеров, генерация картинок, память диалога. Движок: Llama.",
    }
    return c[name]


async def show(query, name, kb):
    first = query.from_user.first_name or ""
    with open(BANNERS / f"{name}.jpg", "rb") as f:
        media = InputMediaPhoto(f.read(), caption=caption(name, first))
    try:
        await query.message.edit_media(media=media, reply_markup=kb)
    except BadRequest:
        pass


async def send_screen(update, name, kb):
    first = update.effective_user.first_name or ""
    with open(BANNERS / f"{name}.jpg", "rb") as f:
        await update.effective_message.reply_photo(f, caption=caption(name, first), reply_markup=kb)


def allowed(update: Update) -> bool:
    return not ALLOWED or (update.effective_user and update.effective_user.id in ALLOWED)


# ---------- команды ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await update.effective_message.reply_text("Доступ закрыт.")
    await send_screen(update, "menu", menu_kb())


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        user(update.effective_user.id)["history"] = []
        save()
        await update.effective_message.reply_text("Чистый лист. Что дальше?")


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await send_screen(update, "modes", modes_kb(user(update.effective_user.id)["mode"]))


async def cmd_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await send_screen(update, "about", back_kb())


async def cmd_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    u = user(update.effective_user.id)
    if ctx.args:
        return await draw(update.effective_message, u, " ".join(ctx.args))
    u["await_image"] = True
    await send_screen(update, "image", back_kb())


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not allowed(update):
        return
    u = user(q.from_user.id)
    d = q.data
    if d == "menu":
        u["await_image"] = False
        await show(q, "menu", menu_kb())
    elif d == "new":
        u["history"] = []
        save()
        await q.message.reply_text("Чистый лист. Что дальше?")
    elif d == "modes":
        await show(q, "modes", modes_kb(u["mode"]))
    elif d.startswith("mode:"):
        u["mode"] = d.split(":", 1)[1]
        u["history"] = []
        save()
        await show(q, "modes", modes_kb(u["mode"]))
    elif d == "image":
        u["await_image"] = True
        await show(q, "image", back_kb())
    elif d in ("help", "about"):
        await show(q, d, back_kb())
    elif d == "img:again":
        if u["last_image"]:
            await draw(q.message, u, u["last_image"])
    elif d.startswith("re:"):
        await regenerate(q.message, u, d.split(":", 1)[1])


# ---------- картинки ----------
async def draw(msg, u, prompt):
    u["last_image"] = prompt
    await msg.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as http:
            r = await http.get(
                "https://image.pollinations.ai/prompt/" + quote(prompt),
                params={"model": IMAGE_MODEL, "width": 1280, "height": 720, "nologo": "true", "seed": random.randint(1, 10**8)},
            )
        if r.status_code == 429:
            return await msg.reply_text("Бесплатный генератор позволяет один запрос раз в 15 секунд. Подожди немного и повтори.")
        r.raise_for_status()
        await msg.reply_photo(io.BytesIO(r.content), caption=prompt[:200], reply_markup=image_kb())
    except Exception:
        log.exception("image failed")
        await msg.reply_text("Картинка не получилась. Бесплатный сервис иногда перегружен, попробуй ещё раз через минуту.")


# ---------- чат ----------
async def safe_edit(msg, text, final=False, kb=None):
    text = text[:4000] or "..."
    try:
        if final:
            try:
                await msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)
                return
            except BadRequest:
                pass
        await msg.edit_text(text, reply_markup=kb)
    except BadRequest:
        pass


async def respond(msg, u, hint=None):
    # убираем кнопки у предыдущего ответа
    prev = u.get("last_kb_msg")
    if prev:
        try:
            await msg.get_bot().edit_message_reply_markup(chat_id=prev[0], message_id=prev[1], reply_markup=None)
        except Exception:
            pass
    system = MODES[u["mode"]][1] + (f"\n\nДополнительное указание для этого ответа: {hint}" if hint else "")
    messages = [{"role": "system", "content": system}] + u["history"]
    await msg.chat.send_action(ChatAction.TYPING)
    out = await msg.reply_text("Думаю...")
    full, last_edit, last_len = "", 0.0, 0
    loop = asyncio.get_running_loop()
    try:
        stream = await client.chat.completions.create(model=LLM_MODEL, messages=messages, stream=True)
        async for chunk in stream:
            if not chunk.choices:
                continue
            full += chunk.choices[0].delta.content or ""
            now = loop.time()
            if now - last_edit > 1.2 and len(full) - last_len > 25:
                await safe_edit(out, full + " |")
                last_edit, last_len = now, len(full)
        if not full:
            full = "Пустой ответ. Переформулируй, попробуем ещё раз."
        await safe_edit(out, full, final=True, kb=answer_kb())
        u["history"].append({"role": "assistant", "content": full})
        u["last_kb_msg"] = (out.chat_id, out.message_id)
        save()
    except Exception:
        log.exception("chat failed")
        await safe_edit(out, "Сбой запроса к модели. Возможно, достигнут бесплатный лимит, подожди минуту. Или проверь LLM_API_KEY и LLM_MODEL.")


async def regenerate(msg, u, kind):
    # убираем последний ответ ассистента и просим сгенерировать заново
    if u["history"] and u["history"][-1]["role"] == "assistant":
        u["history"].pop()
    if not u["history"]:
        return
    hints = {
        "short": "Ответь заметно короче: суть в 2-4 предложениях.",
        "long": "Ответь подробнее и глубже: с примерами, нюансами и выводом.",
        "again": "Дай другой, свежий вариант ответа.",
    }
    await respond(msg, u, hints.get(kind))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    msg = update.effective_message
    u = user(update.effective_user.id)
    if u["await_image"]:
        u["await_image"] = False
        return await draw(msg, u, msg.text)
    u["history"].append({"role": "user", "content": msg.text})
    u["history"] = u["history"][-HISTORY_LIMIT:]
    await respond(msg, u)


# ---------- служебное ----------
class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def start_ping():
    port = int(os.getenv("PORT", "0"))
    if port:
        threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), Ping).serve_forever(), daemon=True).start()


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("menu", "Главное меню"),
        BotCommand("new", "Новый чат"),
        BotCommand("mode", "Выбрать характер"),
        BotCommand("image", "Нарисовать картинку"),
        BotCommand("about", "О Vanta"),
    ])


def main():
    load()
    start_ping()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("image", cmd_image))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
