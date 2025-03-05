import os
import sqlite3
import random
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

bot = Bot(TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

conn = sqlite3.connect('lang_bot.db')
cursor = conn.cursor()

# Создание таблиц с исправлениями
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    registration_date TEXT
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS words (
    word_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    word TEXT,
    translation TEXT,
    added_date TEXT
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS stats (
    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    correct INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
)''')  # Добавлен UNIQUE constraint
conn.commit()

class AddWord(StatesGroup):
    waiting_for_word = State()
    waiting_for_translation = State()

class DeleteWord(StatesGroup):
    waiting_for_delete_choice = State()

user_tests = {}

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    registration_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, registration_date) VALUES (?, ?, ?)',
                   (user_id, username, registration_date))
    conn.commit()
    
    await message.answer(
        "Добро пожаловать в бот для изучения языков!\n"
        "Список команд:\n"
        "/add - добавить новое слово\n"
        "/test - начать тест\n"
        "/stats - показать статистику\n"
        "/delete - удалить слово\n"
        "/help - список команд"
    )

@dp.message_handler(commands=['help'])
async def help(message: types.Message):
    await message.answer(
        "Список команд:\n"
        "/add - добавить новое слово\n"
        "/test - начать тест\n"
        "/stats - показать статистику\n"
        "/delete - удалить слово\n"
        "/help - список команд"
    )

@dp.message_handler(commands=['add'])
async def add_word(message: types.Message):
    await AddWord.waiting_for_word.set()
    await message.answer("Введите слово на изучаемом языке:")

@dp.message_handler(state=AddWord.waiting_for_word)
async def process_word(message: types.Message, state: FSMContext):
    await state.update_data(word=message.text)
    await AddWord.next()
    await message.answer("Теперь введите перевод этого слова:")

@dp.message_handler(state=AddWord.waiting_for_translation)
async def process_translation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    added_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('INSERT INTO words (user_id, word, translation, added_date) VALUES (?, ?, ?, ?)',
                   (user_id, data['word'], message.text, added_date))
    conn.commit()
    
    await state.finish()
    await message.answer("Слово успешно добавлено!")

@dp.message_handler(commands=['test'])
async def start_test(message: types.Message):
    user_id = message.from_user.id
    
    cursor.execute('SELECT word, translation FROM words WHERE user_id = ? ORDER BY RANDOM() LIMIT 1', (user_id,))
    word_data = cursor.fetchone()
    
    if not word_data:
        await message.answer("Ваш словарь пуст. Добавьте слова через /add.")
        return
    
    word, correct_translation = word_data
    user_tests[user_id] = {
        'word': word,
        'correct': correct_translation,
        'attempts_left': 3
    }
    
    await message.answer(f"Переведите слово: {word}")

@dp.message_handler(lambda message: message.from_user.id in user_tests)
async def check_answer(message: types.Message):
    user_id = message.from_user.id
    test_data = user_tests[user_id]
    
    user_answer = message.text.strip().lower()
    correct_answer = test_data['correct'].lower()
    
    test_data['attempts_left'] -= 1
    
    if user_answer == correct_answer:
        date_today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            INSERT INTO stats (user_id, date, correct, total) 
            VALUES (?, ?, 1, 1)
            ON CONFLICT(user_id, date) 
            DO UPDATE SET 
                correct = correct + 1,
                total = total + 1
        ''', (user_id, date_today))
        conn.commit()
        await message.answer("Правильно! 🎉")
        del user_tests[user_id]
    else:
        if test_data['attempts_left'] > 0:
            await message.answer(f"Неверно. Осталось попыток: {test_data['attempts_left']}")
        else:
            date_today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                INSERT INTO stats (user_id, date, total) 
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, date) 
                DO UPDATE SET 
                    total = total + 1
            ''', (user_id, date_today))
            conn.commit()
            await message.answer(f"Попытки закончились. Правильный ответ: {test_data['correct']}")
            del user_tests[user_id]

@dp.message_handler(commands=['delete'])
async def delete_word(message: types.Message, state: FSMContext):  # Исправлено
    user_id = message.from_user.id
    
    cursor.execute('SELECT word_id, word, translation FROM words WHERE user_id = ?', (user_id,))
    words = cursor.fetchall()
    
    if not words:
        await message.answer("Ваш словарь пуст.")
        return
    
    words_list = "\n".join([f"{idx + 1}. {word} - {translation}" for idx, (word_id, word, translation) in enumerate(words)])
    await message.answer(f"Ваши слова:\n{words_list}\nВведите номер слова для удаления:")
    
    async with state.proxy() as data:
        data['words'] = words
    
    await DeleteWord.waiting_for_delete_choice.set()

@dp.message_handler(state=DeleteWord.waiting_for_delete_choice)
async def process_delete_choice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    words = data['words']
    
    try:
        choice = int(message.text.strip()) - 1
        if choice < 0 or choice >= len(words):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Пожалуйста, введите корректный номер из списка.")
        return
    
    word_id = words[choice][0]
    
    cursor.execute('DELETE FROM words WHERE word_id = ?', (word_id,))
    conn.commit()
    
    await state.finish()
    await message.answer("Слово успешно удалено!")

@dp.message_handler(commands=['stats'])
async def show_stats(message: types.Message):
    user_id = message.from_user.id
    
    cursor.execute('SELECT COUNT(*) FROM words WHERE user_id = ?', (user_id,))
    total_words = cursor.fetchone()[0]
    
    date_today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT SUM(correct), SUM(total) FROM stats WHERE user_id = ? AND date = ?', (user_id, date_today))
    today_stats = cursor.fetchone() or (0, 0)
    
    cursor.execute('SELECT SUM(correct), SUM(total) FROM stats WHERE user_id = ?', (user_id,))
    all_time_stats = cursor.fetchone() or (0, 0)
    
    stats_text = (
        f"📊 Статистика:\n"
        f"Всего слов: {total_words}\n\n"
        f"Сегодня:\n"
        f"Правильно: {today_stats[0]}\n"
        f"Всего попыток: {today_stats[1]}\n\n"
        f"За всё время:\n"
        f"Правильно: {all_time_stats[0]}\n"
        f"Всего попыток: {all_time_stats[1]}"
    )

    await message.answer(stats_text)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
