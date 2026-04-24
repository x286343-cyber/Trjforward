import asyncio
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8650069393:AAHcNXjy28HZr2q2S248v-EY4PtW5JdkkLI"
ADMIN_IDS = [8214672871]  # Твой Telegram ID
MAX_ACCOUNTS = 5
# =====================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Хранилище данных
forwarding_tasks = {}   # chat_id -> asyncio.Task
target_groups = {}      # chat_id -> [group_ids]
saved_messages = {}     # chat_id -> message to forward
is_running = {}         # chat_id -> bool

class ForwardStates(StatesGroup):
    waiting_message = State()
    waiting_group = State()

# =================== ГЛАВНОЕ МЕНЮ ===================
def main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Установить сообщение", callback_data="set_message")],
        [InlineKeyboardButton(text="👥 Управление группами", callback_data="manage_groups")],
        [InlineKeyboardButton(text="▶️ Запустить рассылку", callback_data="start_forward")],
        [InlineKeyboardButton(text="⏹ Остановить рассылку", callback_data="stop_forward")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
    ])
    return keyboard

# =================== КОМАНДЫ ===================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У тебя нет доступа.")
        return
    await message.answer(
        "🤖 <b>Панель управления ботом</b>\n\nВыбери действие:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("panel"))
async def cmd_panel(message: types.Message):
    await cmd_start(message)

# =================== CALLBACK ===================
@dp.callback_query(lambda c: c.data == "set_message")
async def cb_set_message(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📩 Перешли мне сообщение которое хочешь рассылать.\n"
        "(Перешли из любого канала/чата)"
    )
    await state.set_state(ForwardStates.waiting_message)
    await callback.answer()

@dp.message(ForwardStates.waiting_message)
async def receive_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    saved_messages[user_id] = message
    await state.clear()
    await message.answer(
        "✅ Сообщение сохранено!\n\n"
        "Теперь укажи группы для рассылки через меню 👇",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "manage_groups")
async def cb_manage_groups(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    groups = target_groups.get(user_id, [])
    
    text = "👥 <b>Группы для рассылки:</b>\n"
    if groups:
        for i, g in enumerate(groups, 1):
            text += f"{i}. <code>{g}</code>\n"
    else:
        text += "Пока нет групп\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить группу", callback_data="add_group")],
        [InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_groups")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_menu")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "add_group")
async def cb_add_group(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📝 Введи ID группы или username.\n\n"
        "Примеры:\n"
        "• <code>-1001234567890</code> (ID группы)\n"
        "• <code>@mygroup</code> (username)\n\n"
        "Бот должен быть участником этой группы!",
        parse_mode="HTML"
    )
    await state.set_state(ForwardStates.waiting_group)
    await callback.answer()

@dp.message(ForwardStates.waiting_group)
async def receive_group(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    group = message.text.strip()
    
    if user_id not in target_groups:
        target_groups[user_id] = []
    
    if group not in target_groups[user_id]:
        target_groups[user_id].append(group)
        await message.answer(f"✅ Группа <code>{group}</code> добавлена!", parse_mode="HTML")
    else:
        await message.answer("⚠️ Эта группа уже в списке.")
    
    await state.clear()
    await message.answer("Выбери действие:", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "clear_groups")
async def cb_clear_groups(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_groups[user_id] = []
    await callback.message.answer("🗑 Список групп очищен.", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "start_forward")
async def cb_start_forward(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in saved_messages:
        await callback.message.answer("❌ Сначала установи сообщение для рассылки!")
        await callback.answer()
        return
    
    if not target_groups.get(user_id):
        await callback.message.answer("❌ Сначала добавь хотя бы одну группу!")
        await callback.answer()
        return
    
    if is_running.get(user_id):
        await callback.message.answer("⚠️ Рассылка уже запущена!")
        await callback.answer()
        return
    
    is_running[user_id] = True
    task = asyncio.create_task(forward_loop(user_id))
    forwarding_tasks[user_id] = task
    
    await callback.message.answer(
        "▶️ <b>Рассылка запущена!</b>\n"
        "Интервал: случайный 1-30 минут",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "stop_forward")
async def cb_stop_forward(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_running.get(user_id):
        await callback.message.answer("⚠️ Рассылка не запущена.")
        await callback.answer()
        return
    
    is_running[user_id] = False
    if user_id in forwarding_tasks:
        forwarding_tasks[user_id].cancel()
    
    await callback.message.answer("⏹ Рассылка остановлена.", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "status")
async def cb_status(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    running = is_running.get(user_id, False)
    msg = saved_messages.get(user_id)
    groups = target_groups.get(user_id, [])
    
    text = (
        f"📊 <b>Статус:</b>\n\n"
        f"🔄 Рассылка: {'✅ Запущена' if running else '⏹ Остановлена'}\n"
        f"📨 Сообщение: {'✅ Установлено' if msg else '❌ Не установлено'}\n"
        f"👥 Групп: {len(groups)}\n"
    )
    if groups:
        text += "\n<b>Группы:</b>\n"
        for g in groups:
            text += f"• <code>{g}</code>\n"
    
    await callback.message.answer(text, parse_mode="HTML", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_menu")
async def cb_back(callback: types.CallbackQuery):
    await callback.message.edit_text("🤖 Панель управления:", reply_markup=main_menu())
    await callback.answer()

# =================== ЦИКЛ РАССЫЛКИ ===================
async def forward_loop(user_id: int):
    while is_running.get(user_id, False):
        msg = saved_messages.get(user_id)
        groups = target_groups.get(user_id, [])
        
        for group in groups:
            if not is_running.get(user_id, False):
                break
            try:
                await bot.forward_message(
                    chat_id=group,
                    from_chat_id=msg.chat.id,
                    message_id=msg.message_id
                )
                await bot.send_message(
                    user_id,
                    f"✅ Переслано в <code>{group}</code>",
                    parse_mode="HTML"
                )
            except Exception as e:
                await bot.send_message(
                    user_id,
                    f"❌ Ошибка в <code>{group}</code>: {str(e)}",
                    parse_mode="HTML"
                )
        
        # Рандомный интервал 1-30 минут
        interval = random.randint(60, 1800)
        mins = interval // 60
        await bot.send_message(
            user_id,
            f"⏳ Следующая отправка через <b>{mins} мин</b>",
            parse_mode="HTML"
        )
        
        await asyncio.sleep(interval)

# =================== ЗАПУСК ===================
async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
