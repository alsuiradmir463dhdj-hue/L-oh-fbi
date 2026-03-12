import os
import asyncio
from telethon import TelegramClient, events
from telethon.tl.custom import Button

# ===== ДАННЫЕ =====
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# ===== СОЗДАЕМ БОТА =====
bot = TelegramClient('bot', API_ID, API_HASH)

# ===== СТАРТ =====
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply(
        "🔐 **Добро пожаловать!**\n\nНажмите кнопку для отправки номера:",
        buttons=[[Button.text("📱 Отправить номер", resize=True)]]
    )

# ===== КНОПКА =====
@bot.on(events.NewMessage)
async def handler(event):
    if event.message.text == "📱 Отправить номер":
        await event.reply(
            "📞 **Поделитесь контактом:**",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )

# ===== КОНТАКТ =====
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact(event):
    contact = event.message.contact
    await event.reply(f"✅ Номер получен: {contact.phone_number}")

# ===== ЗАПУСК =====
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    print(f"✅ Бот @{me.username} запущен!")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())