import asyncio
import aiohttp
import os
import time
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ (Берутся из Environment Variables на Render) ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Параметры фильтрации
TARGET_NETWORKS = ['immutable_zkevm', 'kava', 'mantle', 'linea', 'ronin'] 
MIN_PRICE_CHANGE = 15.0  # Твое условие: 15% за 5 минут
MIN_LIQUIDITY = 3000.0   # Минимальная ликвидность в $, чтобы отсечь мусор

# === ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ РАБОТЫ 24/7 ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Arbitrage Scanner is Active"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# === ЛОГИКА БОТА ===
async def send_telegram_message(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TG_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception as e:
        print(f"Ошибка отправки в TG: {e}")

async def check_markets(session, network):
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200: return
            
            data = await response.json()
            for pool in data.get('data', []):
                attrs = pool.get('attributes', {})
                
                # Процент изменения за 5 минут
                m5_change = float(attrs.get('price_change_percentage', {}).get('m5', 0) or 0)
                
                # Ликвидность
                reserve = float(attrs.get('reserve_in_usd', 0) or 0)

                # Твоё условие: если изменение >= 15%
                if abs(m5_change) >= MIN_PRICE_CHANGE and reserve >= MIN_LIQUIDITY:
                    name = attrs.get('name')
                    address = attrs.get('address')
                    direction = "🚀 РОСТ" if m5_change > 0 else "🩸 ПАДЕНИЕ"
                    
                    msg = (
                        f"⚠️ <b>Аномалия на {network.upper()}!</b>\n"
                        f"Монета: <b>{name}</b>\n"
                        f"Изменение: <code>{m5_change}%</code> (5 мин)\n"
                        f"Ликвидность: ${reserve:,.0f}\n"
                        f"Контракт: <code>{address}</code>\n\n"
                        f"<a href='https://www.geckoterminal.com/{network}/pools/{address}'>Открыть график</a>"
                    )
                    await send_telegram_message(session, msg)
                    await asyncio.sleep(1) # Защита от спама
    except Exception as e:
        print(f"Ошибка парсинга {network}: {e}")

async def main_loop():
    async with aiohttp.ClientSession() as session:
        print("Бот запущен...")
        await send_telegram_message(session, "✅ Бот запущен и ищет скачки от 15%!")
        
        while True:
            for network in TARGET_NETWORKS:
                await check_markets(session, network)
                await asyncio.sleep(2) # Пауза между сетями
            
            print(f"[{time.strftime('%H:%M:%S')}] Проверка завершена, ждем 5 минут...")
            await asyncio.sleep(300)

if __name__ == "__main__":
    keep_alive() # Запуск «будильника»
    asyncio.run(main_loop())
