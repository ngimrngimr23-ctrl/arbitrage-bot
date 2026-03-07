import asyncio
import aiohttp
import os
import time
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Глобальные настройки (теперь их можно менять командой)
settings = {
    'change': 15.0,  # Порог в %
    'volume': 5000.0,
    'liquidity': 3000.0
}

TARGET_NETWORKS = ['immutable_zkevm', 'kava', 'mantle', 'linea', 'ronin']

app = Flask(__name__)

@app.route('/')
def home(): return "Scanner 200 is Active"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# === ЛОГИКА ТЕЛЕГРАМ-КОМАНД ===
async def handle_commands():
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}"
            try:
                async with session.get(url) as resp:
                    data = await resp.json()
                    for update in data.get('result', []):
                        offset = update['update_id'] + 1
                        msg = update.get('message', {})
                        text = msg.get('text', '')
                        
                        # Команда /set [число]
                        if text.startswith('/set'):
                            try:
                                new_val = float(text.split()[1])
                                settings['change'] = new_val
                                await send_tg(session, f"✅ Порог изменен на {new_val}%")
                            except:
                                await send_tg(session, "❌ Ошибка. Пиши например: /set 10")
            except: pass
            await asyncio.sleep(3)

# === ОСНОВНОЙ СКАНЕР ===
async def send_tg(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    await session.post(url, json=payload)

async def check_markets(session, network):
    # ПАГИНАЦИЯ: Листаем 10 страниц по 20 пулов = 200 монет
    for page in range(1, 11): 
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        try:
            async with session.get(url, headers=headers) as response:
                if response.status != 200: break
                
                data = await response.json()
                pools = data.get('data', [])
                if not pools: break

                for pool in pools:
                    attrs = pool.get('attributes', {})
                    m5_change = float(attrs.get('price_change_percentage', {}).get('m5', 0) or 0)
                    vol = float(attrs.get('volume_usd', {}).get('h24', 0) or 0)
                    liq = float(attrs.get('reserve_in_usd', 0) or 0)

                    # Используем актуальное значение из settings
                    if abs(m5_change) >= settings['change'] and vol >= settings['volume'] and liq >= settings['liquidity']:
                        msg = (
                            f"🔥 <b>СИГНАЛ {page} СТР: {network.upper()}</b>\n"
                            f"Монета: <b>{attrs.get('name')}</b>\n"
                            f"Изменение: <code>{m5_change}%</code> (5 мин)\n"
                            f"Контракт: <code>{attrs.get('address')}</code>"
                        )
                        await send_tg(session, msg)
            await asyncio.sleep(1.5) # Пауза чтобы не забанили API
        except: break

async def main_loop():
    asyncio.create_task(handle_commands()) # Запускаем слушатель команд
    async with aiohttp.ClientSession() as session:
        await send_tg(session, f"🚀 Сканер 200 запущен!\nТекущий порог: {settings['change']}%")
        while True:
            for net in TARGET_NETWORKS:
                await check_markets(session, net)
                await asyncio.sleep(2)
            await asyncio.sleep(300)

if __name__ == "__main__":
    Thread(target=run_server).start()
    asyncio.run(main_loop())
