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
    'min_liq': 10000.0,    # ФИЛЬТР ЛИКВИДНОСТИ ВКЛЮЧЕН ($10,000)
    'cooldown': 3600,      # 1 час молчания для дубликатов
    'api_pause': 2.3,      # Пауза между страницами
    'tg_pause': 1.5,       # Пауза между отправками в ТГ
    'request_timeout': 15  # Таймаут запросов
}

TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверь переменные окружения (TG_BOT_TOKEN, TG_CHAT_ID)!")

TOP_CHAINS = ['eth', 'bsc', 'polygon', 'arbitrum', 'base', 'solana']
sent_signals = {}

# Правильные названия сетей для API CoinGecko
CG_NETWORKS = {
    'eth': 'ethereum', 'bsc': 'binance-smart-chain', 
    'polygon_pos': 'polygon-pos', 'arbitrum': 'arbitrum-one', 
    'base': 'base', 'solana': 'solana'
}

app = Flask(__name__)
@app.route('/')
def home(): return "Arbitrage Pro (Deep Scan + Correct Addresses + Liq) Active"

async def check_coingecko_listing(session, token_address, network):
    """Прямой запрос к CG по контракту ТОКЕНА (с защитой от бана)"""
    if not token_address: return None
    cg_net = CG_NETWORKS.get(network, network)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_net}/contract/{token_address}"
    
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('id')
            elif resp.status == 429:
                print(f"⚠️ Лимит CoinGecko API! Пауза 10 сек перед повтором...")
                await asyncio.sleep(10)
                # Повторяем запрос один раз после паузы
                async with session.get(url, timeout=5) as retry_resp:
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
                print(f"⚠️ Ошибка Telegram API: {data.get('description')}")
            return data
    except Exception as e:
        print(f"❌ Сбой сети ТГ: {e}")

async def get_all_networks(session):
    all_nets = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for page in range(1, 5):
        url = f"https://api.geckoterminal.com/api/v2/networks?page={page}"
        try:
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout']) as resp:
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
    h1_th = SETTINGS['h1_dump']
    min_liq = SETTINGS['min_liq']
    
    print(f"\n📡 СКАНИРУЮ: {network.upper()}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    stats = {'passed': 0, 'trash': 0, 'signals': 0, 'cg_api_hits': 0}
    now = time.time()

    # Берем тренды и 30 страниц, подтягиваем ОБА токена из пула
    urls_to_check = [f"https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools?include=base_token,quote_token"]
    for page in range(1, 31): 
        urls_to_check.append(f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}&include=base_token,quote_token")
    
    for url in urls_to_check:
        try:
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout']) as resp:
                if resp.status == 429:
                    print(f"🛑 БАН 429 на GT ({network})")
                    await asyncio.sleep(60); break
                if resp.status != 200: break
                
                rj = await resp.json()
                pools = rj.get('data', [])
                inc = rj.get('included') or []
                tokens = {t['id']: t['attributes'] for t in inc if t.get('type') == 'token'}
                
                for p in pools:
                    try:
                        attrs = p.get('attributes', {})
                        pool_addr = attrs.get('address') # Адрес пула (для ссылок)
                        liq = float(attrs.get('reserve_in_usd') or 0)
                        
                        # --- ПРАВИЛО №1: ЛИКВИДНОСТЬ ---
                        if liq < min_liq:
                            stats['trash'] += 1
                            continue
                            
                        # Вытаскиваем оба токена
                        rels = p.get('relationships', {})
                        base_id = rels.get('base_token', {}).get('data', {}).get('id')
                        quote_id = rels.get('quote_token', {}).get('data', {}).get('id')
                        
                        base_attrs = tokens.get(base_id, {})
                        quote_attrs = tokens.get(quote_id, {})
                        
                        # Ищем ID в любом из токенов
                        cg_id = base_attrs.get('coingecko_coin_id') or quote_attrs.get('coingecko_coin_id')
                        
                        # Адрес контракта монеты (пробуем base, если нет - quote)
                        token_addr = base_attrs.get('address') or quote_attrs.get('address')
                        
                        pct = attrs.get('price_change_percentage') or {}
                        m5, h1, h24 = float(pct.get('m5') or 0), float(pct.get('h1') or 0), float(pct.get('h24') or 0)
                        
                        is_p, is_d = m5 >= p_th, m5 <= -d_th
                        is_h1 = (h1 <= -h1_th) and (h24 <= (h1 * 0.8))
                        is_triggered = is_p or is_d or is_h1
                        
                        # --- ПРАВИЛО №2: ФИЛЬТР COINGECKO ---
                        if not cg_id:
                            if not is_triggered:
                                stats['trash'] += 1
                                continue
                            
                            # Произошел триггер! Делаем запасной запрос по КОНТРАКТУ ТОКЕНА
                            print(f"🔍 Запрос в CG для токена {token_addr}...")
                            cg_id = await check_coingecko_listing(session, token_addr, network)
                            
                            if cg_id:
                                stats['cg_api_hits'] += 1
                                print(f"✅ Найден скрытый ID: {cg_id}")
                            else:
                                stats['trash'] += 1
                                continue 
                        else:
                            if not is_triggered:
                                stats['passed'] += 1
                                continue
                        
                        stats['passed'] += 1
                        
                        # --- ОТПРАВКА СИГНАЛА ---
                        type_sig = "P5" if is_p else ("D5" if is_d else "DH1")
                        key = f"{network}_{pool_addr}_{type_sig}"
                        
                        if key in sent_signals and (now - sent_signals[key]) < SETTINGS['cooldown']: continue
                        sent_signals[key] = now
                        stats['signals'] += 1
                        
                        act = "🚀 ПАМП (5м)" if is_p else ("🩸 ДАМП (5м)" if is_d else "⚠️ ЧАСОВОЙ ДАМП")
                        
                        cg_link = f"🦎 <a href='https://www.coingecko.com/en/coins/{cg_id}'>CoinGecko</a>"
                        gt_link = f"📈 <a href='https://www.geckoterminal.com/{network}/pools/{pool_addr}'>График</a>"
                        
                        msg = (f"{act} | <b>{network.upper()}</b>\n"
                               f"Пара: <code>{attrs.get('name')}</code>\n"
                               f"ID: <code>{cg_id}</code>\n"
                               f"Ликвидность: <b>${liq:,.0f}</b>\n\n"
                               f"5m: <b>{m5}%</b> | 1h: <b>{h1}%</b> | 24h: <b>{h24}%</b>\n\n"
                               f"Контракт пула: <code>{pool_addr}</code>\n"
                               f"Токен: <code>{token_addr}</code>\n\n"
                               f"{cg_link} | {gt_link}")
                        await send_tg(session, msg)
                        await asyncio.sleep(SETTINGS['tg_pause'])
                    except: continue
            
            await asyncio.sleep(2.5) 
        except Exception as e:
            print(f"❌ Ошибка: {e}"); break
            
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
                            await send_tg(sess, f"🤖 <b>Pro Scanner (Correct Addr + Liq)</b>\n\n"
                                               f"🏆 ТОП-6 (P/D): <b>{SETTINGS['top_pump']}%</b> / <b>-{SETTINGS['top_dump']}%</b>\n"
                                               f"💎 Редкие (P/D): <b>{SETTINGS['rare_pump']}%</b> / <b>-{SETTINGS['rare_dump']}%</b>\n"
                                               f"⏳ H1 Дамп: <b>-{SETTINGS['h1_dump']}%</b>\n"
                                               f"💧 Мин. ликвидность: <b>${SETTINGS['min_liq']:,.0f}</b>\n\n"
                                               "<b>Команды:</b>\n"
                                               "/pump_top [ч] | /dump_top [ч]\n"
                                               "/pump_rare [ч] | /dump_rare [ч]\n"
                                               "/dump_h1 [ч] | /min_liq [ч]")
                        elif txt.startswith('/'):
                            parts = txt.split()
                            if len(parts) == 2:
                                try:
                                    val = abs(float(parts[1]))
                                    if '/pump_top' in txt: SETTINGS['top_pump'] = val
                                    elif '/dump_top' in txt: SETTINGS['top_dump'] = val
                                    elif '/pump_rare' in txt: SETTINGS['rare_pump'] = val
                                    elif '/dump_rare' in txt: SETTINGS['rare_dump'] = val
                                    elif '/dump_h1' in txt: SETTINGS['h1_dump'] = val
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
