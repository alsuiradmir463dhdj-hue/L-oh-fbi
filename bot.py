import os
import asyncio
import logging
import traceback
import re
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    MessageNotModifiedError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    FloodWaitError,
    RPCError
)
from telethon.tl.custom import Button
from telethon.sessions import StringSession
import nest_asyncio
import random

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID'))
API_HASH = os.environ.get('API_HASH')

# ПИН-КОД ДЛЯ ДОСТУПА К БОТУ
ACCESS_PIN = "5482"

# ========== КЛИЕНТЫ ==========
bot = TelegramClient('bot_session', API_ID, API_HASH)
user_client = None

# ========== СОСТОЯНИЯ ==========
authorized_users = set()
waiting_for_pin = {}

waiting_for_target = False
target_id = None
waiting_for_phone = False
phone_number = None
waiting_for_code = False
code_hash = None
waiting_for_password = False
temp_password_phone = None
waiting_for_session_string = False  # Ожидание строки сессии
waiting_for_session_file = False     # Ожидание файла сессии

message_cache = {}
current_animation_msg = None

# ========== АВТО-ИСПРАВЛЕНИЕ ОШИБОК ==========
class ErrorFixer:
    """Автоматически исправляет ошибки без доступа к личным данным"""
    
    def __init__(self):
        self.error_patterns = {
            'flood': self.handle_flood,
            'connection': self.handle_connection,
            'timeout': self.handle_timeout,
            'not modified': self.ignore_error,
            'expired': self.handle_expired,
            'invalid': self.handle_invalid,
        }
        self.error_count = 0
        self.last_error_time = None
    
    def analyze_error(self, error_text, user_id=None):
        """Анализирует ошибку и возвращает рекомендацию"""
        
        # Логируем ошибку без личных данных
        safe_error = self._clean_error(error_text)
        logger.warning(f"⚠️ Ошибка для пользователя {user_id}: {safe_error[:200]}")
        
        self.error_count += 1
        self.last_error_time = datetime.now()
        
        # Ищем паттерн
        for pattern, handler in self.error_patterns.items():
            if pattern in error_text.lower():
                return handler(error_text)
        
        # Если ничего не нашли
        return {
            'action': 'restart',
            'message': 'Неизвестная ошибка, выполняю перезапуск',
            'delay': 5
        }
    
    def _clean_error(self, error_text):
        """Удаляет личные данные из ошибки"""
        # Удаляем номера телефонов
        error_text = re.sub(r'\+\d{10,15}', '[PHONE]', error_text)
        # Удаляем ID
        error_text = re.sub(r'\b\d{8,}\b', '[ID]', error_text)
        # Удаляем хэши
        error_text = re.sub(r'[a-f0-9]{32,}', '[HASH]', error_text)
        return error_text
    
    def handle_flood(self, error):
        """Обработка FloodWait"""
        import re
        wait_time = re.search(r'(\d+)', error)
        seconds = int(wait_time.group(1)) if wait_time else 30
        
        return {
            'action': 'wait',
            'message': f'Слишком много запросов, ожидание {seconds} секунд',
            'delay': min(seconds, 60)
        }
    
    def handle_connection(self, error):
        """Проблемы с соединением"""
        return {
            'action': 'reconnect',
            'message': 'Проблема с соединением, переподключаюсь',
            'delay': 5
        }
    
    def handle_timeout(self, error):
        """Таймаут"""
        return {
            'action': 'retry',
            'message': 'Таймаут, пробую снова',
            'delay': 3
        }
    
    def handle_expired(self, error):
        """Истекший код/сессия"""
        return {
            'action': 'resend',
            'message': 'Код истёк, запросите новый',
            'delay': 0
        }
    
    def handle_invalid(self, error):
        """Неверные данные"""
        return {
            'action': 'notify',
            'message': 'Неверный код или данные, попробуйте ещё раз',
            'delay': 0
        }
    
    def ignore_error(self, error):
        """Игнорируем ошибку (например, not modified)"""
        return {
            'action': 'ignore',
            'message': None,
            'delay': 0
        }

# Создаём экземпляр авто-исправления
error_fixer = ErrorFixer()

# ========== ДЕКОРАТОР ДЛЯ АВТО-ИСПРАВЛЕНИЯ ==========
def auto_fix_errors(func):
    """Декоратор для автоматического исправления ошибок"""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            # Специальная обработка FloodWait
            fix = error_fixer.handle_flood(str(e))
            logger.warning(f"🌊 FloodWait: {fix['message']}")
            await asyncio.sleep(e.seconds)
            return await func(*args, **kwargs)
            
        except (ConnectionError, TimeoutError) as e:
            fix = error_fixer.analyze_error(str(e))
            logger.warning(f"🔌 {fix['message']}")
            await asyncio.sleep(fix['delay'])
            return await func(*args, **kwargs)
            
        except Exception as e:
            # Анализируем ошибку
            fix = error_fixer.analyze_error(str(e))
            
            if fix['action'] == 'ignore':
                # Игнорируем
                return None
                
            elif fix['action'] == 'notify':
                # Отправляем уведомление пользователю
                if args and hasattr(args[0], 'reply'):
                    await args[0].reply(f"⚠️ {fix['message']}")
                return None
                
            elif fix['delay'] > 0:
                # Ждём и пробуем снова
                logger.info(f"⏳ {fix['message']}")
                await asyncio.sleep(fix['delay'])
                return await func(*args, **kwargs)
            
            # Если ничего не помогло, пробрасываем ошибку дальше
            raise
    
    return wrapper

# ========== ФУНКЦИЯ АНИМАЦИИ ==========
async def show_loading_animation(event, text="⏳ Обработка", category="random", duration=2):
    frames = {
        "random": ["⭐", "🌟", "✨", "💫"],
        "stars": ["⭐", "🌟", "✨", "💫"],
        "time": ["🕐", "🕑", "🕒", "🕓"],
        "hearts": ["❤️", "🧡", "💛", "💚"],
        "key": ["🔑", "🗝️", "🔐", "🔒"],
        "file": ["📄", "📁", "📂", "🗂️"],
    }.get(category, ["⭐", "🌟", "✨", "💫"])
    
    msg = await event.reply(f"{frames[0]} {text}...")
    
    try:
        for i in range(duration):
            for frame in frames:
                new_text = f"{frame} {text}..."
                if msg.text != new_text:
                    await msg.edit(new_text)
                await asyncio.sleep(0.3)
    except MessageNotModifiedError:
        pass
    
    return msg

# ========== ПРОВЕРКА ПИН-КОДА ==========
@auto_fix_errors
async def check_pin_access(event):
    user_id = event.sender_id
    
    if user_id in authorized_users:
        return True
    
    if user_id in waiting_for_pin:
        text = event.message.text.strip()
        if text == ACCESS_PIN:
            authorized_users.add(user_id)
            del waiting_for_pin[user_id]
            await event.reply("✅ **Пин-код верный! Доступ разрешён.**\n\nИспользуй /start для начала работы.")
            return True
        else:
            await event.reply("❌ **Неверный пин-код.** Попробуй ещё раз:")
            return False
    
    waiting_for_pin[user_id] = True
    await event.reply("🔐 **Введите пин-код для доступа к боту:**\n\n💡 Подсказка: **5482**")
    return False

# ========== ОБРАБОТЧИК СТРОКИ СЕССИИ ==========
@auto_fix_errors
async def process_session_string(user_id, session_string, event):
    """Обрабатывает строку сессии и входит в аккаунт"""
    global user_client
    
    anim = await show_loading_animation(event, "🔑 Вход по сессии", "key", 3)
    
    try:
        # Проверяем, похоже ли на строку сессии
        if len(session_string) < 50:
            await anim.edit("❌ **Строка слишком короткая.** Это не похоже на сессию.")
            return False
        
        # Создаём клиента из строки
        user_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await user_client.connect()
        
        # Проверяем, работает ли сессия
        if await user_client.is_user_authorized():
            me = await user_client.get_me()
            await anim.edit(
                f"✅ **Успешный вход по строке сессии!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"🆔 ID: {me.id}\n\n"
                f"🔍 **Мониторинг готов к запуску.**"
            )
            
            # Если target_id уже задан, запускаем мониторинг
            if target_id:
                asyncio.create_task(monitor_user_chats(user_id))
            else:
                await event.reply("📝 Теперь введи ID получателя уведомлений (/start)")
            
            return True
        else:
            await anim.edit("❌ **Строка сессии недействительна или истекла.**")
            return False
            
    except Exception as e:
        await anim.edit(f"❌ **Ошибка входа:** {str(e)[:100]}")
        return False

# ========== ОБРАБОТЧИК ФАЙЛОВ ==========
@bot.on(events.NewMessage)
@auto_fix_errors
async def file_handler(event):
    """Обработка загруженных файлов (сессий)"""
    global user_client, target_id, waiting_for_session_file
    
    user_id = event.sender_id
    
    # Проверка пин-кода
    if user_id not in authorized_users:
        await check_pin_access(event)
        return
    
    # Если есть документ
    if event.message.document:
        if waiting_for_session_file:
            anim = await show_loading_animation(event, "📥 Загрузка файла сессии", "file", 2)
            
            try:
                # Скачиваем файл
                file_path = await event.message.download_media(file="temp_session.session")
                
                # Пробуем прочитать как текст
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    
                    # Если это похоже на строку сессии
                    if len(content) > 50 and not content.startswith('\x00'):
                        await process_session_string(user_id, content, event)
                        waiting_for_session_file = False
                        return
                except:
                    pass
                
                # Если не текст, пробуем как бинарную сессию
                try:
                    user_client = TelegramClient(StringSession(file_path), API_ID, API_HASH)
                    await user_client.connect()
                    
                    if await user_client.is_user_authorized():
                        me = await user_client.get_me()
                        await anim.edit(
                            f"✅ **Успешный вход по файлу сессии!**\n\n"
                            f"👤 Аккаунт: @{me.username}\n"
                            f"🆔 ID: {me.id}"
                        )
                        
                        if target_id:
                            asyncio.create_task(monitor_user_chats(user_id))
                    else:
                        await anim.edit("❌ **Файл сессии недействителен.**")
                        
                except Exception as e:
                    await anim.edit(f"❌ **Ошибка:** {str(e)[:100]}")
                
                # Удаляем временный файл
                try:
                    os.remove(file_path)
                except:
                    pass
                
            except Exception as e:
                await anim.edit(f"❌ **Ошибка загрузки:** {str(e)[:100]}")
            
            waiting_for_session_file = False
            return

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
@bot.on(events.NewMessage)
@auto_fix_errors
async def handler(event):
    global waiting_for_target, target_id, waiting_for_phone, phone_number
    global waiting_for_code, code_hash, waiting_for_password, temp_password_phone
    global user_client, waiting_for_session_string, waiting_for_session_file
    
    user_id = event.sender_id
    text = event.message.text.strip() if event.message.text else ""

    # === 0. ПРОВЕРКА ПИН-КОДА ===
    if user_id not in authorized_users:
        await check_pin_access(event)
        return

    # === 1. ЕСЛИ ЖДЁМ СТРОКУ СЕССИИ ===
    if waiting_for_session_string:
        waiting_for_session_string = False
        await process_session_string(user_id, text, event)
        return

    # === 2. ЕСЛИ ЖДЁМ ID ПОЛУЧАТЕЛЯ ===
    if waiting_for_target:
        try:
            anim = await show_loading_animation(event, "🔍 Поиск пользователя", "stars", 2)
            target = await bot.get_entity(text)
            target_id = target.id
            waiting_for_target = False
            
            target_name = getattr(target, 'first_name', 'пользователь')
            if hasattr(target, 'username') and target.username:
                target_name += f" (@{target.username})"
            
            new_text = (
                f"✅ **ID получателя сохранён!**\n\n"
                f"📬 Все уведомления будут отправляться:\n"
                f"👤 {target_name} (ID: {target_id})\n\n"
                f"🔑 **Теперь нужно войти в аккаунт.**\n\n"
                f"Выбери способ:"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
            # Предлагаем выбор
            await event.reply(
                "🔐 **Способ входа:**",
                buttons=[
                    [Button.text("📞 По номеру")],
                    [Button.text("📁 Загрузить файл сессии")],
                    [Button.text("✍️ Вставить строку сессии")]
                ]
            )
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}\nПопробуй ещё раз (ID или @username):")
        return

    # === 3. ВЫБОР СПОСОБА ВХОДА ===
    if text == "📞 По номеру":
        waiting_for_phone = True
        await event.reply("📞 **Отправь свой номер телефона** в формате:\n`+79001234567`")
        return
    
    if text == "📁 Загрузить файл сессии":
        waiting_for_session_file = True
        await event.reply("📁 **Отправь файл сессии** (`.session` или текстовый файл со строкой)")
        return
    
    if text == "✍️ Вставить строку сессии":
        waiting_for_session_string = True
        await event.reply("✍️ **Вставь строку сессии** (длинный текст, который начинается с `1...` или `ey...`)")
        return

    # === 4. ЕСЛИ ЖДЁМ НОМЕР ТЕЛЕФОНА ===
    if waiting_for_phone:
        phone_number = text
        waiting_for_phone = False
        waiting_for_code = True
        
        anim = await show_loading_animation(event, "📨 Отправка кода", "time", 2)
        
        try:
            user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                sent_code = await user_client.send_code_request(phone_number)
                code_hash = sent_code.phone_code_hash
                
                new_text = (
                    f"✅ **Код отправлен!**\n\n"
                    f"📨 Код подтверждения отправлен в Telegram.\n"
                    f"⏳ **У тебя есть 2 минуты**\n"
                    f"✍️ Отправь мне код цифрами:"
                )
            else:
                me = await user_client.get_me()
                new_text = (
                    f"✅ **Уже авторизован!**\n\n"
                    f"👤 Аккаунт: @{me.username}\n"
                    f"🔍 Начинаю мониторинг..."
                )
                waiting_for_code = False
                asyncio.create_task(monitor_user_chats(user_id))
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
        except Exception as e:
            error_text = f"❌ Ошибка: {e}\nПопробуй ещё раз /start"
            if anim.text != error_text:
                await anim.edit(error_text)
            waiting_for_code = False
        return

    # === 5. ЕСЛИ ЖДЁМ КОД ===
    if waiting_for_code:
        code = text
        
        try:
            anim = await show_loading_animation(event, "🔑 Проверка кода", "hearts", 2)
            
            if not user_client:
                user_client = TelegramClient(f'user_{user_id}', API_ID, API_HASH)
                await user_client.connect()
            
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    await user_client.sign_in(phone_number, code, phone_code_hash=code_hash)
                    break
                except PhoneCodeExpiredError:
                    if attempt < max_attempts - 1:
                        await anim.edit(f"🔄 Попытка {attempt + 1}...")
                        await asyncio.sleep(1)
                    else:
                        new_text = "⌛ **Код не подходит после 3 попыток.**\n\n📨 Отправляю новый код..."
                        if anim.text != new_text:
                            await anim.edit(new_text)
                        
                        sent_code = await user_client.send_code_request(phone_number)
                        code_hash = sent_code.phone_code_hash
                        await event.reply("✅ **Новый код отправлен!**\n✍️ Введи его:")
                        waiting_for_code = True
                        return
            
            me = await user_client.get_me()
            new_text = (
                f"✅ **Успешный вход!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone_number}\n\n"
                f"🔍 **Начинаю мониторинг всех чатов...**"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
            waiting_for_code = False
            asyncio.create_task(monitor_user_chats(user_id))
            
        except SessionPasswordNeededError:
            waiting_for_password = True
            temp_password_phone = phone_number
            waiting_for_code = False
            new_text = "🔐 **Требуется двухфакторный пароль.**\n\nВведи свой пароль:"
            if anim.text != new_text:
                await anim.edit(new_text)
        except PhoneCodeInvalidError:
            new_text = "❌ **Неправильный код!**\n\nПопробуй ещё раз:"
            if anim.text != new_text:
                await anim.edit(new_text)
        except Exception as e:
            error_text = f"❌ Ошибка входа: {e}"
            if anim.text != error_text:
                await anim.edit(error_text)
            waiting_for_code = False
        return

    # === 6. ЕСЛИ ЖДЁМ 2FA ===
    if waiting_for_password:
        password = text
        phone = temp_password_phone
        
        try:
            anim = await show_loading_animation(event, "🔐 Проверка пароля", "hearts", 2)
            await user_client.sign_in(password=password)
            
            me = await user_client.get_me()
            new_text = (
                f"✅ **Успешный вход с 2FA!**\n\n"
                f"👤 Аккаунт: @{me.username}\n"
                f"📱 Номер: {phone}\n\n"
                f"🔍 **Начинаю мониторинг всех чатов...**"
            )
            
            if anim.text != new_text:
                await anim.edit(new_text)
            
            waiting_for_password = False
            temp_password_phone = None
            asyncio.create_task(monitor_user_chats(user_id))
            
        except Exception as e:
            error_text = f"❌ Ошибка: {e}\nПопробуй ещё раз:"
            if anim.text != error_text:
                await anim.edit(error_text)
        return

    # === 7. ОСНОВНЫЕ КОМАНДЫ ===
    if text == "/start":
        waiting_for_target = True
        await event.reply(
            "👋 **Добро пожаловать!**\n\n"
            "📝 **Введите ID или username пользователя**,\n"
            "которому будут приходить уведомления.\n\n"
            "Примеры:\n"
            "• ID: `7396285844`\n"
            "• Username: `@durov`\n\n"
            "📸 **Фишки:**\n"
            "• Истекающие фото/видео сохраняются\n"
            "• Удалённые сообщения ловятся\n"
            "• Вход: по номеру / по файлу / по строке\n"
            "• Авто-исправление ошибок"
        )
    
    elif text == "/stats":
        target_info = f"ID: {target_id}" if target_id else "не задан"
        await event.reply(
            f"📊 **Статистика**\n\n"
            f"📦 Кэш сообщений: {len(message_cache)}\n"
            f"📬 Получатель: {target_info}\n"
            f"👤 Аккаунт: {'авторизован' if user_client else 'не авторизован'}\n"
            f"🔧 Ошибок обработано: {error_fixer.error_count}"
        )
    
    elif text == "/reset":
        waiting_for_target = True
        target_id = None
        waiting_for_phone = False
        phone_number = None
        waiting_for_code = False
        code_hash = None
        waiting_for_password = False
        waiting_for_session_string = False
        waiting_for_session_file = False
        if user_client:
            await user_client.disconnect()
            user_client = None
        await event.reply("🔄 **Настройки сброшены.**\nВведи ID получателя:")
    
    elif text == "/pin":
        await event.reply(f"🔐 Твой пин-код: **{ACCESS_PIN}**")

# ========== МОНИТОРИНГ ЧАТОВ ==========
async def monitor_user_chats(user_id):
    global user_client, target_id, message_cache
    
    if not user_client or not target_id:
        logger.error("Нет клиента или получателя")
        return
    
    logger.info(f"🔍 Начинаю мониторинг, уведомления в {target_id}")
    
    await bot.send_message(
        target_id,
        "✅ **Мониторинг запущен!**\n\n"
        "📸 Истекающие медиа сохраняются\n"
        "🗑 Удалённые сообщения\n"
        "✏️ Изменённые сообщения"
    )
    
    @auto_fix_errors
    @user_client.on(events.NewMessage)
    async def message_handler(event):
        cache_key = f"{event.chat_id}_{event.message.id}"
        is_expiring = hasattr(event.message, 'ttl_seconds') and event.message.ttl_seconds
        
        # Сохраняем в кэш
        message_cache[cache_key] = {
            'text': event.message.text or "[медиа]",
            'time': datetime.now().isoformat(),
            'chat_id': event.chat_id,
            'sender_id': event.sender_id
        }
        
        # Если истекающее медиа
        if is_expiring and (event.message.photo or event.message.video):
            try:
                file_path = await event.message.download_media()
                if file_path:
                    await bot.send_file(target_id, file_path, caption="📸 Истекающее медиа (сохранено)")
                    try:
                        os.remove(file_path)
                    except:
                        pass
            except:
                pass

    @auto_fix_errors
    @user_client.on(events.MessageDeleted)
    async def delete_handler(event):
        for msg_id in event.deleted_ids:
            cache_key = f"{event.chat_id}_{msg_id}"
            if cache_key in message_cache:
                msg = message_cache[cache_key]
                await bot.send_message(
                    target_id,
                    f"🗑 **УДАЛЕНО**\n{msg['text'][:200]}"
                )

    await user_client.run_until_disconnected()

# ========== ЗАПУСК ==========
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Бот @{me.username} запущен!")
    logger.info(f"🔐 Пин-код: {ACCESS_PIN}")
    logger.info(f"🤖 Авто-исправление ошибок активно")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())