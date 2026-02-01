import os
import logging
import sqlite3
import re
import random
import string
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ================================
# НАСТРОЙКИ БОТА
# ================================
BOT_TOKEN = "8033816997:AAH4YS-rVf31SSmcrdBScJKQkg_Fxd0ed_E"
ADMIN_ID = 6970104969
# ================================

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Рандомные эмодзи для уведомлений
RANDOM_EMOJIS = [
    "🎉", "✨", "🌟", "💫", "🔥", "💖", "🎊", "🎈", 
    "💌", "📮", "✉️", "💬", "🗨️", "👻", "🎭", "🕶️",
    "🎯", "🎪", "🎨", "🖼️", "📸", "🎥", "🎬", "📯",
    "🔮", "💎", "🎁", "🎀", "🦋", "🐱", "🐶", "🐼",
    "🦄", "🦊", "🐰", "🐨", "🐯", "🦁", "🐸", "🐙",
    "🦑", "🐳", "🐬", "🦈", "🐠", "🐡", "🦜", "🦢",
    "🦉", "🦚", "🦩", "🌹", "🌺", "🌸", "🌼", "🌻",
    "💐", "🍀", "🌿", "🍃", "🌙", "⭐", "☀️", "🌈",
    "🌊", "⛰️", "🗻", "🌋", "🏞️", "🎡", "🎢", "🚀",
    "🛸", "👽", "🤖", "🎮", "🕹️", "🎲", "♟️", "🎯",
    "🎳", "⚽", "🏀", "🏈", "⚾", "🎾", "🏐", "🏓",
    "🎿", "⛸️", "🛷", "🎣", "🏹", "🥊", "🤿", "🏄",
    "🏊", "🚣", "🏇", "🚴", "🤸", "🤹", "🎪", "🎭",
    "🎤", "🎧", "🎼", "🎹", "🥁", "🎷", "🎺", "🪕",
    "🎸", "🎻", "🪗", "📱", "💻", "🖥️", "⌨️", "🖱️",
    "🖨️", "📠", "📞", "📟", "📻", "📺", "🎥", "📽️",
    "🎞️", "📀", "💿", "📼", "📷", "📹", "🔍", "🔎",
    "💡", "🔦", "🕯️", "🗺️", "🧭", "⏱️", "⏲️", "⏰",
    "🕰️", "⌛", "⏳", "📡", "🔭", "🔬", "💉", "💊",
    "🩺", "🧪", "🧫", "🧬", "🦠", "🧼", "🛁", "🚿",
    "🛋️", "🛏️", "🛌", "🧸", "🪀", "🪁", "🎗️", "🎖️",
    "🏆", "🥇", "🥈", "🥉", "🏅", "🎖️", "📜", "🏛️"
]

# Функция для получения случайного эмодзи
def get_random_emoji():
    return random.choice(RANDOM_EMOJIS)

# Типы медиафайлов
class MediaType(Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    ANIMATION = "animation"

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name: str = "anonymous_bot.db"):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем существование таблицы users и её структуру
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            users_table_exists = cursor.fetchone()
            
            if users_table_exists:
                # Проверяем наличие колонки ref_code
                cursor.execute("PRAGMA table_info(users)")
                columns = cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                # Добавляем отсутствующие колонки
                if 'ref_code' not in column_names:
                    try:
                        cursor.execute('ALTER TABLE users ADD COLUMN ref_code TEXT UNIQUE')
                        logger.info("Добавлена колонка ref_code в таблицу users")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить колонку ref_code: {e}")
                
                if 'referrer_id' not in column_names:
                    try:
                        cursor.execute('ALTER TABLE users ADD COLUMN referrer_id INTEGER')
                        logger.info("Добавлена колонка referrer_id в таблицу users")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить колонку referrer_id: {e}")
                
                if 'received_messages' not in column_names:
                    try:
                        cursor.execute('ALTER TABLE users ADD COLUMN received_messages INTEGER DEFAULT 0')
                        logger.info("Добавлена колонка received_messages в таблицу users")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить колонку received_messages: {e}")
                
                if 'sent_messages' not in column_names:
                    try:
                        cursor.execute('ALTER TABLE users ADD COLUMN sent_messages INTEGER DEFAULT 0')
                        logger.info("Добавлена колонка sent_messages в таблицу users")
                    except Exception as e:
                        logger.warning(f"Не удалось добавить колонку sent_messages: {e}")
            else:
                # Создаем таблицу пользователей с нуля
                cursor.execute('''
                    CREATE TABLE users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        full_name TEXT NOT NULL,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        referrer_id INTEGER,
                        received_messages INTEGER DEFAULT 0,
                        sent_messages INTEGER DEFAULT 0,
                        ref_code TEXT UNIQUE
                    )
                ''')
                logger.info("Создана таблица users")
            
            # Создаем таблицу сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    text TEXT,
                    media_type TEXT,
                    media_file_id TEXT,
                    media_unique_id TEXT,
                    thumbnail_file_id TEXT,
                    sticker_emoji TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    duration INTEGER,
                    width INTEGER,
                    height INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_by_admin BOOLEAN DEFAULT FALSE,
                    reply_to_message_id INTEGER,
                    is_reply BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Создаем таблицу блокировок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocks (
                    block_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    blocked_user_id INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, blocked_user_id)
                )
            ''')
            
            conn.commit()
            
            # Создаем индексы
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_from_user ON messages(from_user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_to_user ON messages(to_user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_code ON users(ref_code)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_reply_to ON messages(reply_to_message_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocks_user ON blocks(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_user_id)')
                conn.commit()
                logger.info("Индексы созданы успешно")
            except Exception as e:
                logger.warning(f"Не удалось создать индексы: {e}")
            
            logger.info("База данных инициализирована")
    
    def generate_ref_code(self, length: int = 8) -> str:
        """Генерирует уникальный реф-код из букв и цифр"""
        characters = string.ascii_letters + string.digits
        characters = characters.translate(str.maketrans('', '', '0O1Il'))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for _ in range(10):  # Пробуем 10 раз
                ref_code = ''.join(random.choice(characters) for _ in range(length))
                cursor.execute('SELECT user_id FROM users WHERE ref_code = ?', (ref_code,))
                if not cursor.fetchone():
                    return ref_code
        
        # Если не удалось сгенерировать уникальный, добавляем цифры
        return f"{''.join(random.choice(characters) for _ in range(length-2))}{random.randint(10, 99)}"
    
    def add_or_update_user(self, user_id: int, username: str, full_name: str, referrer_id: Optional[int] = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT user_id, ref_code FROM users WHERE user_id = ?', (user_id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                cursor.execute('''
                    UPDATE users 
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                ''', (username, full_name, user_id))
                logger.info(f"Обновлен пользователь: {user_id} - {full_name}")
                
                # Получаем ref_code из результата запроса
                existing_ref_code = existing_user[1] if existing_user and len(existing_user) > 1 else None
                
                if not existing_ref_code:
                    ref_code = self.generate_ref_code()
                    cursor.execute('UPDATE users SET ref_code = ? WHERE user_id = ?', (ref_code, user_id))
                    logger.info(f"Сгенерирован ref_code для пользователя {user_id}: {ref_code}")
                    conn.commit()
                    return ref_code
                else:
                    conn.commit()
                    return existing_ref_code
            else:
                ref_code = self.generate_ref_code()
                try:
                    cursor.execute('''
                        INSERT INTO users (user_id, username, full_name, referrer_id, ref_code)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, username, full_name, referrer_id, ref_code))
                    conn.commit()
                    logger.info(f"Добавлен новый пользователь: {user_id} - {full_name}, ref_code: {ref_code}")
                    return ref_code
                except sqlite3.IntegrityError:
                    ref_code = self.generate_ref_code()
                    cursor.execute('''
                        INSERT INTO users (user_id, username, full_name, referrer_id, ref_code)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, username, full_name, referrer_id, ref_code))
                    conn.commit()
                    logger.info(f"Добавлен новый пользователь с новым ref_code: {user_id} - {full_name}, ref_code: {ref_code}")
                    return ref_code
    
    def get_user_by_id(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()
    
    def get_user_by_ref_code(self, ref_code: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE ref_code = ?', (ref_code,))
            return cursor.fetchone()
    
    def add_message(
        self, 
        from_user_id: int, 
        to_user_id: int, 
        text: Optional[str] = None,
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        media_unique_id: Optional[str] = None,
        thumbnail_file_id: Optional[str] = None,
        sticker_emoji: Optional[str] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        is_reply: bool = False
    ):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO messages (
                    from_user_id, to_user_id, text, media_type, media_file_id,
                    media_unique_id, thumbnail_file_id, sticker_emoji,
                    file_name, mime_type, file_size, duration, width, height,
                    reply_to_message_id, is_reply
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                from_user_id, to_user_id, text, media_type, media_file_id,
                media_unique_id, thumbnail_file_id, sticker_emoji,
                file_name, mime_type, file_size, duration, width, height,
                reply_to_message_id, is_reply
            ))
            
            message_id = cursor.lastrowid
            
            # Обновляем статистику
            if not is_reply:  # Ответы не считаем как новые сообщения в статистике
                cursor.execute('''
                    UPDATE users 
                    SET sent_messages = sent_messages + 1 
                    WHERE user_id = ?
                ''', (from_user_id,))
                
                cursor.execute('''
                    UPDATE users 
                    SET received_messages = received_messages + 1 
                    WHERE user_id = ?
                ''', (to_user_id,))
            
            conn.commit()
            logger.info(f"Добавлено сообщение #{message_id} от {from_user_id} к {to_user_id}")
            return message_id
    
    def get_message(self, message_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE message_id = ?', (message_id,))
            return cursor.fetchone()
    
    def get_last_message_to_user(self, to_user_id: int, from_user_id: int):
        """Получает последнее сообщение от определенного отправителя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM messages 
                WHERE to_user_id = ? AND from_user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            ''', (to_user_id, from_user_id))
            return cursor.fetchone()
    
    # Функции для блокировок
    def block_user(self, user_id: int, blocked_user_id: int) -> bool:
        """Блокирует пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO blocks (user_id, blocked_user_id)
                    VALUES (?, ?)
                ''', (user_id, blocked_user_id))
                conn.commit()
                logger.info(f"Пользователь {user_id} заблокировал {blocked_user_id}")
                return True
            except Exception as e:
                logger.error(f"Ошибка при блокировке пользователя: {e}")
                return False
    
    def unblock_user(self, user_id: int, blocked_user_id: int) -> bool:
        """Разблокирует пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    DELETE FROM blocks 
                    WHERE user_id = ? AND blocked_user_id = ?
                ''', (user_id, blocked_user_id))
                conn.commit()
                logger.info(f"Пользователь {user_id} разблокировал {blocked_user_id}")
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при разблокировке пользователя: {e}")
                return False
    
    def is_user_blocked(self, user_id: int, blocked_user_id: int) -> bool:
        """Проверяет, заблокирован ли пользователь"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 1 FROM blocks 
                WHERE user_id = ? AND blocked_user_id = ?
                LIMIT 1
            ''', (user_id, blocked_user_id))
            return cursor.fetchone() is not None
    
    def get_blocked_users(self, user_id: int):
        """Получает список заблокированных пользователей для обычного пользователя (без информации)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT block_id, blocked_user_id, timestamp
                FROM blocks 
                WHERE user_id = ?
                ORDER BY timestamp DESC
            ''', (user_id,))
            return cursor.fetchall()
    
    def get_blocked_users_for_admin(self, user_id: int):
        """Получает полную информацию о заблокированных пользователях для админа"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT b.block_id, b.blocked_user_id, u.full_name, u.username, b.timestamp
                FROM blocks b
                LEFT JOIN users u ON b.blocked_user_id = u.user_id
                WHERE b.user_id = ?
                ORDER BY b.timestamp DESC
            ''', (user_id,))
            return cursor.fetchall()
    
    def get_all_blocks_for_admin(self):
        """Получает все блокировки для админа"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT b.block_id, b.user_id, u1.full_name as blocker_name, u1.username as blocker_username,
                       b.blocked_user_id, u2.full_name as blocked_name, u2.username as blocked_username,
                       b.timestamp
                FROM blocks b
                LEFT JOIN users u1 ON b.user_id = u1.user_id
                LEFT JOIN users u2 ON b.blocked_user_id = u2.user_id
                ORDER BY b.timestamp DESC
                LIMIT 50
            ''')
            return cursor.fetchall()
    
    def get_user_messages(self, user_id: int, limit: int = 50):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, 
                       u.full_name as sender_name,
                       u.username as sender_username
                FROM messages m
                LEFT JOIN users u ON m.from_user_id = u.user_id
                WHERE m.to_user_id = ? 
                ORDER BY m.timestamp DESC 
                LIMIT ?
            ''', (user_id, limit))
            return cursor.fetchall()
    
    def get_conversation_messages(self, user1_id: int, user2_id: int, limit: int = 20):
        """Получает переписку между двумя пользователями"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*,
                       u1.full_name as sender_name,
                       u2.full_name as receiver_name
                FROM messages m
                LEFT JOIN users u1 ON m.from_user_id = u1.user_id
                LEFT JOIN users u2 ON m.to_user_id = u2.user_id
                WHERE (m.from_user_id = ? AND m.to_user_id = ?)
                   OR (m.from_user_id = ? AND m.to_user_id = ?)
                ORDER BY m.timestamp ASC
                LIMIT ?
            ''', (user1_id, user2_id, user2_id, user1_id, limit))
            return cursor.fetchall()
    
    def get_all_messages(self, limit: int = 100):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, 
                       u1.full_name as from_name, u1.username as from_username,
                       u2.full_name as to_name, u2.username as to_username
                FROM messages m
                LEFT JOIN users u1 ON m.from_user_id = u1.user_id
                LEFT JOIN users u2 ON m.to_user_id = u2.user_id
                ORDER BY m.timestamp DESC 
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
    
    def get_all_users(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY registration_date DESC')
            return cursor.fetchall()
    
    def get_user_stats(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()
    
    def get_total_stats(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as total_users FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) as total_messages FROM messages')
            total_messages = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) as total_replies FROM messages WHERE is_reply = TRUE')
            total_replies = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) as total_blocks FROM blocks')
            total_blocks = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'total_messages': total_messages,
                'total_replies': total_replies,
                'total_blocks': total_blocks
            }

# Инициализация базы данных
db = Database()

# Генерация реф-ссылки
def generate_ref_link(ref_code: str, bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start=ref{ref_code}"

# Хранилище для данных о последних сообщениях пользователей
user_last_messages: Dict[int, Dict[str, Any]] = {}

async def process_media_message(
    message: Message,
    from_user_id: int,
    to_user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_to_message_id: Optional[int] = None,
    is_reply: bool = False
) -> Tuple[str, Optional[str], dict]:
    """Обрабатывает медиа-сообщения"""
    
    # Проверяем, не заблокирован ли отправитель
    if db.is_user_blocked(to_user_id, from_user_id):
        raise Exception("Вы заблокированы этим пользователем")
    
    media_type = None
    media_file_id = None
    media_unique_id = None
    thumbnail_file_id = None
    sticker_emoji = None
    file_name = None
    mime_type = None
    file_size = None
    duration = None
    width = None
    height = None
    caption = message.caption or ""
    
    if message.photo:
        media_type = MediaType.PHOTO.value
        media_file_id = message.photo[-1].file_id
        media_unique_id = message.photo[-1].file_unique_id
        file_size = message.photo[-1].file_size
        width = message.photo[-1].width
        height = message.photo[-1].height
    
    elif message.video:
        media_type = MediaType.VIDEO.value
        media_file_id = message.video.file_id
        media_unique_id = message.video.file_unique_id
        thumbnail_file_id = message.video.thumbnail.file_id if message.video.thumbnail else None
        file_name = message.video.file_name
        mime_type = message.video.mime_type
        file_size = message.video.file_size
        duration = message.video.duration
        width = message.video.width
        height = message.video.height
    
    elif message.document:
        media_type = MediaType.DOCUMENT.value
        media_file_id = message.document.file_id
        media_unique_id = message.document.file_unique_id
        thumbnail_file_id = message.document.thumbnail.file_id if message.document.thumbnail else None
        file_name = message.document.file_name
        mime_type = message.document.mime_type
        file_size = message.document.file_size
    
    elif message.audio:
        media_type = MediaType.AUDIO.value
        media_file_id = message.audio.file_id
        media_unique_id = message.audio.file_unique_id
        thumbnail_file_id = message.audio.thumbnail.file_id if message.audio.thumbnail else None
        file_name = message.audio.file_name
        mime_type = message.audio.mime_type
        file_size = message.audio.file_size
        duration = message.audio.duration
    
    elif message.voice:
        media_type = MediaType.VOICE.value
        media_file_id = message.voice.file_id
        media_unique_id = message.voice.file_unique_id
        file_size = message.voice.file_size
        duration = message.voice.duration
    
    elif message.sticker:
        media_type = MediaType.STICKER.value
        media_file_id = message.sticker.file_id
        media_unique_id = message.sticker.file_unique_id
        sticker_emoji = message.sticker.emoji
        file_size = message.sticker.file_size
        width = message.sticker.width
        height = message.sticker.height
    
    elif message.animation:
        media_type = MediaType.ANIMATION.value
        media_file_id = message.animation.file_id
        media_unique_id = message.animation.file_unique_id
        thumbnail_file_id = message.animation.thumbnail.file_id if message.animation.thumbnail else None
        file_name = message.animation.file_name
        mime_type = message.animation.mime_type
        file_size = message.animation.file_size
        width = message.animation.width
        height = message.animation.height
        duration = message.animation.duration
    
    elif message.text:
        media_type = MediaType.TEXT.value
        caption = message.text
    
    # Сохраняем в базу данных
    message_id = db.add_message(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        text=caption,
        media_type=media_type,
        media_file_id=media_file_id,
        media_unique_id=media_unique_id,
        thumbnail_file_id=thumbnail_file_id,
        sticker_emoji=sticker_emoji,
        file_name=file_name,
        mime_type=mime_type,
        file_size=file_size,
        duration=duration,
        width=width,
        height=height,
        reply_to_message_id=reply_to_message_id,
        is_reply=is_reply
    )
    
    # Сохраняем информацию о последнем отправителе для получателя
    if not is_reply:
        user_last_messages[to_user_id] = {
            "last_sender": from_user_id,
            "last_message_id": message_id,
            "timestamp": datetime.now()
        }
    
    return caption, media_type, {
        'message_id': message_id,
        'media_file_id': media_file_id,
        'thumbnail_file_id': thumbnail_file_id,
        'sticker_emoji': sticker_emoji,
        'reply_to_message_id': reply_to_message_id,
        'is_reply': is_reply
    }

async def send_media_to_recipient(
    context: ContextTypes.DEFAULT_TYPE,
    to_user_id: int,
    media_info: dict,
    caption: str,
    media_type: str,
    is_reply: bool = False,
    original_message_id: Optional[int] = None
):
    """Отправляет медиафайл получателю с рандомным эмодзи"""
    
    try:
        # Получаем случайный эмодзи
        random_emoji = get_random_emoji()
        
        # Формируем уведомление для получателя
        notification_text = f"{random_emoji} У вас новое анонимное сообщение!\n\n"
        
        if is_reply:
            notification_text = f"💬 {random_emoji} Ответ на ваше сообщение:\n\n"
        
        # Добавляем текст сообщения
        if caption:
            full_caption = notification_text + caption
        else:
            full_caption = notification_text + "📎 Медиа-сообщение"
        
        # Создаем клавиатуру с кнопкой "Заблокировать"
        keyboard = [
            [InlineKeyboardButton("🚫 Заблокировать отправителя", callback_data=f"block_{media_info['message_id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем сообщение в зависимости от типа медиа
        if media_type == MediaType.PHOTO.value:
            await context.bot.send_photo(
                chat_id=to_user_id,
                photo=media_info['media_file_id'],
                caption=full_caption,
                reply_markup=reply_markup
            )
        
        elif media_type == MediaType.VIDEO.value:
            await context.bot.send_video(
                chat_id=to_user_id,
                video=media_info['media_file_id'],
                caption=full_caption,
                reply_markup=reply_markup
            )
        
        elif media_type == MediaType.DOCUMENT.value:
            await context.bot.send_document(
                chat_id=to_user_id,
                document=media_info['media_file_id'],
                caption=full_caption,
                reply_markup=reply_markup
            )
        
        elif media_type == MediaType.AUDIO.value:
            await context.bot.send_audio(
                chat_id=to_user_id,
                audio=media_info['media_file_id'],
                caption=full_caption,
                reply_markup=reply_markup
            )
        
        elif media_type == MediaType.VOICE.value:
            await context.bot.send_voice(
                chat_id=to_user_id,
                voice=media_info['media_file_id'],
                caption=notification_text,
                reply_markup=reply_markup
            )
        
        elif media_type == MediaType.STICKER.value:
            # Для стикеров сначала отправляем уведомление, потом стикер
            await context.bot.send_message(
                chat_id=to_user_id,
                text=f"{random_emoji} У вас новое анонимное сообщение - стикер!",
                reply_markup=reply_markup
            )
            await context.bot.send_sticker(
                chat_id=to_user_id,
                sticker=media_info['media_file_id']
            )
        
        elif media_type == MediaType.ANIMATION.value:
            await context.bot.send_animation(
                chat_id=to_user_id,
                animation=media_info['media_file_id'],
                caption=full_caption,
                reply_markup=reply_markup
            )
        
        else:
            # Текстовое сообщение
            await context.bot.send_message(
                chat_id=to_user_id,
                text=full_caption,
                reply_markup=reply_markup
            )
        
        return True
    
    except Exception as e:
        logger.error(f"Ошибка отправки медиа: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_username = (await context.bot.get_me()).username
    
    # Регистрация или обновление пользователя
    ref_code = db.add_or_update_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name
    )
    
    # Обработка реф-ссылки
    if context.args:
        ref_arg = context.args[0]
        if ref_arg.startswith('ref'):
            ref_code_input = ref_arg[3:]
            
            # Ищем пользователя по реф-коду
            target_user = db.get_user_by_ref_code(ref_code_input)
            
            if target_user:
                target_user_id = target_user['user_id']
                
                # Проверяем, не отправляет ли пользователь сообщение самому себе
                if user.id == target_user_id:
                    await update.message.reply_text("❌ Нельзя отправлять сообщения самому себе!")
                    return
                
                # Проверяем, не заблокирован ли отправитель
                if db.is_user_blocked(target_user_id, user.id):
                    await update.message.reply_text("🚫 Вы заблокированы этим пользователем и не можете отправлять ему сообщения.")
                    return
                
                # Устанавливаем получателя в контекст
                context.user_data['awaiting_message_for'] = target_user_id
                context.user_data['is_ref_link'] = True
                
                # Сохраняем информацию о последнем отправителе
                if user.id not in user_last_messages:
                    user_last_messages[user.id] = {
                        "last_sender": target_user_id,
                        "last_message_id": None,
                        "timestamp": datetime.now()
                    }
                
                await update.message.reply_text(
                    f"👋 Теперь вы можете отправлять анонимные сообщения этому пользователю.\n"
                    f"Просто отправьте текст, фото, видео или любой другой файл.\n\n"
                    f"⚠️ Внимание: Если получатель заблокирует вас, вы больше не сможете отправлять ему сообщения."
                )
                return
    
    # Определяем, админ ли это
    if user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Все пользователи", callback_data="admin_users")],
            [InlineKeyboardButton("📨 Все сообщения", callback_data="admin_messages")],
            [InlineKeyboardButton("🔗 Моя реф-ссылка", callback_data="my_ref")],
            [InlineKeyboardButton("🚫 Все блокировки", callback_data="admin_blocks")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👑 Привет, Администратор!\n\n"
            f"Ваша реф-ссылка: {generate_ref_link(ref_code, bot_username)}\n\n"
            f"Используйте кнопки ниже для управления ботом:",
            reply_markup=reply_markup
        )
    else:
        # Клавиатура для обычных пользователей
        keyboard = [
            [InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            f"{get_random_emoji()} Привет! Я бот для анонимных сообщений.\n\n"
            f"🔗 Ваша персональная ссылка:\n"
            f"{generate_ref_link(ref_code, bot_username)}\n\n"
            "Отправьте эту ссылку друзьям, чтобы они могли писать вам анонимно!\n\n"
            "🚫 Вы можете блокировать нежелательных отправителей, используя кнопку под сообщением или через меню блокировок."
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    
    # Пропускаем команды
    if message.text and message.text.startswith('/'):
        return
    
    # Проверяем, является ли это ответом на сообщение
    if message.reply_to_message:
        # Проверяем, кто отвечает
        reply_msg = message.reply_to_message
        
        # Если админ отвечает на уведомление
        if user.id == ADMIN_ID and "🔒 Новое анонимное сообщение!" in reply_msg.text:
            await handle_admin_reply(update, context)
            return
        
        # Если обычный пользователь отвечает на полученное сообщение
        # Проверяем, было ли это сообщение от бота (анонимное сообщение)
        if reply_msg.from_user.id == (await context.bot.get_me()).id:
            # Проверяем, содержит ли сообщение уведомление о новом сообщении
            if "У вас новое анонимное сообщение!" in reply_msg.text or "Ответ на ваше сообщение:" in reply_msg.text:
                # Получаем информацию о последнем отправителе
                if user.id in user_last_messages:
                    last_sender_data = user_last_messages[user.id]
                    target_user_id = last_sender_data["last_sender"]
                    original_message_id = last_sender_data["last_message_id"]
                    
                    if target_user_id:
                        # Проверяем, не заблокирован ли отправитель
                        if db.is_user_blocked(target_user_id, user.id):
                            await message.reply_text("🚫 Вы заблокированы этим пользователем и не можете отправлять ему сообщения.")
                            return
                        
                        # Обрабатываем ответное сообщение
                        caption, media_type, media_info = await process_media_message(
                            message=message,
                            from_user_id=user.id,
                            to_user_id=target_user_id,
                            context=context,
                            reply_to_message_id=original_message_id,
                            is_reply=True
                        )
                        
                        # Уведомление админу
                        await notify_admin(update, context, user, target_user_id, caption, media_type, media_info, is_reply=True)
                        
                        # Отправляем ответ отправителю
                        success = await send_media_to_recipient(
                            context=context,
                            to_user_id=target_user_id,
                            media_info=media_info,
                            caption=caption,
                            media_type=media_type,
                            is_reply=True,
                            original_message_id=original_message_id
                        )
                        
                        if success:
                            await message.reply_text(f"{get_random_emoji()} Ответ отправлен!")
                        else:
                            await message.reply_text("❌ Не удалось отправить ответ.")
                        return
                    else:
                        await message.reply_text("❌ Не найден отправитель для ответа.")
                        return
    
    # Проверяем, установлен ли получатель в контексте (отправка по реф-ссылке)
    if 'awaiting_message_for' not in context.user_data:
        if user.id != ADMIN_ID:
            user_data = db.get_user_by_id(user.id)
            if user_data:
                ref_code = user_data['ref_code']
                bot_username = (await context.bot.get_me()).username
                
                keyboard = [
                    [InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                msg = (
                    f"Чтобы отправить сообщение, перейдите по ссылке получателя!\n\n"
                    f"🔗 Ваша ссылка:\n{generate_ref_link(ref_code, bot_username)}\n\n"
                    f"🚫 Вы можете блокировать нежелательных отправителей через меню блокировок."
                )
                
                await message.reply_text(msg, reply_markup=reply_markup)
        return
    
    target_user_id = context.user_data['awaiting_message_for']
    
    try:
        # Обрабатываем обычное сообщение (не ответ)
        caption, media_type, media_info = await process_media_message(
            message=message,
            from_user_id=user.id,
            to_user_id=target_user_id,
            context=context
        )
        
        # Уведомление админу
        await notify_admin(update, context, user, target_user_id, caption, media_type, media_info)
        
        # Отправляем сообщение получателю
        success = await send_media_to_recipient(
            context=context,
            to_user_id=target_user_id,
            media_info=media_info,
            caption=caption,
            media_type=media_type
        )
        
        if success:
            await message.reply_text(f"{get_random_emoji()} Сообщение отправлено анонимно!")
            
            # Если это была реф-ссылка, очищаем контекст
            if context.user_data.get('is_ref_link'):
                del context.user_data['awaiting_message_for']
                del context.user_data['is_ref_link']
        else:
            await message.reply_text("❌ Не удалось отправить сообщение. Возможно, пользователь заблокировал бота.")
    
    except Exception as e:
        if "Вы заблокированы" in str(e):
            await message.reply_text("🚫 Вы заблокированы этим пользователем и не можете отправлять ему сообщения.")
        else:
            await message.reply_text("❌ Произошла ошибка при отправке сообщения.")

async def notify_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sender,
    target_user_id: int,
    caption: str,
    media_type: str,
    media_info: dict,
    is_reply: bool = False
):
    """Отправляет уведомление админу"""
    
    target_user = db.get_user_by_id(target_user_id)
    target_name = target_user['full_name'] if target_user else f"ID: {target_user_id}"
    
    media_type_names = {
        MediaType.TEXT.value: "📝 Текст",
        MediaType.PHOTO.value: "🖼 Фото",
        MediaType.VIDEO.value: "🎥 Видео",
        MediaType.DOCUMENT.value: "📎 Документ",
        MediaType.AUDIO.value: "🎵 Аудио",
        MediaType.VOICE.value: "🎤 Голосовое",
        MediaType.STICKER.value: "😀 Стикер",
        MediaType.ANIMATION.value: "🎬 GIF"
    }
    
    media_type_text = media_type_names.get(media_type, "📦 Файл")
    
    prefix = "💬 ОТВЕТ" if is_reply else "🔒 НОВОЕ СООБЩЕНИЕ"
    
    admin_message = (
        f"{prefix}!\n\n"
        f"📊 Тип: {media_type_text}\n"
        f"👤 Отправитель: {sender.full_name} (@{sender.username})\n"
        f"🆔 ID отправителя: {sender.id}\n"
        f"🎯 Получатель: {target_name} (ID: {target_user_id})\n"
        f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    
    if media_info.get('reply_to_message_id'):
        admin_message += f"↩️ Ответ на сообщение ID: {media_info['reply_to_message_id']}\n"
    
    if caption and media_type != MediaType.STICKER.value:
        if len(caption) > 100:
            admin_message += f"📝 Текст: {caption[:100]}...\n"
        else:
            admin_message += f"📝 Текст: {caption}\n"
    
    if media_type == MediaType.STICKER.value:
        admin_message += f"😀 Стикер эмодзи: {media_info.get('sticker_emoji', 'N/A')}\n"
    
    admin_message += f"\n🆔 ID сообщения: {media_info['message_id']}"
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message
        )
        
        # Отправляем медиа админу
        if media_type != MediaType.TEXT.value and media_info.get('media_file_id'):
            caption_prefix = "💬 Ответ от анонима\n" if is_reply else ""
            await forward_media_to_admin(context, media_info, media_type, caption_prefix + caption if caption else caption_prefix)
            
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

async def forward_media_to_admin(context: ContextTypes.DEFAULT_TYPE, media_info: dict, media_type: str, caption: str = None):
    """Пересылает медиафайл админу"""
    
    try:
        if media_type == MediaType.PHOTO.value:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=media_info['media_file_id'],
                caption=caption if caption else "📸 Медиа от анонима"
            )
        
        elif media_type == MediaType.VIDEO.value:
            await context.bot.send_video(
                chat_id=ADMIN_ID,
                video=media_info['media_file_id'],
                caption=caption if caption else "🎥 Видео от анонима"
            )
        
        elif media_type == MediaType.DOCUMENT.value:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=media_info['media_file_id'],
                caption=caption if caption else "📎 Документ от анонима"
            )
        
        elif media_type == MediaType.AUDIO.value:
            await context.bot.send_audio(
                chat_id=ADMIN_ID,
                audio=media_info['media_file_id'],
                caption=caption if caption else "🎵 Аудио от анонима"
            )
        
        elif media_type == MediaType.VOICE.value:
            await context.bot.send_voice(
                chat_id=ADMIN_ID,
                voice=media_info['media_file_id'],
                caption=caption if caption else "🎤 Голосовое от анонима"
            )
        
        elif media_type == MediaType.STICKER.value:
            await context.bot.send_sticker(
                chat_id=ADMIN_ID,
                sticker=media_info['media_file_id']
            )
        
        elif media_type == MediaType.ANIMATION.value:
            await context.bot.send_animation(
                chat_id=ADMIN_ID,
                animation=media_info['media_file_id'],
                caption=caption if caption else "🎬 GIF от анонима"
            )
    
    except Exception as e:
        logger.error(f"Ошибка пересылки медиа админу: {e}")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ админа"""
    
    message = update.message
    reply_text = message.reply_to_message.text
    
    message_id_match = re.search(r'ID сообщения: (\d+)', reply_text)
    
    if message_id_match:
        message_id = int(message_id_match.group(1))
        msg_data = db.get_message(message_id)
        
        if msg_data:
            sender_id = msg_data['from_user_id']
            
            try:
                # Отправляем ответ отправителю с рандомным эмодзи
                random_emoji = get_random_emoji()
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"{random_emoji} Ответ администратора на ваше сообщение:\n\n{message.text}"
                )
                await message.reply_text(f"{random_emoji} Ответ отправлен анонимно!")
                
                # Помечаем сообщение как прочитанное
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'UPDATE messages SET read_by_admin = TRUE WHERE message_id = ?',
                        (message_id,)
                    )
                    conn.commit()
                    
            except Exception as e:
                await message.reply_text(f"❌ Ошибка: {str(e)}")
        else:
            await message.reply_text("❌ Сообщение не найдено в базе данных!")
    else:
        await message.reply_text("❌ Не удалось определить ID сообщения для ответа.")

# Команда для управления блокировками
async def blocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню блокировок"""
    user = update.effective_user
    await show_blocks_menu(user.id, update, context)

async def show_blocks_menu(user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню управления блокировками"""
    
    if user_id == ADMIN_ID:
        # Для админа показываем полную информацию
        blocked_users = db.get_all_blocks_for_admin()
        
        if not blocked_users:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]]
            await update.message.reply_text(
                "🚫 Блокировок пока нет.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        text = "🚫 Все блокировки в системе:\n\n"
        
        for block in blocked_users:
            blocker_name = block['blocker_name'] or f"ID: {block['user_id']}"
            blocked_name = block['blocked_name'] or f"ID: {block['blocked_user_id']}"
            timestamp = datetime.fromisoformat(block['timestamp']).strftime('%d.%m.%Y %H:%M')
            
            text += f"👤 {blocker_name} (@{block['blocker_username'] or 'нет'})\n"
            text += f"   🚫 Заблокировал: {blocked_name} (@{block['blocked_username'] or 'нет'})\n"
            text += f"   📅 Дата: {timestamp}\n"
            text += f"   🆔 ID блокировки: {block['block_id']}\n\n"
        
        text += f"📊 Всего блокировок: {len(blocked_users)}"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]]
        
        await update.message.reply_text(
            text[:4000],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Для обычного пользователя
    blocked_users = db.get_blocked_users(user_id)
    
    if not blocked_users:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        await update.message.reply_text(
            "🚫 У вас нет заблокированных пользователей.\n\n"
            "Вы можете заблокировать отправителя, нажав кнопку 'Заблокировать отправителя' под его сообщением.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Для обычного пользователя показываем только номера блокировок
    text = "🚫 Ваши заблокированные пользователи:\n\n"
    keyboard = []
    
    for i, blocked_user in enumerate(blocked_users[:10], 1):  # Ограничиваем 10 пользователями
        block_id = blocked_user['block_id']
        timestamp = datetime.fromisoformat(blocked_user['timestamp']).strftime('%d.%m.%Y')
        
        text += f"#{i}. Заблокирован: {timestamp}\n"
        
        keyboard.append([InlineKeyboardButton(
            f"🔓 Разблокировать #{i}", 
            callback_data=f"unblock_{block_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    
    if len(blocked_users) > 10:
        text += f"\n... и еще {len(blocked_users) - 10} заблокированных пользователей"
    
    text += "\n\nℹ️ Для конфиденциальности не отображаются имена заблокированных пользователей."
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Обработка кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    # Обработка блокировки через сообщение
    if data.startswith('block_'):
        message_id = int(data.split('_')[1])
        message_data = db.get_message(message_id)
        
        if message_data:
            blocked_user_id = message_data['from_user_id']
            
            # Блокируем пользователя
            if db.block_user(user.id, blocked_user_id):
                # Получаем информацию о заблокированном пользователе для админа
                blocked_user = db.get_user_by_id(blocked_user_id)
                blocked_name = blocked_user['full_name'] if blocked_user else f"ID: {blocked_user_id}"
                
                keyboard = [[InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks")]]
                
                await query.edit_message_text(
                    text=f"✅ Отправитель заблокирован!\n\n"
                         f"Он больше не сможет отправлять вам сообщения.\n\n"
                         f"ℹ️ Для конфиденциальности информация о заблокированном пользователе скрыта.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Уведомление админу о блокировке
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"🚫 ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН!\n\n"
                             f"👤 Пользователь: {user.full_name} (@{user.username})\n"
                             f"🆔 ID: {user.id}\n"
                             f"🚫 Заблокировал: {blocked_name}\n"
                             f"🆔 ID заблокированного: {blocked_user_id}\n"
                             f"📝 Сообщение ID: {message_id}\n"
                             f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу о блокировке: {e}")
            else:
                await query.edit_message_text("❌ Не удалось заблокировать пользователя.")
    
    # Обработка разблокировки по ID блокировки
    elif data.startswith('unblock_'):
        block_id = int(data.split('_')[1])
        
        # Находим информацию о блокировке
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, blocked_user_id FROM blocks WHERE block_id = ?
            ''', (block_id,))
            block_info = cursor.fetchone()
        
        if block_info and block_info['user_id'] == user.id:
            blocked_user_id = block_info['blocked_user_id']
            
            # Разблокируем пользователя
            if db.unblock_user(user.id, blocked_user_id):
                # Получаем информацию о разблокированном пользователе для админа
                blocked_user = db.get_user_by_id(blocked_user_id)
                blocked_name = blocked_user['full_name'] if blocked_user else f"ID: {blocked_user_id}"
                
                await query.edit_message_text(
                    text=f"✅ Пользователь разблокирован!\n\n"
                         f"Теперь он снова может отправлять вам сообщения.\n\n"
                         f"ℹ️ Для конфиденциальности информация о пользователе скрыта."
                )
                
                # Уведомление админу о разблокировке
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"🔓 ПОЛЬЗОВАТЕЛЬ РАЗБЛОКИРОВАН!\n\n"
                             f"👤 Пользователь: {user.full_name} (@{user.username})\n"
                             f"🆔 ID: {user.id}\n"
                             f"🔓 Разблокировал: {blocked_name}\n"
                             f"🆔 ID разблокированного: {blocked_user_id}\n"
                             f"🆔 ID блокировки: {block_id}\n"
                             f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления админу о разблокировке: {e}")
            else:
                await query.edit_message_text("❌ Не удалось разблокировать пользователя.")
        else:
            await query.edit_message_text("❌ Блокировка не найдена или у вас нет прав для ее удаления.")
    
    # Меню управления блокировками
    elif data == "manage_blocks":
        await show_blocks_menu(user.id, query, context)
    
    # Все блокировки для админа
    elif data == "admin_blocks":
        if user.id == ADMIN_ID:
            await show_blocks_menu(ADMIN_ID, query, context)
        else:
            await query.answer("❌ Эта функция только для администратора!", show_alert=True)
    
    # Возврат в главное меню для обычных пользователей
    elif data == "back_to_main":
        user_data = db.get_user_by_id(user.id)
        bot_username = (await context.bot.get_me()).username
        
        if user.id == ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 Все пользователи", callback_data="admin_users")],
                [InlineKeyboardButton("📨 Все сообщения", callback_data="admin_messages")],
                [InlineKeyboardButton("🔗 Моя реф-ссылка", callback_data="my_ref")],
                [InlineKeyboardButton("🚫 Все блокировки", callback_data="admin_blocks")]
            ]
            
            if user_data:
                ref_code = user_data['ref_code']
                await query.edit_message_text(
                    text=f"👑 Админ-панель\n\n"
                         f"Ваша реф-ссылка: {generate_ref_link(ref_code, bot_username)}\n\n"
                         f"Выберите действие:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            keyboard = [[InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks")]]
            
            if user_data:
                ref_code = user_data['ref_code']
                await query.edit_message_text(
                    text=f"{get_random_emoji()} Привет! Я бот для анонимных сообщений.\n\n"
                         f"🔗 Ваша персональная ссылка:\n"
                         f"{generate_ref_link(ref_code, bot_username)}\n\n"
                         "Отправьте эту ссылку друзьям, чтобы они могли писать вам анонимно!\n\n"
                         "🚫 Вы можете блокировать нежелательных отправителей, используя кнопку под сообщением или через меню блокировок.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    
    # Остальные кнопки (админские)
    else:
        await handle_admin_buttons(update, context)

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка админских кнопок"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    bot_username = (await context.bot.get_me()).username
    user_data = db.get_user_by_id(user.id)
    
    if not user_data:
        await query.edit_message_text("❌ Ошибка: пользователь не найден в базе данных")
        return
    
    ref_code = user_data['ref_code']
    
    if query.data == "my_ref":
        ref_link = generate_ref_link(ref_code, bot_username)
        await query.edit_message_text(
            text=f"{get_random_emoji()} Ваша реф-ссылка:\n\n{ref_link}\n\n"
                 "Отправьте эту ссылку друзьям, чтобы они могли писать вам анонимно!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
        )
    
    elif query.data == "admin_stats":
        stats = db.get_total_stats()
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT media_type, COUNT(*) as count 
                FROM messages 
                WHERE media_type IS NOT NULL
                GROUP BY media_type
            ''')
            media_stats = cursor.fetchall()
        
        stats_text = (
            f"📊 Статистика бота:\n\n"
            f"👥 Всего пользователей: {stats['total_users']}\n"
            f"📨 Всего сообщений: {stats['total_messages']}\n"
            f"💬 Ответов: {stats['total_replies']}\n"
            f"🚫 Блокировок: {stats['total_blocks']}\n\n"
            f"📈 Статистика по типам:\n"
        )
        
        media_type_names = {
            MediaType.TEXT.value: "📝 Текст",
            MediaType.PHOTO.value: "🖼 Фото",
            MediaType.VIDEO.value: "🎥 Видео",
            MediaType.DOCUMENT.value: "📎 Документы",
            MediaType.AUDIO.value: "🎵 Аудио",
            MediaType.VOICE.value: "🎤 Голосовые",
            MediaType.STICKER.value: "😀 Стикеры",
            MediaType.ANIMATION.value: "🎬 GIF"
        }
        
        for stat in media_stats:
            media_type = stat['media_type']
            count = stat['count']
            type_name = media_type_names.get(media_type, media_type)
            stats_text += f"  {type_name}: {count}\n"
        
        stats_text += f"\n🕒 Время: {datetime.now().strftime('%H:%M:%S')}"
        
        await query.edit_message_text(
            text=stats_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
        )
    
    elif query.data == "admin_users":
        users = db.get_all_users()
        
        if not users:
            await query.edit_message_text(
                text="👥 Пользователей пока нет",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
            )
            return
        
        users_text = f"👥 Всего пользователей: {len(users)}\n\n"
        
        for user_data in users[:10]:
            reg_date = datetime.fromisoformat(user_data['registration_date']).strftime('%d.%m.%Y')
            emoji = get_random_emoji()
            users_text += (
                f"{emoji} {user_data['full_name']}\n"
                f"   🆔 ID: {user_data['user_id']}\n"
                f"   📛 Юзернейм: @{user_data['username'] or 'нет'}\n"
                f"   🔗 Реф-код: {user_data['ref_code']}\n"
                f"   📅 Регистрация: {reg_date}\n"
                f"   📤 Отправлено: {user_data['sent_messages']}\n"
                f"   📥 Получено: {user_data['received_messages']}\n\n"
            )
        
        if len(users) > 10:
            users_text += f"\n... и еще {len(users) - 10} пользователей"
        
        await query.edit_message_text(
            text=users_text[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
        )
    
    elif query.data == "admin_messages":
        messages = db.get_all_messages(limit=10)
        
        if not messages:
            await query.edit_message_text(
                text="📨 Сообщений пока нет",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
            )
            return
        
        messages_text = f"📨 Последние сообщения:\n\n"
        
        for msg in messages:
            timestamp = datetime.fromisoformat(msg['timestamp']).strftime('%d.%m %H:%M')
            media_type = msg['media_type'] or MediaType.TEXT.value
            
            media_icons = {
                MediaType.TEXT.value: "📝",
                MediaType.PHOTO.value: "🖼",
                MediaType.VIDEO.value: "🎥",
                MediaType.DOCUMENT.value: "📎",
                MediaType.AUDIO.value: "🎵",
                MediaType.VOICE.value: "🎤",
                MediaType.STICKER.value: "😀",
                MediaType.ANIMATION.value: "🎬"
            }
            
            icon = media_icons.get(media_type, "📦")
            reply_icon = "↩️ " if msg['is_reply'] else ""
            emoji = get_random_emoji()
            
            from_name = msg['from_name'] or f"ID: {msg['from_user_id']}"
            to_name = msg['to_name'] or f"ID: {msg['to_user_id']}"
            
            text_preview = msg['text'] or ""
            if text_preview and len(text_preview) > 30:
                text_preview = text_preview[:30] + "..."
            
            messages_text += (
                f"{emoji} {reply_icon}{icon} Сообщение #{msg['message_id']}\n"
                f"   👤 От: {from_name}\n"
                f"   🎯 Кому: {to_name}\n"
                f"   📝 Текст: {text_preview or 'нет'}\n"
                f"   🕒 {timestamp}\n\n"
            )
        
        await query.edit_message_text(
            text=messages_text[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]])
        )
    
    elif query.data == "back_to_admin":
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Все пользователи", callback_data="admin_users")],
            [InlineKeyboardButton("📨 Все сообщения", callback_data="admin_messages")],
            [InlineKeyboardButton("🔗 Моя реф-ссылка", callback_data="my_ref")],
            [InlineKeyboardButton("🚫 Все блокировки", callback_data="admin_blocks")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="👑 Админ-панель\n\nВыберите действие:",
            reply_markup=reply_markup
        )

# Админ-команды
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда только для администратора!")
        return
    
    stats = db.get_total_stats()
    
    stats_text = (
        f"{get_random_emoji()} Статистика бота:\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📨 Всего сообщений: {stats['total_messages']}\n"
        f"💬 Ответов: {stats['total_replies']}\n"
        f"🚫 Блокировок: {stats['total_blocks']}\n"
        f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(stats_text)

async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда только для администратора!")
        return
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages')
            cursor.execute('DELETE FROM blocks')
            cursor.execute('UPDATE users SET sent_messages = 0, received_messages = 0')
            conn.commit()
        
        await update.message.reply_text(f"{get_random_emoji()} База данных очищена!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при очистке базы: {str(e)}")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда только для администратора!")
        return
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(messages)")
            columns = cursor.fetchall()
            
            info_text = f"{get_random_emoji()} Структура таблицы messages:\n\n"
            for col in columns:
                info_text += f"{col[1]} ({col[2]})\n"
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            msg_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM blocks")
            blocks_count = cursor.fetchone()[0]
            
            info_text += f"\n📈 Статистика:\n"
            info_text += f"Сообщений: {msg_count}\n"
            info_text += f"Пользователей: {user_count}\n"
            info_text += f"Блокировок: {blocks_count}"
            
            await update.message.reply_text(info_text)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка проверки: {str(e)}")

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_id(user.id)
    
    if user_data:
        ref_code = user_data['ref_code']
        bot_username = (await context.bot.get_me()).username
        ref_link = generate_ref_link(ref_code, bot_username)
        
        keyboard = [[InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks")]]
        
        await update.message.reply_text(
            f"{get_random_emoji()} Ваша реф-ссылка:\n\n"
            f"{ref_link}\n\n"
            f"Отправьте эту ссылку друзьям, чтобы они могли писать вам анонимно!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("❌ Ошибка: пользователь не найден. Попробуйте /start")

def main():
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        print("❌ ОШИБКА: Вы не указали токен бота!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("clean", clean_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("ref", ref_command))
    application.add_handler(CommandHandler("blocks", blocks_command))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Фильтры для сообщений
    media_filter = (filters.TEXT | filters.PHOTO | filters.VIDEO | 
                   filters.Document.ALL | filters.AUDIO | filters.VOICE | 
                   filters.Sticker.ALL | filters.ANIMATION)
    
    # Обработчик всех типов медиа сообщений
    application.add_handler(MessageHandler(media_filter, handle_message))
    
    print("=" * 50)
    print("🤖 АНОНИМНЫЙ БОТ С ЭМОДЗИ И БЛОКИРОВКАМИ")
    print("=" * 50)
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"🎉 Рандомные эмодзи: {len(RANDOM_EMOJIS)} вариантов")
    print(f"🚫 Система блокировок: включена")
    print(f"🔒 Конфиденциальность: пользователи не видят информацию о заблокированных")
    print("📁 База данных: anonymous_bot.db")
    print("⏳ Запуск бота...")
    print("=" * 50)
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
