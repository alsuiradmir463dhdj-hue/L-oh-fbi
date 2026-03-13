import os
import asyncio
import logging
import requests
import re
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
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
        # Получаем прямой URL для скачивания
        if 'yadi.sk' in url or 'disk.yandex' in url:
            # Конвертируем ссылку в прямую
            if 'yadi.sk' in url:
                # Короткие ссылки yadi.sk
                response = requests.get(url, allow_redirects=True)
                if response.url:
                    # Извлекаем публичный ключ
                    match = re.search(r'/public/(\?)', response.url)
                    if match:
                        pub_key = match.group(1)
                        download_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={pub_key}"
                    else:
                        # Альтернативный метод
                        download_url = url.replace('yadi.sk', 'disk.yandex.ru') + '&download=1'
                else:
                    download_url = url + '&download=1'
            else:
                # Прямые ссылки disk.yandex
                download_url = url + '&download=1'
            
            # Скачиваем файл
            response = requests.get(download_url, stream=True)
            
            if response.status_code == 200:
                # Сохраняем во временный файл
                filename = f"temp_session_{datetime.now().timestamp()}.session"
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Читаем содержимое
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                # Удаляем временный файл
                os.remove(filename)
                
                return content
            else:
                return None
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка загрузки с Я.Диска: {e}")
        return None

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
            "1️⃣ Сначала введи ID получателя (например 7396285844)\n"
            "2️⃣ Потом выбери способ входа"
        )
        user_state[user_id] = {'step': 'waiting_target'}
        return

    # === ЖДЁМ ID ===
    if user_state.get(user_id, {}).get('step') == 'waiting_target':
        try:
            target = await bot.get_entity(text)
            target_id = target.id
            user_state[user_id] = {'step': 'waiting_auth_method'}
            await event.reply(
                f"✅ Получатель: {target.first_name}\n\n"
                f"**Выбери способ входа:**",
                buttons=[
                    [Button.text("📞 По номеру")],
                    [Button.text("📁 Файл сессии")],
                    [Button.text("☁️ Ссылка с Яндекс Диска")]
                ]
            )
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз:")
        return

    # === ВЫБОР СПОСОБА ===
    if text == "📞 По номеру":
        user_state[user_id] = {'step': 'waiting_phone'}
        await event.reply("📞 Введи номер в формате +79001234567")
        return

    if text == "📁 Файл сессии":
        user_state[user_id] = {'step': 'waiting_session_file'}
        await event.reply("📁 Отправь файл сессии")
        return

    if text == "☁️ Ссылка с Яндекс Диска":
        user_state[user_id] = {'step': 'waiting_yadisk_link'}
        await event.reply(
            "☁️ **Отправь ссылку на файл с Яндекс Диска**\n\n"
            "Примеры:\n"
            "• https://yadi.sk/d/abcdef123456\n"
            "• https://disk.yandex.ru/d/abcdef123456"
        )
        return

    # === ЖДЁМ ССЫЛКУ С ЯНДЕКС ДИСКА ===
    if user_state.get(user_id, {}).get('step') == 'waiting_yadisk_link':
        await event.reply("🔄 Загружаю файл с Яндекс Диска...")
        
        # Скачиваем содержимое
        content = await download_from_yadisk(text)
        
        if content:
            try:
                # Пробуем создать сессию
                client = TelegramClient(StringSession(content), API_ID, API_HASH)
                await client.connect()
                
                if await client.is_user_authorized():
                    user_client = client
                    me = await client.get_me()
                    await event.reply(f"✅ **Успешный вход!**\n\n👤 Аккаунт: @{me.username}")
                    
                    if target_id:
                        asyncio.create_task(monitor_chats(user_id))
                else:
                    await event.reply("❌ Сессия недействительна")
            except Exception as e:
                await event.reply(f"❌ Ошибка: {e}")
        else:
            await event.reply("❌ Не удалось загрузить файл с Яндекс Диска")
        
        user_state[user_id]['step'] = 'done'
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
            await event.reply("✅ Код отправлен! Введи его (у тебя 2 минуты):")
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
            await event.reply(f"✅ **Вход выполнен!**\n\n👤 Аккаунт: @{me.username}")
            
            if target_id:
                asyncio.create_task(monitor_chats(user_id))
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
            await event.reply(f"✅ **Вход с 2FA выполнен!**\n\n👤 Аккаунт: @{me.username}")
            
            if target_id:
                asyncio.create_task(monitor_chats(user_id))
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")
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
            # Скачиваем файл
            path = await event.message.download_media()
            
            # Читаем как текст
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # Пробуем создать сессию
            client = TelegramClient(StringSession(content), API_ID, API_HASH)
            await client.connect()
            
            if await client.is_user_authorized():
                user_client = client
                me = await client.get_me()
                await event.reply(f"✅ **Вход по сессии выполнен!**\n\n👤 Аккаунт: @{me.username}")
                
                if target_id:
                    asyncio.create_task(monitor_chats(user_id))
            else:
                await event.reply("❌ Сессия недействительна")
            
            # Удаляем временный файл
            os.remove(path)
            
        except Exception as e:
            await event.reply(f"❌ Ошибка загрузки: {e}")
        
        user_state[user_id]['step'] = 'done'

# === МОНИТОРИНГ ===
async def monitor_chats(user_id):
    global user_client, target_id
    
    if not user_client or not target_id:
        return
    
    await bot.send_message(target_id, "🔍 **Мониторинг запущен!**\n\nБот отслеживает удалённые и изменённые сообщения.")
    
    @user_client.on(events.MessageDeleted)
    async def del_handler(event):
        await bot.send_message(target_id, f"🗑 **Удалено** {len(event.deleted_ids)} сообщений")
    
    @user_client.on(events.MessageEdited)
    async def edit_handler(event):
        await bot.send_message(target_id, f"✏️ **Изменено** сообщение")
    
    @user_client.on(events.NewMessage)
    async def msg_handler(event):
        # Кэшируем для будущих удалений
        pass
    
    await user_client.run_until_disconnected()

# === ЗАПУСК ===
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен! Пин-код: {ACCESS_PIN}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())