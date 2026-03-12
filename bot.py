import asyncio
from telethon import TelegramClient, events
from telethon.tl.custom import Button
import os
import logging
from datetime import datetime

# ========== НАСТРОЙКИ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID', 35494524))
API_HASH = os.environ.get('API_HASH', '0e465149f428a082cc47a7c7d016c179')
ACCESS_CODE = "8532"
AUTHORIZED_USERS = []

# ========== СОСТОЯНИЕ ==========
waiting_for_code = {}
user_sessions = {}
deleted_log = []

# ========== СОЗДАНИЕ БОТА ==========
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ========== КОМАНДЫ ==========
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Старт бота - запрос кода"""
    user_id = event.sender_id
    
    if user_id in AUTHORIZED_USERS:
        await show_main_menu(event)
    else:
        await event.reply("🔐 **Введите код доступа:**")
        waiting_for_code[user_id] = True

@bot.on(events.NewMessage)
async def handler(event):
    """Основной обработчик"""
    user_id = event.sender_id
    text = event.message.message.strip()
    
    # Проверка кода
    if user_id in waiting_for_code:
        if text == ACCESS_CODE:
            AUTHORIZED_USERS.append(user_id)
            del waiting_for_code[user_id]
            await event.reply("✅ **Код верный! Доступ разрешён.**")
            await show_main_menu(event)
        else:
            await event.reply("❌ **Неверный код. Попробуйте снова:**")
        return
    
    # Для авторизованных
    if user_id in AUTHORIZED_USERS:
        await handle_authorized(event, text)

async def show_main_menu(event):
    """Главное меню"""
    menu = """
📱 **МЕНЕДЖЕР АККАУНТА** 🤖

**Главное меню:**

1️⃣ **Авторизация номера**
   • Поделиться контактом
   • Получить код
   • Подтвердить вход

2️⃣ **Удалённые сообщения**
   • Просмотр удалённых
   • Переслать в чат

3️⃣ **Авто-ответы**
   • "я с рынка" → "Отправляй подарок"

4️⃣ **Активные сессии**
   • Кто онлайн
   • Завершить сессии

5️⃣ **Настройки**
   • Сменить код
   • Очистить историю

**Отправьте номер пункта:**
"""
    
    buttons = [
        [Button.text("📱 Авторизация", resize=True)],
        [Button.text("🗑 Удалённые")],
        [Button.text("🤖 Автоответ")],
        [Button.text("🔐 Сессии")],
        [Button.text("⚙️ Настройки")]
    ]
    
    await event.reply(menu, buttons=buttons)

async def handle_authorized(event, text):
    """Обработка действий"""
    
    if "авторизация" in text.lower() or text == "1":
        await auth_menu(event)
    
    elif "удалённые" in text.lower() or text == "2":
        await deleted_menu(event)
    
    elif "автоответ" in text.lower() or text == "3":
        await auto_menu(event)
    
    elif "сессии" in text.lower() or text == "4":
        await sessions_menu(event)
    
    elif "настройки" in text.lower() or text == "5":
        await settings_menu(event)
    
    # Автоответ на "я с рынка"
    elif "я с рынка" in text.lower():
        await event.reply("Отправляй подарок! 🎁")

async def auth_menu(event):
    """Меню авторизации"""
    menu = """
📱 **АВТОРИЗАЦИЯ НОМЕРА**

1️⃣ **Поделиться контактом**
   Нажмите кнопку ниже

2️⃣ **Ввести код**
   После отправки номера
   Telegram пришлёт SMS

3️⃣ **Проверить статус**

👇 **Нажмите кнопку:**
"""
    await event.reply(menu, buttons=[
        [Button.request_contact("📱 Отправить контакт")],
        [Button.text("🔙 Назад")]
    ])

async def deleted_menu(event):
    """Меню удалённых сообщений"""
    menu = f"""
🗑 **УДАЛЁННЫЕ СООБЩЕНИЯ**

📊 **Сохранено:** {len(deleted_log)} сообщений

1️⃣ Показать последние
2️⃣ Переслать сюда
3️⃣ Очистить историю
"""
    await event.reply(menu)

async def auto_menu(event):
    """Меню автоответов"""
    menu = """
🤖 **АВТООТВЕТЫ**

**Активно:**
✅ "я с рынка" → "Отправляй подарок 🎁"

1️⃣ Добавить правило
2️⃣ Удалить правило
3️⃣ Список правил
"""
    await event.reply(menu)

async def sessions_menu(event):
    """Меню сессий"""
    menu = """
🔐 **АКТИВНЫЕ СЕССИИ**

1️⃣ Показать все
2️⃣ Завершить все
3️⃣ Завершить кроме текущей
"""
    await event.reply(menu)

async def settings_menu(event):
    """Меню настроек"""
    menu = f"""
⚙️ **НАСТРОЙКИ**

🔑 Текущий код: {ACCESS_CODE}

1️⃣ Сменить код
2️⃣ Очистить историю
3️⃣ Экспорт данных
"""
    await event.reply(menu)

# ===== ОБРАБОТЧИК КОНТАКТОВ =====
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def handle_contact(event):
    """Получение контакта"""
    contact = event.message.contact
    await event.reply(f"""
✅ **Контакт получен!**

📱 Номер: {contact.phone_number}
👤 Имя: {contact.first_name}

Теперь введите код из Telegram, который придёт на этот номер.
""")

# ===== ЗАПУСК =====
async def main():
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info(f"🔐 Код доступа: {ACCESS_CODE}")
    logger.info(f"👑 Разрешённые пользователи: {AUTHORIZED_USERS}")
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
