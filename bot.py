import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import sys

# --- Настройки ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = int(os.getenv('CHAT_ID')) if os.getenv('CHAT_ID') else None

RSS_SOURCES = [
    'https://www.dezeen.com/feed/',
    'https://www.archdaily.com/feed',
    'https://www.houzz.ru/rss',
    'https://www.idei-vashogo-doma.ru/rss.xml',
]

TIMEZONE = 'Europe/Moscow'
MAX_NEWS = 7

logging.basicConfig(level=logging.INFO)

def fetch_image_from_link(url):
    try:
        r = requests.get(url, timeout=5)
        soup = BeautifulSoup(r.content, 'html.parser')
        img = soup.find('meta', property='og:image')
        if img and img.get('content'):
            return img['content']
        img = soup.find('img')
        if img and img.get('src'):
            return img['src']
    except Exception as e:
        logging.warning(f"Ошибка получения картинки: {e}")
    return None

def parse_and_filter_entries():
    news_items = []
    now = datetime.utcnow() + timedelta(hours=3)  # Москва UTC+3
    since = now - timedelta(days=1)

    for source in RSS_SOURCES:
        feed = feedparser.parse(source)
        for entry in feed.entries:
            published = None
            if 'published_parsed' in entry:
                published = datetime(*entry.published_parsed[:6]) + timedelta(hours=3)
            elif 'updated_parsed' in entry:
                published = datetime(*entry.updated_parsed[:6]) + timedelta(hours=3)
            else:
                continue
            if published < since:
                continue

            title = entry.title
            link = entry.link
            summary = BeautifulSoup(entry.summary, 'html.parser').get_text()
            description = ' '.join(summary.split()[:30]) + '...'

            image = None
            if 'media_content' in entry and len(entry.media_content) > 0:
                image = entry.media_content[0].get('url')
            if not image:
                image = fetch_image_from_link(link)

            news_items.append({
                'title': title,
                'link': link,
                'description': description,
                'image': image
            })

            if len(news_items) >= MAX_NEWS:
                break
        if len(news_items) >= MAX_NEWS:
            break
    return news_items

async def send_news(bot: Bot, chat_id: int):
    news = parse_and_filter_entries()
    if not news:
        await bot.send_message(chat_id, "Новости за последние 24 часа не найдены.")
        return

    for item in news:
        text = f"*{escape_markdown(item['title'], version=2)}*\n\n" \
               f"{escape_markdown(item['description'], version=2)}\n\n" \
               f"[Подробнее]({item['link']})"
        try:
            if item['image']:
                await bot.send_photo(chat_id=chat_id, photo=item['image'], caption=text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logging.warning(f"Ошибка при отправке новости: {e}")

async def news_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await send_news(context.bot, chat_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Привет! Твой чат ID: {chat_id}\n"
                                    "Этот бот будет присылать тебе новости каждый день в 10 утра по Москве.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.start()

    if CHAT_ID:
        scheduler.add_job(news_job, 'cron', hour=10, minute=0, kwargs={'context': app, 'job': None}, id='news_job', replace_existing=True)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.run_polling())

if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
        sys.exit()
