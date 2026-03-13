import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
from telethon.tl.custom import Button
from telethon.tl.types import MessageMediaPhoto, MessageMediaVideo, MessageMediaDocument
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Хранилище сессий и данных
user_sessions = {}  # {user_id: {'phone': '...', 'client': ..., 'step': '...'}}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}  # Кэш сообщений для отслеживания удалений
expiring_cache = {}  # Кэш для истекающих сообщений

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
            "1️⃣ Введи номер телефона\n"
            "2️⃣ Получи код в Telegram\n"
            "3️⃣ Введи код сюда\n\n"
            "📞 **Введи номер:**",
            buttons=[[Button.text("📞 Ввести номер", resize=True)]]
        )
        return

    # === ЗАПРОС НОМЕРА ===
    if text == "📞 Ввести номер":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 **Введи номер в формате:**\n`+79001234567`")
        return

    # === ПОЛУЧЕНИЕ НОМЕРА И ОТПРАВКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        phone = text
        user_sessions[user_id]['phone'] = phone
        user_sessions[user_id]['step'] = 'waiting_code'
        
        await event.reply("🔄 **Отправляю запрос кода...**")
        
        try:
            client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone)
            
            user_sessions[user_id]['client'] = client
            user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
            
            await event.reply(
                "✅ **Код отправлен!**\n\n"
                "📨 Проверь Telegram — там пришёл 5-значный код\n"
                "⏳ Код действителен 2 минуты\n"
                "✍️ **Введи код сюда:**"
            )
            
        except Exception as e:
            await event.reply(f"❌ **Ошибка:** {e}\nПроверь номер и попробуй снова.")
            if user_id in user_sessions:
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
                f"🔍 **Запускаю мониторинг...**"
            )
            
            # Удаляем временные данные
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            # Запускаем мониторинг
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except SessionPasswordNeededError:
            user_sessions[user_id]['step'] = 'waiting_2fa'
            await event.reply("🔐 **Требуется двухфакторный пароль.**\nВведи его:")
            
        except PhoneCodeInvalidError:
            await event.reply("❌ **Неверный код!**\nПопробуй ещё раз:")
            
        except PhoneCodeExpiredError:
            await event.reply("⌛ **Код истёк.** Начни заново.")
            if user_id in user_sessions:
                del user_sessions[user_id]
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
            if user_id in user_sessions:
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
            if user_id in user_sessions:
                del user_sessions[user_id]
            asyncio.create_task(monitor_user_chats(user_id, client))
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    """Мониторит удалённые, изменённые и истекающие сообщения"""
    
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**\n\nОтслеживаю:\n• Удалённые сообщения\n• Изменённые сообщения\n• Истекающие фото/видео")
    
    # ===== КЭШИРОВАНИЕ СООБЩЕНИЙ =====
    @client.on(events.NewMessage)
    async def on_new(event):
        """Кэшируем все новые сообщения"""
        cache_key = f"{event.chat_id}_{event.message.id}"
        
        # Определяем тип сообщения
        msg_type = "text"
        if event.message.photo:
            msg_type = "photo"
        elif event.message.video:
            msg_type = "video"
        elif event.message.video_note:
            msg_type = "video_note"
        elif event.message.voice:
            msg_type = "voice"
        
        # Проверяем, истекающее ли сообщение
        is_expiring = False
        ttl = None
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            is_expiring = True
            ttl = event.message.ttl_seconds
            
            # Уведомление об истекающем сообщении
            await bot.send_message(
                user_id,
                f"⏳ **ИСТЕКАЮЩЕЕ СООБЩЕНИЕ**\n\n"
                f"📌 Чат: {event.chat_id}\n"
                f"📝 Тип: {msg_type}\n"
                f"⏱ Истечёт через: {ttl} сек\n"
                f"🔍 Сохраняю перед удалением..."
            )
            
            # Сохраняем медиа, если это фото или видео
            if event.message.photo or event.message.video or event.message.video_note:
                try:
                    # Скачиваем файл
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"expiring_{timestamp}_{msg_type}.dat"
                    path = await event.message.download_media(file=filename)
                    
                    # Отправляем как обычное сообщение
                    await bot.send_file(
                        user_id,
                        path,
                        caption=f"📸 **Сохранённое истекающее {msg_type}**\nИз чата: {event.chat_id}"
                    )
                    
                    # Удаляем временный файл
                    os.remove(path)
                    
                except Exception as e:
                    await bot.send_message(user_id, f"❌ Ошибка сохранения: {e}")
        
        # Сохраняем в кэш
        message_cache[cache_key] = {
            'text': event.message.text or f"[{msg_type}]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'msg_type': msg_type,
            'is_expiring': is_expiring,
            'ttl': ttl
        }
        
        # Ограничиваем кэш
        if len(message_cache) > 1000:
            keys = list(message_cache.keys())[:200]
            for k in keys:
                del message_cache[k]

    # ===== УДАЛЁННЫЕ СООБЩЕНИЯ =====
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        """Отслеживает удалённые сообщения"""
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                
                # Пропускаем, если это было истекающее (уже сохранили)
                if msg.get('is_expiring'):
                    continue
                
                await bot.send_message(
                    user_id,
                    f"🗑 **УДАЛЕНО**\n\n"
                    f"📌 Чат: {event.chat_id}\n"
                    f"📝 Текст: {msg['text'][:200]}\n"
                    f"⏰ Было: {msg['time'][:19]}"
                )
                
                # Удаляем из кэша
                del message_cache[cache_key]

    # ===== ИЗМЕНЁННЫЕ СООБЩЕНИЯ =====
    @client.on(events.MessageEdited)
    async def on_edit(event):
        """Отслеживает изменённые сообщения"""
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old_text = message_cache[cache_key]['text']
            new_text = event.message.text
            
            if old_text != new_text:
                await bot.send_message(
                    user_id,
                    f"✏️ **ИЗМЕНЕНО**\n\n"
                    f"📌 Чат: {event.chat_id}\n"
                    f"📝 Было: {old_text[:200]}\n"
                    f"📝 Стало: {new_text[:200]}"
                )
                
                # Обновляем кэш
                message_cache[cache_key]['text'] = new_text
                message_cache[cache_key]['time'] = datetime.now().isoformat()

    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info("🔍 Мониторинг: удалённые, изменённые, истекающие")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())