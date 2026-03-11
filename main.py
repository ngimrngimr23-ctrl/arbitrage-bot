import asyncio
import aiohttp
import os
import time
import random
import re
from flask import Flask
from threading import Thread

# --- ЦЕНТРАЛЬНЫЕ НАСТРОЙКИ ---
SETTINGS = {
    'rare_pump': 20.0,     # Порог пампа для экзотических сетей
    'rare_dump': 20.0,     # Порог дампа для экзотических сетей
    'min_liq': 10000.0,    
    'cooldown': 3600,      
    'api_pause': 0.5,      # ТУРБО-РЕЖИМ (0.5 сек между страницами)
    'tg_pause': 1.5,       
    'request_timeout': 10  
}

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

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

# ЧЕРНЫЙ СПИСОК СЕТЕЙ (Вырезаем ТОП-8)
EXCLUDE_NETWORKS = ['eth', 'solana', 'bsc', 'base', 'arbitrum', 'polygon_pos', 'avax', 'optimism']

sent_signals = {}

# Игнорируем стейблы и обернутые токены
IGNORE_SYMBOLS = ['usdt', 'usdc', 'weth', 'wbnb', 'wsol', 'wbtc', 'wpol', 'wmatic', 'dai', 'fdusd']

app = Flask(__name__)
@app.route('/')
def home(): 
    status = "Proxy Pool Enabled (TURBO 1000 IPs)" if PROXY_URL else "Direct Connection"
    return f"Arbitrage Pro Active | EXOTIC NETWORKS ONLY | ({status})"

def get_rotating_proxy():
    """Случайно выбирает 1 из 1000 портов для каждого запроса"""
    if not PROXY_URL: return None
    if "pool.proxy.market" in PROXY_URL:
        return re.sub(r':\d+$', f':{random.randint(10000, 10999)}', PROXY_URL)
    return PROXY_URL

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

async def get_all_exotic_networks(session):
    """Собирает ВСЕ сети, кроме ТОП-8"""
    all_nets = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Сканируем 10 страниц API, чтобы собрать более 200 редких сетей
    for page in range(1, 11):
        url = f"https://api.geckoterminal.com/api/v2/networks?page={page}"
        try:
            current_proxy = get_rotating_proxy()
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout'], proxy=current_proxy) as resp:
                if resp.status != 200: break
                data = await resp.json()
                for net in data.get('data', []):
                    net_id = net['id']
                    if net_id not in EXCLUDE_NETWORKS:
                        all_nets.append(net_id)
            await asyncio.sleep(0.5)
        except: break
    return all_nets

async def check_markets(session, network):
    p_th = SETTINGS['rare_pump']
    d_th = SETTINGS['rare_dump']
    min_liq = SETTINGS['min_liq']
    
    proxy_msg = "(Пул 1000 IP - ТУРБО)" if PROXY_URL else ""
    print(f"\n📡 СКАНИРУЮ: {network.upper()} {proxy_msg}")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    stats = {'passed': 0, 'trash': 0, 'signals': 0}
    now = time.time()

    urls_to_check = [f"https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools?include=base_token,quote_token"]
    for page in range(1, 21): 
        urls_to_check.append(f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}&include=base_token,quote_token")
    
    for url in urls_to_check:
        retries = 3
        while retries > 0:
            current_proxy = get_rotating_proxy() 
            try:
                async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout'], proxy=current_proxy) as resp:
                    if resp.status == 429:
                        print(f"⚡ БАН 429. Мгновенная смена IP (осталось попыток: {retries-1})...")
                        await asyncio.sleep(0.5) 
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
                            
                            # Берем адрес токена напрямую из GT (Никаких CoinGecko)
                            token_addr = target_attrs.get('address')
                            
                            if not token_addr:
                                stats['trash'] += 1
                                continue
                            
                            pct = attrs.get('price_change_percentage') or {}
                            m5 = float(pct.get('m5') or 0)
                            
                            is_triggered = abs(m5) >= min(p_th, d_th) 
                            
                            if not is_triggered:
                                stats['passed'] += 1
                                continue
                            
                            stats['passed'] += 1
                            
                            type_sig = "V5_EXOTIC"
                            key = f"{network}_{pool_addr}_{type_sig}"
                            
                            if key in sent_signals and (now - sent_signals[key]) < SETTINGS['cooldown']: continue
                            sent_signals[key] = now
                            stats['signals'] += 1
                            
                            act = "💎 ЭКЗОТИЧЕСКИЙ ПРЫЖОК (5м)"
                            gt_token_link = f"🪙 <a href='https://www.geckoterminal.com/{network}/tokens/{token_addr}'>Токен (GeckoTerminal)</a>"
                            gt_pool_link = f"📈 <a href='https://www.geckoterminal.com/{network}/pools/{pool_addr}'>График пула</a>"
                            
                            msg = (f"{act} | <b>{network.upper()}</b>\n"
                                   f"Пара: <code>{attrs.get('name')}</code>\n"
                                   f"Ликвидность: <b>${liq:,.0f}</b>\n\n"
                                   f"Изменение 5m: <b>{m5}%</b>\n\n"
                                   f"Контракт пула: <code>{pool_addr}</code>\n"
                                   f"Контракт токена: <code>{token_addr}</code>\n\n"
                                   f"{gt_token_link} | {gt_pool_link}")
                            await send_tg(session, msg)
                            await asyncio.sleep(SETTINGS['tg_pause'])
                        except: continue
                    break 
            except Exception as e:
                await asyncio.sleep(0.5) 
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
                            status = "ВКЛЮЧЕН ✅ (1000 IPs TURBO)" if PROXY_URL else "ВЫКЛЮЧЕН ❌"
                            await send_tg(sess, f"🤖 <b>Экзотический Сканнер (Без ТОП-8)</b>\n\n"
                                               f"💎 Порог (Редкие): <b>{SETTINGS['rare_pump']}%</b> / <b>-{SETTINGS['rare_dump']}%</b>\n"
                                               f"💧 Мин. ликвидность: <b>${SETTINGS['min_liq']:,.0f}</b>\n"
                                               f"🛡️ Прокси: <b>{status}</b>\n\n"
                                               "<b>Команды:</b>\n"
                                               "/pump_rare [ч] | /dump_rare [ч]\n"
                                               "/min_liq [ч]")
                        elif txt.startswith('/'):
                            parts = txt.split()
                            if len(parts) == 2:
                                try:
                                    val = abs(float(parts[1]))
                                    if '/pump_rare' in txt: SETTINGS['rare_pump'] = val
                                    elif '/dump_rare' in txt: SETTINGS['rare_dump'] = val
                                    elif '/min_liq' in txt: SETTINGS['min_liq'] = val
                                    await send_tg(sess, f"✅ Обновлено: {val}")
                                except: pass
            except: pass
            await asyncio.sleep(2)

async def main_loop():
    asyncio.create_task(handle_cmds())
    conn = aiohttp.TCPConnector(limit=20) 
    async with aiohttp.ClientSession(connector=conn) as sess:
        while True:
            # 1. Собираем все доступные сети
            nets = await get_all_exotic_networks(sess)
            
            print(f"\n====================================")
            print(f"🚀 НАЧИНАЮ НОВЫЙ КРУГ ({len(nets)} Экзотических сетей)")
            print(f"====================================")
            
            # 2. Сканируем собранные сети
            for n in nets: 
                await check_markets(sess, n)
            
            cur = time.time()
            to_del = [k for k, v in sent_signals.items() if (cur - v) > SETTINGS['cooldown']]
            for k in to_del: del sent_signals[k]
            
            print("🏁 КРУГ ЗАВЕРШЕН. Отдыхаем 15 секунд...") 
            await asyncio.sleep(15)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    srv = Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True)
    srv.start()
    asyncio.run(main_loop())                            
