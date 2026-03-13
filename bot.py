import os
import asyncio
import logging
import requests
import re
import json
import time
import random
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberUnoccupiedError
)
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.types import (
    MessageEntityTextUrl,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaVideo
)
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
user_state = {}  # Состояния пользователей
user_client = None  # Клиент пользователя
target_id = None  # ID получателя уведомлений
message_cache = {}  # Кэш сообщений
deleted_log = []  # Лог удалённых

# Пин-код
ACCESS_PIN = "5482"
authorized_users = set()

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
user_settings = {}

DEFAULT_SETTINGS = {
    'monitor_deleted': True,
    'monitor_edited': True,
    'monitor_expiring': True,
    'notify_photos': True,
    'notify_videos': True,
    'notify_text': True,
    'auto_read_code': True,  # Авто-чтение кода из сообщений
    'auto_confirm': False,
    'work_mode': 'balanced',  # 'work', 'rest', 'balanced'
    'work_hours': {'start': 9, 'end': 21},
    'rest_hours': {'start': 21, 'end': 9},
    'notification_channels': [],  # Куда дублировать уведомления
    'filter_keywords': [],  # Фильтр по ключевым словам
    'filter_users': [],  # Фильтр по пользователям
    'backup_enabled': True,
    'backup_interval': 3600  # Секунды
}

# ========== РАБОЧИЕ ЧАСЫ ==========
def is_work_time():
    """Проверяет, рабочее ли сейчас время"""
    current_hour = datetime.now().hour
    # По умолчанию: работа с 9 до 21, отдых с 21 до 9
    work_start = 9
    work_end = 21
    
    if work_start <= work_end:
        return work_start <= current_hour < work_end
    else:
        return current_hour >= work_start or current_hour < work_end

def get_time_status():
    """Возвращает статус времени"""
    if is_work_time():
        return "💼 **Рабочее время**"
    else:
        return "😴 **Время отдыха**"

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ТЕКСТОВЫМИ ФАЙЛАМИ ==========
async def extract_code_from_text(text):
    """Извлекает код подтверждения из текста"""
    # Ищем 5-значный код
    patterns = [
        r'код:?\s*(\d{5})',
        r'code:?\s*(\d{5})',
        r'(\d{5})\s*[-\s]',
        r'^(\d{5})$',
        r'(\d{5})[^\d]'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Если не нашли, ищем любые 5 цифр подряд
    digits = re.findall(r'\d{5}', text)
    if digits:
        return digits[0]
    
    return None

async def extract_session_from_text(text):
    """Извлекает строку сессии из текста"""
    # Ищем длинные строки, похожие на сессию
    patterns = [
        r'([A-Za-z0-9+/=]{100,})',
        r'1[A-Za-z0-9+/=]{200,}',
        r'eyJ[A-Za-z0-9+/=]{50,}'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    
    return None

# ========== ЗАГРУЗКА С РАЗНЫХ ИСТОЧНИКОВ ==========
async def download_from_url(url):
    """Универсальная загрузка с URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.text
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки URL: {e}")
        return None

async def download_from_yadisk(url):
    """Скачивает файл с Яндекс Диска"""
    try:
        if 'yadi.sk' in url or 'disk.yandex' in url:
            if 'yadi.sk' in url:
                response = requests.get(url, allow_redirects=True)
                file_id = re.search(r'/d/([a-zA-Z0-9_-]+)', response.url)
                if file_id:
                    direct_url = f"https://disk.yandex.ru/d/{file_id.group(1)}?download=1"
                else:
                    direct_url = url.replace('yadi.sk', 'disk.yandex.ru') + '&download=1'
            else:
                direct_url = url + '&download=1'
            
            response = requests.get(direct_url, stream=True)
            if response.status_code == 200:
                filename = f"temp_{datetime.now().timestamp()}.txt"
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                os.remove(filename)
                return content
        return None
    except Exception as e:
        logger.error(f"Ошибка Я.Диска: {e}")
        return None

async def download_from_google_drive(url):
    """Скачивает с Google Drive"""
    try:
        file_id = None
        if 'drive.google.com' in url:
            match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
            if match:
                file_id = match.group(1)
        
        if file_id:
            direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            response = requests.get(direct_url)
            return response.text
        return None
    except Exception as e:
        logger.error(f"Ошибка Google Drive: {e}")
        return None

async def download_from_pastebin(url):
    """Скачивает с Pastebin"""
    try:
        if 'pastebin.com' in url:
            code = url.split('/')[-1]
            raw_url = f"https://pastebin.com/raw/{code}"
            response = requests.get(raw_url)
            return response.text
        return None
    except Exception as e:
        logger.error(f"Ошибка Pastebin: {e}")
        return None

# ========== INLINE КНОПКИ ==========
async def send_with_inline_buttons(event, text, buttons_data):
    """Отправляет сообщение с inline кнопками"""
    buttons = []
    for row in buttons_data:
        button_row = []
        for btn in row:
            button_row.append(Button.inline(btn['text'], data=btn['data'].encode()))
        buttons.append(button_row)
    
    await event.reply(text, buttons=buttons)

# ========== ОБРАБОТЧИК КНОПОК ==========
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    """Обрабатывает нажатия на inline кнопки"""
    user_id = event.sender_id
    data = event.data.decode()
    
    global target_id, user_client, user_settings
    
    if user_id not in authorized_users:
        await event.answer("❌ Сначала введи пин-код", alert=True)
        return
    
    if data == "work_mode":
        current = user_settings.get(user_id, {}).get('work_mode', 'balanced')
        modes = ['work', 'rest', 'balanced']
        next_mode = modes[(modes.index(current) + 1) % 3]
        
        if user_id not in user_settings:
            user_settings[user_id] = DEFAULT_SETTINGS.copy()
        user_settings[user_id]['work_mode'] = next_mode
        
        status = {
            'work': "💼 Только работа",
            'rest': "😴 Только отдых",
            'balanced': "⚖️ Сбалансированный"
        }
        
        await event.edit(f"✅ Режим изменён на: {status[next_mode]}")
        await event.answer()
        
    elif data == "set_work_hours":
        await event.edit("⏰ Введи часы работы в формате: 9 21")
        user_state[user_id] = {'step': 'waiting_work_hours'}
        await event.answer()
        
    elif data == "auto_read":
        if user_id not in user_settings:
            user_settings[user_id] = DEFAULT_SETTINGS.copy()
        user_settings[user_id]['auto_read_code'] = not user_settings[user_id].get('auto_read_code', True)
        status = "✅ Включено" if user_settings[user_id]['auto_read_code'] else "❌ Выключено"
        await event.edit(f"📖 Авто-чтение кода: {status}")
        await event.answer()
        
    elif data == "auth_phone":
        user_state[user_id] = {'step': 'waiting_phone'}
        await event.edit("📞 Введи номер в формате +79001234567")
        await event.answer()
        
    elif data == "auth_file":
        user_state[user_id] = {'step': 'waiting_session_file'}
        await event.edit("📁 Отправь файл сессии (любой формат)")
        await event.answer()
        
    elif data == "auth_yadisk":
        user_state[user_id] = {'step': 'waiting_yadisk_link'}
        await event.edit("☁️ **Отправь ссылку на Яндекс Диск**")
        await event.answer()
        
    elif data == "auth_google":
        user_state[user_id] = {'step': 'waiting_google_link'}
        await event.edit("📎 **Отправь ссылку на Google Drive**")
        await event.answer()
        
    elif data == "auth_pastebin":
        user_state[user_id] = {'step': 'waiting_pastebin_link'}
        await event.edit("📋 **Отправь ссылку на Pastebin**")
        await event.answer()
        
    elif data == "auth_text":
        user_state[user_id] = {'step': 'waiting_code_text'}
        await event.edit("📝 **Отправь текст с кодом**\nЯ сам найду код")
        await event.answer()
        
    elif data == "start_monitor":
        if target_id:
            await event.edit("🔍 Запускаю мониторинг...")
            asyncio.create_task(monitor_chats(user_id))
        else:
            await event.edit("❌ Сначала введи ID получателя через /start")
        await event.answer()
        
    elif data == "reset_all":
        target_id = None
        user_client = None
        user_state[user_id] = {'step': 'waiting_target'}
        await event.edit("🔄 Настройки сброшены. Введи ID получателя через /start")
        await event.answer()
        
    elif data == "show_stats":
        stats = f"📊 **Статистика**\n\n"
        stats += f"📦 Кэш: {len(message_cache)}\n"
        stats += f"🗑 Удалено: {len(deleted_log)}\n"
        stats += f"👤 Аккаунт: {'есть' if user_client else 'нет'}\n"
        stats += f"⏰ {get_time_status()}"
        await event.edit(stats)
        await event.answer()
        
    elif data == "help_menu":
        help_text = (
            "📚 **Помощь**\n\n"
            "**Режимы:**\n"
            "• 💼 Работа - полный мониторинг\n"
            "• 😴 Отдых - тихий режим\n"
            "• ⚖️ Баланс - по расписанию\n\n"
            "**Вход:**\n"
            "• 📞 По номеру\n"
            "• 📁 Файл\n"
            "• ☁️ Яндекс Диск\n"
            "• 📎 Google Drive\n"
            "• 📋 Pastebin\n"
            "• 📝 Текст с кодом\n\n"
            "**Команды:**\n"
            "/start - начать\n"
            "/settings - настройки\n"
            "/stats - статистика"
        )
        await event.edit(help_text)
        await event.answer()

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
@bot.on(events.NewMessage)
async def handler(event):
    user_id = event.sender_id
    text = event.message.text.strip() if event.message.text else ""
    
    global target_id, user_client, user_settings

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply("✅ Доступ разрешён! Используй /start")
        else:
            await event.reply("🔐 Введите пин-код (5482):")
        return

    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start":
        await send_with_inline_buttons(
            event,
            f"👋 **Добро пожаловать!**\n\n{get_time_status()}\n\n"
            f"📝 **Введи ID или username получателя**\n"
            f"(Кому отправлять уведомления)",
            [
                [{'text': '📞 Вход по номеру', 'data': 'auth_phone'}],
                [{'text': '📁 Файл сессии', 'data': 'auth_file'}],
                [{'text': '☁️ Яндекс Диск', 'data': 'auth_yadisk'}],
                [{'text': '📎 Google Drive', 'data': 'auth_google'}],
                [{'text': '📋 Pastebin', 'data': 'auth_pastebin'}],
                [{'text': '📝 Текст с кодом', 'data': 'auth_text'}],
                [
                    {'text': '⚙️ Настройки', 'data': 'settings_menu'},
                    {'text': '📊 Статистика', 'data': 'show_stats'},
                    {'text': '❓ Помощь', 'data': 'help_menu'}
                ]
            ]
        )
        user_state[user_id] = {'step': 'waiting_target'}
        return

    if text == "/settings":
        settings = user_settings.get(user_id, DEFAULT_SETTINGS.copy())
        status = {
            'work': "💼",
            'rest': "😴",
            'balanced': "⚖️"
        }
        await send_with_inline_buttons(
            event,
            f"⚙️ **Настройки**\n\n"
            f"Режим: {status.get(settings['work_mode'], '⚖️')}\n"
            f"Авто-чтение кода: {'✅' if settings.get('auto_read_code', True) else '❌'}\n"
            f"Мониторинг удалённых: {'✅' if settings['monitor_deleted'] else '❌'}\n\n"
            f"⏰ {get_time_status()}",
            [
                [{'text': '🔄 Сменить режим', 'data': 'work_mode'}],
                [{'text': '⏰ Установить часы', 'data': 'set_work_hours'}],
                [{'text': '📖 Авто-чтение кода', 'data': 'auto_read'}],
                [{'text': '🔙 Назад', 'data': 'back_to_main'}]
            ]
        )
        return

    # === ЖДЁМ ID ===
    if user_state.get(user_id, {}).get('step') == 'waiting_target':
        try:
            target = await bot.get_entity(text)
            target_id = target.id
            user_state[user_id] = {'step': 'waiting_auth_method'}
            
            await send_with_inline_buttons(
                event,
                f"✅ **Получатель:** {target.first_name}\n\n"
                f"**Выбери способ входа:**",
                [
                    [{'text': '📞 По номеру', 'data': 'auth_phone'}],
                    [{'text': '📁 Файл сессии', 'data': 'auth_file'}],
                    [{'text': '☁️ Яндекс Диск', 'data': 'auth_yadisk'}],
                    [{'text': '📎 Google Drive', 'data': 'auth_google'}],
                    [{'text': '📋 Pastebin', 'data': 'auth_pastebin'}],
                    [{'text': '📝 Текст с кодом', 'data': 'auth_text'}],
                    [
                        {'text': '🚀 Старт', 'data': 'start_monitor'},
                        {'text': '🔄 Сброс', 'data': 'reset_all'}
                    ]
                ]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз:")
        return

    # === ЖДЁМ ТЕКСТ С КОДОМ ===
    if user_state.get(user_id, {}).get('step') == 'waiting_code_text':
        await event.reply("🔍 Анализирую текст...")
        
        # Ищем код в тексте
        code = await extract_code_from_text(text)
        
        if code:
            await event.reply(f"✅ Найден код: {code}")
            # Здесь можно автоматически вставить код
            # И продолжить процесс входа
        else:
            await event.reply("❌ Код не найден в тексте")
        
        return

    # === ЖДЁМ НОМЕР ===
    if user_state.get(user_id, {}).get('step') == 'waiting_phone':
        phone = text
        user_state[user_id] = {'step': 'waiting_code', 'phone': phone}
        
        try:
            client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await client.connect()
            sent = await client.send_code_request(phone)
            user_state[user_id]['code_hash'] = sent.phone_code_hash
            user_state[user_id]['client'] = client
            
            await send_with_inline_buttons(
                event,
                "✅ **Код отправлен!**\n\n"
                "Ты можешь:\n"
                "• Ввести код вручную\n"
                "• Отправить текст с кодом (я найду сам)\n"
                "• Отправить файл с кодом",
                [
                    [{'text': '📝 Отправить текст с кодом', 'data': 'auth_text'}],
                    [{'text': '🔄 Новый код', 'data': 'resend_code'}],
                    [{'text': '❌ Отмена', 'data': 'reset_all'}]
                ]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        return

    # === ЖДЁМ КОД ===
    if user_state.get(user_id, {}).get('step') == 'waiting_code':
        code = text
        state = user_state[user_id]
        
        try:
            await state['client'].sign_in(state['phone'], code, phone_code_hash=state['code_hash'])
            user_client = state['client']
            me = await user_client.get_me()
            
            await send_with_inline_buttons(
                event,
                f"✅ **Успешный вход!**\n\n👤 Аккаунт: @{me.username}\n\n"
                f"Нажми '🚀 Старт' для начала мониторинга:",
                [
                    [{'text': '🚀 Старт', 'data': 'start_monitor'}],
                    [{'text': '📊 Статистика', 'data': 'show_stats'}]
                ]
            )
            
        except SessionPasswordNeededError:
            user_state[user_id]['step'] = 'waiting_2fa'
            await event.reply("🔐 Требуется пароль 2FA. Введи его:")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        return

    # === ЖДЁМ ССЫЛКУ ===
    if user_state.get(user_id, {}).get('step') in ['waiting_yadisk_link', 'waiting_google_link', 'waiting_pastebin_link']:
        await event.reply("🔄 Загружаю файл...")
        
        content = None
        step = user_state[user_id]['step']
        
        if step == 'waiting_yadisk_link':
            content = await download_from_yadisk(text)
        elif step == 'waiting_google_link':
            content = await download_from_google_drive(text)
        elif step == 'waiting_pastebin_link':
            content = await download_from_pastebin(text)
        
        if content:
            # Ищем сессию или код в загруженном файле
            session = await extract_session_from_text(content)
            code = await extract_code_from_text(content)
            
            if session:
                try:
                    client = TelegramClient(StringSession(session), API_ID, API_HASH)
                    await client.connect()
                    if await client.is_user_authorized():
                        user_client = client
                        me = await client.get_me()
                        await event.reply(f"✅ Вход по сессии выполнен! Аккаунт: @{me.username}")
                except Exception as e:
                    await event.reply(f"❌ Ошибка сессии: {e}")
            
            elif code:
                await event.reply(f"✅ Найден код: {code}")
                # Здесь можно продолжить вход
            else:
                await event.reply("❌ Ни сессия, ни код не найдены в файле")
        else:
            await event.reply("❌ Не удалось загрузить файл")
        
        user_state[user_id]['step'] = 'done'
        return

# === ОБРАБОТКА ФАЙЛОВ ===
@bot.on(events.NewMessage)
async def file_handler(event):
    user_id = event.sender_id
    
    global target_id, user_client
    
    if user_id not in authorized_users:
        return
    
    if user_state.get(user_id, {}).get('step') == 'waiting_session_file' and event.message.document:
        await event.reply("📥 Анализирую файл...")
        
        try:
            path = await event.message.download_media()
            
            # Пробуем разные кодировки
            content = None
            encodings = ['utf-8', 'cp1251', 'latin-1', 'ascii', 'utf-16']
            
            for enc in encodings:
                try:
                    with open(path, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except:
                    continue
            
            if not content:
                # Пробуем как бинарный
                with open(path, 'rb') as f:
                    binary = f.read()
                    try:
                        content = binary.decode('utf-8')
                    except:
                        content = str(binary)
            
            # Ищем сессию
            session = await extract_session_from_text(content)
            
            if session:
                try:
                    client = TelegramClient(StringSession(session), API_ID, API_HASH)
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        user_client = client
                        me = await client.get_me()
                        
                        await send_with_inline_buttons(
                            event,
                            f"✅ **Вход по файлу выполнен!**\n\n👤 Аккаунт: @{me.username}",
                            [
                                [{'text': '🚀 Старт', 'data': 'start_monitor'}],
                                [{'text': '📊 Статистика', 'data': 'show_stats'}]
                            ]
                        )
                    else:
                        await event.reply("❌ Сессия недействительна")
                except Exception as e:
                    await event.reply(f"❌ Ошибка сессии: {e}")
            else:
                # Ищем код
                code = await extract_code_from_text(content)
                if code:
                    await event.reply(f"✅ В файле найден код: {code}")
                else:
                    await event.reply("❌ В файле не найдено ни сессии, ни кода")
            
            os.remove(path)
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        
        user_state[user_id]['step'] = 'done'

# === МОНИТОРИНГ ===
async def monitor_chats(user_id):
    global user_client, target_id, message_cache, deleted_log
    
    if not user_client or not target_id:
        return
    
    settings = user_settings.get(user_id, DEFAULT_SETTINGS.copy())
    
    # Проверяем рабочее время
    if settings['work_mode'] == 'rest':
        await bot.send_message(target_id, "😴 Режим отдыха. Мониторинг приостановлен.")
        return
    elif settings['work_mode'] == 'balanced' and not is_work_time():
        await bot.send_message(target_id, "😴 Сейчас нерабочее время. Мониторинг приостановлен.")
        return
    
    await bot.send_message(target_id, "🔍 **Мониторинг запущен!**")
    
    @user_client.on(events.NewMessage)
    async def msg_handler(event):
        if event.message.text:
            cache_key = f"{event.chat_id}_{event.message.id}"
            message_cache[cache_key] = {
                'text': event.message.text,
                'time': datetime.now().isoformat(),
                'from_id': event.sender_id
            }
            
            # Ограничиваем кэш
            if len(message_cache) > 1000:
                keys = list(message_cache.keys())[:200]
                for k in keys:
                    del message_cache[k]
    
    @user_client.on(events.MessageDeleted)
    async def del_handler(event):
        if not settings['monitor_deleted']:
            return
            
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                deleted_log.append({
                    'time': datetime.now().isoformat(),
                    'text': msg['text'],
                    'from_id': msg['from_id']
                })
                
                await bot.send_message(
                    target_id,
                    f"🗑 **Удалено сообщение**\n\n"
                    f"👤 От: {msg['from_id']}\n"
                    f"📝 {msg['text'][:200]}"
                )
    
    @user_client.on(events.MessageEdited)
    async def edit_handler(event):
        if not settings['monitor_edited']:
            return
            
        cache_key = f"{event.chat_id}_{event.message.id}"
        if cache_key in message_cache:
            old = message_cache[cache_key]['text']
            new = event.message.text
            if old != new:
                await bot.send_message(
                    target_id,
                    f"✏️ **Изменено сообщение**\n\n"
                    f"📝 Было: {old[:200]}\n"
                    f"📝 Стало: {new[:200]}"
                )
                message_cache[cache_key]['text'] = new
    
    await user_client.run_until_disconnected()

# ========== ЗАПУСК ==========
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: {ACCESS_PIN}")
    logger.info("💼 Режимы: работа/отдых/баланс")
    logger.info("📁 Поддерживаются: файлы, ссылки, текст с кодом")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())