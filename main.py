import asyncio
import aiohttp
import time
import os
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ TELEGRAM (берутся из скрытых переменных Render) ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# --- НАСТРОЙКИ ПАРСЕРА ---
TARGET_NETWORKS = ['immutable_zkevm', 'kava', 'mantle', 'linea', 'ronin'] 
MIN_LIQUIDITY = 4000.0
MIN_PRICE_CHANGE = 15.0

# === ВЕБ-СЕРВЕР ДЛЯ RENDER ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Arbitrage Bot is running on Render!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.start()
# =============================

async def send_telegram_message(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TG_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        await session.post(url, json=payload)
    except Exception:
        pass 

async def fetch_and_filter_pools(session, network):
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return

            data = await response.json()
            pools = data.get('data', [])

            for pool in pools:
                attrs = pool.get('attributes', {})
                name = attrs.get('name', 'Unknown')
                address = attrs.get('address', 'Unknown')

                reserve_str = attrs.get('reserve_in_usd')
                reserve = float(reserve_str) if reserve_str else 0.0

                price_change_dict = attrs.get('price_change_percentage', {})
                m5_change_str = price_change_dict.get('m5') if price_change_dict else None
                m5_change = float(m5_change_str) if m5_change_str else 0.0

                if reserve >= MIN_LIQUIDITY and abs(m5_change) >= MIN_PRICE_CHANGE:
                    direction = "📈 РОСТ" if m5_change > 0 else "📉 ПАДЕНИЕ"
                    msg = (
                        f"🔥 <b>Сигнал: {network.upper()}</b>\n\n"
                        f"{direction}: <b>{m5_change}%</b> за 5 минут\n"
                        f"Пул: <code>{name}</code>\n"
                        f"Ликвидность: ${reserve:,.0f}\n"
                        f"Контракт: <code>{address}</code>\n\n"
                        f"<a href='https://www.geckoterminal.com/{network}/pools/{address}'>Открыть пул</a>"
                    )
                    await send_telegram_message(session, msg)
    except Exception:
        pass

async def main():
    async with aiohttp.ClientSession() as session:
        await send_telegram_message(session, "✅ <b>Сканер арбитража успешно запущен на Render!</b>")
        
        while True:
            for net in TARGET_NETWORKS:
                await fetch_and_filter_pools(session, net)
                await asyncio.sleep(2) 

            await asyncio.sleep(300) 

if __name__ == "__main__":
    keep_alive() # Запускаем веб-сервер
    asyncio.run(main()) # Запускаем бота
