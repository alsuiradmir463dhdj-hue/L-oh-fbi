import os
import asyncio
from telethon import TelegramClient

API_ID = 35494524
API_HASH = '0e465149f428a082cc47a7c7d016c179'

async def test():
    client = TelegramClient('test_session', API_ID, API_HASH)
    await client.connect()
    
    phone = '+79001234567'  # ЗАМЕНИ НА СВОЙ НОМЕР
    
    try:
        sent = await client.send_code_request(phone)
        print(f"✅ Код отправлен! Hash: {sent.phone_code_hash}")
        print("Проверь Telegram — должен прийти код")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

asyncio.run(test())