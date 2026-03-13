import os
import sys
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.custom import Button

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Данные из секретов
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# Создаем клиента
bot = TelegramClient('bot', API_ID, API_HASH)

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply(
        "✅ **Бот работает!**\n\nНажми кнопку:",
        buttons=[[Button.text("📱 Отправить номер", resize=True)]]
    )

@bot.on(events.NewMessage)
async def handler(event):
    if event.message.text == "📱 Отправить номер":
        await event.reply(
            "📞 Поделись контактом:",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact(event):
    phone = event.message.contact.phone_number
    await event.reply(f"✅ Номер: {phone}")

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ @{me.username} запущен")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())