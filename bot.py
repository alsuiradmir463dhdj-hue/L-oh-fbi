import os
import asyncio
import logging
import requests
import re
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.custom import Button
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

bot = TelegramClient('bot', API_ID, API_HASH)

# Состояния
user_state = {}
user_client = None
target_id = None

# Пин-код
ACCESS_PIN = "5482"
authorized_users = set()

# ========== ФУНКЦИЯ ЗАГРУЗКИ С ЯНДЕКС ДИСКА ==========
async def download_from_yadisk(url):
    """Скачивает файл с Яндекс Диска по ссылке"""
    try:
        if 'yadi.sk' in url or 'disk.yandex' in url:
            # Конвертируем в прямую ссылку для скачивания
            if 'yadi.sk' in url:
                # Получаем реальный URL
                response = requests.get(url, allow_redirects=True)
                file_id = re.search(r'/d/([a-zA-Z0-9_-]+)', response.url)
                if file_id:
                    direct_url = f"https://disk.yandex.ru/d/{file_id.group(1)}?download=1"
                else:
                    direct_url = url.replace('yadi.sk', 'disk.yandex.ru') + '&download=1'
            else:
                direct_url = url + '&download=1'
            
            # Скачиваем
            response = requests.get(direct_url, stream=True)
            if response.status_code == 200:
                filename = f"temp_session_{datetime.now().timestamp()}.session"
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                os.remove(filename)
                return content
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")
        return None

# ========== INLINE КНОПКИ ДЛЯ СООБЩЕНИЙ ==========
async def send_with_inline_buttons(event, text, buttons_data):
    """Отправляет сообщение с inline кнопками"""
    buttons = []
    for row in buttons_data:
        button_row = []
        for btn in row:
            # Создаём inline кнопку с callback данными
            button_row.append(Button.inline(btn['text'], data=btn['data'].encode()))
        buttons.append(button_row)
    
    await event.reply(text, buttons=buttons)

# ========== ОБРАБОТЧИК INLINE КНОПОК ==========
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    """Обрабатывает нажатия на inline кнопки"""
    user_id = event.sender_id
    data = event.data.decode()
    
    # Проверяем пин-код
    if user_id not in authorized_users:
        await event.answer("❌ Сначала введи пин-код", alert=True)
        return
    
    # Обрабатываем разные callback данные
    if data == "auth_phone":
        user_state[user_id] = {'step': 'waiting_phone'}
        await event.edit("📞 Введи номер в формате +79001234567")
        await event.answer()
        
    elif data == "auth_file":
        user_state[user_id] = {'step': 'waiting_session_file'}
        await event.edit("📁 Отправь файл сессии")
        await event.answer()
        
    elif data == "auth_yadisk":
        user_state[user_id] = {'step': 'waiting_yadisk_link'}
        await event.edit(
            "☁️ **Отправь ссылку на файл с Яндекс Диска**\n\n"
            "Пример: https://yadi.sk/d/abcdef123456"
        )
        await event.answer()
        
    elif data == "start_monitor":
        if target_id:
            await event.edit("🔍 Запускаю мониторинг...")
            asyncio.create_task(monitor_chats(user_id))
        else:
            await event.edit("❌ Сначала введи ID получателя через /start")
        await event.answer()
        
    elif data == "reset_all":
        # Сброс всех настроек
        global target_id, user_client
        target_id = None
        user_client = None
        user_state[user_id] = {'step': 'waiting_target'}
        await event.edit("🔄 Настройки сброшены. Введи ID получателя через /start")
        await event.answer()
        
    elif data == "help_menu":
        help_text = (
            "📚 **Помощь**\n\n"
            "• /start - начать настройку\n"
            "• Введи ID получателя\n"
            "• Выбери способ входа\n"
            "• После входа начнётся мониторинг"
        )
        await event.edit(help_text)
        await event.answer()

@bot.on(events.NewMessage)
async def handler(event):
    global user_client, target_id
    
    user_id = event.sender_id
    text = event.message.text.strip()

    # === ПИН-КОД ===
    if user_id not in authorized_users:
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            await event.reply("✅ Доступ разрешён! Используй /start")
        else:
            await event.reply("🔐 Введите пин-код (5482):")
        return

    # === КОМАНДЫ ===
    if text == "/start":
        await event.reply(
            "👋 **Бот для мониторинга**\n\n"
            "📝 **Введи ID или username пользователя**,\n"
            "которому будут приходить уведомления.\n\n"
            "Примеры:\n"
            "• ID: `7396285844`\n"
            "• Username: `@durov`"
        )
        user_state[user_id] = {'step': 'waiting_target'}
        return

    # === ЖДЁМ ID ===
    if user_state.get(user_id, {}).get('step') == 'waiting_target':
        try:
            target = await bot.get_entity(text)
            target_id = target.id
            user_state[user_id] = {'step': 'waiting_auth_method'}
            
            # Отправляем inline кнопки прямо в сообщении
            await send_with_inline_buttons(
                event,
                f"✅ **Получатель:** {target.first_name}\n\n"
                f"**Выбери способ входа:**",
                [
                    [{'text': '📞 По номеру', 'data': 'auth_phone'}],
                    [{'text': '📁 Файл сессии', 'data': 'auth_file'}],
                    [{'text': '☁️ Яндекс Диск', 'data': 'auth_yadisk'}],
                    [
                        {'text': '🚀 Старт', 'data': 'start_monitor'},
                        {'text': '🔄 Сброс', 'data': 'reset_all'},
                        {'text': '❓ Помощь', 'data': 'help_menu'}
                    ]
                ]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз:")
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
                "✅ **Код отправлен!**\n\nВведи код из Telegram:",
                [
                    [{'text': '🔄 Отправить новый код', 'data': 'resend_code'}],
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

    # === ЖДЁМ 2FA ===
    if user_state.get(user_id, {}).get('step') == 'waiting_2fa':
        password = text
        state = user_state[user_id]
        
        try:
            await state['client'].sign_in(password=password)
            user_client = state['client']
            me = await user_client.get_me()
            
            await send_with_inline_buttons(
                event,
                f"✅ **Вход с 2FA выполнен!**\n\n👤 Аккаунт: @{me.username}\n\n"
                f"Нажми '🚀 Старт' для начала мониторинга:",
                [
                    [{'text': '🚀 Старт', 'data': 'start_monitor'}],
                    [{'text': '📊 Статистика', 'data': 'show_stats'}]
                ]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
        return

    # === ЖДЁМ ССЫЛКУ С ЯНДЕКС ДИСКА ===
    if user_state.get(user_id, {}).get('step') == 'waiting_yadisk_link':
        await event.reply("🔄 Загружаю файл с Яндекс Диска...")
        
        content = await download_from_yadisk(text)
        
        if content:
            try:
                client = TelegramClient(StringSession(content), API_ID, API_HASH)
                await client.connect()
                
                if await client.is_user_authorized():
                    user_client = client
                    me = await client.get_me()
                    
                    await send_with_inline_buttons(
                        event,
                        f"✅ **Успешный вход по ссылке!**\n\n👤 Аккаунт: @{me.username}\n\n"
                        f"Нажми '🚀 Старт' для начала мониторинга:",
                        [
                            [{'text': '🚀 Старт', 'data': 'start_monitor'}],
                            [{'text': '📊 Статистика', 'data': 'show_stats'}]
                        ]
                    )
                else:
                    await event.reply("❌ Сессия недействительна")
            except Exception as e:
                await event.reply(f"❌ Ошибка: {e}")
        else:
            await event.reply("❌ Не удалось загрузить файл с Яндекс Диска")
        
        user_state[user_id]['step'] = 'done'
        return

# === ОБРАБОТКА ФАЙЛОВ ===
@bot.on(events.NewMessage)
async def file_handler(event):
    global user_client, target_id
    
    user_id = event.sender_id
    
    if user_id not in authorized_users:
        return
    
    if user_state.get(user_id, {}).get('step') == 'waiting_session_file' and event.message.document:
        await event.reply("📥 Загружаю файл...")
        
        try:
            path = await event.message.download_media()
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            client = TelegramClient(StringSession(content), API_ID, API_HASH)
            await client.connect()
            
            if await client.is_user_authorized():
                user_client = client
                me = await client.get_me()
                
                await send_with_inline_buttons(
                    event,
                    f"✅ **Вход по файлу выполнен!**\n\n👤 Аккаунт: @{me.username}\n\n"
                    f"Нажми '🚀 Старт' для начала мониторинга:",
                    [
                        [{'text': '🚀 Старт', 'data': 'start_monitor'}],
                        [{'text': '📊 Статистика', 'data': 'show_stats'}]
                    ]
                )
            else:
                await event.reply("❌ Сессия недействительна")
            
            os.remove(path)
            
        except Exception as e:
            await event.reply(f"❌ Ошибка загрузки: {e}")
        
        user_state[user_id]['step'] = 'done'

# === МОНИТОРИНГ ===
async def monitor_chats(user_id):
    global user_client, target_id
    
    if not user_client or not target_id:
        return
    
    await bot.send_message(target_id, "🔍 **Мониторинг запущен!**")
    
    @user_client.on(events.MessageDeleted)
    async def del_handler(event):
        await bot.send_message(target_id, f"🗑 **Удалено** {len(event.deleted_ids)} сообщений")
    
    @user_client.on(events.MessageEdited)
    async def edit_handler(event):
        await bot.send_message(target_id, f"✏️ **Изменено** сообщение")
    
    await user_client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: {ACCESS_PIN}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())