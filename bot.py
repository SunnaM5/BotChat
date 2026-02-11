import os
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
import json
from pathlib import Path
import re

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# ВАЖНО: сюда пишите без @ (например: dunya_jewellryad)
MANAGER_USERNAME = (os.getenv("MANAGER_USERNAME", "") or "").strip().lstrip("@")
MANAGER_CHANNEL = (os.getenv("MANAGER_CHANNEL", "dunya_jewellry") or "").strip()
MANAGER_PHONE = (os.getenv("MANAGER_PHONE", "") or "").strip()  # опционально

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    raise SystemExit("Заполните BOT_TOKEN и ADMIN_CHAT_ID в .env")

if not MANAGER_USERNAME:
    raise SystemExit("Заполните MANAGER_USERNAME в .env (без @)")

# ====== ТОВАРЫ ======
@dataclass
class Product:
    id: str
    name: str
    price: int
    desc: str
    photo_url: str

DATA_FILE = Path(__file__).with_name("products.json")

def load_products() -> Dict[str, Product]:
    if not DATA_FILE.exists():
        raise SystemExit("Нет файла products.json рядом с bot.py")
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    out: Dict[str, Product] = {}
    for item in raw:
        p = Product(
            id=item["id"],
            name=item["name"],
            price=int(item["price"]),
            desc=item.get("desc", ""),
            photo_url=item.get("photo_url", ""),
        )
        out[p.id] = p
    return out

PRODUCTS: Dict[str, Product] = load_products()
SIZES = [15, 16, 17, 18, 19]

# ====== ПАМЯТЬ ======
cart: Dict[int, List[dict]] = {}
checkout_state: Dict[int, dict] = {}  # {uid: {"step":..., "data":..., "selected_sizes":...}}

# ====== УТИЛИТЫ ======
def normalize_phone(raw: str) -> Optional[str]:
    """
    Приводит телефон к виду +998901234567
    Возвращает None, если мусор.
    """
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"[^\d+]", "", s)

    if s.startswith("998"):
        s = "+" + s

    digits = re.sub(r"\D", "", s)
    if digits.startswith("998") and len(digits) == 12:
        return "+" + digits

    if re.fullmatch(r"\+998\d{9}", s):
        return s

    if s.startswith("+") and len(re.sub(r"\D", "", s)) >= 7:
        return s

    return None

# ====== КЛАВИАТУРЫ ======
def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🛍 Каталог")
    kb.button(text="🧺 Корзина")
    kb.button(text="💬 Связаться")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)

def catalog_kb():
    kb = InlineKeyboardBuilder()
    for p in PRODUCTS.values():
        kb.button(
            text=f"{p.name} — {p.price:,} сум".replace(",", " "),
            callback_data=f"p:{p.id}",
        )
    kb.adjust(1)
    return kb.as_markup()

def product_kb(product_id: str):
    kb = InlineKeyboardBuilder()
    for s in SIZES:
        kb.button(text=f"Размер {s}", callback_data=f"s:{product_id}:{s}")
    kb.adjust(3)
    kb.row()
    kb.button(text="🧺 В корзину", callback_data=f"add:{product_id}")
    kb.button(text="⬅️ Назад", callback_data="back:catalog")
    kb.adjust(2)
    return kb.as_markup()

def cart_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    items = cart.get(user_id, [])
    for i, _it in enumerate(items):
        kb.button(text=f"➕ {i+1}", callback_data=f"inc:{i}")
        kb.button(text=f"➖ {i+1}", callback_data=f"dec:{i}")
        kb.button(text=f"🗑 {i+1}", callback_data=f"del:{i}")
        kb.adjust(3)

    if items:
        kb.row()
        kb.button(text="✅ Оформить заказ", callback_data="checkout:start")
        kb.button(text="🧹 Очистить", callback_data="cart:clear")
        kb.adjust(2)
    return kb.as_markup()

def contact_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Написать менеджеру", url=f"https://t.me/{MANAGER_USERNAME}")
    if MANAGER_CHANNEL:
        kb.button(text="📣 Канал", url=f"https://t.me/{MANAGER_CHANNEL.lstrip('@')}")
    kb.adjust(1)
    return kb.as_markup()

def after_order_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Написать менеджеру", url=f"https://t.me/{MANAGER_USERNAME}")
    kb.button(text="🛍 В каталог", callback_data="go:catalog")
    kb.adjust(1)
    return kb.as_markup()

def admin_contact_kb(username: Optional[str]):
    if not username:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Написать клиенту", url=f"https://t.me/{username}")
    return kb.as_markup()

# ====== КОРЗИНА ======
def format_cart(user_id: int) -> str:
    items = cart.get(user_id, [])
    if not items:
        return "Корзина пустая."
    total = 0
    lines = ["🧺 *Ваша корзина:*"]
    for idx, it in enumerate(items, 1):
        p = PRODUCTS[it["product_id"]]
        sum_ = p.price * it["qty"]
        total += sum_
        lines.append(
            f"{idx}) {p.name}\n   Размер: {it['size']} | Кол-во: {it['qty']} | {sum_:,} сум".replace(",", " ")
        )
    lines.append(f"\n*Итого:* {total:,} сум".replace(",", " "))
    return "\n".join(lines)

def get_selected_size(user_id: int, product_id: str) -> int:
    st = checkout_state.get(user_id, {})
    selected = st.get("selected_sizes", {})
    return int(selected.get(product_id, 17))

def set_selected_size(user_id: int, product_id: str, size: int):
    st = checkout_state.setdefault(user_id, {})
    st.setdefault("selected_sizes", {})
    st["selected_sizes"][product_id] = size

def add_to_cart(user_id: int, product_id: str):
    size = get_selected_size(user_id, product_id)
    items = cart.setdefault(user_id, [])
    for it in items:
        if it["product_id"] == product_id and it["size"] == size:
            it["qty"] += 1
            return
    items.append({"product_id": product_id, "size": size, "qty": 1})

# ====== BOT ======
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "Добро пожаловать в *Dunya Jewellery* 🩶\nВыберите действие:",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown",
    )

@dp.message(Command("cancel"))
async def cancel(m: Message):
    uid = m.from_user.id
    if uid in checkout_state:
        checkout_state.pop(uid, None)
        await m.answer("❌ Оформление заказа отменено.", reply_markup=main_menu_kb())
    else:
        await m.answer("Сейчас нет активного оформления.", reply_markup=main_menu_kb())

@dp.message(F.text == "🛍 Каталог")
async def show_catalog(m: Message):
    await m.answer("🛍 *Каталог:*", reply_markup=catalog_kb(), parse_mode="Markdown")

@dp.message(F.text == "💬 Связаться")
async def contact(m: Message):
    text = f"💬 Менеджер: @{MANAGER_USERNAME}"
    if MANAGER_PHONE:
        text += f"\n📞 Телефон: {MANAGER_PHONE}"
    await m.answer(text, reply_markup=contact_kb(), disable_web_page_preview=True)

@dp.message(F.text == "🧺 Корзина")
async def show_cart(m: Message):
    text = format_cart(m.from_user.id)
    await m.answer(text, reply_markup=cart_kb(m.from_user.id), parse_mode="Markdown")

@dp.callback_query(F.data == "go:catalog")
async def go_catalog(c: CallbackQuery):
    await c.message.answer("🛍 *Каталог:*", reply_markup=catalog_kb(), parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data == "back:catalog")
async def back_catalog(c: CallbackQuery):
    await c.message.edit_text("🛍 *Каталог:*", reply_markup=catalog_kb(), parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data.startswith("p:"))
async def open_product(c: CallbackQuery):
    pid = c.data.split(":", 1)[1]
    p = PRODUCTS[pid]
    await c.message.delete()
    await bot.send_photo(
        chat_id=c.from_user.id,
        photo=p.photo_url,
        caption=f"*{p.name}*\n{p.desc}\n\nЦена: *{p.price:,} сум*".replace(",", " "),
        reply_markup=product_kb(pid),
        parse_mode="Markdown",
    )
    await c.answer()

@dp.callback_query(F.data.startswith("s:"))
async def pick_size(c: CallbackQuery):
    _, pid, size = c.data.split(":")
    set_selected_size(c.from_user.id, pid, int(size))
    await c.answer(f"Размер выбран: {size}")

@dp.callback_query(F.data.startswith("add:"))
async def add_item(c: CallbackQuery):
    pid = c.data.split(":", 1)[1]
    add_to_cart(c.from_user.id, pid)
    await c.answer("Добавлено в корзину ✅")

@dp.callback_query(F.data == "cart:clear")
async def clear_cart(c: CallbackQuery):
    cart[c.from_user.id] = []
    await c.message.edit_text("Корзина очищена.", reply_markup=cart_kb(c.from_user.id))
    await c.answer()

@dp.callback_query(F.data.startswith("inc:"))
async def inc_item(c: CallbackQuery):
    idx = int(c.data.split(":")[1])
    items = cart.get(c.from_user.id, [])
    if 0 <= idx < len(items):
        items[idx]["qty"] += 1
    await c.message.edit_text(format_cart(c.from_user.id), reply_markup=cart_kb(c.from_user.id), parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data.startswith("dec:"))
async def dec_item(c: CallbackQuery):
    idx = int(c.data.split(":")[1])
    items = cart.get(c.from_user.id, [])
    if 0 <= idx < len(items):
        items[idx]["qty"] -= 1
        if items[idx]["qty"] <= 0:
            items.pop(idx)
    await c.message.edit_text(format_cart(c.from_user.id), reply_markup=cart_kb(c.from_user.id), parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data.startswith("del:"))
async def del_item(c: CallbackQuery):
    idx = int(c.data.split(":")[1])
    items = cart.get(c.from_user.id, [])
    if 0 <= idx < len(items):
        items.pop(idx)
    await c.message.edit_text(format_cart(c.from_user.id), reply_markup=cart_kb(c.from_user.id), parse_mode="Markdown")
    await c.answer()

# ====== ОФОРМЛЕНИЕ ======
@dp.callback_query(F.data == "checkout:start")
async def checkout_start(c: CallbackQuery):
    uid = c.from_user.id
    if not cart.get(uid):
        await c.answer("Корзина пустая.")
        return

    prev = checkout_state.get(uid, {})
    selected_sizes = prev.get("selected_sizes", {})
    checkout_state[uid] = {"step": "name", "data": {}, "selected_sizes": selected_sizes}

    await bot.send_message(uid, "Введите *имя*:\n(для отмены: /cancel)", parse_mode="Markdown")
    await c.answer()

@dp.message()
async def checkout_flow(m: Message):
    uid = m.from_user.id
    st = checkout_state.get(uid)
    if not st:
        return

    text = (m.text or "").strip()
    if not text:
        await m.answer("Пусто. Введите значение ещё раз.")
        return

    if text in ("🛍 Каталог", "🧺 Корзина", "💬 Связаться"):
        step = st["step"]
        prompt = {
            "name": "Введите *имя*:\n(для отмены: /cancel)",
            "phone": "Введите *телефон* (например +998901234567):\n(для отмены: /cancel)",
            "address": "Введите *адрес доставки*:\n(для отмены: /cancel)",
            "comment": "Комментарий (если нет — напишите `-`):\n(для отмены: /cancel)",
        }[step]
        await m.answer(prompt, parse_mode="Markdown")
        return

    step = st["step"]
    data = st["data"]

    if step == "name":
        data["name"] = text
        st["step"] = "phone"
        await m.answer("Введите *телефон* (например +998901234567):\n(для отмены: /cancel)", parse_mode="Markdown")
        return

    if step == "phone":
        normalized = normalize_phone(text)
        if not normalized:
            await m.answer("Телефон неверный. Пример: +998901234567\nВведите телефон ещё раз:")
            return
        data["phone"] = normalized
        st["step"] = "address"
        await m.answer("Введите *адрес доставки*:\n(для отмены: /cancel)", parse_mode="Markdown")
        return

    if step == "address":
        data["address"] = text
        st["step"] = "comment"
        await m.answer("Комментарий (если нет — напишите `-`):\n(для отмены: /cancel)", parse_mode="Markdown")
        return

    if step == "comment":
        data["comment"] = text

        username = m.from_user.username
        full_name = (m.from_user.full_name or "").strip()
        phone = data.get("phone", "")
        uid_str = str(uid)
        link = f"https://t.me/{username}" if username else "нет (у клиента нет username)"

        msg = "\n".join([
            "🧾 *Новый заказ Dunya Jewellery*",
            f"Покупатель: {data['name']}",
            f"Телефон: {phone}",
            f"Адрес: {data['address']}",
            f"Комментарий: {data['comment']}",
            "",
            "👤 *Контакт клиента:*",
            f"Имя TG: {full_name}" if full_name else "Имя TG: -",
            f"ID: `{uid_str}`",
            f"Username: @{username}" if username else "Username: (нет)",
            f"Ссылка: {link}",
            "",
            format_cart(uid),
        ])

        await bot.send_message(
            ADMIN_CHAT_ID,
            msg,
            parse_mode="Markdown",
            reply_markup=admin_contact_kb(username),
            disable_web_page_preview=True,
        )

        # контакт админу — чтобы можно было звонить/писать по телефону
        try:
            await bot.send_contact(
                chat_id=ADMIN_CHAT_ID,
                phone_number=phone,
                first_name=(data["name"][:64] if data["name"] else "Клиент"),
                last_name="",
            )
        except Exception:
            pass

        # клиенту: сразу кнопка "Написать менеджеру"
        await m.answer(
            "✅ Заказ принят! Чтобы уточнить детали — нажмите кнопку и напишите менеджеру.",
            reply_markup=after_order_kb(),
        )

        cart[uid] = []
        checkout_state.pop(uid, None)
        return

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
