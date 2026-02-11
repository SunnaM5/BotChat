import os
import asyncio
from dataclasses import dataclass
from typing import Dict, List
import json
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    raise SystemExit("Заполните BOT_TOKEN и ADMIN_CHAT_ID в .env")

# ====== ТОВАРЫ (быстро: храним прямо в коде) ======
@dataclass
class Product:
    id: str
    name: str
    price: int
    desc: str
    photo_url: str  # можно заменить на file_id позже

DATA_FILE = Path(__file__).with_name("products.json")

def load_products() -> Dict[str, Product]:
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

# ====== ПАМЯТЬ (быстро, без базы) ======
cart: Dict[int, List[dict]] = {}
checkout_state: Dict[int, dict] = {}

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
        kb.button(text=f"{p.name} — {p.price:,} сум".replace(",", " "), callback_data=f"p:{p.id}")
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
    for i, it in enumerate(items):
        p = PRODUCTS[it["product_id"]]
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
        lines.append(f"{idx}) {p.name}\n   Размер: {it['size']} | Кол-во: {it['qty']} | {sum_:,} сум".replace(",", " "))
    lines.append(f"\n*Итого:* {total:,} сум".replace(",", " "))
    return "\n".join(lines)

def get_selected_size(user_id: int, product_id: str) -> int:
    state = checkout_state.get(user_id, {})
    selected = state.get("selected_sizes", {})
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

@dp.message(F.text == "🛍 Каталог")
async def show_catalog(m: Message):
    await m.answer("🛍 *Каталог колец:*", reply_markup=catalog_kb(), parse_mode="Markdown")

@dp.message(F.text == "💬 Связаться")
async def contact(m: Message):
    # УБРАЛ @ из ссылки
    await m.answer("💬 Напишите сюда: @dunya_jewellryad\nКанал: https://t.me/dunya_jewellry")

@dp.message(F.text == "🧺 Корзина")
async def show_cart(m: Message):
    text = format_cart(m.from_user.id)
    await m.answer(text, reply_markup=cart_kb(m.from_user.id), parse_mode="Markdown")

@dp.callback_query(F.data == "back:catalog")
async def back_catalog(c: CallbackQuery):
    await c.message.edit_text("🛍 *Каталог колец:*", reply_markup=catalog_kb(), parse_mode="Markdown")
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

# ====== Оформление заказа ======
@dp.callback_query(F.data == "checkout:start")
async def checkout_start(c: CallbackQuery):
    if not cart.get(c.from_user.id):
        await c.answer("Корзина пустая.")
        return
    # не трогаем selected_sizes, чтобы выбор размера не ломался
    prev = checkout_state.get(c.from_user.id, {})
    selected_sizes = prev.get("selected_sizes", {})
    checkout_state[c.from_user.id] = {"step": "name", "data": {}, "selected_sizes": selected_sizes}

    await bot.send_message(c.from_user.id, "Введите *имя*:", parse_mode="Markdown")
    await c.answer()

def make_contact_link(uid: int, username: str | None) -> str:
    # Если username есть — лучше https://t.me/username
    # Если нет — tg://user?id=uid (работает в Telegram Desktop)
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={uid}"

@dp.message()
async def checkout_flow(m: Message):
    uid = m.from_user.id
    st = checkout_state.get(uid)
    if not st:
        return

    text = (m.text or "").strip()
    step = st["step"]
    data = st["data"]

    # защита от пустого ввода
    if not text:
        await m.answer("Пусто. Введите значение ещё раз.")
        return

    if step == "name":
        # если юзер случайно нажал "Каталог/Корзина" во время оформления — это мусор
        if text in ("🛍 Каталог", "🧺 Корзина", "💬 Связаться"):
            await m.answer("Сейчас идёт оформление заказа. Введите *имя*:", parse_mode="Markdown")
            return
        data["name"] = text
        st["step"] = "phone"
        await m.answer("Введите *телефон* (например +998901234567):", parse_mode="Markdown")
        return

    if step == "phone":
        data["phone"] = text
        st["step"] = "address"
        await m.answer("Введите *адрес доставки*:", parse_mode="Markdown")
        return

    if step == "address":
        data["address"] = text
        st["step"] = "comment"
        await m.answer("Комментарий (если нет — напишите `-`):", parse_mode="Markdown")
        return

    if step == "comment":
        data["comment"] = text

        username = m.from_user.username
        full_name = (m.from_user.full_name or "").strip()
        link = make_contact_link(uid, username)

        order_text = [
            "🧾 *Новый заказ Dunya Jewellery*",
            f"Покупатель: {data['name']}",
            f"Телефон: {data['phone']}",
            f"Адрес: {data['address']}",
            f"Комментарий: {data['comment']}",
            "",
            "👤 *Контакт клиента:*",
            f"Имя TG: {full_name}" if full_name else "Имя TG: -",
            f"ID: `{uid}`",
            f"Username: @{username}" if username else "Username: (нет)",
            f"Связь: {link}",
            "",
            format_cart(uid),
        ]
        msg = "\n".join(order_text)

        await bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="Markdown")

        # НЕ обещаем "мы свяжемся" — вы сами связываетесь
        await m.answer("✅ Заказ принят! Данные получены.", reply_markup=main_menu_kb())

        cart[uid] = []
        checkout_state.pop(uid, None)
        return

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
