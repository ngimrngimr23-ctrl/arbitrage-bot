import aiohttp
import asyncio
import json
import os

API_TOKEN = os.environ.get("GIFT_SATELLITE_TOKEN")
BASE_URL = "https://gift-satellite.dev/api"

async def main():
    headers = {"Authorization": f"Token {API_TOKEN}"}
    
    # Список возможных форматов, которые обычно используют такие API
    test_slugs = [
        "durovs-cap",      # Классика
        "durov-s-cap",     # С дефисом вместо апострофа
        "durovs_cap",      # С нижним подчеркиванием
        "durovscap",       # Слитно
        "plush-pepe",      # Проверим другую коллекцию на всякий случай
        "plush_pepe"
    ]
    
    print("🚀 Начинаем взлом формата коллекций...")
    
    async with aiohttp.ClientSession() as session:
        for slug in test_slugs:
            url = f"{BASE_URL}/search/tg/{slug}?limit=1"
            print(f"👉 Пробуем: {slug}")
            
            try:
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        data = await r.json()
                        print(f"✅ УСПЕХ! Правильный формат: '{slug}'")
                        print("================ JSON СТАРТ ================")
                        print(json.dumps(data, indent=4, ensure_ascii=False))
                        print("================ JSON КОНЕЦ ================")
                        return # Бинго! Выходим из цикла
                    else:
                        data = await r.json()
                        print(f"❌ Не подошло: {r.status} - {data.get('message')}")
            except Exception as e:
                print(f"⚠️ Ошибка запроса: {e}")
            
            # Небольшая пауза, чтобы API не забанил за спам
            await asyncio.sleep(1)
            
        print("😭 Ни один формат не подошел. Надо искать другой эндпоинт.")

if __name__ == "__main__":
    asyncio.run(main())
