import asyncio
import aiohttp
import os
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

TOP_CHAINS = ['eth', 'bsc', 'polygon', 'arbitrum', 'base', 'solana']
settings = {
    'top_pump': 15.0, 
    'top_dump': 15.0,
    'rare_pump': 20.0, 
    'rare_dump': 20.0,
    'h1_dump': 25.0  # Падение за час по умолчанию
}

app = Flask(__name__)
@app.route('/')
def home(): return "Global Arbitrage Scanner (ID Only) Active"

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
    
    # Гарантируем, что ТОП-6 всегда в списке
    for top in TOP_CHAINS:
        if top not in all_nets: all_nets.append(top)
    return all_nets

async def check_markets(session, network):
    is_top = network in TOP_CHAINS
    pump_th = settings['top_pump'] if is_top else settings['rare_pump']
    dump_th = settings['top_dump'] if is_top else settings['rare_dump']
    h1_dump_th = settings['h1_dump']
    
    print(f"\n📡 СКАНИРУЮ СЕТЬ: {network.upper()}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Счетчики для статистики в логах Render
    stats_with_id = 0
    stats_without_id = 0
    stats_signals = 0
    
    for page in range(1, 11):
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}&include=base_token"
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 429:
                    print(f"🛑 БАН 429 на {network}! Ждем 60 сек...")
                    await asyncio.sleep(60)
                    break
                
                if response.status != 200:
                    print(f"⚠️ Ошибка {response.status} на {network}")
                    break
                
                resp_json = await response.json()
                pools = resp_json.get('data', [])
                
                included_data = resp_json.get('included') or []
                tokens_info = {t['id']: t['attributes'] for t in included_data if t.get('type') == 'token'}
                
                for pool in pools:
                    attrs = pool.get('attributes', {})
                    
                    try:
                        # 1. ЖЕСТКИЙ ФИЛЬТР ПО ID
                        base_token_id = pool.get('relationships', {}).get('base_token', {}).get('data', {}).get('id')
                        if not base_token_id: 
                            stats_without_id += 1
                            continue
                        
                        token_data = tokens_info.get(base_token_id, {})
                        cg_id = token_data.get('coingecko_coin_id')
                        
                        if not cg_id: 
                            stats_without_id += 1
                            continue # Пропускаем монеты без ID
                            
                        stats_with_id += 1 # Монета прошла фильтр
                        
                        # 2. ПОЛУЧАЕМ ПРОЦЕНТЫ
                        pct = attrs.get('price_change_percentage') or {}
                        m5 = float(pct.get('m5') or 0)
                        h1 = float(pct.get('h1') or 0)
                        h24 = float(pct.get('h24') or 0)
                        
                        # 3. ЛОГИКА ТРИГГЕРОВ
                        is_m5_pump = m5 >= pump_th
                        is_m5_dump = m5 <= -dump_th
                        is_h1_dump = (h1 <= -h1_dump_th) and (h24 <= (h1 * 0.8))
                        
                        if is_m5_pump or is_m5_dump or is_h1_dump:
                            stats_signals += 1
                            if is_m5_pump: action = "🚀 ПАМП (5м)"
                            elif is_m5_dump: action = "🩸 ДАМП (5м)"
                            else: action = "⚠️ ЧАСОВОЙ ДАМП"
                            
                            name = attrs.get('name', 'Unknown')
                            addr = attrs.get('address', 'Unknown')
                            
                            msg = (
                                f"{action} | <b>{network.upper()}</b>\n"
                                f"Пара: <code>{name}</code>\n"
                                f"ID: <code>{cg_id}</code>\n\n"
                                f"Изм 5м: <b>{m5}%</b>\n"
                                f"Изм 1ч: <b>{h1}%</b>\n"
                                f"Изм 24ч: <b>{h24}%</b>\n\n"
                                f"Контракт: <code>{addr}</code>\n"
                                f"📈 <a href='https://dexscreener.com/{network}/{addr}'>DexScreener</a>"
                            )
                            await send_tg(session, msg)
                            await asyncio.sleep(1.5) # Антиспам ТГ
                            
                    except Exception as inner_e:
                        continue
                        
            # Идеальный тайминг для обхода лимитов
            await asyncio.sleep(2.2) 
        except Exception as e:
            print(f"❌ ОШИБКА в {network}: {e}")
            break
            
    print(f"📊 Итог по {network.upper()}:")
    print(f"   ✅ С ID: {stats_with_id}")
    print(f"   🗑 Без ID: {stats_without_id}")
    print(f"   📨 Отправлено сигналов: {stats_signals}")

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
                                "🤖 <b>Арбитражный Бот (Только ID активы)</b>\n\n"
                                f"🏆 ТОП-6: Памп <b>{settings['top_pump']}%</b> | Дамп <b>-{settings['top_dump']}%</b>\n"
                                f"💎 Редкие: Памп <b>{settings['rare_pump']}%</b> | Дамп <b>-{settings['rare_dump']}%</b>\n"
                                f"⏳ Часовой дамп: <b>-{settings['h1_dump']}%</b> (условие 24ч: 80%)\n\n"
                                "<b>Команды (вводи положительное число):</b>\n"
                                "/pump_top [ч] | /dump_top [ч]\n"
                                "/pump_rare [ч] | /dump_rare [ч]\n"
                                "/dump_h1 [ч] — порог часового падения"
                            )
                            await send_tg(session, msg)
                            
                        elif text.startswith('/'):
                            parts = text.split()
                            if len(parts) == 2:
                                cmd = parts[0]
                                try:
                                    val = abs(float(parts[1]))
                                    if cmd == '/pump_top': settings['top_pump'] = val
                                    elif cmd == '/dump_top': settings['top_dump'] = val
                                    elif cmd == '/pump_rare': settings['rare_pump'] = val
                                    elif cmd == '/dump_rare': settings['rare_dump'] = val
                                    elif cmd == '/dump_h1': settings['h1_dump'] = val
                                    await send_tg(session, f"✅ Обновлено: <b>{val}%</b>")
                                except: pass
            except: pass
            await asyncio.sleep(1.5)

async def main_loop():
    asyncio.create_task(handle_commands())
    async with aiohttp.ClientSession() as session:
        while True:
            networks = await get_all_networks(session)
            print(f"\n====================================")
            print(f"🚀 НАЧИНАЮ НОВЫЙ КРУГ (Сетей: {len(networks)})")
            print(f"====================================")
            
            for net in networks:
                await check_markets(session, net)
                
            print("\n🏁 КРУГ ЗАВЕРШЕН. Отдыхаем 30 секунд...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()
    asyncio.run(main_loop())
