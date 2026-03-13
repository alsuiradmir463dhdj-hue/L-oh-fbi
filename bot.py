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
bot = TelegramClient('bot_session', API_ID, API_HASH)
user_client = None

# ========== СОСТОЯНИЯ ==========
waiting_for_target = False
target_id = None
waiting_for_phone = False
waiting_for_code = None
waiting_for_password = False
temp_password_phone = None
message_cache = {}

# ========== ОБРАБОТЧИКИ ==========

@bot.on(events.NewMessage)
async def handler(event):
    global waiting_for_target, target_id, waiting_for_phone, waiting_for_code, user_client
    global waiting_for_password, temp_password_phone
    
    user_id = event.sender_id
    text = event.message.text

    # === 1. ЕСЛИ ЖДЁМ ID ПОЛУЧАТЕЛЯ ===
    if waiting_for_target:
        try:
            target = await bot.get_entity(text.strip())
            target_id = target.id
            waiting_for_target = False
            
            target_name = getattr(target, 'first_name', 'пользователь')
            if hasattr(target, 'username') and target.username:
                target_name += f" (@{target.username})"
            
            # Отправляем сообщение с кнопкой контакта (правильный синтаксис)
            await event.reply(
                f"✅ **ID получателя сохранён!**\n\n"
                f"📬 Все уведомления будут отправляться:\n"
                f"👤 {target_name} (ID: {target_id})\n\n"
                f"📞 **Теперь нужно войти в твой аккаунт.**\n"
                f"Нажми кнопку ниже, чтобы отправить номер телефона.",
                buttons=[Button.request_contact("📞 Поделиться контактом")]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз (ID или @username):")
        return

    # === 2. ЕСЛИ ЖДЁМ 2FA ПАРОЛЬ ===
    if waiting_for_password:
        password = text.strip()
        phone = temp_password_phone
        
        try:
            await user_client.sign_in(password=password)
            
            me = await user_client.get_me()
            await event.reply(
                f"✅ **Успешный вход с 2FA!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 Теперь бот будет отслеживать все чаты."
            )
            
            waiting_for_password = False
            temp_password_phone = None
            asyncio.create_task(monitor_user_chats())
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз:")
        return

    # === 3. ЕСЛИ ЖДЁМ КОД ===
    if waiting_for_code is not None:
        phone = waiting_for_code
        code = text.strip()
        
        try:
            user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.sign_in(phone, code)
            
            me = await user_client.get_me()
            await event.reply(
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 Теперь бот будет отслеживать все чаты."
            )
            
            waiting_for_code = None
            waiting_for_phone = False
            asyncio.create_task(monitor_user_chats())
            
        except SessionPasswordNeededError:
            waiting_for_password = True
            temp_password_phone = phone
            waiting_for_code = None
            await event.reply(
                "🔐 **Требуется двухфакторный пароль.**\n\n"
                "Введи свой пароль от Telegram:"
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка входа: {e}")
            waiting_for_code = None
            waiting_for_phone = False
        return

    # === 4. ОСНОВНЫЕ КОМАНДЫ ===
    if text == "/start":
        waiting_for_target = True
        await event.reply(
            "👋 **Бот для мониторинга чатов**\n\n"
            "📝 **Введите ID или username пользователя**,\n"
            "которому будут приходить уведомления.\n\n"
            "Примеры:\n"
            "• ID: `7396285844`\n"
            "• Username: `@durov`"
        )
    
    elif text == "/stats":
        target_info = f"ID: {target_id}" if target_id else "не задан"
        await event.reply(
            f"📊 **Статистика**\n\n"
            f"📦 Кэш сообщений: {len(message_cache)}\n"
            f"📬 Получатель: {target_info}"
        )
    
    elif text == "/reset":
        waiting_for_target = True
        target_id = None
        waiting_for_phone = False
        waiting_for_code = None
        waiting_for_password = False
        await event.reply("🔄 **Настройки сброшены.**\nВведи ID получателя:")

# ========== ПОЛУЧЕНИЕ КОНТАКТА ==========

@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    global waiting_for_code
    
    contact = event.message.contact
    phone = contact.phone_number
    
    waiting_for_code = phone
    
    await event.reply(
        f"✅ **Номер получен:** `{phone}`\n\n"
        f"📨 **Код подтверждения отправлен** в Telegram.\n"
        f"✍️ Введи его сюда (только цифры):"
    )

# ========== МОНИТОРИНГ ЧАТОВ ==========

async def monitor_user_chats():
    global user_client
    
    if not user_client or not target_id:
        logger.error("Нет клиента или получателя")
        return
    
    logger.info(f"🔍 Начинаю мониторинг, уведомления в {target_id}")
    
    @user_client.on(events.NewMessage)
    async def user_message_handler(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        message_cache[cache_key] = {
            'text': event.message.text or "[медиа]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'sender_id': event.sender_id
        }
        
        if len(message_cache) > 2000:
            keys = list(message_cache.keys())[:500]
            for k in keys:
                del message_cache[k]

    @user_client.on(events.MessageDeleted)
    async def user_delete_handler(event):
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                try:
                    chat = await user_client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                except:
                    chat_name = "Неизвестный чат"
                
                await bot.send_message(
                    target_id,
                    f"🗑 **УДАЛЕНО** в чате {chat_name}\n\n"
                    f"👤 От: {msg['sender_id']}\n"
                    f"💬 {msg['text'][:300]}"
                )

    @user_client.on(events.MessageEdited)
    async def user_edit_handler(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old = message_cache[cache_key]['text']
            new = event.message.text
            if old != new:
                try:
                    chat = await user_client.get_entity(event.chat_id)
                    chat_name = getattr(chat, 'title', getattr(chat, 'first_name', 'Чат'))
                except:
                    chat_name = "Неизвестный чат"
                
                await bot.send_message(
                    target_id,
                    f"✏️ **ИЗМЕНЕНО** в чате {chat_name}\n\n"
                    f"📝 Было: {old[:200]}\n"
                    f"📝 Стало: {new[:200]}"
                )
                message_cache[cache_key]['text'] = new

    await user_client.run_until_disconnected()

# ========== ЗАПУСК ==========

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info("👑 Ожидание ввода ID получателя...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())