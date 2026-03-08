import asyncio
import aiohttp
import os
from flask import Flask
from threading import Thread

TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Топ 6 самых популярных сетей
TOP_CHAINS = ['eth', 'bsc', 'polygon', 'arbitrum', 'base', 'solana']

# Настройки по умолчанию (все значения в абсолютных процентах)
settings = {
    'top_pump': 15.0,
    'top_dump': 15.0,
    'rare_pump': 20.0,
    'rare_dump': 20.0
}

app = Flask(__name__)
@app.route('/')
def home(): return "Scanner 7.3m Active"

async def send_tg(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except: pass

async def get_all_networks(session):
    all_nets = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for page in range(1, 5): 
        url = f"https://api.geckoterminal.com/api/v2/networks?page={page}"
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200: break
                data = await resp.json()
                for net in data.get('data', []):
                    all_nets.append(net['id'])
            await asyncio.sleep(1)
        except: break
    
    # Гарантируем, что Топ-6 всегда в списке, даже если API глюканет
    for top in TOP_CHAINS:
        if top not in all_nets: all_nets.append(top)
        
    return all_nets

async def check_markets(session, network):
    is_top = network in TOP_CHAINS
    pump_th = settings['top_pump'] if is_top else settings['rare_pump']
    dump_th = settings['top_dump'] if is_top else settings['rare_dump']
    
    cat_name = "🏆 ТОП-6" if is_top else "💎 РЕДКАЯ"
    print(f">>> СКАНИРУЮ {network.upper()} [{cat_name}] | P: {pump_th}% / D: -{dump_th}%")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for page in range(1, 11):
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}"
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 429:
                    print(f"🛑 Лимит API на {network}. Ждем 60 сек...")
                    await asyncio.sleep(60)
                    break 
                
                if response.status != 200: break
                
                data = await response.json()
                pools = data.get('data', [])
                
                for pool in pools:
                    attrs = pool.get('attributes', {})
                    price_change = attrs.get('price_change_percentage')
                    
                    if not price_change: continue
                    m5 = float(price_change.get('m5') or 0)
                    
                    # Логика: Памп (>= порога) ИЛИ Дамп (<= минус порога)
                    is_pump = m5 >= pump_th
                    is_dump = m5 <= -dump_th
                    
                    if is_pump or is_dump:
                        action = "🚀 ПАМП" if is_pump else "🩸 ДАМП"
                        name = attrs.get('name')
                        addr = attrs.get('address')
                        msg = (
                            f"{action} | {cat_name}: <b>{network.upper()}</b>\n"
                            f"Пара: <code>{name}</code>\n"
                            f"Изменение: <b>{m5}%</b> (5 мин)\n"
                            f"Контракт: <code>{addr}</code>\n"
                            f"📈 <a href='https://dexscreener.com/{network}/{addr}'>DexScreener</a>"
                        )
                        await send_tg(session, msg)
                        await asyncio.sleep(1.5) # Пауза Телеграма (анти-спам)
                        
            # Идеальный тайминг 2.2 сек для 7.3 минут на круг
            await asyncio.sleep(2.2) 
            
        except Exception as e:
            print(f"Ошибка {network}: {e}")
            break

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
                        
                        if text == '/start':
                            msg = (
                                "🤖 <b>Арбитраж Бот 7.3м запущен!</b>\n\n"
                                "<b>Текущие настройки:</b>\n"
                                f"🏆 ТОП-6 сетей: Памп <b>{settings['top_pump']}%</b> | Дамп <b>-{settings['top_dump']}%</b>\n"
                                f"💎 Редкие сети: Памп <b>{settings['rare_pump']}%</b> | Дамп <b>-{settings['rare_dump']}%</b>\n\n"
                                "<b>Нажми на команду, чтобы изменить (вводи положительное число):</b>\n"
                                "👉 /pump_top [число] — памп для Топ-6\n"
                                "👉 /dump_top [число] — дамп для Топ-6\n"
                                "👉 /pump_rare [число] — памп редких\n"
                                "👉 /dump_rare [число] — дамп редких"
                            )
                            await send_tg(session, msg)
                            
                        elif text.startswith('/'):
                            parts = text.split()
                            if len(parts) == 2:
                                cmd = parts[0]
                                try:
                                    val = abs(float(parts[1])) # Всегда берем по модулю
                                    if cmd == '/pump_top': settings['top_pump'] = val
                                    elif cmd == '/dump_top': settings['top_dump'] = val
                                    elif cmd == '/pump_rare': settings['rare_pump'] = val
                                    elif cmd == '/dump_rare': settings['rare_dump'] = val
                                    await send_tg(session, f"✅ Значение обновлено: <b>{val}%</b>")
                                except: pass
            except: pass
            await asyncio.sleep(1.5)

async def main_loop():
    asyncio.create_task(handle_commands())
    async with aiohttp.ClientSession() as session:
        while True:
            networks = await get_all_networks(session)
            print(f"--- НАЧИНАЮ КРУГ (Сетей: {len(networks)}) ---")
            for net in networks:
                await check_markets(session, net)
                # Нет паузы между сетями для скорости
            print("🏁 КРУГ ЗАВЕРШЕН. Отдых 30 сек.")
            await asyncio.sleep(30)

if __name__ == "__main__":
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()
    asyncio.run(main_loop())
