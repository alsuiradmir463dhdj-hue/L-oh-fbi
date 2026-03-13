import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.custom import Button

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot_session', API_ID, API_HASH)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "🔐 **Добро пожаловать!**\n\nНажмите кнопку ниже для отправки номера телефона:",
        buttons=[[Button.text("📱 Отправить номер", resize=True)]]
    )
    logger.info(f"Пользователь {event.sender_id} запустил бота")

@bot.on(events.NewMessage)
async def message_handler(event):
    text = event.message.text
    if text == "📱 Отправить номер":
        await event.reply(
            "📞 **Поделитесь вашим контактом:**",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        logger.info(f"Пользователь {event.sender_id} запросил отправку номера")

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    contact = event.message.contact
    phone = contact.phone_number
    await event.reply(
        f"✅ **Номер получен!**\n\n📱 Телефон: `{phone}`\n👤 Имя: {contact.first_name or 'не указано'}"
    )
    logger.info(f"Получен контакт от {event.sender_id}: {phone}")

@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    await event.reply("📋 **Команды:**\n/start - начать\n/help - помощь\n/status - статус")

@bot.on(events.NewMessage(pattern='/status'))
async def status_handler(event):
    await event.reply("✅ Бот работает нормально!")

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} успешно запущен!")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")