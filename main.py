import asyncio
import aiohttp
import os
from flask import Flask
from threading import Thread

TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

settings = {'change': 15.0}

app = Flask(__name__)
@app.route('/')
def home(): return "Global Scanner Active"

async def send_tg(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    async with session.post(url, json=payload) as resp:
        return await resp.json()

# Функция получения ВСЕХ доступных сетей
async def get_all_networks(session):
    url = "https://api.geckoterminal.com/api/v2/networks?page=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    networks = []
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                for net in data.get('data', []):
                    networks.append(net['id'])
        # Для бесплатного API берем первую страницу сетей (самые живые), 
        # их там около 20-30 основных + редкие.
        return networks if networks else ['eth', 'bsc', 'polygon', 'base', 'kava']
    except:
        return ['eth', 'bsc', 'polygon', 'base', 'kava']

async def check_markets(session, network):
    print(f">>> СКАНИРУЮ СЕТЬ: {network.upper()}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for page in range(1, 11):
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}"
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 429:
                    await asyncio.sleep(60)
                    return
                if response.status != 200: break
                
                data = await response.json()
                for pool in data.get('data', []):
                    attrs = pool.get('attributes', {})
                    m5 = float(attrs.get('price_change_percentage', {}).get('m5', 0) or 0)
                    
                    if abs(m5) >= settings['change']:
                        name = attrs.get('name')
                        addr = attrs.get('address')
                        msg = f"💎 <b>{network.upper()}</b> (Стр {page})\n{name}: <b>{m5}%</b>\n<code>{addr}</code>"
                        await send_tg(session, msg)
            await asyncio.sleep(2) # Пауза для стабильности
        except: break

async def handle_commands():
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            try:
                async with session.get(url) as resp:
                    data = await resp.json()
                    for update in data.get('result', []):
                        offset = update['update_id'] + 1
                        text = update.get('message', {}).get('text', '')
                        if text.startswith('/set'):
                            settings['change'] = float(text.split()[1])
                            await send_tg(session, f"⚙️ Порог: {settings['change']}%")
            except: pass
            await asyncio.sleep(2)

async def main_loop():
    asyncio.create_task(handle_commands())
    async with aiohttp.ClientSession() as session:
        while True:
            networks = await get_all_networks(session)
            print(f"--- НАЙДЕНО СЕТЕЙ: {len(networks)} ---")
            for net in networks:
                await check_markets(session, net)
                await asyncio.sleep(1)
            await asyncio.sleep(60)

if __name__ == "__main__":
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()
    asyncio.run(main_loop())
