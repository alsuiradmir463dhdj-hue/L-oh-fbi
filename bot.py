import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot_session', API_ID, API_HASH)

# Хранилища
message_cache = {}
user_settings = {}
owner_username = None  # Сюда сохраним username владельца
waiting_for_owner = True  # Флаг: ждём ввода username

@bot.on(events.NewMessage)
async def handler(event):
    global owner_username, waiting_for_owner
    user_id = event.sender_id
    text = event.message.text

    # ===== ЕСЛИ ЕЩЁ НЕТ ВЛАДЕЛЬЦА =====
    if waiting_for_owner:
        # Запрашиваем username
        await event.reply(
            "👑 **Привет! Я новый бот.**\n\n"
            "Напиши **свой Telegram username**, чтобы я знал, кому отправлять уведомления.\n\n"
            "Пример: `@durov`"
        )
        waiting_for_owner = False  # Чтобы не спамить
        return

    # ===== ЕСЛИ ЖДЁМ USERNAME =====
    if owner_username is None:
        # Проверяем, что прислали
        if text.startswith('@'):
            owner_username = text.strip()
        else:
            owner_username = '@' + text.strip()
        
        try:
            # Пробуем найти владельца
            owner = await bot.get_entity(owner_username)
            await event.reply(
                f"✅ **Отлично!** Владелец @{owner.username} найден.\n\n"
                f"📬 Все уведомления буду отправлять туда.\n\n"
                f"Теперь можешь пользоваться ботом: /start"
            )
            logger.info(f"Владелец установлен: {owner_username}")
        except Exception as e:
            await event.reply(
                f"❌ **Ошибка:** Не могу найти пользователя {owner_username}.\n"
                f"Проверь username и попробуй ещё раз."
            )
            owner_username = None
        return

    # ===== ОСНОВНАЯ ЛОГИКА (когда владелец уже есть) =====
    if text == "/start":
        await event.reply(
            "👋 **Бот для отслеживания сообщений**\n\n"
            f"📬 Уведомления отправляются: {owner_username}\n"
            f"📊 Статистика: /stats"
        )
    
    elif text == "/stats":
        await event.reply(
            f"📊 **Статистика**\n\n"
            f"👑 Владелец: {owner_username}\n"
            f"📦 Кэш сообщений: {len(message_cache)}"
        )
    
    # Кэшируем сообщения
    cache_key = f"{event.chat_id}_{event.message.id}"
    message_cache[cache_key] = {
        'text': event.message.text,
        'time': datetime.now().isoformat(),
        'chat_id': event.chat_id,
        'sender_id': event.sender_id
    }
    
    # Ограничиваем кэш
    if len(message_cache) > 1000:
        keys = list(message_cache.keys())[:200]
        for k in keys:
            del message_cache[k]

@bot.on(events.MessageDeleted)
async def on_delete(event):
    """Удалённые сообщения"""
    if owner_username is None:
        return
    
    try:
        owner = await bot.get_entity(owner_username)
    except:
        return
    
    for msg_id in event.deleted_ids:
        cache_key = f"{event.chat_id}_{msg_id}"
        if cache_key in message_cache:
            msg = message_cache[cache_key]
            await bot.send_message(
                owner.id,
                f"🗑 **Удалено:**\n{msg['text'][:200]}"
            )

@bot.on(events.MessageEdited)
async def on_edit(event):
    """Изменённые сообщения"""
    if owner_username is None:
        return
    
    try:
        owner = await bot.get_entity(owner_username)
    except:
        return
    
    cache_key = f"{event.chat_id}_{event.message.id}"
    if cache_key in message_cache:
        old = message_cache[cache_key]['text']
        new = event.message.text
        if old != new:
            await bot.send_message(
                owner.id,
                f"✏️ **Изменено:**\n"
                f"Было: {old[:200]}\n"
                f"Стало: {new[:200]}"
            )
            message_cache[cache_key]['text'] = new

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info("👑 Ожидание ввода username владельца...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())