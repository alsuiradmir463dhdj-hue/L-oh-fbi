import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
import nest_asyncio

# Применяем nest_asyncio для стабильной работы
nest_asyncio.apply()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Данные из секретов
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# Хранилища данных
message_cache = {}  # {chat_id_msg_id: data}
user_settings = {}  # {user_id: settings}
notification_targets = {}  # {user_id: target_id} - кому отправлять уведомления
user_states = {}  # {user_id: {'step': 'waiting_target'}}
bot_owner_username = None  # Будет запрошен при запуске

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    'monitor_deleted': True,
    'monitor_edited': True,
    'monitor_expiring': True,
    'notify_photos': True,
    'notify_videos': True,
    'notify_text': True,
    'notify_voice': True,
    'selected_chats': [],  # [] = все чаты
    'ignore_chats': []
}

# Создаем клиента
bot = TelegramClient('bot_session', API_ID, API_HASH)

# ========== ФУНКЦИЯ ЗАПРОСА USERNAME ==========

async def ask_owner_username():
    """Запрашивает username владельца в консоли"""
    print("\n" + "="*50)
    print("🔐 НАСТРОЙКА БОТА")
    print("="*50)
    print("\nВведите свой Telegram username (например: @username):")
    username = input(">>> ").strip()
    
    if not username.startswith('@'):
        username = '@' + username
    
    print(f"\n✅ Username сохранен: {username}")
    print("="*50 + "\n")
    return username

# ========== КОМАНДЫ ==========

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Начало работы - выбор получателя уведомлений"""
    user_id = event.sender_id
    user_name = event.sender.first_name or "Пользователь"
    
    # Сохраняем состояние
    user_states[user_id] = {'step': 'waiting_target'}
    
    # Отправляем приветствие с вопросом
    await event.reply(
        f"👋 **Привет, {user_name}!**\n\n"
        f"🔐 **Настройка получения уведомлений**\n\n"
        f"Куда отправлять уведомления о удалённых/изменённых сообщениях?\n\n"
        f"1️⃣ **Мне в личку** (сюда, в этого бота)\n"
        f"2️⃣ **Владельцу бота** (@{bot_owner_username.replace('@', '')})\n"
        f"3️⃣ **В другой чат** (укажите ID или username)\n\n"
        f"📝 **Ответь цифрой (1, 2 или 3):**",
        buttons=[
            [Button.text("1️⃣ Мне в личку", resize=True)],
            [Button.text(f"2️⃣ Владельцу (@{bot_owner_username.replace('@', '')})")],
            [Button.text("3️⃣ Другой чат")]
        ]
    )
    logger.info(f"Пользователь {user_id} начал настройку")

@bot.on(events.NewMessage)
async def text_handler(event):
    """Обработка текстовых сообщений"""
    user_id = event.sender_id
    text = event.message.text
    
    # Обработка выбора получателя
    if user_id in user_states and user_states[user_id].get('step') == 'waiting_target':
        await handle_target_selection(event, user_id, text)
        return
    
    # Обработка выбора ID чата
    if user_id in user_states and user_states[user_id].get('step') == 'waiting_chat_id':
        await handle_chat_id_input(event, user_id, text)
        return
    
    # Обработка команд меню
    if text == "📋 Настройки":
        await show_settings(event, user_id)
    elif text == "📊 Статистика":
        await show_stats(event, user_id)
    elif text == "🔄 Изменить получателя":
        await change_target(event, user_id)

async def handle_target_selection(event, user_id, text):
    """Обработка выбора получателя уведомлений"""
    
    if text == "1️⃣ Мне в личку" or text == "1":
        # Отправлять самому пользователю
        notification_targets[user_id] = user_id
        await event.reply(
            "✅ **Настройки сохранены!**\n\n"
            "📬 Уведомления будут приходить **сюда**, в этого бота.\n\n"
            "Теперь бот будет отслеживать удалённые и изменённые сообщения.",
            buttons=[[Button.text("📋 Настройки")]]
        )
        del user_states[user_id]
        logger.info(f"Пользователь {user_id} выбрал получателя: себя")
        
        # Отправляем тестовое уведомление
        await event.reply("🔔 **Тестовое уведомление**\nВсё работает!")
        
    elif text == f"2️⃣ Владельцу (@{bot_owner_username.replace('@', '')})" or text == "2":
        # Находим владельца по username
        try:
            owner = await bot.get_entity(bot_owner_username)
            owner_id = owner.id
            notification_targets[user_id] = owner_id
            
            await event.reply(
                f"✅ **Настройки сохранены!**\n\n"
                f"📬 Уведомления будут приходить **владельцу** (@{bot_owner_username.replace('@', '')}).\n\n"
                f"Теперь бот будет отслеживать удалённые и изменённые сообщения.",
                buttons=[[Button.text("📋 Настройки")]]
            )
            del user_states[user_id]
            logger.info(f"Пользователь {user_id} выбрал получателя: владелец")
            
            # Уведомляем владельца
            await bot.send_message(
                owner_id,
                f"👤 **Новый пользователь**\n\n"
                f"ID: {user_id}\n"
                f"Имя: {event.sender.first_name}\n"
                f"Настроил отправку уведомлений вам!"
            )
        except Exception as e:
            await event.reply(f"❌ Не удалось найти владельца: {e}")
        
    elif text == "3️⃣ Другой чат" or text == "3":
        # Запрашиваем ID чата
        user_states[user_id]['step'] = 'waiting_chat_id'
        await event.reply(
            "📝 **Введите ID чата или username:**\n\n"
            "Например: `@channel` или `-100123456789`\n\n"
            "Отправь ссылку или ID:"
        )
    else:
        await event.reply("❌ Пожалуйста, выбери 1, 2 или 3")

async def handle_chat_id_input(event, user_id, text):
    """Обработка ввода ID чата"""
    try:
        # Пытаемся получить сущность по введенному тексту
        target = await bot.get_entity(text.strip())
        target_id = target.id
        
        notification_targets[user_id] = target_id
        
        # Определяем тип цели
        if hasattr(target, 'title'):
            target_name = f"канал/чат {target.title}"
        else:
            target_name = f"пользователь @{target.username}" if target.username else f"ID {target_id}"
        
        await event.reply(
            f"✅ **Настройки сохранены!**\n\n"
            f"📬 Уведомления будут приходить в **{target_name}**.\n\n"
            f"Теперь бот будет отслеживать удалённые и изменённые сообщения.",
            buttons=[[Button.text("📋 Настройки")]]
        )
        del user_states[user_id]
        logger.info(f"Пользователь {user_id} выбрал получателя: {target_name}")
        
    except Exception as e:
        await event.reply(f"❌ Не удалось найти чат: {e}\n\nПопробуй ещё раз или отправь /start заново.")

async def change_target(event, user_id):
    """Изменение получателя уведомлений"""
    user_states[user_id] = {'step': 'waiting_target'}
    await event.reply(
        "🔄 **Куда отправлять уведомления?**\n\n"
        f"1️⃣ Мне в личку\n"
        f"2️⃣ Владельцу (@{bot_owner_username.replace('@', '')})\n"
        f"3️⃣ Другой чат",
        buttons=[
            [Button.text("1️⃣ Мне в личку")],
            [Button.text(f"2️⃣ Владельцу")],
            [Button.text("3️⃣ Другой чат")]
        ]
    )

async def show_settings(event, user_id):
    """Показать настройки пользователя"""
    target_id = notification_targets.get(user_id)
    
    if target_id is None:
        target_text = "не настроено"
    elif target_id == user_id:
        target_text = "себе"
    else:
        try:
            target = await bot.get_entity(target_id)
            if hasattr(target, 'title'):
                target_text = f"чат {target.title}"
            elif target.username:
                target_text = f"@{target.username}"
            else:
                target_text = f"ID {target_id}"
        except:
            target_text = f"ID {target_id}"
    
    settings = user_settings.get(user_id, DEFAULT_SETTINGS.copy())
    
    await event.reply(
        f"📋 **Твои настройки**\n\n"
        f"📬 Получатель: {target_text}\n"
        f"🗑 Мониторинг удалённых: {'✅' if settings['monitor_deleted'] else '❌'}\n"
        f"✏️ Мониторинг изменённых: {'✅' if settings['monitor_edited'] else '❌'}\n\n"
        f"📸 Фото: {'✅' if settings['notify_photos'] else '❌'}\n"
        f"🎥 Видео: {'✅' if settings['notify_videos'] else '❌'}\n"
        f"📝 Текст: {'✅' if settings['notify_text'] else '❌'}\n\n"
        f"Используй /menu для изменения",
        buttons=[
            [Button.text("🔄 Изменить получателя")],
            [Button.text("📊 Статистика")]
        ]
    )

async def show_stats(event, user_id):
    """Показать статистику"""
    # Подсчитываем статистику для пользователя
    user_msgs = [m for k, m in message_cache.items() if m.get('target') == user_id]
    deleted_count = len([m for m in user_msgs if m.get('deleted')])
    edited_count = len([m for m in user_msgs if m.get('edited')])
    
    await event.reply(
        f"📊 **Статистика**\n\n"
        f"📝 Отслежено сообщений: {len(user_msgs)}\n"
        f"🗑 Удалено: {deleted_count}\n"
        f"✏️ Изменено: {edited_count}\n"
        f"⏳ Активных в кэше: {len(message_cache)}"
    )

# ========== МОНИТОРИНГ СООБЩЕНИЙ ==========

@bot.on(events.NewMessage)
async def cache_messages(event):
    """Кэшируем новые сообщения"""
    if not event.message.text and not event.message.media:
        return
    
    chat_id = event.chat_id
    msg_id = event.message.id
    
    # Получаем информацию об отправителе
    try:
        sender = await event.get_sender()
        sender_name = getattr(sender, 'first_name', 'Неизвестно')
        if hasattr(sender, 'last_name') and sender.last_name:
            sender_name += f" {sender.last_name}"
        if hasattr(sender, 'username') and sender.username:
            sender_name += f" (@{sender.username})"
        sender_id = sender.id
    except:
        sender_name = "Неизвестно"
        sender_id = 0
    
    # Определяем тип медиа
    media_type = "text"
    if event.message.photo:
        media_type = "photo"
    elif event.message.video:
        media_type = "video"
    elif event.message.audio or event.message.voice:
        media_type = "audio"
    elif event.message.document:
        media_type = "document"
    
    # Сохраняем в кэш
    cache_key = f"{chat_id}_{msg_id}"
    message_cache[cache_key] = {
        'sender_id': sender_id,
        'sender_name': sender_name,
        'text': event.message.text or f"[{media_type.upper()}]",
        'media_type': media_type,
        'time': datetime.now().isoformat(),
        'chat_id': chat_id,
        'msg_id': msg_id,
        'deleted': False,
        'edited': False,
        'target': None
    }
    
    # Ограничиваем размер кэша
    if len(message_cache) > 1000:
        keys_to_remove = list(message_cache.keys())[:200]
        for key in keys_to_remove:
            del message_cache[key]

@bot.on(events.MessageDeleted)
async def deleted_handler(event):
    """Отслеживание удалённых сообщений"""
    chat_id = event.chat_id
    deleted_ids = event.deleted_ids
    
    # Получаем информацию о чате
    try:
        chat = await bot.get_entity(chat_id)
        chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Неизвестный чат'))
    except:
        chat_name = "Неизвестный чат"
    
    for msg_id in deleted_ids:
        cache_key = f"{chat_id}_{msg_id}"
        
        if cache_key in message_cache:
            msg_data = message_cache[cache_key]
            msg_data['deleted'] = True
            
            # Определяем, кому отправлять уведомление
            target_id = notification_targets.get(msg_data['sender_id'])
            
            if target_id:
                # Формируем уведомление
                alert = (
                    f"🗑 **СООБЩЕНИЕ УДАЛЕНО**\n\n"
                    f"📌 Чат: {chat_name}\n"
                    f"👤 Отправитель: {msg_data['sender_name']}\n"
                    f"⏰ Отправлено: {msg_data['time'][:19]}\n"
                    f"📝 Текст: {msg_data['text']}\n"
                    f"🆔 ID: {msg_id}"
                )
                
                # Отправляем уведомление
                try:
                    await bot.send_message(target_id, alert)
                    logger.info(f"Уведомление об удалении отправлено в {target_id}")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление: {e}")

@bot.on(events.MessageEdited)
async def edited_handler(event):
    """Отслеживание изменённых сообщений"""
    message = event.message
    chat_id = event.chat_id
    msg_id = message.id
    cache_key = f"{chat_id}_{msg_id}"
    
    # Получаем информацию о чате
    try:
        chat = await bot.get_entity(chat_id)
        chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Неизвестный чат'))
    except:
        chat_name = "Неизвестный чат"
    
    # Получаем информацию об отправителе
    try:
        sender = await event.get_sender()
        sender_name = getattr(sender, 'first_name', 'Неизвестно')
        if hasattr(sender, 'last_name') and sender.last_name:
            sender_name += f" {sender.last_name}"
        if hasattr(sender, 'username') and sender.username:
            sender_name += f" (@{sender.username})"
        sender_id = sender.id
    except:
        sender_name = "Неизвестно"
        sender_id = 0
    
    old_text = "Неизвестно"
    if cache_key in message_cache:
        old_text = message_cache[cache_key].get('text', 'Неизвестно')
        message_cache[cache_key]['edited'] = True
        message_cache[cache_key]['text'] = message.text or "[Медиа]"
    
    # Определяем, кому отправлять уведомление
    target_id = notification_targets.get(sender_id)
    
    if target_id:
        # Формируем уведомление
        alert = (
            f"✏️ **СООБЩЕНИЕ ИЗМЕНЕНО**\n\n"
            f"📌 Чат: {chat_name}\n"
            f"👤 Отправитель: {sender_name}\n"
            f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📝 Было: {old_text}\n"
            f"📝 Стало: {message.text or '[Медиа]'}\n"
            f"🆔 ID: {msg_id}"
        )
        
        # Отправляем уведомление
        try:
            await bot.send_message(target_id, alert)
            logger.info(f"Уведомление об изменении отправлено в {target_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление: {e}")

# ========== ЗАПУСК ==========

async def main():
    """Запуск бота"""
    global bot_owner_username
    
    # Запрашиваем username владельца в консоли
    bot_owner_username = await ask_owner_username()
    
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info(f"👤 Владелец: {bot_owner_username}")
    
    # Пытаемся найти владельца и отправить уведомление
    try:
        owner = await bot.get_entity(bot_owner_username)
        await bot.send_message(
            owner.id,
            f"✅ **Бот @{me.username} запущен!**\n\n"
            f"📋 **Команды:**\n"
            f"/start - начать работу\n"
            f"📋 Настройки - меню настроек\n"
            f"📊 Статистика - статистика\n\n"
            f"Бот отслеживает удалённые и изменённые сообщения!"
        )
        logger.info(f"✅ Уведомление отправлено владельцу {bot_owner_username}")
    except Exception as e:
        logger.error(f"⚠️ Не удалось найти владельца {bot_owner_username}: {e}")
        logger.info("Бот продолжает работу без уведомления владельцу")
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")