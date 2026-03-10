import asyncio
import aiohttp
import os
import time
from flask import Flask
from threading import Thread

# --- ЦЕНТРАЛЬНЫЕ НАСТРОЙКИ ---
SETTINGS = {
    'top_pump': 15.0,
    'top_dump': 15.0,
    'rare_pump': 20.0,
    'rare_dump': 20.0,
    'h1_dump': 25.0,
    'min_liq': 10000.0,    
    'cooldown': 3600,      
    'api_pause': 6.0,      # <--- ЗАМЕДЛИЛИ БОТА ДО 6 СЕКУНД (Стелс-режим)
    'tg_pause': 1.5,       
    'request_timeout': 20  # <--- ДАЛИ РЕЗИДЕНТНЫМ ПРОКСИ БОЛЬШЕ ВРЕМЕНИ НА ОТВЕТ
}

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

# Автоматическая починка прокси (если Render не сохранил http://)
raw_proxy = os.environ.get('PROXY_URL')
if raw_proxy:
    raw_proxy = raw_proxy.strip()
    if not raw_proxy.startswith('http'):
        PROXY_URL = f"http://{raw_proxy}"
    else:
        PROXY_URL = raw_proxy
else:
    PROXY_URL = None

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверь переменные окружения (TG_BOT_TOKEN, TG_CHAT_ID)!")

TOP_CHAINS = ['eth', 'bsc', 'polygon', 'arbitrum', 'base', 'solana']
sent_signals = {}

CG_NETWORKS = {
    'eth': 'ethereum', 'bsc': 'binance-smart-chain', 
    'polygon_pos': 'polygon-pos', 'arbitrum': 'arbitrum-one', 
    'base': 'base', 'solana': 'solana'
}

# Игнорируем стейблы и обернутые токены
IGNORE_SYMBOLS = ['usdt', 'usdc', 'weth', 'wbnb', 'wsol', 'wbtc', 'wpol', 'wmatic', 'dai', 'fdusd']

app = Flask(__name__)
@app.route('/')
def home(): 
    status = "Proxy Enabled (Stealth Mode)" if PROXY_URL else "Direct Connection"
    return f"Arbitrage Pro Active ({status})"

async def check_coingecko_listing(session, token_address, network):
    if not token_address: return None
    cg_net = CG_NETWORKS.get(network, network)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_net}/contract/{token_address}"
    try:
        async with session.get(url, timeout=5, proxy=PROXY_URL) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('id')
            elif resp.status == 429:
                await asyncio.sleep(10) 
                async with session.get(url, timeout=5, proxy=PROXY_URL) as retry_resp:
                    if retry_resp.status == 200:
                        data = await retry_resp.json()
                        return data.get('id')
            return None
    except:
        return None

async def send_tg(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        async with session.post(url, json=payload, timeout=SETTINGS['request_timeout']) as resp:
            data = await resp.json()
            if not data.get('ok'):
                print(f"⚠️ Ошибка ТГ API: {data.get('description')}")
            return data
    except Exception as e:
        print(f"❌ Сбой сети ТГ: {e}")

async def get_all_networks(session):
    all_nets = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for page in range(1, 5):
        url = f"https://api.geckoterminal.com/api/v2/networks?page={page}"
        try:
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout'], proxy=PROXY_URL) as resp:
                if resp.status != 200: break
                data = await resp.json()
                for net in data.get('data', []):
                    all_nets.append(net['id'])
            await asyncio.sleep(1)
        except: break
    for top in TOP_CHAINS:
        if top not in all_nets: all_nets.append(top)
    return all_nets

async def check_markets(session, network):
    is_top = network in TOP_CHAINS
    p_th = SETTINGS['top_pump'] if is_top else SETTINGS['rare_pump']
    d_th = SETTINGS['top_dump'] if is_top else SETTINGS['rare_dump']
    min_liq = SETTINGS['min_liq']
    
    proxy_msg = "(Через PROXY)" if PROXY_URL else ""
    print(f"\n📡 СКАНИРУЮ: {network.upper()} {proxy_msg}")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    stats = {'passed': 0, 'trash': 0, 'signals': 0, 'cg_api_hits': 0}
    now = time.time()

    urls_to_check = [f"https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools?include=base_token,quote_token"]
    for page in range(1, 21): 
        urls_to_check.append(f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}&include=base_token,quote_token")
    
    for url in urls_to_check:
        retries = 3
        while retries > 0:
            try:
                async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout'], proxy=PROXY_URL) as resp:
                    if resp.status == 429:
                        print(f"🛑 БАН 429. Ждем 20 сек (попытка {4-retries}/3)...")
                        await asyncio.sleep(20)
                        retries -= 1
                        continue 
                    
                    if resp.status != 200: break
                    
                    rj = await resp.json()
                    pools = rj.get('data', [])
                    inc = rj.get('included') or []
                    tokens = {t['id']: t['attributes'] for t in inc if t.get('type') == 'token'}
                    
                    for p in pools:
                        try:
                            attrs = p.get('attributes', {})
                            pool_addr = attrs.get('address')
                            liq = float(attrs.get('reserve_in_usd') or 0)
                            name_lower = attrs.get('name', '').lower()
                            
                            # Жесткий фильтр от мусора и кредитных токенов
                            if liq < min_liq or any(word in name_lower for word in ['loan', 'lend', 'credit', 'borrow']):
                                stats['trash'] += 1
                                continue
                                
                            rels = p.get('relationships', {})
                            b_id = rels.get('base_token', {}).get('data', {}).get('id')
                            q_id = rels.get('quote_token', {}).get('data', {}).get('id')
                            
                            b_attrs = tokens.get(b_id, {})
                            q_attrs = tokens.get(q_id, {})
                            
                            target_attrs = None
                            if b_attrs.get('symbol', '').lower() not in IGNORE_SYMBOLS:
                                target_attrs = b_attrs
                            elif q_attrs.get('symbol', '').lower() not in IGNORE_SYMBOLS:
                                target_attrs = q_attrs
                                
                            if not target_attrs:
                                stats['trash'] += 1
                                continue
                            
                            cg_id = target_attrs.get('coingecko_coin_id')
                            token_addr = target_attrs.get('address')
                            
                            pct = attrs.get('price_change_percentage') or {}
                            m5 = float(pct.get('m5') or 0)
                            
                            # Прострелы и вверх, и вниз
                            is_triggered = abs(m5) >= min(p_th, d_th) 
                            
                            if not cg_id:
                                if not is_triggered:
                                    stats['trash'] += 1
                                    continue
                                
                                cg_id = await check_coingecko_listing(session, token_addr, network)
                                
                                if cg_id:
                                    stats['cg_api_hits'] += 1
                                else:
                                    stats['trash'] += 1
                                    continue 
                            else:
                                if not is_triggered:
                                    stats['passed'] += 1
                                    continue
                            
                            stats['passed'] += 1
                            
                            type_sig = "V5"
                            key = f"{network}_{pool_addr}_{type_sig}"
                            
                            if key in sent_signals and (now - sent_signals[key]) < SETTINGS['cooldown']: continue
                            sent_signals[key] = now
                            stats['signals'] += 1
                            
                            act = "⚡ СИЛЬНОЕ ДВИЖЕНИЕ (5м)"
                            cg_link = f"🦎 <a href='https://www.coingecko.com/en/coins/{cg_id}'>CoinGecko</a>"
                            gt_link = f"📈 <a href='https://www.geckoterminal.com/{network}/pools/{pool_addr}'>График</a>"
                            
                            msg = (f"{act} | <b>{network.upper()}</b>\n"
                                   f"Пара: <code>{attrs.get('name')}</code>\n"
                                   f"ID: <code>{cg_id}</code>\n"
                                   f"Ликвидность: <b>${liq:,.0f}</b>\n\n"
                                   f"Изменение 5m: <b>{m5}%</b>\n\n"
                                   f"Контракт пула: <code>{pool_addr}</code>\n"
                                   f"Токен: <code>{token_addr}</code>\n\n"
                                   f"{cg_link} | {gt_link}")
                            await send_tg(session, msg)
                            await asyncio.sleep(SETTINGS['tg_pause'])
                        except: continue
                    break 
            except Exception as e:
                print(f"❌ Ошибка загрузки URL: {e}")
                await asyncio.sleep(10) # Увеличили паузу при ошибке прокси
                retries -= 1
        await asyncio.sleep(SETTINGS['api_pause']) 
            
    print(f"📊 {network}: Проверено: {stats['passed']} | Мусор: {stats['trash']} | Сигналы: {stats['signals']}")

async def handle_cmds():
    offset = 0
    async with aiohttp.ClientSession() as sess:
        while True:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            try:
                async with sess.get(url, timeout=SETTINGS['request_timeout']) as resp:
                    data = await resp.json()
                    for up in data.get('result', []):
                        offset = up['update_id'] + 1
                        msg = up.get('message')
                        if not msg or str(msg.get('chat', {}).get('id')) != str(TG_CHAT_ID): continue
                        txt = msg.get('text', '')
                        
                        if txt == '/start':
                            status = "ВКЛЮЧЕН ✅ (Стелс)" if PROXY_URL else "ВЫКЛЮЧЕН ❌"
                            await send_tg(sess, f"🤖 <b>Pro Scanner (Анти-Бан + Proxy)</b>\n\n"
                                               f"🏆 ТОП-6: <b>{SETTINGS['top_pump']}%</b> / <b>-{SETTINGS['top_dump']}%</b>\n"
                                               f"💎 Редкие: <b>{SETTINGS['rare_pump']}%</b> / <b>-{SETTINGS['rare_dump']}%</b>\n"
                                               f"💧 Мин. ликвидность: <b>${SETTINGS['min_liq']:,.0f}</b>\n"
                                               f"🛡️ Прокси: <b>{status}</b>\n\n"
                                               "<b>Команды:</b>\n"
                                               "/pump_top [ч] | /dump_top [ч]\n"
                                               "/pump_rare [ч] | /dump_rare [ч]\n"
                                               "/min_liq [ч]")
                        elif txt.startswith('/'):
                            parts = txt.split()
                            if len(parts) == 2:
                                try:
                                    val = abs(float(parts[1]))
                                    if '/pump_top' in txt: SETTINGS['top_pump'] = val
                                    elif '/dump_top' in txt: SETTINGS['top_dump'] = val
                                    elif '/pump_rare' in txt: SETTINGS['rare_pump'] = val
                                    elif '/dump_rare' in txt: SETTINGS['rare_dump'] = val
                                    elif '/min_liq' in txt: SETTINGS['min_liq'] = val
                                    await send_tg(sess, f"✅ Обновлено: {val}")
                                except: pass
            except: pass
            await asyncio.sleep(2)

async def main_loop():
    asyncio.create_task(handle_cmds())
    conn = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=conn) as sess:
        while True:
            nets = await get_all_networks(sess)
            print(f"\n====================================")
            print(f"🚀 НАЧИНАЮ НОВЫЙ КРУГ ({len(nets)} сетей)")
            print(f"====================================")
            for n in nets: await check_markets(sess, n)
            
            cur = time.time()
            to_del = [k for k, v in sent_signals.items() if (cur - v) > SETTINGS['cooldown']]
            for k in to_del: del sent_signals[k]
            
            print("🏁 КРУГ ЗАВЕРШЕН. Отдыхаем 30 секунд...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    srv = Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True)
    srv.start()
    asyncio.run(main_loop()) 
