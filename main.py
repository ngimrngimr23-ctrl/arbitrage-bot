import aiohttp
import asyncio
import json
import os
import urllib.parse

# Настройки из Environment Variables
API_TOKEN = os.environ.get("GIFT_SATELLITE_TOKEN")
BASE_URL = "https://gift-satellite.dev/api"

# Список всех коллекций
ALL_COLLECTIONS = [
    "Heart Locket", "Plush Pepe", "Heroic Helmet", "Mighty Arm", "Ion Gem", 
    "Durov's Cap", "Nail Bracelet", "Perfume Bottle", "Magic Potion", "Mini Oscar", 
    "Astral Shard", "Artisan Brick", "Gem Signet", "Sharp Tongue", "Moon Pendant", 
    "Lunar Snake", "Holiday Drink", "Record Player", "Joyful Bundle", "Restless Jar", 
    "Big Year", "Light Sword", "Jingle Bells", "Eternal Candle", "Skull Flower", 
    "Sakura Flower", "Jelly Bunny", "Cupid Charm", "Hanging Star", "Easter Egg", 
    "Spy Agaric", "Homemade Cake", "Snow Globe", "Xmas Stocking", "B-Day Candle", 
    "Candy Cane", "Lush Bouquet", "Top Hat", "Scared Cat", "Spiced Wine", 
    "Evil Eye", "Ionic Dryer", "Ginger Cookie", "Hex Pot", "Stellar Rocket", 
    "Trapped Heart", "Snake Box", "Loot Bag", "Electric Skull", "Love Candle", 
    "Jack-in-the-Box", "Witch Hat", "Love Potion", "Kissed Frog", "Diamond Ring", 
    "Neko Helmet", "Pet Snake", "Jester Hat", "Flying Broom", "Party Sparkler", 
    "Star Notepad", "Voodoo Doll", "Bonded Ring", "Snow Mittens", "Crystal Ball", 
    "Berry Box", "Tama Gadget", "Valentine Box", "Cookie Heart", "Precious Peach", 
    "Bow Tie", "Signet Ring", "Lol Pop", "Santa Hat", "Hypno Lollipop", 
    "Winter Wreath", "Vintage Cigar", "Bunny Muffin", "Mad Pumpkin", "Eternal Rose", 
    "Jolly Chimp", "Input Key", "Desk Calendar", "Swiss Watch", "Sleigh Bell", 
    "Toy Bear", "Sky Stilettos", "Fresh Socks", "Clover Pin", "Instant Ramen", 
    "Mousse Cake", "Spring Basket", "Chill Bar", "Faith Amulet", "Telegram Pin",
    "UFC Strike", "Snoop Dogg", "Swag Bag", "Snoop Cigar", "Low Rider", 
    "Westside Sign", "Khabib's Papakha"
]

async def fetch_prices(session, market, coll):
    # Кодируем название, чтобы не было ошибки 400
    safe_coll = urllib.parse.quote(coll)
    url = f"{BASE_URL}/search/{market}/{safe_coll}?limit=1000"
    headers = {"Authorization": f"Token {API_TOKEN}"}
    
    try:
        async with session.get(url, headers=headers, timeout=15) as r:
            if r.status == 200:
                data = await r.json()
                # Извлекаем список предметов
                items = data if isinstance(data, list) else (data.get("data") or [])
                return items
            elif r.status == 429:
                return "RATE_LIMIT"
    except:
        pass
    return []

async def main():
    # 3 площадки для анализа
    markets = ["tg", "mrkt", "portals"]
    final_data = {}

    print(f"🚀 Начинаю сбор данных по {len(ALL_COLLECTIONS)} коллекциям на 3 площадках...")

    async with aiohttp.ClientSession() as session:
        for coll in ALL_COLLECTIONS:
            coll_min_prices = {}
            
            for mkt in markets:
                res = await fetch_prices(session, mkt, coll)
                
                # Если поймали лимит — ждем
                if res == "RATE_LIMIT":
                    print(f"⏳ Лимит на {mkt}, жду 5 секунд...")
                    await asyncio.sleep(5)
                    res = await fetch_prices(session, mkt, coll)
                
                if isinstance(res, list):
                    for item in res:
                        model = item.get("modelName")
                        price = float(item.get("normalizedPrice", 0))
                        
                        if model and price > 0:
                            model = str(model).strip()
                            # Оставляем только самую низкую цену для этой модели
                            if model not in coll_min_prices or price < coll_min_prices[model]:
                                coll_min_prices[model] = price
                
                # Пауза между запросами к площадкам
                await asyncio.sleep(2)
            
            if coll_min_prices:
                final_data[coll] = coll_min_prices
                print(f"✅ {coll}: данные собраны.")
            
            # Пауза перед следующей коллекцией
            await asyncio.sleep(1)

    print("\n================ ФИНАЛЬНАЯ ВЫЖИМКА (MIN PRICES) ================")
    print(json.dumps(final_data, indent=2, ensure_ascii=False))
    print("================ КОНЕЦ ДАННЫХ ================")

if __name__ == "__main__":
    asyncio.run(main())
    
