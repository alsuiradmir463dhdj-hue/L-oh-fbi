import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.errors import SessionPasswordNeededError
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# ========== КЛИЕНТЫ ==========
bot = TelegramClient('bot_session', API_ID, API_HASH)          # для бота
user_client = None                                              # для твоего аккаунта

# ========== СОСТОЯНИЯ ==========
owner_username = None
waiting_for_owner = True
waiting_for_phone = {}          # user_id -> True
waiting_for_code = {}           # user_id -> phone
user_clients = {}                # user_id -> client
message_cache = {}               # кэш сообщений
notification_targets = {}        # кому отправлять уведомления

# ========== ОБРАБОТЧИКИ ==========

@bot.on(events.NewMessage)
async def handler(event):
    global owner_username, waiting_for_owner, user_client
    user_id = event.sender_id
    text = event.message.text

    # === 1. ЗАПРОС USERNAME ===
    if waiting_for_owner:
        await event.reply(
            "👑 **Привет!**\n\n"
            "Напиши **свой Telegram username**, чтобы я знал, кому отправлять уведомления.\n"
            "Пример: `@durov`"
        )
        waiting_for_owner = False
        return

    if owner_username is None:
        if text.startswith('@'):
            owner_username = text.strip()
        else:
            owner_username = '@' + text.strip()
        
        try:
            owner = await bot.get_entity(owner_username)
            await event.reply(
                f"✅ **Владелец @{owner.username} найден!**\n\n"
                f"📬 Все уведомления будут приходить сюда.\n\n"
                f"📞 **Теперь нужно войти в твой аккаунт.**\n"
                f"Нажми кнопку ниже, чтобы отправить номер телефона.",
                buttons=[[Button.request_contact("📞 Отправить номер")]]
            )
            notification_targets[user_id] = owner.id
            logger.info(f"Владелец установлен: {owner_username}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз.")
            owner_username = None
        return

    # === 2. ПОЛУЧЕНИЕ НОМЕРА ===
    if user_id in waiting_for_phone:
        # Этот блок уже обрабатывается contact_handler
        return

    # === 3. ВВОД КОДА ===
    if user_id in waiting_for_code:
        phone = waiting_for_code[user_id]
        code = text.strip()
        
        try:
            # Создаём клиент для пользователя
            user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.sign_in(phone, code)
            
            user_clients[user_id] = user_client
            me = await user_client.get_me()
            
            await event.reply(
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 Теперь бот будет отслеживать все чаты."
            )
            
            # Запускаем мониторинг
            asyncio.create_task(monitor_user_chats(user_id))
            
        except SessionPasswordNeededError:
            await event.reply("⚠️ Требуется двухфакторный пароль. Пока не поддерживается.")
        except Exception as e:
            await event.reply(f"❌ Ошибка входа: {e}")
        
        del waiting_for_code[user_id]
        return

    # === 4. ОБЫЧНЫЕ КОМАНДЫ ===
    if text == "/start":
        await event.reply(
            "👋 **Бот для мониторинга чатов**\n\n"
            f"📬 Уведомления: {owner_username}\n"
            f"📊 Статистика: /stats"
        )
    
    elif text == "/stats":
        await event.reply(
            f"📊 **Статистика**\n\n"
            f"👑 Владелец: {owner_username}\n"
            f"📦 Кэш: {len(message_cache)}"
        )

# ========== ПОЛУЧЕНИЕ КОНТАКТА ==========

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    phone = contact.phone_number
    
    waiting_for_phone[user_id] = True
    waiting_for_code[user_id] = phone
    
    await event.reply(
        f"✅ **Номер получен:** `{phone}`\n\n"
        f"📨 **Код подтверждения отправлен** в Telegram.\n"
        f"✍️ Введи его сюда (только цифры):"
    )

# ========== МОНИТОРИНГ ЧАТОВ ==========

async def monitor_user_chats(user_id):
    """Мониторит все чаты от имени пользователя"""
    client = user_clients.get(user_id)
    if not client:
        return
    
    logger.info(f"🔍 Начинаю мониторинг для пользователя {user_id}")
    
    @client.on(events.NewMessage)
    async def user_message_handler(event):
        """Кэшируем сообщения"""
        cache_key = f"{event.chat_id}_{event.message.id}"
        message_cache[cache_key] = {
            'text': event.message.text or "[медиа]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'sender_id': event.sender_id,
            'from_user': user_id
        }
        
        # Ограничение кэша
        if len(message_cache) > 2000:
            keys = list(message_cache.keys())[:500]
            for k in keys:
                del message_cache[k]

    @client.on(events.MessageDeleted)
    async def user_delete_handler(event):
        """Удалённые сообщения"""
        target = notification_targets.get(user_id)
        if not target:
            return
        
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                try:
                    chat = await client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                except:
                    chat_name = "Неизвестный чат"
                
                await bot.send_message(
                    target,
                    f"🗑 **УДАЛЕНО** в чате {chat_name}\n\n"
                    f"👤 От: {msg['sender_id']}\n"
                    f"💬 {msg['text'][:300]}"
                )

    @client.on(events.MessageEdited)
    async def user_edit_handler(event):
        """Изменённые сообщения"""
        target = notification_targets.get(user_id)
        if not target:
            return
        
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old = message_cache[cache_key]['text']
            new = event.message.text
            if old != new:
                try:
                    chat = await client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                except:
                    chat_name = "Неизвестный чат"
                
                await bot.send_message(
                    target,
                    f"✏️ **ИЗМЕНЕНО** в чате {chat_name}\n\n"
                    f"📝 Было: {old[:200]}\n"
                    f"📝 Стало: {new[:200]}"
                )
                message_cache[cache_key]['text'] = new

    await client.run_until_disconnected()

# ========== ЗАПУСК ==========

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info("👑 Ожидание ввода username владельца...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())