import logging
import sqlite3
import sys
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, PreCheckoutQueryHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest


BOT_TOKEN = "8310201354:AAH_MIyv9q_YRpPbCoAbkS39oCb8UGRyzNg"
CHANNEL_ID = "@anonalmet" 
ADMIN_IDS = [6970104969]  

# Настройки спама (разные для обычных и премиум пользователей)
DEFAULT_SPAM_COOLDOWN = 60  # 60 секунд для обычных пользователей
PREMIUM_SPAM_COOLDOWN = 3   # 3 секунды для премиум пользователей (почти нет спам-режима)

PREMIUM_PRICE = 25  # 25 Stars за 1 месяц премиума


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

user_cooldowns: Dict[int, datetime] = {}
pending_replies: Dict[int, tuple] = {}
pending_edits: Dict[int, tuple] = {}

# Список популярных премиум-эмодзи Telegram (расширенный)
PREMIUM_EMOJIS = [
    "🔥", "✨", "🌟", "💎", "🚀", "🎯", "🏆", "🎨", "🦄", "🌈",
    "⭐", "💫", "☄️", "🎭", "🎪", "🎮", "🎲", "🎵", "🎶", "🎸",
    "🏅", "🎖️", "🥇", "🥈", "🥉", "⚡", "💥", "🌠", "🌌", "🌙",
    "☀️", "🌞", "🪐", "🌊", "🌸", "🌺", "🌹", "🍀", "🎄", "🎁",
    "🎀", "🎊", "🎉", "🕹️", "🎬", "🎥", "📽️", "🎞️", "🎤", "🎧",
    "🐲", "🦁", "🐯", "🦊", "🐺", "🦋", "🐢", "🦉", "🦚", "🦜",
    "⚓", "⛵", "🚁", "🚂", "🚲", "🛵", "🏍️", "🚗", "🚕", "🚙",
    "🏠", "🏰", "🎡", "🎢", "🚧", "🛤️", "🗼", "🗽", "⛲", "🏟️",
    "🛒", "🛍️", "🎈", "🎏", "🎀", "🧸", "🪀", "🪁", "🧩", "♟️",
    "🎼", "🎹", "🥁", "🎷", "🎺", "🪕", "🎸", "🎤", "🎧", "📻"
]

def escape_markdown(text: str) -> str:
    """Экранировать специальные символы Markdown"""
    if not text:
        return text
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

class Database:
    def __init__(self):
        self.db_file = 'anonymous_bot.db'
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        """Создание таблиц с правильной структурой"""
        cursor = self.conn.cursor()
        
        # Таблица users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_banned INTEGER DEFAULT 0,
                registration_date TEXT,
                is_premium INTEGER DEFAULT 0,
                custom_emoji TEXT DEFAULT "📨",
                premium_until TEXT DEFAULT NULL,
                emoji_type TEXT DEFAULT "standard",
                payment_history TEXT DEFAULT NULL,
                emoji_unique INTEGER DEFAULT 1,
                emoji_lock INTEGER DEFAULT 0,
                nickname TEXT DEFAULT NULL,
                message_count INTEGER DEFAULT 0,
                edit_count INTEGER DEFAULT 0,
                delete_count INTEGER DEFAULT 0,
                last_activity TEXT DEFAULT NULL
            )
        ''')
        
        # Таблица emoji_reservations (для уникальных эмодзи)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emoji_reservations (
                emoji TEXT PRIMARY KEY,
                user_id INTEGER UNIQUE,
                reserved_at TEXT,
                is_premium INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Таблица messages с ВСЕМИ нужными колонками
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_message_id INTEGER NOT NULL,
                text TEXT,
                timestamp TEXT NOT NULL,
                reply_to INTEGER DEFAULT NULL,
                is_reply INTEGER DEFAULT 0,
                emoji_used TEXT,
                is_edited INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                edit_count INTEGER DEFAULT 0,
                last_edit_time TEXT
            )
        ''')
        
        # Таблица replies
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS replies (
                reply_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_message_id INTEGER,
                reply_message_id INTEGER,
                user_id INTEGER,
                timestamp TEXT
            )
        ''')
        
        # Таблица payments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT DEFAULT "XTR",
                status TEXT DEFAULT "pending",
                timestamp TEXT NOT NULL,
                product TEXT,
                payload TEXT
            )
        ''')
        
        # Таблица used_emojis (история использованных эмодзи)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS used_emojis (
                emoji TEXT PRIMARY KEY,
                user_id INTEGER,
                last_used TEXT,
                use_count INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица message_edits (история редактирований)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_edits (
                edit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                old_text TEXT,
                new_text TEXT,
                user_id INTEGER,
                edit_time TEXT,
                FOREIGN KEY (message_id) REFERENCES messages(channel_message_id)
            )
        ''')
        
        self.conn.commit()
        logger.info("База данных создана/проверена")
    
    def reset_database(self):
        """Пересоздать базу данных (для отладки)"""
        cursor = self.conn.cursor()
        
        # Удаляем все таблицы
        tables = ['users', 'emoji_reservations', 'messages', 'replies', 'payments', 'used_emojis', 'message_edits']
        for table in tables:
            try:
                cursor.execute(f'DROP TABLE IF EXISTS {table}')
            except:
                pass
        
        self.conn.commit()
        
        # Создаем таблицы заново
        self.create_tables()
        logger.info("База данных пересоздана")
    
    def register_user(self, user_id: int, username: str, first_name: str, last_name: str):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if cursor.fetchone():
            cursor.execute('''
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, last_activity = ?
                WHERE user_id = ?
            ''', (username, first_name, last_name, datetime.now().isoformat(), user_id))
        else:
            cursor.execute('''
                INSERT INTO users 
                (user_id, username, first_name, last_name, registration_date, custom_emoji, emoji_type, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, datetime.now().isoformat(), "📨", "standard", datetime.now().isoformat()))
        self.conn.commit()
    
    def get_user_info(self, user_id: int) -> Optional[tuple]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result
    
    def is_user_premium(self, user_id: int) -> bool:
        user = self.get_user_info(user_id)
        if not user:
            return False
        
        if user[8]:  # premium_until
            try:
                premium_until = datetime.fromisoformat(user[8])
                if datetime.now() > premium_until:
                    cursor = self.conn.cursor()
                    cursor.execute('''
                        UPDATE users 
                        SET is_premium = 0, premium_until = NULL 
                        WHERE user_id = ?
                    ''', (user_id,))
                    self.conn.commit()
                    
                    # Освобождаем зарезервированный эмодзи при истечении премиума
                    cursor.execute('DELETE FROM emoji_reservations WHERE user_id = ?', (user_id,))
                    self.conn.commit()
                    return False
            except:
                pass
        
        return user[6] == 1  # is_premium поле
    
    def get_user_emoji(self, user_id: int) -> str:
        user = self.get_user_info(user_id)
        if not user:
            return "📨"
        
        if user[7]:  # custom_emoji поле
            return user[7]
        
        return "📨"
    
    def update_user_activity(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', 
                      (datetime.now().isoformat(), user_id))
        self.conn.commit()
    
    def log_message(self, user_id: int, channel_message_id: int, text: str, reply_to: int = None, emoji_used: str = None):
        cursor = self.conn.cursor()
        is_reply = 1 if reply_to is not None else 0
        timestamp = datetime.now().isoformat()
        
        try:
            cursor.execute('''
                INSERT INTO messages 
                (user_id, channel_message_id, text, timestamp, reply_to, is_reply, emoji_used, is_edited, is_deleted, edit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            ''', (user_id, channel_message_id, text or '', timestamp, reply_to, is_reply, emoji_used))
            
            # Увеличиваем счетчик сообщений и обновляем активность
            cursor.execute('UPDATE users SET message_count = message_count + 1, last_activity = ? WHERE user_id = ?', 
                          (timestamp, user_id))
            
            self.conn.commit()
            
            if reply_to is not None:
                cursor.execute('''
                    INSERT INTO replies (original_message_id, reply_message_id, user_id, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (reply_to, channel_message_id, user_id, timestamp))
                self.conn.commit()
                
        except Exception as e:
            logger.error(f"Error logging message: {e}")
            self.conn.rollback()
            raise
    
    def get_message_owner(self, message_id: int) -> Optional[int]:
        """Получить ID владельца сообщения"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM messages WHERE channel_message_id = ?', (message_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def is_message_owner(self, user_id: int, message_id: int) -> bool:
        """Проверить, является ли пользователь владельцем сообщения"""
        owner_id = self.get_message_owner(message_id)
        return owner_id == user_id
    
    def edit_message(self, user_id: int, message_id: int, new_text: str) -> bool:
        """Редактировать сообщение в базе данных"""
        cursor = self.conn.cursor()
        
        try:
            # Проверяем, является ли пользователь владельцем сообщения
            if not self.is_message_owner(user_id, message_id):
                return False
            
            # Получаем текущий текст сообщения
            cursor.execute('SELECT text FROM messages WHERE channel_message_id = ?', (message_id,))
            result = cursor.fetchone()
            
            if not result:
                return False
            
            old_text = result[0]
            
            # Если текст не изменился, просто возвращаем True
            if old_text == new_text:
                logger.info(f"Текст сообщения {message_id} не изменился, пропускаем редактирование")
                return True
            
            # Сохраняем историю редактирования
            cursor.execute('''
                INSERT INTO message_edits (message_id, old_text, new_text, user_id, edit_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (message_id, old_text, new_text, user_id, datetime.now().isoformat()))
            
            # Обновляем сообщение
            cursor.execute('''
                UPDATE messages 
                SET text = ?, is_edited = 1, edit_count = edit_count + 1, last_edit_time = ?
                WHERE channel_message_id = ?
            ''', (new_text, datetime.now().isoformat(), message_id))
            
            # Увеличиваем счетчик редактирований пользователя
            cursor.execute('UPDATE users SET edit_count = edit_count + 1, last_activity = ? WHERE user_id = ?', 
                          (datetime.now().isoformat(), user_id))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            self.conn.rollback()
            return False
    
    def delete_message(self, user_id: int, message_id: int) -> bool:
        """Пометить сообщение как удаленное"""
        cursor = self.conn.cursor()
        
        try:
            # Проверяем, является ли пользователь владельцем сообщения
            if not self.is_message_owner(user_id, message_id):
                return False
            
            # Помечаем сообщение как удаленное
            cursor.execute('''
                UPDATE messages 
                SET is_deleted = 1 
                WHERE channel_message_id = ?
            ''', (message_id,))
            
            # Увеличиваем счетчик удалений пользователя
            cursor.execute('UPDATE users SET delete_count = delete_count + 1, last_activity = ? WHERE user_id = ?', 
                          (datetime.now().isoformat(), user_id))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            self.conn.rollback()
            return False
    
    def get_message_info(self, message_id: int):
        """Получить информацию о сообщении"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM messages WHERE channel_message_id = ?', (message_id,))
        result = cursor.fetchone()
        return result
    
    def set_user_premium(self, user_id: int, months: int = 1, emoji_type: str = "premium"):
        cursor = self.conn.cursor()
        premium_until = datetime.now() + timedelta(days=30 * months)
        cursor.execute('''
            UPDATE users 
            SET is_premium = 1, premium_until = ?, emoji_type = ?, emoji_unique = 1
            WHERE user_id = ?
        ''', (premium_until.isoformat(), emoji_type, user_id))
        self.conn.commit()
    
    def add_premium_days(self, user_id: int, days: int):
        cursor = self.conn.cursor()
        user = self.get_user_info(user_id)
        
        if user and user[8]:  # premium_until
            try:
                current_until = datetime.fromisoformat(user[8])
                new_until = current_until + timedelta(days=days)
            except:
                new_until = datetime.now() + timedelta(days=days)
        else:
            new_until = datetime.now() + timedelta(days=days)
        
        cursor.execute('''
            UPDATE users 
            SET is_premium = 1, premium_until = ?, emoji_type = "premium"
            WHERE user_id = ?
        ''', (new_until.isoformat(), user_id))
        self.conn.commit()
    
    def get_all_users(self, limit: int = 100):
        """Получить всех пользователей"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, last_name, is_premium, registration_date, 
                   message_count, edit_count, delete_count, last_activity
            FROM users 
            ORDER BY registration_date DESC 
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    
    def get_user_count(self):
        """Получить количество пользователей"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        return cursor.fetchone()[0]
    
    def get_premium_users_count(self):
        """Получить количество премиум пользователей"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_premium = 1')
        return cursor.fetchone()[0]
    
    def get_message_count(self):
        """Получить количество сообщений"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages')
        return cursor.fetchone()[0]
    
    def ban_user(self, user_id: int):
        """Забанить пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def unban_user(self, user_id: int):
        """Разбанить пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def is_user_banned(self, user_id: int) -> bool:
        """Проверить, забанен ли пользователь"""
        user = self.get_user_info(user_id)
        if not user:
            return False
        return user[4] == 1  # is_banned поле
    
    def get_reserved_emoji_for_user(self, user_id: int) -> Optional[str]:
        """Получить зарезервированный эмодзи пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT emoji FROM emoji_reservations WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def get_reserved_emoji_owner(self, emoji: str) -> Optional[int]:
        """Получить владельца зарезервированного эмодзи"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM emoji_reservations WHERE emoji = ?', (emoji,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def set_user_emoji_with_reservation(self, user_id: int, emoji: str, emoji_type: str = None) -> bool:
        """Установить эмодзи с закреплением (только для премиум)"""
        cursor = self.conn.cursor()
        
        if emoji_type is None:
            emoji_type = "premium" if emoji in PREMIUM_EMOJIS else "standard"
        
        # Проверяем, является ли пользователь премиум
        if not self.is_user_premium(user_id):
            # Для не-премиум просто устанавливаем эмодзи
            cursor.execute('UPDATE users SET custom_emoji = ?, emoji_type = ? WHERE user_id = ?', 
                          (emoji, emoji_type, user_id))
            self.conn.commit()
            return True
        
        # Для премиум пользователей - закрепляем эмодзи
        # Сначала освобождаем предыдущий эмодзи пользователя
        cursor.execute('DELETE FROM emoji_reservations WHERE user_id = ?', (user_id,))
        
        # Проверяем, занят ли новый эмодзи
        cursor.execute('SELECT user_id FROM emoji_reservations WHERE emoji = ?', (emoji,))
        if cursor.fetchone():
            return False
        
        # Резервируем новый эмодзи
        cursor.execute('''
            INSERT OR REPLACE INTO emoji_reservations (emoji, user_id, reserved_at, is_premium)
            VALUES (?, ?, ?, 1)
        ''', (emoji, user_id, datetime.now().isoformat()))
        
        # Устанавливаем эмодзи в таблицу users
        cursor.execute('UPDATE users SET custom_emoji = ?, emoji_type = ? WHERE user_id = ?', 
                      (emoji, emoji_type, user_id))
        
        self.conn.commit()
        return True
    
    def get_available_emojis(self) -> List[str]:
        """Получить список доступных (не занятых) премиум эмодзи"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT emoji FROM emoji_reservations')
        reserved_emojis = {row[0] for row in cursor.fetchall()}
        
        available_emojis = [emoji for emoji in PREMIUM_EMOJIS if emoji not in reserved_emojis]
        return available_emojis
    
    def get_all_reserved_emojis(self) -> List[tuple]:
        """Получить все зарезервированные эмодзи"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT e.emoji, u.user_id, u.username, u.first_name, e.reserved_at
            FROM emoji_reservations e
            JOIN users u ON e.user_id = u.user_id
            ORDER BY e.reserved_at DESC
        ''')
        return cursor.fetchall()
    
    def free_emoji(self, emoji: str) -> bool:
        """Освободить эмодзи (админ команда)"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM emoji_reservations WHERE emoji = ?', (emoji,))
        affected = cursor.rowcount
        self.conn.commit()
        return affected > 0

# Инициализируем базу данных
db = Database()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def check_spam_cooldown(user_id: int) -> Optional[str]:
    now = datetime.now()
    
    if user_id in user_cooldowns:
        last_time = user_cooldowns[user_id]
        
        # Определяем время ожидания в зависимости от статуса пользователя
        if db.is_user_premium(user_id):
            cooldown = PREMIUM_SPAM_COOLDOWN
        else:
            cooldown = DEFAULT_SPAM_COOLDOWN
        
        time_diff = (now - last_time).total_seconds()
        
        if time_diff < cooldown:
            wait_time = int(cooldown - time_diff)
            return f"⏳ Подождите {wait_time} секунд перед отправкой следующего сообщения."
    
    user_cooldowns[user_id] = now
    return None

def validate_emoji(emoji: str) -> bool:
    if not emoji or len(emoji.strip()) == 0:
        return False
    
    if len(emoji) > 4:
        return False
    
    return True

# ===================== АДМИН КОМАНДЫ =====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ меню"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к админ меню\\.")
        return
    
    # Получаем статистику
    total_users = db.get_user_count()
    premium_users = db.get_premium_users_count()
    total_messages = db.get_message_count()
    
    text = (
        f"👑 *Админ панель*\n\n"
        f"📊 *Статистика:*\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Премиум пользователей: {premium_users}\n"
        f"• Всего сообщений: {total_messages}\n\n"
        f"📋 *Доступные команды:*\n"
        f"`/stats` \\- подробная статистика\n"
        f"`/users` \\- список пользователей\n"
        f"`/ban \\[ID\\]` \\- забанить пользователя\n"
        f"`/unban \\[ID\\]` \\- разбанить пользователя\n"
        f"`/premium \\[ID\\] \\[дни\\]` \\- выдать премиум\n"
        f"`/emojiadmin` \\- управление эмодзи\n"
        f"`/broadcast` \\- рассылка сообщений\n"
        f"`/resetdb` \\- сбросить базу данных\n\n"
        f"🛠️ *Технические команды:*\n"
        f"`/checkuser \\[ID\\]` \\- информация о пользователе\n"
        f"`/checkmsg \\[ID\\]` \\- информация о сообщении\n"
        f"`/freeemoji \\[эмодзи\\]` \\- освободить эмодзи"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробная статистика"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    # Получаем статистику
    total_users = db.get_user_count()
    premium_users = db.get_premium_users_count()
    total_messages = db.get_message_count()
    
    # Получаем последних 5 пользователей
    recent_users = db.get_all_users(5)
    
    text = (
        f"📊 *Подробная статистика*\n\n"
        f"👥 *Пользователи:*\n"
        f"• Всего: {total_users}\n"
        f"• Премиум: {premium_users}\n"
        f"• Обычные: {total_users - premium_users}\n\n"
        f"💬 *Сообщения:*\n"
        f"• Всего: {total_messages}\n\n"
        f"🆕 *Последние пользователи:*\n"
    )
    
    for i, (user_id, username, first_name, last_name, is_premium, reg_date, msg_count, edit_count, delete_count, last_activity) in enumerate(recent_users, 1):
        name = f"@{username}" if username else f"{first_name or ''} {last_name or ''}".strip() or f"ID: {user_id}"
        premium_status = "✅" if is_premium else "❌"
        
        try:
            reg_date_obj = datetime.fromisoformat(reg_date)
            reg_date_str = reg_date_obj.strftime("%d\\.%m\\.%Y %H:%M")
        except:
            reg_date_str = "Неизвестно"
        
        text += f"{i}\\. {escape_markdown(name)} {premium_status} \\(сообщений: {msg_count}\\)\n"
    
    # Получаем зарезервированные эмодзи
    reserved_emojis = db.get_all_reserved_emojis()
    if reserved_emojis:
        text += f"\n🔒 *Занятые эмодзи:* {len(reserved_emojis)}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    limit = 20
    if context.args:
        try:
            limit = min(int(context.args[0]), 50)
        except:
            pass
    
    users = db.get_all_users(limit)
    
    text = f"👥 *Список пользователей \\(последние {len(users)}\\)*\n\n"
    
    for i, (user_id, username, first_name, last_name, is_premium, reg_date, msg_count, edit_count, delete_count, last_activity) in enumerate(users, 1):
        name = f"@{username}" if username else f"{first_name or ''} {last_name or ''}".strip() or f"ID: {user_id}"
        premium_status = "⭐" if is_premium else "👤"
        
        try:
            reg_date_obj = datetime.fromisoformat(reg_date)
            reg_date_str = reg_date_obj.strftime("%d\\.%m")
        except:
            reg_date_str = "??"
        
        text += f"{i}\\. {premium_status} {escape_markdown(name)} \\(ID: `{user_id}`\\)\n"
        text += f"   📅 {reg_date_str} | 💬 {msg_count} | ✏️ {edit_count} | 🗑️ {delete_count}\n"
    
    text += f"\nВсего пользователей: {db.get_user_count()}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Забанить пользователя"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/ban ID\\_пользователя`\n"
            "Пример: `/ban 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        user_id_to_ban = int(context.args[0])
        
        # Нельзя забанить самого себя или другого админа
        if user_id_to_ban == user.id:
            await update.message.reply_text("❌ Нельзя забанить самого себя\\.")
            return
        
        if user_id_to_ban in ADMIN_IDS:
            await update.message.reply_text("❌ Нельзя забанить другого администратора\\.")
            return
        
        user_info = db.get_user_info(user_id_to_ban)
        if not user_info:
            await update.message.reply_text("❌ Пользователь не найден\\.")
            return
        
        db.ban_user(user_id_to_ban)
        
        username = f"@{user_info[1]}" if user_info[1] else f"{user_info[2] or ''} {user_info[3] or ''}".strip() or f"ID: {user_id_to_ban}"
        
        await update.message.reply_text(
            f"✅ Пользователь {escape_markdown(username)} \\(ID: `{user_id_to_ban}`\\) забанен\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя\\.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбанить пользователя"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/unban ID\\_пользователя`\n"
            "Пример: `/unban 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        user_id_to_unban = int(context.args[0])
        
        user_info = db.get_user_info(user_id_to_unban)
        if not user_info:
            await update.message.reply_text("❌ Пользователь не найден\\.")
            return
        
        db.unban_user(user_id_to_unban)
        
        username = f"@{user_info[1]}" if user_info[1] else f"{user_info[2] or ''} {user_info[3] or ''}".strip() or f"ID: {user_id_to_unban}"
        
        await update.message.reply_text(
            f"✅ Пользователь {escape_markdown(username)} \\(ID: `{user_id_to_unban}`\\) разбанен\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя\\.")

async def premium_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдать премиум (админ команда)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: `/premiumadmin ID\\_пользователя количество\\_дней`\n"
            "Пример: `/premiumadmin 123456789 30`\n"
            "Пример: `/premiumadmin 123456789 0` \\- отобрать премиум",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        
        user_info = db.get_user_info(user_id)
        if not user_info:
            await update.message.reply_text("❌ Пользователь не найден\\.")
            return
        
        username = f"@{user_info[1]}" if user_info[1] else f"{user_info[2] or ''} {user_info[3] or ''}".strip() or f"ID: {user_id}"
        
        if days <= 0:
            # Отобрать премиум
            cursor = db.conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET is_premium = 0, premium_until = NULL 
                WHERE user_id = ?
            ''', (user_id,))
            cursor.execute('DELETE FROM emoji_reservations WHERE user_id = ?', (user_id,))
            db.conn.commit()
            
            await update.message.reply_text(
                f"✅ Премиум отобран у пользователя {escape_markdown(username)} \\(ID: `{user_id}`\\)\\!",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # Выдать премиум
            db.add_premium_days(user_id, days)
            
            await update.message.reply_text(
                f"✅ Пользователю {escape_markdown(username)} \\(ID: `{user_id}`\\) выдан премиум на {days} дней\\!",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат аргументов\\.")

async def emojiadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление эмодзи (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    # Получаем все зарезервированные эмодзи
    reserved_emojis = db.get_all_reserved_emojis()
    available_emojis = db.get_available_emojis()
    
    text = (
        f"🎨 *Управление эмодзи*\n\n"
        f"📊 *Статистика:*\n"
        f"• Всего премиум эмодзи: {len(PREMIUM_EMOJIS)}\n"
        f"• Занято эмодзи: {len(reserved_emojis)}\n"
        f"• Свободно эмодзи: {len(available_emojis)}\n\n"
        f"🔒 *Занятые эмодзи:*\n"
    )
    
    if reserved_emojis:
        for i, (emoji, user_id, username, first_name, reserved_at) in enumerate(reserved_emojis[:10], 1):
            name = f"@{username}" if username else f"{first_name or ''}" or f"ID: {user_id}"
            try:
                reserved_date = datetime.fromisoformat(reserved_at)
                date_str = reserved_date.strftime("%d\\.%m")
            except:
                date_str = "??"
            
            text += f"{i}\\. {emoji} \\- {escape_markdown(name)} \\(ID: `{user_id}`\\) \\[{date_str}\\]\n"
        
        if len(reserved_emojis) > 10:
            text += f"\\.\\.\\. и еще {len(reserved_emojis) - 10}\n"
    else:
        text += "Нет занятых эмодзи\\n"
    
    text += (
        f"\n🛠️ *Команды:*\n"
        f"`/freeemoji \\[эмодзи\\]` \\- освободить эмодзи\n"
        f"`/checkuser \\[ID\\]` \\- проверить пользователя\n"
        f"`/emojiadmin` \\- обновить список"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def freeemoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Освободить эмодзи (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/freeemoji \\[эмодзи\\]`\n"
            "Пример: `/freeemoji 🔥`\n\n"
            "Эта команда освобождает эмодзи\\, чтобы его могли использовать другие пользователи\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    emoji = context.args[0]
    
    success = db.free_emoji(emoji)
    
    if success:
        await update.message.reply_text(f"✅ Эмодзи {emoji} освобожден\\!")
    else:
        await update.message.reply_text(f"❌ Эмодзи {emoji} не был занят или произошла ошибка\\.")

async def checkuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить пользователя (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/checkuser \\[ID\\_пользователя\\]`\n"
            "Пример: `/checkuser 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        user_id = int(context.args[0])
        user_info = db.get_user_info(user_id)
        
        if not user_info:
            await update.message.reply_text("❌ Пользователь не найден\\.")
            return
        
        # Распаковываем информацию о пользователе
        (user_id_db, username, first_name, last_name, is_banned, 
         registration_date, is_premium, custom_emoji, premium_until, 
         emoji_type, payment_history, emoji_unique, emoji_lock, nickname,
         message_count, edit_count, delete_count, last_activity) = user_info
        
        # Форматируем даты
        try:
            reg_date = datetime.fromisoformat(registration_date)
            reg_date_str = reg_date.strftime("%d\\.%m\\.%Y %H:%M:%S")
        except:
            reg_date_str = "Неизвестно"
        
        try:
            if last_activity:
                activity_date = datetime.fromisoformat(last_activity)
                activity_str = activity_date.strftime("%d\\.%m\\.%Y %H:%M:%S")
            else:
                activity_str = "Неизвестно"
        except:
            activity_str = "Неизвестно"
        
        premium_status = "✅ Активен" if is_premium else "❌ Не активен"
        ban_status = "🚫 Забанен" if is_banned else "✅ Не забанен"
        
        if premium_until:
            try:
                until_date = datetime.fromisoformat(premium_until)
                days_left = (until_date - datetime.now()).days
                premium_until_str = until_date.strftime("%d\\.%m\\.%Y %H:%M")
                premium_info = f"{premium_status} \\(до {premium_until_str}\\, осталось {days_left} дней\\)"
            except:
                premium_info = premium_status
        else:
            premium_info = premium_status
        
        reserved_emoji = db.get_reserved_emoji_for_user(user_id)
        emoji_reservation = f"🔒 {reserved_emoji}" if reserved_emoji else "⚠️ Не зарезервирован"
        
        text = (
            f"👤 *Информация о пользователе*\n\n"
            f"*Основное:*\n"
            f"• ID: `{user_id}`\n"
            f"• Имя: {escape_markdown(first_name or 'Не указано')} {escape_markdown(last_name or '')}\n"
            f"• Username: {'@' + escape_markdown(username) if username else 'Не указан'}\n"
            f"• Статус: {ban_status}\n"
            f"• Премиум: {premium_info}\n\n"
            f"*Статистика:*\n"
            f"• Сообщений: {message_count}\n"
            f"• Редактирований: {edit_count}\n"
            f"• Удалений: {delete_count}\n"
            f"• Эмодзи: {custom_emoji}\n"
            f"• Резервация: {emoji_reservation}\n\n"
            f"*Даты:*\n"
            f"• Регистрация: {reg_date_str}\n"
            f"• Последняя активность: {activity_str}"
        )
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID пользователя\\.")

async def checkmsg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить сообщение (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/checkmsg \\[ID\\_сообщения\\]`\n"
            "Пример: `/checkmsg 123`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        message_id = int(context.args[0])
        message_info = db.get_message_info(message_id)
        
        if not message_info:
            await update.message.reply_text("❌ Сообщение не найдено\\.")
            return
        
        # Распаковываем информацию о сообщении
        (db_id, user_id, channel_msg_id, text, timestamp, reply_to, 
         is_reply, emoji_used, is_edited, is_deleted, edit_count, last_edit_time) = message_info
        
        # Получаем информацию об отправителе
        sender_info = db.get_user_info(user_id)
        sender_name = "Неизвестный"
        if sender_info:
            username = sender_info[1]
            first_name = sender_info[2]
            sender_name = f"@{username}" if username else f"{first_name or ''}" or f"ID: {user_id}"
        
        # Форматируем даты
        try:
            msg_date = datetime.fromisoformat(timestamp)
            date_str = msg_date.strftime("%d\\.%m\\.%Y %H:%M:%S")
        except:
            date_str = "Неизвестно"
        
        status = []
        if is_deleted:
            status.append("🗑️ Удалено")
        if is_edited:
            status.append(f"✏️ Редактировано \\(раз: {edit_count}\\)")
        if is_reply:
            status.append(f"↩️ Ответ на сообщение #{reply_to}")
        
        status_text = "\\, ".join(status) if status else "✅ Обычное сообщение"
        
        text_preview = escape_markdown(text[:100]) if text else "Нет текста"
        if text and len(text) > 100:
            text_preview += "\\.\\.\\."
        
        message_text = (
            f"💬 *Информация о сообщении*\n\n"
            f"*Основное:*\n"
            f"• ID в базе: `{db_id}`\n"
            f"• ID в канале: `{channel_msg_id}`\n"
            f"• Отправитель: {escape_markdown(sender_name)} \\(ID: `{user_id}`\\)\n"
            f"• Дата: {date_str}\n"
            f"• Статус: {status_text}\n"
            f"• Эмодзи: {emoji_used or 'Не указан'}\n\n"
            f"*Текст сообщения:*\n"
            f"```\n{text_preview}\n```"
        )
        
        await update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID сообщения\\.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассылка сообщений (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Использование: `/broadcast \\[текст\\_сообщения\\]`\n"
            "Пример: `/broadcast Важное объявление для всех пользователей\\!`\n\n"
            "⚠️ *Внимание:* Эта команда отправляет сообщение всем пользователям бота\\!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Получаем всех пользователей
    users = db.get_all_users(1000)  # Ограничим 1000 пользователей
    
    if not users:
        await update.message.reply_text("❌ Нет пользователей для рассылки\\.")
        return
    
    message_text = " ".join(context.args)
    broadcast_text = (
        f"📢 *ОБЪЯВЛЕНИЕ ОТ АДМИНИСТРАЦИИ*\n\n"
        f"{escape_markdown(message_text)}\n\n"
        f"\\-\\-\\-\n"
        f"*Anon Bot* \\| @anonalmet"
    )
    
    sent_count = 0
    failed_count = 0
    
    await update.message.reply_text(f"🔄 Начинаю рассылку для {len(users)} пользователей\\.\\.\\.")
    
    for user_data in users:
        user_id = user_data[0]
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=broadcast_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            sent_count += 1
            await asyncio.sleep(0.1)  # Небольшая задержка чтобы не превысить лимиты API
            
        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user_id}: {e}")
            failed_count += 1
            continue
    
    await update.message.reply_text(
        f"✅ Рассылка завершена\\!\n\n"
        f"• Отправлено: {sent_count}\n"
        f"• Не удалось: {failed_count}\n"
        f"• Всего: {len(users)}",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def resetdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить базу данных (админ)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде\\.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data='resetdb_confirm'),
            InlineKeyboardButton("❌ Отмена", callback_data='resetdb_cancel')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ *ВНИМАНИЕ\\!*\n\n"
        "Вы собираетесь полностью сбросить базу данных\\.\n"
        "Это действие:\n"
        "• Удалит ВСЕХ пользователей\n"
        "• Удалит ВСЕ сообщения\n"
        "• Удалит ВСЕ платежи\n"
        "• Удалит ВСЕ резервации эмодзи\n\n"
        "❗ *Это действие необратимо\\!*\n"
        "Вы уверены, что хотите продолжить\\?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

# ===================== СТАРТ КОМАНДА =====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Регистрируем пользователя
    db.register_user(
        user.id, 
        user.username if user.username else None, 
        user.first_name if user.first_name else None, 
        user.last_name if user.last_name else None
    )
    
    # Простое приветствие с эмодзи (все специальные символы экранированы)
    welcome_text = (
        "👋 *Анонимный бот*\n\n"
        "📢 Канал: @anonalmet\n\n"
        "Просто отправьте сообщение\\, фото или видео \\- оно будет в канале\\.\n"
        "✉️ Для ответа на сообщение перешлите его из канала\n\n"
        "Все сообщения отправляются анонимно\\! 👤"
    )
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN_V2)
    
    # Если пользователь админ, показываем админ меню
    if is_admin(user.id):
        keyboard = [
            [InlineKeyboardButton("👑 Админ панель", callback_data='admin_panel')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🛠️ *Доступны админ команды\\!*\n"
            "Используйте /admin для админ меню\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )

# ===================== РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ СООБЩЕНИЙ (ИСПРАВЛЕННЫЕ) =====================

async def edit_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактировать сообщение"""
    user = update.effective_user
    
    # Проверяем права пользователя
    if not db.is_user_premium(user.id) and not is_admin(user.id):
        await update.message.reply_text(
            "❌ Эта функция доступна только для премиум пользователей\\.\n"
            "Используйте /premium для получения премиума\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "✏️ *Редактирование сообщения*\n\n"
            "*Использование:*\n"
            "`/edit ID\\_сообщения` \\- начать редактирование сообщения\n\n"
            "*Для редактирования:*\n"
            "1\\. Найдите ID сообщения \\(отображается при отправке\\)\n"
            "2\\. Используйте /edit ID\n"
            "3\\. Отправьте новый текст\n\n"
            "*Пример:* `/edit 123`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        message_id = int(context.args[0])
        
        # Проверяем, существует ли сообщение
        message_info = db.get_message_info(message_id)
        if not message_info:
            await update.message.reply_text("❌ Сообщение не найдено\\.")
            return
        
        # Проверяем, является ли пользователь владельцем сообщения
        if not db.is_message_owner(user.id, message_id) and not is_admin(user.id):
            await update.message.reply_text("❌ Вы не являетесь владельцем этого сообщения\\.\n"
                                           "Можно редактировать только свои сообщения\\.")
            return
        
        # Проверяем, не удалено ли сообщение
        if len(message_info) > 9 and message_info[9] == 1:  # is_deleted поле
            await update.message.reply_text("❌ Сообщение было удалено\\.")
            return
        
        # Сохраняем в pending_edits
        pending_edits[user.id] = (message_id, message_info[3])  # message_id, old_text
        
        old_text_escaped = escape_markdown(message_info[3] or "")
        
        await update.message.reply_text(
            f"✏️ *Редактирование сообщения \\#{message_id}*\n\n"
            f"*Текущий текст:*\n"
            f"```\n{old_text_escaped}\n```\n\n"
            f"*Теперь отправьте новый текст:*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID сообщения\\.")

async def delete_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить сообщение"""
    user = update.effective_user
    
    # Проверяем права пользователя
    if not db.is_user_premium(user.id) and not is_admin(user.id):
        await update.message.reply_text(
            "❌ Эта функция доступна только для премиум пользователей\\.\n"
            "Используйте /premium для получения премиума\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "🗑️ *Удаление сообщения*\n\n"
            "*Использование:*\n"
            "`/delete ID\\_сообщения` \\- удалить сообщение\n\n"
            "*Для удаления:*\n"
            "1\\. Найдите ID сообщения \\(отображается при отправке\\)\n"
            "2\\. Используйте /delete ID\n"
            "3\\. Подтвердите удаление\n\n"
            "*Пример:* `/delete 123`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    try:
        message_id = int(context.args[0])
        
        # Проверяем, существует ли сообщение
        message_info = db.get_message_info(message_id)
        if not message_info:
            await update.message.reply_text("❌ Сообщение не найдено\\.")
            return
        
        # Проверяем, является ли пользователь владельцем сообщения
        if not db.is_message_owner(user.id, message_id) and not is_admin(user.id):
            await update.message.reply_text("❌ Вы не являетесь владельцем этого сообщения\\.\n"
                                           "Можно удалять только свои сообщения\\.")
            return
        
        # Проверяем, не удалено ли уже сообщение
        if len(message_info) > 9 and message_info[9] == 1:  # is_deleted поле
            await update.message.reply_text("❌ Сообщение уже удалено\\.")
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f'delete_confirm_{message_id}'),
                InlineKeyboardButton("❌ Отмена", callback_data=f'delete_cancel_{message_id}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = message_info[3] or ""
        message_preview = escape_markdown(message_text[:200])
        
        await update.message.reply_text(
            f"🗑️ *Подтверждение удаления*\n\n"
            f"Вы действительно хотите удалить сообщение \\#{message_id}\\?\n\n"
            f"*Текст сообщения:*\n"
            f"```\n{message_preview}{'\\.\\.\\.' if len(message_text) > 200 else ''}\n```\n\n"
            f"❗ *Внимание:* Это действие нельзя отменить\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID сообщения\\.")

# ===================== ОБРАБОТКА РЕДАКТИРОВАНИЯ ТЕКСТА (ИСПРАВЛЕННАЯ) =====================

async def process_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Обработка текста для редактирования"""
    if user_id not in pending_edits:
        await update.message.reply_text("❌ Сессия редактирования истекла\\. Пожалуйста, начните заново\\.")
        return
    
    message_id, old_text = pending_edits[user_id]
    new_text = update.message.text or update.message.caption or ""
    
    if not new_text.strip():
        await update.message.reply_text("❌ Текст не может быть пустым\\.")
        return
    
    # Если текст не изменился, просто сообщаем об этом
    if old_text == new_text:
        await update.message.reply_text(
            "⚠️ *Текст не изменился*\n\n"
            "Новый текст совпадает со старым\\, редактирование не требуется\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        del pending_edits[user_id]
        return
    
    try:
        # Проверяем права еще раз
        message_info = db.get_message_info(message_id)
        if not message_info:
            await update.message.reply_text("❌ Сообщение не найдено\\.")
            del pending_edits[user_id]
            return
        
        # Проверяем, является ли пользователь владельцем сообщения
        if not db.is_message_owner(user_id, message_id) and not is_admin(user_id):
            await update.message.reply_text("❌ Вы не являетесь владельцем этого сообщения\\.\n"
                                           "Можно редактировать только свои сообщения\\.")
            del pending_edits[user_id]
            return
        
        # Обновляем в базе данных
        success = db.edit_message(user_id, message_id, new_text)
        
        if not success:
            await update.message.reply_text("❌ Не удалось отредактировать сообщение\\.")
            del pending_edits[user_id]
            return
        
        # Получаем эмодзи пользователя
        user_emoji = db.get_user_emoji(user_id)
        
        # Форматируем новое сообщение
        message_prefix = f"{user_emoji}: "
        formatted_message = f"{message_prefix}{new_text}"
        
        # Редактируем сообщение в канале
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                text=formatted_message,
                parse_mode=ParseMode.MARKDOWN if any(mark in new_text for mark in ['*', '_', '`']) else None
            )
            
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info(f"Сообщение {message_id} не изменилось, пропускаем")
            else:
                logger.error(f"Ошибка редактирования в канале: {e}")
        except Exception as e:
            logger.error(f"Ошибка редактирования в канале: {e}")
            # Сообщение все равно считается отредактированным в БД
        
        # Удаляем из pending_edits
        del pending_edits[user_id]
        
        await update.message.reply_text(
            f"✅ *Сообщение отредактировано\\!*\n\n"
            f"Сообщение \\#{message_id} успешно обновлено\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка редактирования: {error_msg}")
        await update.message.reply_text(f"❌ Ошибка при редактировании: {error_msg}")
        if user_id in pending_edits:
            del pending_edits[user_id]

# ===================== ОБРАБОТЧИК КНОПОК (ИСПРАВЛЕННЫЙ) =====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Всегда отвечаем на callback_query, даже если возникла ошибка
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback_query: {e}")
    
    user = query.from_user
    data = query.data
    
    # Обработка админ панели
    if data == 'admin_panel':
        if not is_admin(user.id):
            await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
            [InlineKeyboardButton("🎨 Управление эмодзи", callback_data='admin_emoji')],
            [InlineKeyboardButton("🛠️ Технические команды", callback_data='admin_tech')],
            [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message_text(
            query,
            "👑 *Админ панель*\n\n"
            "Выберите раздел для управления ботом:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        return
    
    elif data == 'admin_stats':
        await admin_stats_callback(update, context)
        return
    
    elif data == 'admin_users':
        await admin_users_callback(update, context)
        return
    
    elif data == 'admin_emoji':
        await admin_emoji_callback(update, context)
        return
    
    elif data == 'admin_tech':
        await admin_tech_callback(update, context)
        return
    
    elif data == 'admin_broadcast':
        await admin_broadcast_callback(update, context)
        return
    
    # Обработка сброса базы данных
    elif data == 'resetdb_confirm':
        await resetdb_confirm_callback(update, context)
        return
    
    elif data == 'resetdb_cancel':
        await resetdb_cancel_callback(update, context)
        return
    
    # Обработка удаления сообщений
    elif data.startswith('delete_confirm_'):
        await delete_confirm_callback(update, context)
        return
    
    elif data.startswith('delete_cancel_'):
        await delete_cancel_callback(update, context)
        return
    
    # Обработка редактирования/удаления через кнопки
    elif data == "edit_select":
        await edit_select_callback(update, context)
        return
    
    elif data == "delete_select":
        await delete_select_callback(update, context)
        return
    
    # Обработка покупки премиума через Stars
    elif data == "buy_premium_stars":
        await buy_premium_stars_callback(update, context)
        return
    
    # Обработка тестового премиума (для отладки)
    elif data == "test_premium":
        await test_premium_callback(update, context)
        return
    
    # Обработка других кнопок
    else:
        await safe_edit_message_text(query, "❌ Неизвестная команда\\.")

async def safe_edit_message_text(query, text, **kwargs):
    """Безопасное редактирование сообщения с обработкой ошибок"""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info(f"Сообщение не изменилось, пропускаем: {text[:50]}...")
        else:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Если не удалось отредактировать, отправляем новое сообщение
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception as e2:
                logger.error(f"Ошибка при отправке нового сообщения: {e2}")
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception as e2:
            logger.error(f"Ошибка при отправке нового сообщения: {e2}")

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк статистики админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
        return
    
    # Получаем статистику
    total_users = db.get_user_count()
    premium_users = db.get_premium_users_count()
    total_messages = db.get_message_count()
    
    # Получаем последних 5 пользователей
    recent_users = db.get_all_users(5)
    
    text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 *Пользователи:*\n"
        f"• Всего: {total_users}\n"
        f"• Премиум: {premium_users}\n"
        f"• Обычные: {total_users - premium_users}\n\n"
        f"💬 *Сообщения:*\n"
        f"• Всего: {total_messages}\n\n"
        f"🆕 *Последние пользователи:*\n"
    )
    
    for i, (user_id, username, first_name, last_name, is_premium, reg_date, msg_count, edit_count, delete_count, last_activity) in enumerate(recent_users, 1):
        name = f"@{username}" if username else f"{first_name or ''} {last_name or ''}".strip() or f"ID: {user_id}"
        premium_status = "⭐" if is_premium else "👤"
        text += f"{i}\\. {premium_status} {escape_markdown(name)}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_stats')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк пользователей админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
        return
    
    text = (
        f"👥 *Управление пользователями*\n\n"
        f"*Доступные команды:*\n"
        f"`/users` \\- список пользователей\n"
        f"`/ban \\[ID\\]` \\- забанить пользователя\n"
        f"`/unban \\[ID\\]` \\- разбанить пользователя\n"
        f"`/premiumadmin \\[ID\\] \\[дни\\]` \\- выдать премиум\n"
        f"`/checkuser \\[ID\\]` \\- информация о пользователя\n\n"
        f"*Быстрые действия:*\n"
        f"Используйте команды выше для управления пользователями\\."
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

async def admin_emoji_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк управления эмодзи админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
        return
    
    # Получаем все зарезервированные эмодзи
    reserved_emojis = db.get_all_reserved_emojis()
    
    text = (
        f"🎨 *Управление эмодзи*\n\n"
        f"*Доступные команды:*\n"
        f"`/emojiadmin` \\- просмотр занятых эмодзи\n"
        f"`/freeemoji \\[эмодзи\\]` \\- освободить эмодзи\n\n"
        f"*Статистика:*\n"
        f"• Занято эмодзи: {len(reserved_emojis)}\n"
        f"• Свободно эмодзи: {len(PREMIUM_EMOJIS) - len(reserved_emojis)}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_emoji')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

async def admin_tech_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк технических команд админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
        return
    
    text = (
        f"🛠️ *Технические команды*\n\n"
        f"*Информация:*\n"
        f"`/checkuser \\[ID\\]` \\- информация о пользователе\n"
        f"`/checkmsg \\[ID\\]` \\- информация о сообщении\n\n"
        f"*Управление базой данных:*\n"
        f"`/resetdb` \\- сбросить базу данных \\(опасно\\!\\)\n\n"
        f"*Для проверки работы бота:*\n"
        f"1\\. Отправьте тестовое сообщение в бота\n"
        f"2\\. Проверьте\\, что оно появилось в канале\n"
        f"3\\. Используйте `/checkmsg ID` для проверки\n"
        f"4\\. Проверьте статистику командой `/stats`"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк рассылки админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к админ меню\\.")
        return
    
    text = (
        f"📢 *Рассылка сообщений*\n\n"
        f"*Команда:*\n"
        f"`/broadcast \\[текст\\_сообщения\\]`\n\n"
        f"*Пример:*\n"
        f"`/broadcast Важное обновление бота\\!`\n\n"
        f"⚠️ *Внимание:*\n"
        f"• Рассылка отправляется ВСЕМ пользователям бота\n"
        f"• Используйте осторожно\n"
        f"• Не спамьте пользователям"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

async def resetdb_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса базы данных"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if not is_admin(user.id):
        await safe_edit_message_text(query, "❌ У вас нет доступа к этой команде\\.")
        return
    
    try:
        # Сбрасываем базу данных
        db.reset_database()
        
        await safe_edit_message_text(
            query,
            "✅ *База данных успешно сброшена\\!*\n\n"
            "Все данные были удалены\\, бот готов к работе с чистой базой\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе базы данных: {e}")
        await safe_edit_message_text(
            query,
            f"❌ Произошла ошибка при сбросе базы данных:\n"
            f"```\n{str(e)}\n```",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def resetdb_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса базы данных"""
    query = update.callback_query
    await query.answer()
    
    await safe_edit_message_text(
        query,
        "❌ Сброс базы данных отменен\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def test_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая активация премиума (для отладки)"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if db.is_user_premium(user.id):
        await safe_edit_message_text(
            query,
            "✅ У вас уже есть активная премиум подписка\\!\n"
            "Используйте /myemoji чтобы посмотреть ваш текущий эмодзи\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Активируем премиум на 30 дней
    db.set_user_premium(user.id, months=1, emoji_type="premium")
    
    text = (
        f"🎉 *Тестовая активация Premium\\!*\n\n"
        f"✅ Премиум подписка активирована на 1 месяц \\(тестовый режим\\)\\!\n\n"
        f"✨ *Теперь вам доступно:*\n"
        f"• Редактирование и удаление сообщений ✏️\n"
        f"• Уникальный закрепленный эмодзи 🔒\n"
        f"• Выбор из {len(PREMIUM_EMOJIS)} премиум эмодзи ⭐\n\n"
        f"*Как редактировать сообщения:*\n"
        f"1\\. Используйте `/edit ID` для редактирования\n"
        f"2\\. Используйте `/delete ID` для удаления\n\n"
        f"*Как закрепить эмодзи:*\n"
        f"1\\. Используйте `/availableemojis`\n"
        f"2\\. Выберите свободный эмодзи\n"
        f"3\\. Используйте `/emoji \\[эмодзи\\]`\n\n"
        f"*Посмотреть все функции:*\n"
        f"Используйте `/premium`\n\n"
        f"⚠️ *Примечание:* Это тестовая активация\\. В реальном боте используется оплата через Telegram Stars\\."
    )
    
    await safe_edit_message_text(query, text, parse_mode=ParseMode.MARKDOWN_V2)

async def buy_premium_stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Колбэк для оплаты через Stars"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if db.is_user_premium(user.id):
        await safe_edit_message_text(
            query,
            "✅ У вас уже есть активная премиум подписка\\!\n"
            "Используйте /myemoji чтобы посмотреть ваш текущий эмодзи\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Создаем инвойс для оплаты через Stars
    try:
        # Уникальный payload для идентификации платежа
        payload = f"premium_1month_{user.id}"
        
        # Отправляем инвойс
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Anon Premium - 1 месяц",
            description="Премиум подписка на 1 месяц\n✅ Редактирование сообщений\n✅ Уникальный эмодзи\n✅ Без спам-режима",
            payload=payload,
            provider_token="",  # Для Stars оставляем пустым
            currency="XTR",  # Telegram Stars
            prices=[LabeledPrice(label="Premium (1 месяц)", amount=PREMIUM_PRICE)],
            start_parameter="anon_premium",
            need_email=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False,
            protect_content=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании инвойса: {e}")
        await safe_edit_message_text(
            query,
            "❌ Произошла ошибка при создании платежа\\. Попробуйте позже\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления сообщения"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    message_id = int(query.data.replace('delete_confirm_', ''))
    
    try:
        # Проверяем, является ли пользователь владельцем сообщения
        if not db.is_message_owner(user.id, message_id) and not is_admin(user.id):
            await safe_edit_message_text(query, "❌ Вы не являетесь владельцем этого сообщения\\.\n"
                                               "Можно удалять только свои сообщения\\.")
            return
        
        # Удаляем сообщение в базе данных
        success = db.delete_message(user.id, message_id)
        
        if not success:
            await safe_edit_message_text(query, "❌ Не удалось удалить сообщение\\.")
            return
        
        # Пытаемся удалить сообщение из канала
        try:
            await context.bot.delete_message(
                chat_id=CHANNEL_ID,
                message_id=message_id
            )
        except Exception as e:
            logger.error(f"Ошибка удаления из канала: {e}")
            # Сообщение все равно считается удаленным в БД
        
        await safe_edit_message_text(
            query,
            f"✅ *Сообщение удалено\\!*\n\n"
            f"Сообщение \\#{message_id} было успешно удалено\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await safe_edit_message_text(query, f"❌ Ошибка при удалении: {str(e)}")

async def delete_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена удаления сообщения"""
    query = update.callback_query
    await query.answer()
    
    await safe_edit_message_text(
        query,
        "❌ Удаление отменено\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def edit_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор сообщения для редактирования"""
    query = update.callback_query
    await query.answer()
    
    await safe_edit_message_text(
        query,
        "✏️ *Редактирование сообщения*\n\n"
        "Введите ID сообщения для редактирования:\n"
        "*Пример:* `/edit 123`",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def delete_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор сообщения для удаления"""
    query = update.callback_query
    await query.answer()
    
    await safe_edit_message_text(
        query,
        "🗑️ *Удаление сообщения*\n\n"
        "Введите ID сообщения для удаления:\n"
        "*Пример:* `/delete 123`",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ===================== ОСНОВНЫЕ ФУНКЦИИ =====================

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if update.message and update.message.text and update.message.text.startswith('/'):
        return
    
    # Проверяем, является ли пользователь в процессе редактирования
    if user.id in pending_edits:
        await process_edit_text(update, context, user.id)
        return
    
    # Проверяем, является ли пользователь в процессе ответа
    if user.id in pending_replies:
        await process_reply_text(update, context, user.id)
        return
    
    # Проверяем, является ли сообщение пересланным (ответом)
    if hasattr(update.message, 'forward_from_chat') and update.message.forward_from_chat:
        # Это пересланное сообщение из канала - обработка ответа
        if update.message.forward_from_chat.username == CHANNEL_ID.replace('@', ''):
            await handle_reply_message(update, context)
            return
    
    # Если не пересланное сообщение или не из нашего канала - обычное сообщение
    await handle_new_message(update, context)

async def handle_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа на сообщение"""
    user = update.effective_user
    
    spam_check = check_spam_cooldown(user.id)
    if spam_check:
        await update.message.reply_text(spam_check)
        return
    
    db.register_user(
        user.id, 
        user.username if user.username else None, 
        user.first_name if user.first_name else None, 
        user.last_name if user.last_name else None
    )
    
    # Получаем ID оригинального сообщения
    if not update.message.forward_from_message_id:
        await update.message.reply_text(
            "❌ Не удалось определить сообщение для ответа\\.\n"
            "Пожалуйста, перешлите сообщение из канала корректно\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    original_message_id = update.message.forward_from_message_id
    
    # Проверяем, существует ли оригинальное сообщение
    message_info = db.get_message_info(original_message_id)
    if not message_info:
        await update.message.reply_text(
            "❌ Оригинальное сообщение не найдено в базе данных\\.\n"
            "Возможно, оно было удалено\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Сохраняем информацию об ответе
    pending_replies[user.id] = (original_message_id, None)
    
    # Всегда запрашиваем текст ответа
    await update.message.reply_text(
        "✏️ *Ответ на сообщение*\n\n"
        f"Вы отвечаете на сообщение \\#{original_message_id}\n\n"
        f"*Теперь отправьте текст вашего ответа:*",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def process_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Обработка текста ответа"""
    if user_id not in pending_replies:
        await update.message.reply_text("❌ Сессия ответа истекла\\. Пожалуйста, начните заново\\.")
        return
    
    original_message_id, _ = pending_replies[user_id]
    
    # Получаем текст ответа
    reply_text = update.message.text or update.message.caption or ""
    if not reply_text.strip():
        await update.message.reply_text("❌ Ответ не может быть пустым\\.")
        return
    
    # Получаем данные пользователя
    user_emoji = db.get_user_emoji(user_id)
    
    # Форматируем ответ
    message_prefix = f"{user_emoji}: "
    formatted_reply = f"{message_prefix}{reply_text}"
    
    try:
        # Отправляем ответ в канал
        sent_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=formatted_reply,
            parse_mode=ParseMode.MARKDOWN if any(mark in reply_text for mark in ['*', '_', '`']) else None
        )
        
        # Логируем ответ в базе данных
        db.log_message(user_id, sent_message.message_id, reply_text, 
                      reply_to=original_message_id, emoji_used=user_emoji)
        
        # Удаляем из pending_replies
        del pending_replies[user_id]
        
        # Создаем клавиатуру с кнопками управления для премиум пользователей
        keyboard = []
        if db.is_user_premium(user_id) or is_admin(user_id):
            keyboard = [
                [
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_select'),
                    InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')
                ]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        response_text = (
            f"✅ *Ответ отправлен\\!*\n\n"
            f"Ваш ответ был отправлен как ответ на сообщение \\#{original_message_id}"
        )
        
        if not db.is_user_premium(user_id):
            response_text += f"\n\n✨ *Получите Premium\\, чтобы редактировать и удалять сообщения\\!*\nИспользуйте /premium"
        
        await update.message.reply_text(
            response_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка отправки ответа: {error_msg}")
        
        await update.message.reply_text(f"❌ Ошибка при отправке: {error_msg}")

async def handle_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового сообщения (не ответа)"""
    user = update.effective_user
    
    spam_check = check_spam_cooldown(user.id)
    if spam_check:
        await update.message.reply_text(spam_check)
        return
    
    db.register_user(
        user.id, 
        user.username if user.username else None, 
        user.first_name if user.first_name else None, 
        user.last_name if user.last_name else None
    )
    
    # Проверяем, не является ли это текстом ответа на пересланное сообщение
    if user.id in pending_replies:
        # Это должно обрабатываться в handle_all_messages
        return
    
    try:
        message = update.message
        
        # Получаем эмодзи пользователя
        user_emoji = db.get_user_emoji(user.id)
        
        # Форматируем префикс сообщения
        message_prefix = f"{user_emoji}: "
        
        if message.text:
            formatted_message = f"{message_prefix}{message.text}"
            
            # Отправляем сообщение в канал
            sent_message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=formatted_message,
                parse_mode=ParseMode.MARKDOWN if any(mark in message.text for mark in ['*', '_', '`']) else None
            )
            
            # Логируем сообщение
            db.log_message(user.id, sent_message.message_id, message.text, emoji_used=user_emoji)
            
            # Создаем клавиатуру с кнопками управления
            keyboard = []
            if db.is_user_premium(user.id) or is_admin(user.id):
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_select'),
                        InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')
                    ]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            response_text = (
                f"✅ *Сообщение отправлено\\!*\n\n"
                f"ID сообщения: `{sent_message.message_id}`"
            )
            
            if not db.is_user_premium(user.id):
                response_text += f"\n\n✨ *Получите Premium\\, чтобы редактировать и удалять сообщения\\!*\nИспользуйте /premium"
            
            await update.message.reply_text(
                response_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
        elif message.photo:
            photo = message.photo[-1]
            caption = f"{message_prefix}Анонимное фото"
            if message.caption:
                caption = f"{message_prefix}{message.caption}"
            
            sent_message = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN if message.caption and any(mark in message.caption for mark in ['*', '_', '`']) else None
            )
            
            if message.caption:
                db.log_message(user.id, sent_message.message_id, message.caption, emoji_used=user_emoji)
            else:
                db.log_message(user.id, sent_message.message_id, "Анонимное фото", emoji_used=user_emoji)
            
            keyboard = []
            if db.is_user_premium(user.id) or is_admin(user.id):
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_select'),
                        InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')
                    ]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            response_text = (
                f"✅ *Фото отправлено\\!*\n\n"
                f"ID сообщения: `{sent_message.message_id}`\n"
                f"\\(Редактирование фото недоступно\\)"
            )
            
            if not db.is_user_premium(user.id):
                response_text += f"\n\n✨ *Получите Premium\\, чтобы удалять сообщения\\!*\nИспользуйте /premium"
            
            await update.message.reply_text(
                response_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
        elif message.video:
            video = message.video
            caption = f"{message_prefix}Анонимное видео"
            if message.caption:
                caption = f"{message_prefix}{message.caption}"
            
            sent_message = await context.bot.send_video(
                chat_id=CHANNEL_ID,
                video=video.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN if message.caption and any(mark in message.caption for mark in ['*', '_', '`']) else None
            )
            
            if message.caption:
                db.log_message(user.id, sent_message.message_id, message.caption, emoji_used=user_emoji)
            else:
                db.log_message(user.id, sent_message.message_id, "Анонимное видео", emoji_used=user_emoji)
            
            keyboard = []
            if db.is_user_premium(user.id) or is_admin(user.id):
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_select'),
                        InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')
                    ]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            response_text = (
                f"✅ *Видео отправлено\\!*\n\n"
                f"ID сообщения: `{sent_message.message_id}`\n"
                f"\\(Редактирование видео недоступно\\)"
            )
            
            if not db.is_user_premium(user.id):
                response_text += f"\n\n✨ *Получите Premium\\, чтобы удалять сообщения\\!*\nИспользуйте /premium"
            
            await update.message.reply_text(
                response_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
        elif message.voice:
            voice = message.voice
            caption = f"{message_prefix}Анонимное голосовое сообщение"
            
            sent_message = await context.bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=voice.file_id,
                caption=caption
            )
            
            db.log_message(user.id, sent_message.message_id, "Анонимное голосовое сообщение", emoji_used=user_emoji)
            
            keyboard = []
            if db.is_user_premium(user.id) or is_admin(user.id):
                keyboard = [
                    [InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            response_text = "✅ Голосовое сообщение отправлено в канал\\!"
            
            if not db.is_user_premium(user.id):
                response_text += f"\n\n✨ *Получите Premium\\, чтобы удалять сообщения\\!*\nИспользуйте /premium"
            
            await update.message.reply_text(
                response_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
        elif message.document:
            document = message.document
            caption = f"{message_prefix}Анонимный документ"
            if message.caption:
                caption = f"{message_prefix}{message.caption}"
            
            sent_message = await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=document.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN if message.caption and any(mark in message.caption for mark in ['*', '_', '`']) else None
            )
            
            if message.caption:
                db.log_message(user.id, sent_message.message_id, message.caption, emoji_used=user_emoji)
            else:
                db.log_message(user.id, sent_message.message_id, "Анонимный документ", emoji_used=user_emoji)
            
            keyboard = []
            if db.is_user_premium(user.id) or is_admin(user.id):
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_select'),
                        InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_select')
                    ]
                ]
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            response_text = "✅ Документ отправлен в канал\\!"
            
            if not db.is_user_premium(user.id):
                response_text += f"\n\n✨ *Получите Premium\\, чтобы редактировать и удалять сообщения\\!*\nИспользуйте /premium"
            
            await update.message.reply_text(
                response_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка отправки: {error_msg}")
        await update.message.reply_text(f"❌ Ошибка: {error_msg}")

# ===================== УНИКАЛЬНЫЕ ЭМОДЗИ =====================

async def emoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not db.is_user_premium(user.id):
        await update.message.reply_text(
            "❌ Эта функция доступна только для премиум пользователей\\.\n\n"
            "Используйте /premium чтобы узнать больше или /buy\\_premium чтобы приобрести\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    if not context.args:
        current_emoji = db.get_user_emoji(user.id)
        reserved_emoji = db.get_reserved_emoji_for_user(user.id)
        
        text = (
            f"🎨 *Смена эмодзи*\n\n"
            f"Текущий эмодзи: {current_emoji}\n"
        )
        
        if reserved_emoji:
            if reserved_emoji == current_emoji:
                text += f"🔒 *Зарезервирован за вами*\n\n"
            else:
                text += f"⚠️ *Закреплен другой эмодзи: {reserved_emoji}*\n\n"
        else:
            text += f"⚠️ *Не зарезервирован*\n\n"
        
        text += (
            f"*Использование:*\n"
            f"`/emoji \\[эмодзи\\]` \\- выбрать и закрепить эмодзи\n\n"
            f"*Примеры:*\n"
            f"`/emoji 🔥` \\- закрепить огонь за собой\n"
            f"`/emoji ✨` \\- закрепить искры за собой\n\n"
            f"*Посмотреть доступные эмодзи:*\n"
            f"`/availableemojis`"
        )
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    emoji = context.args[0]
    
    if not validate_emoji(emoji):
        await update.message.reply_text(
            "❌ Пожалуйста, используйте валидный эмодзи\\.\n"
            "*Например:* `/emoji 🔥` или `/emoji ✨`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Проверяем, не занят ли эмодзи
    reserved_owner = db.get_reserved_emoji_owner(emoji)
    if reserved_owner and reserved_owner != user.id:
        # Проверяем, является ли пользователь админом
        if is_admin(user.id):
            # Админ видит реального владельца
            owner_info = db.get_user_info(reserved_owner)
            owner_name = f"@{owner_info[1]}" if owner_info and owner_info[1] else f"ID: {reserved_owner}"
            
            await update.message.reply_text(
                f"🔒 *Только для админа:*\n\n"
                f"❌ Эмодзи {emoji} уже закреплен за пользователем {escape_markdown(owner_name)}\n\n"
                f"Если нужно\\, освободите его командой:\n"
                f"`/freeemoji {emoji}`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # Обычные пользователи видят общее сообщение
            await update.message.reply_text(
                f"❌ Этот эмодзи уже занят\\.\n\n"
                f"Используйте команду `/availableemojis` чтобы увидеть свободные эмодзи\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        return
    
    # Устанавливаем эмодзи с закреплением
    success = db.set_user_emoji_with_reservation(user.id, emoji)
    
    if not success:
        await update.message.reply_text(
            "❌ Не удалось закрепить эмодзи\\. Попробуйте другой\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    type_text = "⭐ Премиум эмодзи" if emoji in PREMIUM_EMOJIS else "📱 Стандартный эмодзи"
    
    await update.message.reply_text(
        f"✅ Эмодзи успешно закреплен за вами\\!\n\n"
        f"Новый эмодзи: {emoji}\n"
        f"Тип: {type_text}\n"
        f"Статус: 🔒 *Уникальный закрепленный эмодзи*\n\n"
        f"Теперь этот эмодзи закреплен только за вами\\!\n"
        f"Другие пользователи не смогут его использовать\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def availableemojis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать доступные эмодзи для закрепления"""
    user = update.effective_user
    
    if not db.is_user_premium(user.id):
        await update.message.reply_text(
            "❌ Эта функция доступна только для премиум пользователей\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Получаем доступные и занятые эмодзи
    available_emojis = db.get_available_emojis()
    reserved_emojis = db.get_all_reserved_emojis()
    
    text = "📋 *Доступные эмодзи для закрепления*\n\n"
    
    if available_emojis:
        text += f"✅ *Свободно: {len(available_emojis)} эмодзи*\n\n"
        
        # Показываем доступные эмодзи группами
        for i in range(0, len(available_emojis), 10):
            group = available_emojis[i:i+10]
            text += " ".join(group) + "\n"
        
        text += f"\nИспользуйте `/emoji \\[эмодзи\\]` чтобы закрепить\n"
        text += f"*Пример:* `/emoji {available_emojis[0] if available_emojis else '🔥'}`\n\n"
    else:
        text += "😔 *Все эмодзи заняты*\n\n"
    if reserved_emojis:
        # Для админов показываем детали, для обычных пользователей - только количество
        if is_admin(user.id):
            for i, (emoji, user_id, username, first_name, reserved_at) in enumerate(reserved_emojis[:5], 1):
                name = f"@{username}" if username else f"{first_name or f'ID {user_id}'}"
                text += f"{i}\\. {emoji} \\- {escape_markdown(name)}\n"
            
            if len(reserved_emojis) > 5:
                text += f"\\.\\.\\. и еще {len(reserved_emojis) - 5} занятых эмодзи\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def myreservations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мои зарезервированные эмодзи"""
    user = update.effective_user
    
    if not db.is_user_premium(user.id):
        await update.message.reply_text(
            "❌ Эта функция доступна только для премиум пользователей\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    current_emoji = db.get_user_emoji(user.id)
    reserved_emoji = db.get_reserved_emoji_for_user(user.id)
    
    text = "🔒 *Мои зарезервированные эмодзи*\n\n"
    
    if reserved_emoji:
        text += f"✅ Текущий закрепленный эмодзи: {reserved_emoji}\n"
        
        if current_emoji == reserved_emoji:
            text += f"📝 Используется в сообщениях: Да\n"
        else:
            text += f"⚠️ Внимание: В настройках установлен другой эмодзи\n"
            text += f"📝 Текущий эмодзи: {current_emoji}\n"
        
        # Информация о статусе премиума
        user_info = db.get_user_info(user.id)
        if user_info and user_info[8]:
            try:
                until_date = datetime.fromisoformat(user_info[8])
                days_left = (until_date - datetime.now()).days
                text += f"📅 Эмодзи закреплен до окончания премиума \\({days_left} дней\\)\n"
            except:
                pass
        
        text += f"\n*Для смены эмодзи:*\n"
        text += f"Используйте `/emoji \\[новый\\_эмодзи\\]`\n"
        text += f"Старый эмодзи будет освобожден автоматически\\.\n"
    else:
        text += f"⚠️ У вас нет закрепленных эмодзи\n\n"
        text += f"*Как закрепить эмодзи:*\n"
        text += f"1\\. Используйте `/availableemojis` для просмотра доступных\n"
        text += f"2\\. Выберите понравившийся эмодзи\n"
        text += f"3\\. Используйте `/emoji \\[эмодзи\\]` для закрепления\n\n"
        text += f"*Текущий эмодзи:* {current_emoji}\n"
        text += f"⚠️ Этот эмодзи не закреплен и могут использовать другие"
    
    text += f"\n*Преимущества закрепления:*\n"
    text += f"• Уникальность \\- эмодзи только ваш\n"
    text += f"• Узнаваемость \\- другие видят ваш уникальный стиль\n"
    text += f"• Эксклюзивность \\- доступно только премиум пользователям"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

async def myemoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /myemoji для просмотра текущего эмодзи"""
    user = update.effective_user
    
    current_emoji = db.get_user_emoji(user.id)
    is_premium = db.is_user_premium(user.id)
    reserved_emoji = db.get_reserved_emoji_for_user(user.id)
    
    if is_premium:
        text = (
            f"🎨 *Ваш эмодзи*\n\n"
            f"Текущий эмодзи: {current_emoji}\n"
            f"Статус: ✅ Premium активен\n"
            f"Спам\\-режим: 🔓 *ОТКЛЮЧЕН*\n"
        )
        
        if reserved_emoji:
            if reserved_emoji == current_emoji:
                text += f"🔒 *Эмодзи закреплен за вами*\n\n"
            else:
                text += f"⚠️ *Закреплен другой эмодзи: {reserved_emoji}*\n\n"
        else:
            text += f"⚠️ *Эмодзи не закреплен*\n\n"
        
        text += (
            f"*Изменить эмодзи:*\n"
            f"`/emoji \\[новый\\_эмодзи\\]`\n"
            f"*Пример:* `/emoji ✨`\n\n"
            f"*Посмотреть доступные эмодзи:*\n"
            f"`/availableemojis`\n\n"
            f"*Мои закрепленные эмодзи:*\n"
            f"`/myreservations`\n\n"
            f"*Редактирование/Удаление:*\n"
            f"`/edit ID` \\- редактировать\n"
            f"`/delete ID` \\- удалить"
        )
    else:
        text = (
            f"🎨 *Ваш эмодзи*\n\n"
            f"Текущий эмодзи: {current_emoji}\n"
            f"Статус: ❌ Premium не активен\n"
            f"Спам\\-режим: ⏳ *{DEFAULT_SPAM_COOLDOWN} секунд*\n\n"
            f"*Получить премиум:*\n"
            f"`/premium` \\- узнать о премиуме\n"
            f"`/buy\\_premium` \\- купить премиум за {PREMIUM_PRICE}⭐\n\n"
            f"С премиумом вы сможете:\n"
            f"• Редактировать и удалять сообщения ✏️\n"
            f"• Закрепить уникальный эмодзи за собой 🔒\n"
            f"• Использовать премиум эмодзи Telegram ⭐\n"
            f"• 🔓 *ОТКЛЮЧЕНИЕ спам\\-режима*\n\n"
            f"*Поддержка:* @anonaltshelper"
        )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

# ===================== PREMIUM КОМАНДЫ (РЕАЛЬНАЯ ОПЛАТА) =====================

async def buy_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупка премиум подписки через Telegram Stars"""
    user = update.effective_user
    
    if db.is_user_premium(user.id):
        await update.message.reply_text(
            "✅ У вас уже есть активная премиум подписка\\!\n"
            "Используйте /myemoji чтобы посмотреть ваш текущий эмодзи\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    text = (
        f"✨ *Anon Premium \\- 1 месяц*\n\n"
        f"*Стоимость:* {PREMIUM_PRICE} звезд Telegram ⭐\n\n"
        f"*Включает:*\n"
        f"✅ Редактирование и удаление сообщений ✏️\n"
        f"✅ Уникальный закрепленный эмодзи 🔒\n"
        f"✅ Премиум эмодзи Telegram ⭐\n"
        f"✅ 🔓 *Отключение спам\\-режима*\n\n"
        f"*Особенности:*\n"
        f"• Редактируйте отправленные сообщения\n"
        f"• Удаляйте свои сообщения\n"
        f"• Закрепите уникальный эмодзи за собой\n"
        f"• Используйте премиум эмодзи\n"
        f"• Отправляйте сообщения без ожидания\n\n"
        f"*Обычный пользователь:* ⏳ {DEFAULT_SPAM_COOLDOWN} секунд ожидания\n"
        f"*Премиум пользователь:* 🔓 почти нет ограничений \\({PREMIUM_SPAM_COOLDOWN} сек\\)\n\n"
        f"*Поддержка:* @anonaltshelper"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"💰 Купить за {PREMIUM_PRICE}⭐", callback_data="buy_premium_stars")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in buy_premium: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка\\. Попробуйте позже\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик предварительной проверки платежа"""
    query = update.pre_checkout_query
    
    # Проверяем payload
    payload = query.invoice_payload
    if not payload.startswith("premium_1month_"):
        await query.answer(ok=False, error_message="Неверный тип товара")
        return
    
    try:
        user_id = int(payload.split("_")[-1])
        user = db.get_user_info(user_id)
        
        if not user:
            await query.answer(ok=False, error_message="Пользователь не найден")
            return
        
        # Проверяем, не купил ли уже пользователь премиум
        if db.is_user_premium(user_id):
            await query.answer(ok=False, error_message="У вас уже есть активная подписка")
            return
        
        await query.answer(ok=True)
    except Exception as e:
        logger.error(f"Error in pre_checkout: {e}")
        await query.answer(ok=False, error_message="Произошла ошибка")

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты"""
    user = update.effective_user
    payment = update.message.successful_payment
    
    try:
        # Активируем премиум
        db.set_user_premium(user.id, months=1, emoji_type="premium")
        
        # Сохраняем информацию о платеже в базе данных
        cursor = db.conn.cursor()
        cursor.execute('''
            INSERT INTO payments (payment_id, user_id, amount, currency, status, timestamp, product, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            payment.telegram_payment_charge_id,
            user.id,
            payment.total_amount,
            payment.currency,
            "completed",
            datetime.now().isoformat(),
            "premium_1month",
            payment.invoice_payload
        ))
        db.conn.commit()
        
        # Отправляем поздравление
        text = (
            f"🎉 *Поздравляем\\!*\n\n"
            f"✅ Премиум подписка активирована на 1 месяц\\!\n\n"
            f"✨ *Теперь вам доступно:*\n"
            f"• Редактирование и удаление сообщений ✏️\n"
            f"• Уникальный закрепленный эмодзи 🔒\n"
            f"• Выбор из {len(PREMIUM_EMOJIS)} премиум эмодзи ⭐\n"
            f"• 🔓 *ОТКЛЮЧЕНИЕ спам\\-режима*\n\n"
            f"*Как редактировать сообщения:*\n"
            f"1\\. Используйте `/edit ID` для редактирования\n"
            f"2\\. Используйте `/delete ID` для удаления\n\n"
            f"*Как закрепить эмодзи:*\n"
            f"1\\. Используйте `/availableemojis`\n"
            f"2\\. Выберите свободный эмодзи\n"
            f"3\\. Используйте `/emoji \\[эмодзи\\]`\n\n"
            f"*Отправка сообщений:*\n"
            f"🔓 Теперь вы можете отправлять сообщения без долгого ожидания\\!\n"
            f"Обычные пользователи ждут {DEFAULT_SPAM_COOLDOWN} секунд\\,\n"
            f"премиум пользователи \\- всего {PREMIUM_SPAM_COOLDOWN} секунды\\!\n\n"
            f"*Посмотреть все функции:*\n"
            f"Используйте `/premium`\n\n"
            f"Спасибо за покупку\\! 💫"
        )
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        
    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при активации премиума\\. Свяжитесь с администратором @anonaltshelper\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if db.is_user_premium(user.id):
        user_emoji = db.get_user_emoji(user.id)
        reserved_emoji = db.get_reserved_emoji_for_user(user.id)
        
        text = (
            f"✨ *Anon Premium*\n\n"
            f"✅ Ваш премиум аккаунт активен\\!\n"
            f"🎨 Текущий эмодзи: {user_emoji}\n"
            f"⏱️ Спам\\-режим: 🔓 *ОТКЛЮЧЕН*\n"
        )
        
        if reserved_emoji and reserved_emoji == user_emoji:
            text += f"🔒 *Уникальный закрепленный эмодзи*\n\n"
        elif reserved_emoji:
            text += f"\n⚠️ Внимание: Закреплен {reserved_emoji}\\, но используется {user_emoji}\n\n"
        else:
            text += f"\n⚠️ *Эмодзи не закреплен*\n\n"
        
        text += (
            f"*Преимущества:*\n"
            f"• Редактирование сообщений ✏️\n"
            f"• Удаление сообщений 🗑️\n"
            f"• Уникальный закрепленный эмодзи 🔒\n"
            f"• Выбор из {len(PREMIUM_EMOJIS)} премиум эмодзи ⭐\n"
            f"• 🔓 Отключение спам\\-режима\n\n"
            f"*Команды:*\n"
            f"`/emoji` \\- закрепить новый эмодзи\n"
            f"`/availableemojis` \\- доступные эмодзи\n"
            f"`/myreservations` \\- мои резервации\n"
            f"`/edit ID` \\- редактировать сообщение\n"
            f"`/delete ID` \\- удалить сообщение\n\n"
            f"*Поддержка:* @anonaltshelper"
        )
        
    else:
        text = (
            f"✨ *Anon Premium*\n\n"
            f"⭐ *Получите расширенные функции\\!*\n\n"
            f"*Что входит в премиум:*\n"
            f"✅ Редактирование отправленных сообщений ✏️\n"
            f"✅ Удаление своих сообщений 🗑️\n"
            f"✅ Уникальный закрепленный эмодзи 🔒\n"
            f"✅ {len(PREMIUM_EMOJIS)} премиум эмодзи Telegram ⭐\n"
            f"✅ 🔓 *Отключение спам\\-режима*\n\n"
            f"*Особенности редактирования:*\n"
            f"• Изменяйте текст отправленных сообщений\n"
            f"• Удаляйте сообщения\\, которые хотите скрыть\n"
            f"• Закрепите уникальный эмодзи за собой\n"
            f"• Используйте премиум эмодзи Telegram\n\n"
            f"*Отличие от обычных пользователей:*\n"
            f"👤 *Обычный:* ⏳ {DEFAULT_SPAM_COOLDOWN} сек ожидания\n"
            f"⭐ *Премиум:* 🔓 {PREMIUM_SPAM_COOLDOWN} сек \\(почти нет ограничений\\)\n\n"
            f"*Стоимость:*\n"
            f"1 месяц \\- {PREMIUM_PRICE} звезд Telegram ⭐\n\n"
            f"*Поддержка:* @anonaltshelper"
        )
        
        keyboard = [
            [InlineKeyboardButton(f"💰 Купить Premium \\({PREMIUM_PRICE}⭐\\)", callback_data="buy_premium_stars")],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        return
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

# ===================== ЗАПУСК БОТА =====================

def main():
    print("=" * 60)
    print("🤖 АНОНИМНЫЙ БОТ С УНИКАЛЬНЫМИ ЭМОДЗИ")
    print("=" * 60)
    print(f"📢 Канал: {CHANNEL_ID}")
    print(f"👑 Админ ID: {ADMIN_IDS[0]}")
    print(f"💰 Стоимость премиума: {PREMIUM_PRICE} Stars")
    print(f"🎨 Доступно эмодзи: {len(PREMIUM_EMOJIS)}")
    print(f"⏱️ Антиспам обычные: {DEFAULT_SPAM_COOLDOWN} секунд")
    print(f"⏱️ Антиспам премиум: {PREMIUM_SPAM_COOLDOWN} секунды")
    print("=" * 60)
    print("✨ *Премиум функции:*")
    print(f"• {PREMIUM_PRICE} Stars за 1 месяц")
    print("• Редактирование сообщений ✏️")
    print("• Удаление сообщений 🗑️")
    print("• Уникальный закрепленный эмодзи 🔒")
    print("• Премиум эмодзи Telegram ⭐")
    print("• 🔓 ОТКЛЮЧЕНИЕ спам-режима")
    print("=" * 60)
    print("👑 *Админ команды:*")
    print("• /admin - админ панель")
    print("• /stats - статистика")
    print("• /users - список пользователей")
    print("• /ban - забанить пользователя")
    print("• /premiumadmin - выдать премиум")
    print("• /resetdb - сбросить базу данных")
    print("=" * 60)
    print("📌 Поддержка: @anonaltshelper")
    print("=" * 60)
    print("🔄 Создаю/проверяю базу данных...")
    
    # Пересоздаем базу данных для исправления структуры
    try:
        db.reset_database()
        print("✅ База данных пересоздана с правильной структурой")
    except Exception as e:
        print(f"⚠️ Ошибка при пересоздании базы данных: {e}")
        print("Продолжаем с текущей структурой...")
    
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Основные команды
        app.add_handler(CommandHandler("start", start_command))
        
        # Админ команды
        app.add_handler(CommandHandler("admin", admin_command))
        app.add_handler(CommandHandler("stats", stats_command))
        app.add_handler(CommandHandler("users", users_command))
        app.add_handler(CommandHandler("ban", ban_command))
        app.add_handler(CommandHandler("unban", unban_command))
        app.add_handler(CommandHandler("premiumadmin", premium_admin_command))
        app.add_handler(CommandHandler("emojiadmin", emojiadmin_command))
        app.add_handler(CommandHandler("freeemoji", freeemoji_command))
        app.add_handler(CommandHandler("checkuser", checkuser_command))
        app.add_handler(CommandHandler("checkmsg", checkmsg_command))
        app.add_handler(CommandHandler("broadcast", broadcast_command))
        app.add_handler(CommandHandler("resetdb", resetdb_command))
        
        # Premium команды с уникальными эмодзи
        app.add_handler(CommandHandler("premium", premium_command))
        app.add_handler(CommandHandler("emoji", emoji_command))
        app.add_handler(CommandHandler("myemoji", myemoji_command))
        app.add_handler(CommandHandler("availableemojis", availableemojis_command))
        app.add_handler(CommandHandler("myreservations", myreservations_command))
        
        # Команды редактирования и удаления
        app.add_handler(CommandHandler("edit", edit_message_command))
        app.add_handler(CommandHandler("delete", delete_message_command))
        app.add_handler(CommandHandler("buy_premium", buy_premium_command))
        
        # Обработчики платежей через Stars
        app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
        app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
        
        # Обработчики кнопок
        app.add_handler(CallbackQueryHandler(button_handler))
        
        # Обработчик всех сообщений
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_all_messages
        ))
        
        print("✅ Бот запущен")
        print("👉 Используйте /start для начала работы")
        print("⭐ Используйте /premium для информации о премиуме")
        print("👑 Используйте /admin для админ панели (только для админов)")
        print("🎨 Используйте /availableemojis для выбора эмодзи")
        print("✏️ Премиум пользователи получают кнопки управления сообщениями")
        print("💳 Используйте /buy_premium для покупки премиума через Stars")
        print("🔓 Премиум пользователи: почти НЕТ спам-режима!")
        print("📌 Поддержка: @anonaltshelper")
        print("=" * 60)
        
        app.run_polling(drop_pending_updates=True)
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
