import os
import asyncio
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, MessageNotModifiedError, CodeExpiredError, PhoneCodeInvalidError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaVideo
import nest_asyncio
import tempfile
import os.path

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# ========== КЛИЕНТЫ ==========
bot = TelegramClient('bot_session', API_ID, API_HASH)
user_client = None

# ========== СОСТОЯНИЯ ==========
waiting_for_target = False
target_id = None
waiting_for_phone = False
phone_number = None
waiting_for_code = False
code_hash = None
waiting_for_password = False
temp_password_phone = None
message_cache = {}
current_animation_msg = None

# ========== ФУНКЦИЯ АНИМАЦИИ ==========
async def show_loading_animation(event, text="⏳ Обработка"):
    """Показывает анимацию со звёздочкой"""
    global current_animation_msg
    
    frames = ["⭐", "🌟", "✨", "💫"]
    msg = await event.reply(f"{frames[0]} {text}...")
    current_animation_msg = msg
    
    try:
        for i in range(10):
            for frame in frames:
                new_text = f"{frame} {text}..."
                if msg.text != new_text:
                    await msg.edit(new_text)
                await asyncio.sleep(0.3)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        logger.error(f"Ошибка анимации: {e}")
    
    return msg

# ========== СОХРАНЕНИЕ МЕДИА ==========
async def download_expiring_media(event):
    """Скачивает истекающее медиа и сохраняет во временный файл"""
    try:
        # Создаём временную директорию, если её нет
        os.makedirs("temp_media", exist_ok=True)
        
        # Генерируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if event.message.photo:
            # Скачиваем фото
            filename = f"temp_media/photo_{timestamp}.jpg"
            path = await event.message.download_media(file=filename)
            return path, "photo"
            
        elif event.message.video:
            # Скачиваем видео
            filename = f"temp_media/video_{timestamp}.mp4"
            path = await event.message.download_media(file=filename)
            return path, "video"
            
        elif event.message.video_note:
            # Скачиваем кружок
            filename = f"temp_media/video_note_{timestamp}.mp4"
            path = await event.message.download_media(file=filename)
            return path, "video_note"
            
        elif event.message.document:
            # Скачиваем документ
            filename = f"temp_media/doc_{timestamp}.bin"
            path = await event.message.download_media(file=filename)
            return path, "document"
            
    except Exception as e:
        logger.error(f"Ошибка скачивания медиа: {e}")
        return None, None
    
    return None, None

# ========== ОБРАБОТЧИКИ ==========

@bot.on(events.NewMessage)
async def handler(event):
    global waiting_for_target, target_id, waiting_for_phone, phone_number
    global waiting_for_code, code_hash, waiting_for_password, temp_password_phone
    global user_client
    
    user_id = event.sender_id
    text = event.message.text.strip() if event.message.text else ""

    # === 1. ЕСЛИ ЖДЁМ ID ПОЛУЧАТЕЛЯ ===
    if waiting_for_target:
        try:
            anim = await show_loading_animation(event, "🔍 Поиск пользователя")
            target = await bot.get_entity(text)
            target_id = target.id
            waiting_for_target = False
            
            target_name = getattr(target, 'first_name', 'пользователь')
            if hasattr(target, 'username') and target.username:
                target_name += f" (@{target.username})"
            
            new_text = (
                f"✅ **ID получателя сохранён!**\n\n"
                f"📬 Все уведомления будут отправляться:\n"
                f"👤 {target_name} (ID: {target_id})\n\n"
                f"📞 **Теперь отправь мне свой номер телефона** в формате:\n"
                f"`+79001234567`"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            waiting_for_phone = True
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз (ID или @username):")
        return

    # === 2. ЕСЛИ ЖДЁМ НОМЕР ТЕЛЕФОНА ===
    if waiting_for_phone:
        phone_number = text
        waiting_for_phone = False
        waiting_for_code = True
        
        anim = await show_loading_animation(event, "📨 Отправка кода")
        
        try:
            user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                sent_code = await user_client.send_code_request(phone_number)
                code_hash = sent_code.phone_code_hash
                
                new_text = (
                    f"✅ **Код отправлен!**\n\n"
                    f"📨 Код подтверждения отправлен в Telegram.\n"
                    f"⏳ **Ожидание кода...** (до 2 минут)\n"
                    f"✍️ Отправь мне код цифрами:"
                )
            else:
                me = await user_client.get_me()
                new_text = (
                    f"✅ **Уже авторизован!**\n\n"
                    f"👤 Аккаунт: @{me.username}\n"
                    f"🔍 Начинаю мониторинг..."
                )
                waiting_for_code = False
                asyncio.create_task(monitor_user_chats(user_id))
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
        except Exception as e:
            error_text = f"❌ Ошибка: {e}\nПопробуй ещё раз /start"
            if anim.text != error_text:
                await anim.edit(error_text)
            waiting_for_code = False
        return

    # === 3. ЕСЛИ ЖДЁМ КОД ===
    if waiting_for_code:
        code = text
        
        try:
            anim = await show_loading_animation(event, "🔑 Проверка кода")
            
            if not user_client:
                user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
                await user_client.connect()
            
            await user_client.sign_in(phone_number, code, phone_code_hash=code_hash)
            
            me = await user_client.get_me()
            new_text = (
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone_number}\n\n"
                f"🔍 **Начинаю мониторинг всех чатов...**\n"
                f"• Истекающие фото/видео будут сохраняться"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
            waiting_for_code = False
            asyncio.create_task(monitor_user_chats(user_id))
            
        except SessionPasswordNeededError:
            waiting_for_password = True
            temp_password_phone = phone_number
            waiting_for_code = False
            new_text = "🔐 **Требуется двухфакторный пароль.**\n\nВведи свой пароль:"
            if anim.text != new_text:
                await anim.edit(new_text)
                
        except PhoneCodeInvalidError:
            new_text = "❌ **Неправильный код!**\n\nПопробуй ещё раз:"
            if anim.text != new_text:
                await anim.edit(new_text)
                
        except CodeExpiredError:
            new_text = "⌛ **Код истёк!**\n\n📨 Отправляю новый код..."
            if anim.text != new_text:
                await anim.edit(new_text)
            
            sent_code = await user_client.send_code_request(phone_number)
            code_hash = sent_code.phone_code_hash
            await event.reply("✅ Новый код отправлен! Введи его:")
                
        except Exception as e:
            error_text = f"❌ Ошибка входа: {e}"
            if anim.text != error_text:
                await anim.edit(error_text)
            waiting_for_code = False
        return

    # === 4. ЕСЛИ ЖДЁМ 2FA ПАРОЛЬ ===
    if waiting_for_password:
        password = text
        phone = temp_password_phone
        
        try:
            anim = await show_loading_animation(event, "🔐 Проверка пароля")
            await user_client.sign_in(password=password)
            
            me = await user_client.get_me()
            new_text = (
                f"✅ **Успешный вход с 2FA!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 **Начинаю мониторинг всех чатов...**"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
            waiting_for_password = False
            temp_password_phone = None
            asyncio.create_task(monitor_user_chats(user_id))
            
        except Exception as e:
            error_text = f"❌ Ошибка: {e}\nПопробуй ещё раз:"
            if anim.text != error_text:
                await anim.edit(error_text)
        return

    # === 5. ОСНОВНЫЕ КОМАНДЫ ===
    if text == "/start":
        waiting_for_target = True
        await event.reply(
            "👋 **Бот для мониторинга чатов**\n\n"
            "📝 **Введите ID или username пользователя**,\n"
            "которому будут приходить уведомления.\n\n"
            "Примеры:\n"
            "• ID: `7396285844`\n"
            "• Username: `@durov`\n\n"
            "📸 **Фишки:**\n"
            "• Истекающие фото/видео сохраняются\n"
            "• Пересылаются как обычные\n"
            "• Удалённые сообщения ловятся"
        )
    
    elif text == "/stats":
        target_info = f"ID: {target_id}" if target_id else "не задан"
        await event.reply(
            f"📊 **Статистика**\n\n"
            f"📦 Кэш сообщений: {len(message_cache)}\n"
            f"📬 Получатель: {target_info}\n"
            f"👤 Аккаунт: {'авторизован' if user_client else 'не авторизован'}"
        )
    
    elif text == "/reset":
        waiting_for_target = True
        target_id = None
        waiting_for_phone = False
        phone_number = None
        waiting_for_code = False
        code_hash = None
        waiting_for_password = False
        if user_client:
            await user_client.disconnect()
            user_client = None
        await event.reply("🔄 **Настройки сброшены.**\nВведи ID получателя:")

# ========== МОНИТОРИНГ ЧАТОВ ==========

async def monitor_user_chats(user_id):
    """Мониторит все чаты от имени пользователя"""
    global user_client, target_id, message_cache
    
    if not user_client or not target_id:
        logger.error("Нет клиента или получателя")
        return
    
    logger.info(f"🔍 Начинаю мониторинг для пользователя {user_id}, уведомления в {target_id}")
    
    # Уведомление о старте
    await bot.send_message(
        target_id,
        "✅ **Мониторинг запущен!**\n\n"
        "📸 **Истекающие фото/видео** будут сохраняться\n"
        "и отправляться как обычные.\n\n"
        "🗑 Удалённые сообщения\n"
        "✏️ Изменённые сообщения"
    )
    
    # ===== ОСНОВНОЙ ОБРАБОТЧИК =====
    @user_client.on(events.NewMessage)
    async def message_handler(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        
        # Проверяем на истекающие медиа
        is_expiring = False
        ttl = None
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            is_expiring = True
            ttl = event.message.ttl_seconds
        
        # Определяем тип контента
        content_type = "text"
        if event.message.photo:
            content_type = "photo"
        elif event.message.video:
            content_type = "video"
        elif event.message.video_note:
            content_type = "video_note"
        elif event.message.voice:
            content_type = "voice"
        elif event.message.document:
            content_type = "document"
        
        # Получаем информацию о чате и отправителе
        try:
            chat = await user_client.get_entity(event.chat_id)
            chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
            sender = await event.get_sender()
            sender_name = getattr(sender, 'first_name', 'Неизвестно')
            if hasattr(sender, 'username') and sender.username:
                sender_name += f" (@{sender.username})"
        except:
            chat_name = "Неизвестный чат"
            sender_name = "Неизвестно"
        
        # ЕСЛИ ЭТО ИСТЕКАЮЩЕЕ МЕДИА — СОХРАНЯЕМ И ПЕРЕСЫЛАЕМ
        if is_expiring and (event.message.photo or event.message.video or event.message.video_note):
            # Скачиваем медиа
            file_path, media_type = await download_expiring_media(event)
            
            if file_path and os.path.exists(file_path):
                # Отправляем как обычное медиа
                caption = (
                    f"📸 **ИСТЕКАЮЩЕЕ СООБЩЕНИЕ (сохранено)**\n\n"
                    f"📌 Чат: {chat_name}\n"
                    f"👤 От: {sender_name}\n"
                    f"⏱ Истекало через: {ttl} сек"
                )
                
                await bot.send_file(target_id, file_path, caption=caption)
                
                # Удаляем временный файл
                try:
                    os.remove(file_path)
                except:
                    pass
                
                # Кэшируем информацию
                message_cache[cache_key] = {
                    'text': f"[Сохранённое {media_type}]",
                    'time': datetime.now().isoformat(),
                    'chat_id': event.chat_id,
                    'sender_id': event.sender_id,
                    'content_type': media_type,
                    'is_expiring': True,
                    'deleted': False,
                    'edited': False,
                    'saved': True
                }
                return
        
        # Кэшируем обычные сообщения
        message_cache[cache_key] = {
            'text': event.message.text or f"[{content_type.upper()}]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'sender_id': event.sender_id,
            'content_type': content_type,
            'is_expiring': is_expiring,
            'ttl': ttl,
            'deleted': False,
            'edited': False
        }
        
        # Ограничение кэша
        if len(message_cache) > 5000:
            keys = list(message_cache.keys())[:1000]
            for k in keys:
                del message_cache[k]

    # ===== УДАЛЁННЫЕ СООБЩЕНИЯ =====
    @user_client.on(events.MessageDeleted)
    async def delete_handler(event):
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                
                # Не уведомляем об удалении, если это было истекающее и мы его сохранили
                if msg.get('saved'):
                    continue
                
                try:
                    chat = await user_client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                    
                    await bot.send_message(
                        target_id,
                        f"🗑 **УДАЛЕНО**\n\n"
                        f"📌 Чат: {chat_name}\n"
                        f"👤 От: {msg['sender_id']}\n"
                        f"📝 {msg['text'][:300]}\n"
                        f"⏰ Было: {msg['time'][:19]}"
                    )
                except:
                    pass

    # ===== ИЗМЕНЁННЫЕ СООБЩЕНИЯ =====
    @user_client.on(events.MessageEdited)
    async def edit_handler(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old = message_cache[cache_key]['text']
            new = event.message.text
            if old != new and old != "[Сохранённое photo]" and old != "[Сохранённое video]":
                try:
                    chat = await user_client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                    
                    await bot.send_message(
                        target_id,
                        f"✏️ **ИЗМЕНЕНО**\n\n"
                        f"📌 Чат: {chat_name}\n"
                        f"👤 От: {message_cache[cache_key]['sender_id']}\n"
                        f"📝 Было: {old[:200]}\n"
                        f"📝 Стало: {new[:200]}"
                    )
                    message_cache[cache_key]['text'] = new
                except:
                    pass

    await user_client.run_until_disconnected()

# ========== ЗАПУСК ==========

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info("👑 Ожидание ввода ID получателя...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())