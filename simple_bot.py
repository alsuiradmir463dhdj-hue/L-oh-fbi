import os
import sys
import time
from telethon import TelegramClient, events

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

print("🚀 Запуск простого бота...")
print(f"Токен: {BOT_TOKEN[:10]}...")

# СОЗДАЕМ КЛИЕНТА
bot = TelegramClient('simple', API_ID, API_HASH)

# ПРОСТОЙ ОБРАБОТЧИК
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("✅ Бот работает! (упрощенная версия)")

# ЗАПУСК
print("🔄 Подключение...")
bot.start(bot_token=BOT_TOKEN)
print("✅ Бот запущен!")

# ДЕРЖИМ ОТКРЫТЫМ
bot.run_until_disconnected()