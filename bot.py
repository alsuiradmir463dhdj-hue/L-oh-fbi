import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.custom import Button

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Получаем переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# Создаем клиента
bot = TelegramClient('bot_session', API_ID, API_HASH)

# ========== ОБРАБОТЧИКИ ==========

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Обработчик команды /start"""
    await event.reply(
        "🔐 **Добро пожаловать!**\n\n"
        "Нажмите кнопку ниже для отправки номера телефона:",
        buttons=[[Button.text("📱 Отправить номер", resize=True)]]
    )
    logger.info(f"Пользователь {event.sender_id} запустил бота")

@bot.on(events.NewMessage)
async def message_handler(event):
    """Обработчик текстовых сообщений"""
    text = event.message.text
    
    if text == "📱 Отправить номер":
        await event.reply(
            "📞 **Поделитесь вашим контактом:**\n\n"
            "Нажмите кнопку ниже:",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        logger.info(f"Пользователь {event.sender_id} запросил отправку номера")

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    """Обработчик полученного контакта"""
    contact = event.message.contact
    user_id = event.sender_id
    phone = contact.phone_number
    
    await event.reply(
        f"✅ **Номер получен!**\n\n"
        f"📱 Телефон: `{phone}`\n"
        f"👤 Имя: {contact.first_name or 'не указано'}\n\n"
        f"Спасибо за предоставленную информацию!"
    )
    logger.info(f"Получен контакт от пользователя {user_id}: {phone}")

@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    """Обработчик команды /help"""
    await event.reply(
        "📋 **Доступные команды:**\n\n"
        "/start - Начать работу\n"
        "/help - Показать это сообщение\n"
        "/status - Проверить статус бота\n\n"
        "📱 **Кнопка:** Отправить номер"
    )

@bot.on(events.NewMessage(pattern='/status'))
async def status_handler(event):
    """Обработчик команды /status"""
    await event.reply("✅ Бот работает нормально!")

# ========== ЗАПУСК ==========

async def main():
    """Главная функция запуска"""
    try:
        # Запускаем бота
        await bot.start(bot_token=BOT_TOKEN)
        
        # Получаем информацию о боте
        me = await bot.get_me()
        logger.info(f"✅ Бот @{me.username} успешно запущен!")
        logger.info(f"🆔 ID бота: {me.id}")
        
        # Отправляем уведомление о запуске (опционально)
        # await bot.send_message(me.id, "✅ Бот запущен!")
        
        # Держим соединение открытым
        await bot.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске: {e}")
        raise
    finally:
        await bot.disconnect()
        logger.info("Бот отключен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")