import os
from telethon import TelegramClient, events

print("✅ СТАРТ")

# Данные
token = os.environ.get('BOT_TOKEN')
api_id = int(os.environ.get('API_ID'))
api_hash = os.environ.get('API_HASH')

print("✅ Токен есть")

# Клиент
bot = TelegramClient('s', api_id, api_hash)

@bot.on(events.NewMessage)
async def hello(e):
    if e.message.text == "/start":
        await e.reply("✅ Живой!")

print("✅ Запуск...")
bot.start(bot_token=token)
print("✅ Бот работает")
bot.run_until_disconnected()