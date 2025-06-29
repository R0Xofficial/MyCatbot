# MyCatBot - Telegram bot
# Copyright (C) 2025 R0X
# Licensed under the GNU General Public License v3.0
# See the LICENSE file for details.

#!/usr/bin/env python
# -*- coding: utf-8 -*-

# --- MyCatBot [TEST] ---
# The bot is initially ready to go, but not everything has been thoroughly tested yet.
# Errors, exceptions, and unexpected restarts are possible.
# Report issues if you see them!

import logging
import random
import os
import requests
import html
import sqlite3
import speedtest
import asyncio
import re
import io
import telegram
from typing import List, Tuple
from telegram import Update, User, Chat, constants, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ApplicationHandlerStop, JobQueue
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from datetime import datetime, timezone, timedelta
from texts import (
    MEOW_TEXTS, NAP_TEXTS, PLAY_TEXTS, TREAT_TEXTS, ZOOMIES_TEXTS, 
    JUDGE_TEXTS, ATTACK_TEXTS, KILL_TEXTS, PUNCH_TEXTS, SLAP_TEXTS, 
    BITE_TEXTS, HUG_TEXTS, FED_TEXTS, OWNER_WELCOME_TEXTS, LEAVE_TEXTS,
    CANT_TARGET_OWNER_TEXTS, CANT_TARGET_SELF_TEXTS,
    CANT_TARGET_OWNER_HUG_TEXTS, CANT_TARGET_SELF_HUG_TEXTS
)

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor.ptb_urllib3.urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Owner ID Configuration & Bot Start Time ---
OWNER_ID = None
BOT_START_TIME = datetime.now()
TENOR_API_KEY = None
DB_NAME = "catbot_data.db"
LOG_CHAT_ID = None

# --- Load configuration from environment variables ---
try:
    owner_id_str = os.getenv("TELEGRAM_OWNER_ID")
    if owner_id_str: OWNER_ID = int(owner_id_str); logger.info(f"Owner ID loaded: {OWNER_ID}")
    else: raise ValueError("TELEGRAM_OWNER_ID environment variable not set or empty")
except (ValueError, TypeError) as e: logger.critical(f"CRITICAL: Invalid or missing TELEGRAM_OWNER_ID: {e}"); print(f"\n--- FATAL ERROR --- \nInvalid or missing TELEGRAM_OWNER_ID."); exit(1)
except Exception as e: logger.critical(f"CRITICAL: Unexpected error loading OWNER_ID: {e}"); print(f"\n--- FATAL ERROR --- \nUnexpected error loading OWNER_ID: {e}"); exit(1)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN: logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN not set!"); print("\n--- FATAL ERROR --- \nTELEGRAM_BOT_TOKEN is not set."); exit(1)

TENOR_API_KEY = os.getenv("TENOR_API_KEY")
if not TENOR_API_KEY: logger.warning("WARNING: TENOR_API_KEY not set. Themed GIFs disabled.")
else: logger.info("Tenor API Key loaded. Themed GIFs enabled.")

log_chat_id_str = os.getenv("LOG_CHAT_ID")
if log_chat_id_str:
    try:
        LOG_CHAT_ID = int(log_chat_id_str)
        logger.info(f"Log Chat ID loaded: {LOG_CHAT_ID}")
    except ValueError:
        logger.error(f"Invalid LOG_CHAT_ID: '{log_chat_id_str}' is not a valid integer. Will fallback to OWNER_ID for logs.")
        LOG_CHAT_ID = None
else:
    logger.info("LOG_CHAT_ID not set. Operational logs (globalbans/blacklist/sudo) will be sent to OWNER_ID if available.")

# --- Database Initialization ---
def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_bot INTEGER,
                last_seen TEXT 
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_username ON users (username)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_by_id INTEGER,
                timestamp TEXT 
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sudo_users (
                user_id INTEGER PRIMARY KEY,
                added_by_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_by_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_chats (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                added_at TEXT NOT NULL,
                enforce_gban INTEGER DEFAULT 1 NOT NULL 
            )
        """)
        
        conn.commit()
        logger.info(f"Database '{DB_NAME}' initialized successfully (tables users, blacklist, sudo_users ensured).")
    except sqlite3.Error as e:
        logger.error(f"SQLite error during DB initialization: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Blacklist Helper Functions ---
def add_to_blacklist(user_id: int, banned_by_id: int, reason: str | None = "No reason provided.") -> bool:
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        current_timestamp_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "INSERT OR IGNORE INTO blacklist (user_id, reason, banned_by_id, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, reason, banned_by_id, current_timestamp_iso)
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"SQLite error adding user {user_id} to blacklist: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

def remove_from_blacklist(user_id: int) -> bool:
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"SQLite error removing user {user_id} from blacklist: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

def get_blacklist_reason(user_id: int) -> str | None:
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT reason FROM blacklist WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return row[0]
        return None
    except sqlite3.Error as e:
        logger.error(f"SQLite error checking blacklist reason for user {user_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def is_user_blacklisted(user_id: int) -> bool:
    return get_blacklist_reason(user_id) is not None

# --- Blacklist Check Handler ---
async def check_blacklist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user

    if user.id == OWNER_ID:
        return

    if is_user_blacklisted(user.id):
        user_mention_log = f"@{user.username}" if user.username else str(user.id)
        message_text_preview = update.message.text[:50] if update.message.text else "[No text content]"
        
        logger.info(f"User {user.id} ({user_mention_log}) is blacklisted. Silently ignoring and blocking interaction: '{message_text_preview}'")
        
        raise ApplicationHandlerStop

# --- Sudo ---
def add_sudo_user(user_id: int, added_by_id: int) -> bool:
    """Adds a user to the sudo list."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        current_timestamp_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "INSERT OR IGNORE INTO sudo_users (user_id, added_by_id, timestamp) VALUES (?, ?, ?)",
            (user_id, added_by_id, current_timestamp_iso)
        )
        conn.commit()
        return cursor.rowcount > 0 
    except sqlite3.Error as e:
        logger.error(f"SQLite error adding sudo user {user_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

def remove_sudo_user(user_id: int) -> bool:
    """Removes a user from the sudo list."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sudo_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"SQLite error removing sudo user {user_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

def is_sudo_user(user_id: int) -> bool:
    """Checks if a user is on the sudo list (specifically, not checking if they are THE owner)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sudo_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"SQLite error checking sudo for user {user_id}: {e}", exc_info=True)
        return False 
    finally:
        if conn:
            conn.close()

def is_privileged_user(user_id: int) -> bool:
    """Checks if the user is the Owner or a Sudo user."""
    if user_id == OWNER_ID:
        return True
    return is_sudo_user(user_id)

# --- User logger ---
def update_user_in_db(user: User | None):
    if not user:
        return
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        current_timestamp_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code, is_bot, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                language_code = excluded.language_code,
                is_bot = excluded.is_bot,
                last_seen = excluded.last_seen 
        """, (
            user.id, user.username, user.first_name, user.last_name,
            user.language_code, 1 if user.is_bot else 0, current_timestamp_iso
        ))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"SQLite error updating user {user.id} in users table: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def get_user_from_db_by_username(username_query: str) -> User | None:
    if not username_query:
        return None
    conn = None
    user_obj: User | None = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        normalized_username = username_query.lstrip('@').lower()
        cursor.execute(
            "SELECT user_id, username, first_name, last_name, language_code, is_bot FROM users WHERE LOWER(username) = ?",
            (normalized_username,)
        )
        row = cursor.fetchone()
        if row:
            user_obj = User(
                id=row[0], username=row[1], first_name=row[2] or "",
                last_name=row[3], language_code=row[4], is_bot=bool(row[5])
            )
            logger.info(f"User {username_query} found in DB with ID {row[0]}.")
    except sqlite3.Error as e:
        logger.error(f"SQLite error fetching user by username '{username_query}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return user_obj

async def log_user_from_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        update_user_in_db(update.effective_user)
    
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        update_user_in_db(update.message.reply_to_message.from_user)

    chat = update.effective_chat
    if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if 'known_chats' not in context.bot_data:
            context.bot_data['known_chats'] = set()
            try:
                with sqlite3.connect(DB_NAME) as conn:
                    cursor = conn.cursor()
                    known_ids = {row[0] for row in cursor.execute("SELECT chat_id FROM bot_chats")}
                    context.bot_data['known_chats'] = known_ids
                    logger.info(f"Loaded {len(known_ids)} known chats into cache.")
            except sqlite3.Error as e:
                logger.error(f"Could not preload known chats into cache: {e}")

        if chat.id not in context.bot_data['known_chats']:
            logger.info(f"Passively discovered and adding new chat to DB: {chat.title} ({chat.id})")
            add_chat_to_db(chat.id, chat.title or f"Untitled Chat {chat.id}")
            context.bot_data['known_chats'].add(chat.id)

def get_all_sudo_users_from_db() -> List[Tuple[int, str]]:
    conn = None
    sudo_list = []
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, timestamp FROM sudo_users ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        for row in rows:
            sudo_list.append((row[0], row[1]))
    except sqlite3.Error as e:
        logger.error(f"SQLite error fetching all sudo users: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return sudo_list

def parse_duration_to_timedelta(duration_str: str | None) -> timedelta | None:
    if not duration_str:
        return None
    duration_str = duration_str.lower()
    value = 0
    unit = None
    match = re.match(r"(\d+)([smhdw])", duration_str)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
    else:
        try:
            value = int(duration_str)
            unit = 'm' 
        except ValueError:
            return None
    if unit == 's': return timedelta(seconds=value)
    elif unit == 'm': return timedelta(minutes=value)
    elif unit == 'h': return timedelta(hours=value)
    elif unit == 'd': return timedelta(days=value)
    elif unit == 'w': return timedelta(weeks=value)
    return None

async def _parse_mod_command_args(args: list[str]) -> tuple[str | None, str | None, str | None]:
    target_arg: str | None = None
    duration_arg: str | None = None
    reason_list: list[str] = []
    if not args: return None, None, None
    target_arg = args[0]
    remaining_args = args[1:]
    if remaining_args:
        potential_duration_td = parse_duration_to_timedelta(remaining_args[0])
        if potential_duration_td is not None:
            duration_arg = remaining_args[0]
            reason_list = remaining_args[1:]
        else:
            reason_list = remaining_args
    reason_str = " ".join(reason_list) if reason_list else None
    return target_arg, duration_arg, reason_str

def parse_promote_args(args: list[str]) -> tuple[str | None, str | None]:
    target_arg: str | None = None
    custom_title_full: str | None = None

    if not args:
        return None, None
    
    target_arg = args[0]
    if len(args) > 1:
        custom_title_full = " ".join(args[1:])
        
    return target_arg, custom_title_full

async def send_safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """
    Tries to reply to the message. If the original message is deleted,
    it sends a new message to the chat instead of crashing.
    """
    try:
        await update.message.reply_text(text=text, **kwargs)
    except telegram.error.BadRequest as e:
        if "Message to be replied not found" in str(e):
            logger.warning("Original message not found for reply. Sending as a new message.")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
        else:
            raise e

async def _can_user_perform_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    permission: str,
    failure_message: str,
    allow_bot_privileged_override: bool = True
) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if allow_bot_privileged_override and is_privileged_user(user.id):
        return True

    try:
        actor_chat_member = await context.bot.get_chat_member(chat.id, user.id)
        
        if actor_chat_member.status == "creator":
            return True

        if actor_chat_member.status == "administrator" and getattr(actor_chat_member, permission, False):
            return True
            
    except TelegramError as e:
        logger.error(f"Error checking permissions for {user.id} in chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify your permissions due to an API error.")
        return False

    await send_safe_reply(update, context, text=failure_message)
    return False

# --- Utility Functions ---
def get_readable_time_delta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0: 
        return "0s"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days > 0: 
        parts.append(f"{days}d")
    if hours > 0: 
        parts.append(f"{hours}h")
    if minutes > 0: 
        parts.append(f"{minutes}m")
    if not parts and seconds >= 0 : 
        parts.append(f"{seconds}s")
    elif seconds > 0: 
        parts.append(f"{seconds}s")
    return ", ".join(parts) if parts else "0s"

def add_to_gban(user_id: int, banned_by_id: int, reason: str | None) -> bool:
    reason = reason or "No reason provided."
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT OR REPLACE INTO global_bans (user_id, reason, banned_by_id, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, reason, banned_by_id, timestamp)
            )
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"SQLite error adding user {user_id} to gban list: {e}")
        return False

def remove_from_gban(user_id: int) -> bool:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM global_bans WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"SQLite error removing user {user_id} from gban list: {e}")
        return False

def get_gban_reason(user_id: int) -> str | None:
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT reason FROM global_bans WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    except sqlite3.Error as e:
        logger.error(f"SQLite error checking gban status for user {user_id}: {e}")
        return None

def add_chat_to_db(chat_id: int, chat_title: str):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT OR REPLACE INTO bot_chats (chat_id, chat_title, added_at) VALUES (?, ?, ?)",
                (chat_id, chat_title, timestamp)
            )
    except sqlite3.Error as e:
        logger.error(f"Failed to add chat {chat_id} to DB: {e}")

def remove_chat_from_db(chat_id: int):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bot_chats WHERE chat_id = ?", (chat_id,))
    except sqlite3.Error as e:
        logger.error(f"Failed to remove chat {chat_id} from DB: {e}")

def is_gban_enforced(chat_id: int) -> bool:
    """Checks if gban enforcement is enabled for a specific chat."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            res = cursor.execute(
                "SELECT enforce_gban FROM bot_chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if res is None:
                return True 
            return bool(res[0])
    except sqlite3.Error as e:
        logger.error(f"Could not check gban enforcement status for chat {chat_id}: {e}")
        return True

# --- Helper Functions (Check Targets, Get GIF) ---
async def check_target_protection(target_user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if target_user_id == OWNER_ID: return True
    if target_user_id == context.bot.id: return True
    return False

async def check_username_protection(target_mention: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, bool]:
    is_protected = False; is_owner_match = False; bot_username = context.bot.username
    if bot_username and target_mention.lower() == f"@{bot_username.lower()}": is_protected = True
    elif OWNER_ID:
        owner_username = None
        try: owner_chat = await context.bot.get_chat(OWNER_ID); owner_username = owner_chat.username
        except Exception as e: logger.warning(f"Could not fetch owner username for protection check: {e}")
        if owner_username and target_mention.lower() == f"@{owner_username.lower()}": is_protected = True; is_owner_match = True
    return is_protected, is_owner_match

async def get_themed_gif(context: ContextTypes.DEFAULT_TYPE, search_terms: list[str]) -> str | None:
    if not TENOR_API_KEY: return None
    if not search_terms: logger.warning("No search terms for get_themed_gif."); return None
    search_term = random.choice(search_terms); logger.info(f"Searching Tenor: '{search_term}'")
    url = "https://tenor.googleapis.com/v2/search"; params = { "q": search_term, "key": TENOR_API_KEY, "client_key": "my_cat_bot_project_py", "limit": 15, "media_filter": "gif", "contentfilter": "medium", "random": "true" }
    try:
        response = requests.get(url, params=params, timeout=7)
        if response.status_code != 200:
            logger.error(f"Tenor API failed for '{search_term}', status: {response.status_code}")
            try: error_content = response.json(); logger.error(f"Tenor error content: {error_content}")
            except requests.exceptions.JSONDecodeError: logger.error(f"Tenor error response (non-JSON): {response.text[:500]}")
            return None
        data = response.json(); results = data.get("results")
        if results:
            selected_gif = random.choice(results); gif_url = selected_gif.get("media_formats", {}).get("gif", {}).get("url")
            if not gif_url: gif_url = selected_gif.get("media_formats", {}).get("tinygif", {}).get("url")
            if gif_url: logger.info(f"Found GIF URL: {gif_url}"); return gif_url
            else: logger.warning(f"Could not extract GIF URL from Tenor item for '{search_term}'.")
        else: logger.warning(f"No results on Tenor for '{search_term}'."); logger.debug(f"Tenor response (no results): {data}")
    except requests.exceptions.Timeout: logger.error(f"Timeout fetching GIF from Tenor for '{search_term}'.")
    except requests.exceptions.RequestException as e: logger.error(f"Network/Request error fetching GIF from Tenor: {e}")
    except Exception as e: logger.error(f"Unexpected error in get_themed_gif for '{search_term}': {e}", exc_info=True)
    return None

# --- Command Handlers ---
HELP_TEXT = """
<b>Meeeow! 🐾 Here are the commands you can use:</b>

<b>Bot Commands:</b>
/start - Shows the welcome message. ✨
/help - Shows this help message. ❓
/github - Get the link to my source code! 💻
/owner - Info about my designated human! ❤️
/sudocmds - List sudo commands. 👷‍♂️

<b>User Commands:</b>
/info &lt;ID/@user/reply&gt; - Get info about a user. 👤
/chatstat - Get basic stats about the current chat. 📈
/kickme - Kick yourself from chat. 👋
/listadmins - Show the list of administrators in the current chat. 📃
<i>Note: /admins works too</i>

<b>Management Commands:</b>
/ban &lt;ID/@user/reply&gt; [Time] [Reason] - Ban user in chat. ⛔️
/unban &lt;ID/@user/reply&gt; - Unban user in chat. 🔓
/mute &lt;ID/@user/reply&gt; [Time] [Reason] - Mute user in chat. 🚫
/unmute &lt;ID/@user/reply&gt; - Unmute user in chat. 🎙 
<i>Note: [Time] is optional</i>
/kick &lt;ID/@user/reply&gt; [Reason] - Kick user from chat. ⚠️
/promote &lt;ID/@user/reply&gt; [Title] - Promote a user to administrator. 👷‍♂️
<i>Note: [Title] is optional</i>
/demote &lt;ID/@user/reply&gt; - Demote an administrator to a regular member. 🙍‍♂️
/pin &lt;loud|notify&gt; - Pin the replied message. 📌
/unpin - Unpin the replied message. 📍
/purge &lt;silent&gt; - Deletes user messages up to the replied-to message. 🗑
/report &lt;ID/@user/reply&gt; [reason] - Report user. ⚠️

<b>Security:</b>
/enforcegban &lt;yes/no&gt; - Enable/disable Global Ban enforcement in this chat. 🛡️
<i>(Chat Creator only)</i>

<b>4FUN Commands:</b>
/gif - Get a random cat GIF! 🖼️
/photo - Get a random cat photo! 📷
/meow - Get a random cat sound or phrase. 🔊
/nap - What's on a cat's mind during naptime? 😴
/play - Random playful cat actions. 🧶
/treat - Demand treats! 🎁
/zoomies - Witness sudden bursts of cat energy! 💥
/judge - Get judged by a superior feline. 🧐
/fed - I just ate, thank you! 😋
/attack &lt;@user/reply&gt; - Launch a playful attack! ⚔️
/kill &lt;@user/reply&gt; - Metaphorically eliminate someone! 💀
/punch &lt;@user/reply&gt; - Deliver a textual punch! 👊
/slap &lt;@user/reply&gt; - Administer a swift slap! 👋
/bite &lt;@user/reply&gt; - Take a playful bite! 😬
/hug &lt;@user/reply&gt; - Offer a comforting hug! 🤗
"""

SUDO_COMMANDS_TEXT = """
<b>Sudo Commands:</b>
/status - Show bot status.
/cinfo [Optional chat ID] - Get detailed info about the current or specified chat.
/say [Optional chat ID] [Your text] - Send message as bot.
/blist &lt;ID/@user/reply&gt; [Reason] - Add user to blacklist.
/unblist &lt;ID/@user/reply&gt; - Remove user from blacklist.
/gban &lt;ID/@user/reply&gt; [Reason] - Ban user globally.
/ungban &lt;ID/@user/reply&gt; - Unban user globally.

<i>Note: Commands: /ban, /unban, /mute, /unmute, /kick, /pin, /unpin, /purge; can be used by sudo users even if they are not chat creator/administrator.</i>
"""

OWNER_COMMANDS_TEXT = """
<b>Owner Commands:</b>
/leave [Optional chat ID] - Make the bot leave a chat.
/speedtest - Perform an internet speed test.
/listsudo - List all users with sudo privileges.
/addsudo &lt;ID/@user/reply&gt; - Grants SUDO (bot admin) permissions to a user.
/delsudo &lt;ID/@user/reply&gt; - Revokes SUDO (bot admin) permissions from a user.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    welcome_message = f"Meow {user.mention_html()}! I'm the Meow Bot. 🐾\nUse /help to see available commands!"
    
    if context.args:
        if context.args[0] == 'help':
            await update.message.reply_html(HELP_TEXT, disable_web_page_preview=True)
            return
        
        if context.args[0] == 'sudocmds':
            if not is_privileged_user(user.id):
                return

            final_sudo_help = SUDO_COMMANDS_TEXT
            if user.id == OWNER_ID:
                final_sudo_help += "\n" + OWNER_COMMANDS_TEXT
            
            await update.message.reply_html(final_sudo_help, disable_web_page_preview=True)
            return
            
    await update.message.reply_html(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_html(HELP_TEXT, disable_web_page_preview=True)
        return

    bot_username = context.bot.username
    deep_link_url = f"https://t.me/{bot_username}?start=help"
    
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text="📬 Get Help (PM)", url=deep_link_url)]
        ]
    )
    
    message_text = "Meeeow! 🐾 I've sent the help message to your private chat. Please click the button below to see it."
    
    await send_safe_reply(update, context, text=message_text, reply_markup=keyboard)

async def github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    github_link = "https://github.com/R0Xofficial/MyCatbot"
    await update.message.reply_text(f"Meeeow! I'm open source! 💻 Here is my code: {github_link}", disable_web_page_preview=True)

async def owner_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if OWNER_ID:
        owner_mention = f"<code>{OWNER_ID}</code>"; owner_name = "My Esteemed Human"
        try: owner_chat = await context.bot.get_chat(OWNER_ID); owner_mention = owner_chat.mention_html(); owner_name = owner_chat.full_name or owner_chat.username or owner_name
        except TelegramError as e: logger.warning(f"Could not fetch owner info ({OWNER_ID}): {e}")
        except Exception as e: logger.warning(f"Unexpected error fetching owner info: {e}")
        message = (f"My designated human is: 👤 <b>{html.escape(owner_name)}</b> ({owner_mention}) ❤️")
        await update.message.reply_html(message)
    else: await update.message.reply_text("Meow? Owner info not configured! 😿")

# --- User Info Command ---
def format_entity_info(entity: Chat | User,
                       chat_member_status_str: str | None = None,
                       is_target_owner: bool = False,
                       is_target_sudo: bool = False,
                       blacklist_reason_str: str | None = None,
                       gban_reason_str: str | None = None,
                       current_chat_id_for_status: int | None = None,
                       bot_context: ContextTypes.DEFAULT_TYPE | None = None
                       ) -> str:
    
    info_lines = []
    entity_id = entity.id
    is_user_type = isinstance(entity, User) 
    entity_chat_type = getattr(entity, 'type', None) if not is_user_type else ChatType.PRIVATE

    if is_user_type or entity_chat_type == ChatType.PRIVATE:
        user = entity
        info_lines.append(f"👤 <b>User Information:</b>\n")        
        first_name = html.escape(getattr(user, 'first_name', "N/A") or "N/A")
        last_name = html.escape(getattr(user, 'last_name', "") or "")
        username_display = f"@{html.escape(user.username)}" if user.username else "N/A"
        permalink_user_url = f"tg://user?id={user.id}"
        permalink_text_display = "Link" 
        permalink_html_user = f"<a href=\"{permalink_user_url}\">{permalink_text_display}</a>"
        is_bot_val = getattr(user, 'is_bot', False)
        is_bot_str = "Yes" if is_bot_val else "No"
        language_code_val = getattr(user, 'language_code', "N/A")

        info_lines.extend([
            f"<b>• ID:</b> <code>{user.id}</code>",
            f"<b>• First Name:</b> {first_name}",
        ])
        if getattr(user, 'last_name', None):
            info_lines.append(f"<b>• Last Name:</b> {last_name}")
        
        info_lines.extend([
            f"<b>• Username:</b> {username_display}",
            f"<b>• Permalink:</b> {permalink_html_user}",
            f"<b>• Is Bot:</b> <code>{is_bot_str}</code>",
            f"<b>• Language Code:</b> <code>{language_code_val if language_code_val else 'N/A'}</code>\n"
        ])

        if chat_member_status_str and current_chat_id_for_status != user.id and current_chat_id_for_status is not None:
            display_status = ""
            if chat_member_status_str == "creator": display_status = "<code>Creator</code>"
            elif chat_member_status_str == "administrator": display_status = "<code>Admin</code>"
            elif chat_member_status_str == "member": display_status = "<code>Member</code>"
            elif chat_member_status_str == "left": display_status = "<code>Not in chat</code>"
            elif chat_member_status_str == "kicked": display_status = "<code>Banned</code>"
            elif chat_member_status_str == "restricted": display_status = "<code>Muted</code>"
            elif chat_member_status_str == "not_a_member": display_status = "<code>Not in chat</code>"
            else: display_status = f"<code>{html.escape(chat_member_status_str.replace('_', ' ').capitalize())}</code>"
            info_lines.append(f"<b>• Status:</b> {display_status}\n")

        if is_target_owner:
            info_lines.append(f"<b>• Bot Owner:</b> <code>Yes</code>")
        elif is_target_sudo:
            info_lines.append(f"<b>• Bot Sudo:</b> <code>Yes</code>")
            
        if blacklist_reason_str is not None:
            info_lines.append(f"<b>• Blacklisted:</b> <code>Yes</code>")
            info_lines.append(f"<b>Reason:</b> {html.escape(blacklist_reason_str)}")
        else:
            info_lines.append(f"<b>• Blacklisted:</b> <code>No</code>")

        if gban_reason_str is not None:
            info_lines.append(f"<b>• Globally Banned:</b> <code>Yes</code>")
            info_lines.append(f"<b>Reason:</b> {html.escape(gban_reason_str)}")
        else:
            info_lines.append(f"<b>• Globally Banned:</b> <code>No</code>")

    elif entity_chat_type == ChatType.CHANNEL:
        channel = entity
        info_lines.append(f"📢 <b>Channel info:</b>\n")
        info_lines.append(f"<b>• ID:</b> <code>{channel.id}</code>")
        channel_name_to_display = channel.title or getattr(channel, 'first_name', None) or f"Channel {channel.id}"
        info_lines.append(f"<b>• Title:</b> {html.escape(channel_name_to_display)}")
        
        if channel.username:
            info_lines.append(f"<b>• Username:</b> @{html.escape(channel.username)}")
            permalink_channel_url = f"https://t.me/{html.escape(channel.username)}"
            permalink_text_display = "Link"
            permalink_channel_html = f"<a href=\"{permalink_channel_url}\">{permalink_text_display}</a>"
            info_lines.append(f"<b>• Permalink:</b> {permalink_channel_html}")
        else:
            info_lines.append(f"<b>• Permalink:</b> Private channel (no public link)")
        
    elif entity_chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        chat = entity
        title = html.escape(chat.title or f"{entity_chat_type.capitalize()} {chat.id}")
        info_lines.append(f"ℹ️ Entity <code>{chat.id}</code> is a <b>{entity_chat_type.capitalize()}</b> ({title}).")
        info_lines.append(f"This command primarily provides detailed info for Users and Channels.")

    else:
        info_lines.append(f"❓ <b>Unknown or Unsupported Entity Type:</b> ID <code>{html.escape(str(entity_id))}</code>")
        if entity_chat_type:
            info_lines.append(f"  • Type detected: {entity_chat_type.capitalize()}")

    return "\n".join(info_lines)

async def entity_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_entity_obj: Chat | User | None = None
    initial_user_obj_from_update: User | None = None
    target_chat_obj_from_api: Chat | None = None
    initial_entity_id_for_refresh: int | None = None
    
    current_chat_id = update.effective_chat.id
    command_caller_id = update.effective_user.id

    if update.effective_user:
        update_user_in_db(update.effective_user)

    if update.message.reply_to_message:
        if update.message.reply_to_message.sender_chat:
            target_chat_obj_from_api = update.message.reply_to_message.sender_chat
            initial_entity_id_for_refresh = target_chat_obj_from_api.id
            logger.info(f"/info target is replied sender_chat: ID={target_chat_obj_from_api.id}")
        else:
            initial_user_obj_from_update = update.message.reply_to_message.from_user
            if initial_user_obj_from_update:
                update_user_in_db(initial_user_obj_from_update)
                initial_entity_id_for_refresh = initial_user_obj_from_update.id
                logger.info(f"/info target is replied user: {initial_user_obj_from_update.id}")
    elif context.args:
        target_input_str = context.args[0]
        logger.info(f"/info target is argument: {target_input_str}")
        
        resolved_user_from_db: User | None = None
        if target_input_str.startswith("@"):
            username_to_find = target_input_str[1:]
            resolved_user_from_db = get_user_from_db_by_username(username_to_find)
            if resolved_user_from_db:
                initial_user_obj_from_update = resolved_user_from_db
                initial_entity_id_for_refresh = resolved_user_from_db.id
            else:
                logger.info(f"Trying find entity @{username_to_find} by using Telegram API.")
                try:
                    target_chat_obj_from_api = await context.bot.get_chat(target_input_str)
                    initial_entity_id_for_refresh = target_chat_obj_from_api.id
                    if target_chat_obj_from_api.type == ChatType.PRIVATE:
                         user_to_save = User(id=target_chat_obj_from_api.id, first_name=target_chat_obj_from_api.first_name or "", is_bot=getattr(target_chat_obj_from_api, 'is_bot', False), username=target_chat_obj_from_api.username, last_name=target_chat_obj_from_api.last_name, language_code=getattr(target_chat_obj_from_api, 'language_code', None))
                         update_user_in_db(user_to_save)
                         initial_user_obj_from_update = user_to_save
                except TelegramError as e:
                    logger.error(f"Telegram API error for @ '{target_input_str}': {e}")
                    await update.message.reply_text(f"😿 Mrow! I couldn't find '{html.escape(target_input_str)}'.")
                    return
                except Exception as e:
                    logger.error(f"Unexpected error processing @ '{target_input_str}': {e}", exc_info=True)
                    await update.message.reply_text(f"💥 An unexpected error occurred with '{html.escape(target_input_str)}'.")
                    return
        else:
            try:
                target_id = int(target_input_str)
                initial_entity_id_for_refresh = target_id
                target_chat_obj_from_api = await context.bot.get_chat(target_id)
                if target_chat_obj_from_api.type == ChatType.PRIVATE:
                    user_to_save = User(id=target_chat_obj_from_api.id, first_name=target_chat_obj_from_api.first_name or "", is_bot=getattr(target_chat_obj_from_api, 'is_bot', False), username=target_chat_obj_from_api.username, last_name=target_chat_obj_from_api.last_name, language_code=getattr(target_chat_obj_from_api, 'language_code', None))
                    update_user_in_db(user_to_save)
                    initial_user_obj_from_update = user_to_save
            except ValueError:
                await update.message.reply_text(f"Mrow? Invalid format: '{html.escape(target_input_str)}'.")
                return
            except TelegramError as e:
                logger.error(f"Error fetching chat/user info for ID '{target_input_str}': {e}")
                await update.message.reply_text(f"😿 Couldn't find or access info for ID '{html.escape(target_input_str)}': {e}")
                return
            except Exception as e:
                logger.error(f"Unexpected error processing ID '{target_input_str}': {e}", exc_info=True)
                await update.message.reply_text(f"💥 An unexpected error occurred processing ID '{html.escape(target_input_str)}'.")
                return
    else:
        initial_user_obj_from_update = update.effective_user
        if initial_user_obj_from_update:
            update_user_in_db(initial_user_obj_from_update)
            initial_entity_id_for_refresh = initial_user_obj_from_update.id
            logger.info(f"/info target is command sender: {initial_user_obj_from_update.id}")

    final_entity_to_display: Chat | User | None = None
    if initial_user_obj_from_update:
        final_entity_to_display = initial_user_obj_from_update
    elif target_chat_obj_from_api:
        final_entity_to_display = target_chat_obj_from_api

    if final_entity_to_display and initial_entity_id_for_refresh is not None:
        is_target_owner_flag = False
        is_target_sudo_flag = False
        member_status_in_current_chat_str: str | None = None
        blacklist_reason_str: str | None = None
        gban_reason_str: str | None = None

        try:
            fresh_data_chat_obj = await context.bot.get_chat(chat_id=initial_entity_id_for_refresh)
            
            if isinstance(final_entity_to_display, User) or fresh_data_chat_obj.type == ChatType.PRIVATE:
                current_is_bot = getattr(final_entity_to_display, 'is_bot', False)
                current_lang_code = getattr(final_entity_to_display, 'language_code', None)

                refreshed_user = User(
                    id=fresh_data_chat_obj.id,
                    first_name=fresh_data_chat_obj.first_name or getattr(final_entity_to_display, 'first_name', None) or "",
                    last_name=fresh_data_chat_obj.last_name or getattr(final_entity_to_display, 'last_name', None),
                    username=fresh_data_chat_obj.username or getattr(final_entity_to_display, 'username', None),
                    is_bot=getattr(fresh_data_chat_obj, 'is_bot', current_is_bot),
                    language_code=getattr(fresh_data_chat_obj, 'language_code', current_lang_code)
                )
                update_user_in_db(refreshed_user)
                final_entity_to_display = refreshed_user
                
                is_target_owner_flag = (OWNER_ID is not None and final_entity_to_display.id == OWNER_ID)
                if not is_target_owner_flag:
                     is_target_sudo_flag = is_sudo_user(final_entity_to_display.id)
                
                blacklist_reason_str = get_blacklist_reason(final_entity_to_display.id)
                gban_reason_str = get_gban_reason(final_entity_to_display.id)

                if current_chat_id != final_entity_to_display.id and update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                    try:
                        chat_member = await context.bot.get_chat_member(chat_id=current_chat_id, user_id=final_entity_to_display.id)
                        member_status_in_current_chat_str = chat_member.status
                    except TelegramError as e:
                        if "user not found" in str(e).lower(): member_status_in_current_chat_str = "not_a_member"
                        else: logger.warning(f"Could not get status for {final_entity_to_display.id}: {e}")
                    except Exception as e: logger.error(f"Unexpected error getting status: {e}", exc_info=True)
            else:
                final_entity_to_display = fresh_data_chat_obj

            logger.info(f"Loaded entity data for {final_entity_to_display.id} from API.")
        except TelegramError as e:
            logger.warning(f"Could not load entity data for {initial_entity_id_for_refresh} from API: {e}. Using initially identified data.")
        except Exception as e:
            logger.error(f"Unexpected error loading entity data for {initial_entity_id_for_refresh}: {e}", exc_info=True)

        if final_entity_to_display:
            info_message = format_entity_info(
                final_entity_to_display, 
                member_status_in_current_chat_str, 
                is_target_owner_flag, 
                is_target_sudo_flag, 
                blacklist_reason_str, 
                gban_reason_str,
                current_chat_id, 
                context
            )
            try:
                await update.message.reply_html(info_message)
                logger.info(f"Sent /info response for entity {final_entity_to_display.id} in chat {update.effective_chat.id}")
            except TelegramError as e_reply:
                logger.error(f"Failed to send /info reply in chat {update.effective_chat.id}: {e_reply}")
            except Exception as e_reply_other:
                logger.error(f"Unexpected error sending /info reply: {e_reply_other}", exc_info=True)
        else:
            await update.message.reply_text("Mrow? Could not obtain entity details to display.")
    else:
        await update.message.reply_text("Mrow? Couldn't determine what to get info for.")

async def list_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        await update.message.reply_text("Meeeow! I can only list admins for groups, supergroups, or channels.")
        return

    try:
        administrators = await context.bot.get_chat_administrators(chat_id=chat.id)
    except TelegramError as e:
        logger.error(f"Failed to get admin list for chat {chat.id} ('{chat.title}'): {e}")
        await update.message.reply_text(f"Mrow! Couldn't fetch the admin list for this chat. Error: {html.escape(str(e))}")
        return
    except Exception as e:
        logger.error(f"Unexpected error getting admin list for chat {chat.id}: {e}", exc_info=True)
        await update.message.reply_text("Mrow! An unexpected error occurred while fetching the admin list.")
        return

    if not administrators:
        await update.message.reply_text("Meeeow! It seems there are no administrators in this chat (or I can't see them).")
        return

    chat_title_display = html.escape(chat.title or chat.first_name or f"Chat ID {chat.id}")
    response_lines = [f"<b>🛡️ Admin list in {chat_title_display}:</b>\n"]

    creator_line: str | None = None

    for admin_member in administrators:
        admin_user = admin_member.user
        
        user_display_name = ""
        if admin_user.username:
            user_display_name = f"<a href=\"tg://user?id={admin_user.id}\">@{html.escape(admin_user.username)}</a>"
        elif admin_user.full_name:
            user_display_name = f"<a href=\"tg://user?id={admin_user.id}\">{html.escape(admin_user.full_name)}</a>"
        elif admin_user.first_name:
            user_display_name = f"<a href=\"tg://user?id={admin_user.id}\">{html.escape(admin_user.first_name)}</a>"
        else:
            user_display_name = f"<a href=\"tg://user?id={admin_user.id}\">User {admin_user.id}</a>"

        admin_info_line = f"• {user_display_name}"

        custom_title = getattr(admin_member, 'custom_title', None)
        is_anonymous = getattr(admin_member, 'is_anonymous', False)

        if is_anonymous:
            admin_info_line += " <i>(Anonymous Admin)</i>"
        
        if custom_title:
            admin_info_line += f" (<code>{html.escape(custom_title)}</code>)"
        
        if admin_member.status == "creator":
            admin_info_line += " 👑"
            creator_line = admin_info_line
        else:
            response_lines.append(admin_info_line)

    if creator_line:
        response_lines.insert(1, creator_line)

    message_text = "\n".join(response_lines)
    
    if len(message_text) > 4090:
        logger.info(f"Admin list for chat {chat.id} is too long, attempting to send as a file.")
        try:
            import io
            file_content = "\n".join(response_lines).replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
            file_content = file_content.replace("</a>", "").replace("✨", "").replace("🛡️", "")
            file_content = re.sub(r'<a href="[^"]*">', '', file_content)

            bio = io.BytesIO(file_content.encode('utf-8'))
            bio.name = f"admin_list_{chat.id}.txt"
            await update.message.reply_document(document=bio, caption=f"🛡️ Admin list for {chat_title_display} is too long to display directly. See the attached file.")
        except Exception as e_file:
            logger.error(f"Failed to send long admin list as file: {e_file}")
            await update.message.reply_text("Mrow! The admin list is too long to display, and I couldn't send it as a file. 😿")
    else:
        await update.message.reply_html(message_text, disable_web_page_preview=True)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_who_bans = update.effective_user

    if chat.type == ChatType.PRIVATE:
        await send_safe_reply(update, context, text="Mrow? Cannot ban users in a private chat.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to ban users in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /ban for chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_restrict_members', "Meeeow! You need to be an admin with rights to ban users in this chat."):
        return

    target_user: User | None = None
    duration_str: str | None = None
    reason_list: list[str] = []
    reason: str = "No reason provided."
    args_to_parse_for_duration_reason = list(context.args)

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        target_arg = context.args[0]
        args_to_parse_for_duration_reason = list(context.args[1:])
        if target_arg.startswith("@"):
            username_to_find = target_arg[1:]
            target_user = get_user_from_db_by_username(username_to_find)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_arg)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or "",is_bot=getattr(chat_info, 'is_bot', False),username=chat_info.username, last_name=chat_info.last_name)
                except: pass
            if not target_user: await send_safe_reply(update, context, text=f"User @{html.escape(username_to_find)} not found."); return
        else:
            try:
                target_id = int(target_arg)
                try:
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or f"User {target_id}", is_bot=getattr(chat_info, 'is_bot',False), username=chat_info.username, last_name=chat_info.last_name)
                    else: await send_safe_reply(update, context, text="Target ID does not seem to be a user."); return
                except: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError: await send_safe_reply(update, context, text="Invalid user ID."); return
    else:
        await send_safe_reply(update, context, text="Usage: /ban <ID/@username/reply> [duration (e.g., 1h, 30m)] [reason]")
        return

    if args_to_parse_for_duration_reason:
        potential_duration_td = parse_duration_to_timedelta(args_to_parse_for_duration_reason[0])
        if potential_duration_td:
            duration_str = args_to_parse_for_duration_reason[0]
            if len(args_to_parse_for_duration_reason) > 1: reason_list = args_to_parse_for_duration_reason[1:]
        else:
            reason_list = args_to_parse_for_duration_reason
        if reason_list: reason = " ".join(reason_list)

    if not target_user: await send_safe_reply(update, context, text="Could not identify user to ban."); return
    if not isinstance(target_user, User): await send_safe_reply(update, context, text="Ban can only be applied to users."); return
    if target_user.id == context.bot.id: await send_safe_reply(update, context, text="I can't ban myself!"); return
    if target_user.id == user_who_bans.id: await send_safe_reply(update, context, text="Mrow? You can't ban yourself."); return

    try:
        target_chat_member = await context.bot.get_chat_member(chat.id, target_user.id)
        if target_chat_member.status == "creator":
            await send_safe_reply(update, context, text="Meeeow! The chat Creator is sacred and cannot be touched by this bot! 😼👑")
            return
        if target_chat_member.status == "administrator":
            actor_chat_member = await context.bot.get_chat_member(chat.id, user_who_bans.id)
            if not (actor_chat_member.status == "creator" or user_who_bans.id == OWNER_ID):
                await send_safe_reply(update, context, text="Meeeow! Only the chat Creator or the Bot Owner can ban other administrators.")
                return
    except TelegramError as e:
        if "user not found" in str(e).lower(): logger.info(f"Target user {target_user.id} for /ban not found in chat {chat.id}.")
        else: logger.warning(f"Could not get target's chat member status for /ban: {e}")

    duration_td = parse_duration_to_timedelta(duration_str)
    until_date_for_api: datetime | int | None = None
    time_str_display = "permanently"

    if duration_td:
        until_date_dt_aware_utc = datetime.now(timezone.utc) + duration_td
        until_date_for_api = until_date_dt_aware_utc
        time_str_display = f"for {duration_str}"

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_user.id, until_date=until_date_for_api)
        user_display_name = target_user.mention_html() if target_user.username else html.escape(target_user.first_name or str(target_user.id))
        response_lines = ["Meow! User Banned:"]
        response_lines.append(f"<b>• User:</b> {user_display_name} (<code>{target_user.id}</code>)")
        response_lines.append(f"<b>• Reason:</b> {html.escape(reason)}")
        if duration_str and until_date_for_api and isinstance(until_date_for_api, datetime):
            response_lines.append(f"<b>• Duration:</b> <code>{time_str_display.replace('for ', '')}</code> (until <code>{until_date_for_api.strftime('%Y-%m-%d %H:%M:%S %Z')}</code>)")
        else:
            response_lines.append(f"<b>• Duration:</b> <code>Permanent</code>")
        await send_safe_reply(update, context, text="\n".join(response_lines), parse_mode=ParseMode.HTML)
    except TelegramError as e: await send_safe_reply(update, context, text=f"Failed to ban user: {html.escape(str(e))}")
    except Exception as e: logger.error(f"Unexpected error in /ban: {e}", exc_info=True); await send_safe_reply(update, context, text="An unexpected error occurred.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat

    if chat.type == ChatType.PRIVATE:
        await send_safe_reply(update, context, text="Mrow? Cannot unban users in a private chat.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to unban users in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /unban for chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_restrict_members', "Meeeow! You need to be an admin with rights to unban users in this chat."):
        return

    target_user: User | None = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        target_arg = context.args[0]
        if target_arg.startswith("@"):
            username_to_find = target_arg[1:]
            target_user = get_user_from_db_by_username(username_to_find)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_arg)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or "",is_bot=getattr(chat_info, 'is_bot', False),username=chat_info.username, last_name=chat_info.last_name)
                except: pass
            if not target_user: await send_safe_reply(update, context, text=f"User @{html.escape(username_to_find)} not found."); return
        else:
            try:
                target_id = int(target_arg)
                try:
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or f"User {target_id}", is_bot=getattr(chat_info, 'is_bot',False), username=chat_info.username, last_name=chat_info.last_name)
                    else: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
                except: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError: await send_safe_reply(update, context, text="Invalid user ID."); return
    else:
        await send_safe_reply(update, context, text="Usage: /unban <ID/@username/reply>")
        return

    if not target_user: await send_safe_reply(update, context, text="Could not identify user to unban."); return
    if not isinstance(target_user, User): await send_safe_reply(update, context, text="Unban can only be applied to users."); return

    try:
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=target_user.id, only_if_banned=True)
        user_display_name = target_user.mention_html() if target_user.username else html.escape(target_user.first_name or str(target_user.id))
        response_lines = ["Meow! User Unbanned:", f"<b>• User:</b> {user_display_name} (<code>{target_user.id}</code>)"]
        await send_safe_reply(update, context, text="\n".join(response_lines), parse_mode=ParseMode.HTML)
    except TelegramError as e: await send_safe_reply(update, context, text=f"Failed to unban user: {html.escape(str(e))}")
    except Exception as e: logger.error(f"Unexpected error in /unban: {e}", exc_info=True); await send_safe_reply(update, context, text="An unexpected error occurred.")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_who_mutes = update.effective_user

    if chat.type == ChatType.PRIVATE:
        await send_safe_reply(update, context, text="Mrow? Cannot mute users in a private chat.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to restrict users in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /mute for chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_restrict_members', "Meeeow! You need to be an admin with rights to restrict users in this chat."):
        return

    target_user: User | None = None
    duration_str: str | None = None
    reason_list: list[str] = []
    reason: str = "No reason provided."
    args_to_parse_for_duration_reason = list(context.args)

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        target_arg = context.args[0]
        args_to_parse_for_duration_reason = list(context.args[1:])
        if target_arg.startswith("@"):
            username_to_find = target_arg[1:]
            target_user = get_user_from_db_by_username(username_to_find)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_arg)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or "",is_bot=getattr(chat_info, 'is_bot',False),username=chat_info.username, last_name=chat_info.last_name)
                except: pass
            if not target_user: await send_safe_reply(update, context, text=f"User @{html.escape(username_to_find)} not found."); return
        else:
            try:
                target_id = int(target_arg)
                try:
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or f"User {target_id}", is_bot=getattr(chat_info, 'is_bot',False), username=chat_info.username, last_name=chat_info.last_name)
                    else: await send_safe_reply(update, context, text="Target ID does not seem to be a user."); return
                except: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError: await send_safe_reply(update, context, text="Invalid user ID."); return
    else:
        await send_safe_reply(update, context, text="Usage: /mute <ID/@username/reply> [duration] [reason]")
        return

    if args_to_parse_for_duration_reason:
        potential_duration_td = parse_duration_to_timedelta(args_to_parse_for_duration_reason[0])
        if potential_duration_td:
            duration_str = args_to_parse_for_duration_reason[0]
            if len(args_to_parse_for_duration_reason) > 1: reason_list = args_to_parse_for_duration_reason[1:]
        else:
            reason_list = args_to_parse_for_duration_reason
        if reason_list: reason = " ".join(reason_list)

    if not target_user: await send_safe_reply(update, context, text="Could not identify user to mute."); return
    if not isinstance(target_user, User): await send_safe_reply(update, context, text="Mute can only be applied to users."); return
    if target_user.id == context.bot.id: await send_safe_reply(update, context, text="I can't mute myself!"); return
    if target_user.id == user_who_mutes.id: await send_safe_reply(update, context, text="Mrow? You can't mute yourself."); return

    try:
        target_chat_member = await context.bot.get_chat_member(chat.id, target_user.id)
        if target_chat_member.status == "creator":
            await send_safe_reply(update, context, text="Meeeow! The chat Creator is sacred and cannot be muted by this bot! 😼👑")
            return
        if target_chat_member.status == "administrator":
            actor_chat_member = await context.bot.get_chat_member(chat.id, user_who_mutes.id)
            if not (actor_chat_member.status == "creator" or user_who_mutes.id == OWNER_ID):
                 await send_safe_reply(update, context, text="Meeeow! Only the chat Creator or the Bot Owner can mute other administrators.")
                 return
    except TelegramError as e:
        if "user not found" in str(e).lower():
            await send_safe_reply(update, context, text=f"User {target_user.mention_html()} is not in this chat, cannot be muted.", parse_mode=ParseMode.HTML)
            return
        logger.warning(f"Could not get target's chat member status for /mute: {e}")

    duration_td = parse_duration_to_timedelta(duration_str)
    permissions_to_set_for_mute = ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False)
    until_date_dt: datetime | None = None
    time_str_display = "permanently"

    if duration_td:
        until_date_dt = datetime.now(timezone.utc) + duration_td
        time_str_display = f"for {duration_str}"

    try:
        await context.bot.restrict_chat_member(chat_id=chat.id, user_id=target_user.id, permissions=permissions_to_set_for_mute, until_date=until_date_dt, use_independent_chat_permissions=True)
        user_display_name = target_user.mention_html() if target_user.username else html.escape(target_user.first_name or str(target_user.id))

        response_lines = ["Meow! User Muted:"]
        response_lines.append(f"<b>• User:</b> {user_display_name} (<code>{target_user.id}</code>)")
        response_lines.append(f"<b>• Reason:</b> {html.escape(reason)}")
        if duration_str and until_date_dt: response_lines.append(f"<b>• Duration:</b> <code>{time_str_display.replace('for ', '')}</code> (until <code>{until_date_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}</code>)")
        else: response_lines.append(f"<b>• Duration:</b> <code>Permanent</code>")
        await send_safe_reply(update, context, text="\n".join(response_lines), parse_mode=ParseMode.HTML)
    except TelegramError as e: await send_safe_reply(update, context, text=f"Failed to mute user: {html.escape(str(e))}")
    except Exception as e: logger.error(f"Unexpected error in /mute: {e}", exc_info=True); await send_safe_reply(update, context, text="An unexpected error occurred.")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat

    if chat.type == ChatType.PRIVATE:
        await send_safe_reply(update, context, text="Mrow? Cannot unmute users in a private chat.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to change user permissions in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /unmute for chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_restrict_members', "Meeeow! You need to be an admin with rights to change user permissions in this chat."):
        return

    target_user: User | None = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        target_arg = context.args[0]
        if target_arg.startswith("@"):
            username_to_find = target_arg[1:]
            target_user = get_user_from_db_by_username(username_to_find)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_arg)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or "",is_bot=getattr(chat_info, 'is_bot',False),username=chat_info.username, last_name=chat_info.last_name)
                except: pass
            if not target_user: await send_safe_reply(update, context, text=f"User @{html.escape(username_to_find)} not found."); return
        else:
            try:
                target_id = int(target_arg)
                try:
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or f"User {target_id}", is_bot=getattr(chat_info, 'is_bot',False), username=chat_info.username, last_name=chat_info.last_name)
                    else: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
                except: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError: await send_safe_reply(update, context, text="Invalid user ID."); return
    else:
        await send_safe_reply(update, context, text="Usage: /unmute <ID/@username/reply>")
        return

    if not target_user: await send_safe_reply(update, context, text="Could not identify user to unmute."); return
    if not isinstance(target_user, User): await send_safe_reply(update, context, text="Unmute can only be applied to users."); return

    permissions_to_restore = ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=None, can_invite_users=None, can_pin_messages=None, can_manage_topics=None
    )

    try:
        await context.bot.restrict_chat_member(chat_id=chat.id, user_id=target_user.id, permissions=permissions_to_restore, use_independent_chat_permissions=True)
        user_display_name = target_user.mention_html() if target_user.username else html.escape(target_user.first_name or str(target_user.id))
        response_lines = ["Meow! User Unmuted:", f"<b>• User:</b> {user_display_name} (<code>{target_user.id}</code>)"]
        await send_safe_reply(update, context, text="\n".join(response_lines), parse_mode=ParseMode.HTML)
    except TelegramError as e: await send_safe_reply(update, context, text=f"Failed to unmute user: {html.escape(str(e))}")
    except Exception as e: logger.error(f"Unexpected error in /unmute: {e}", exc_info=True); await send_safe_reply(update, context, text="An unexpected error occurred.")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_who_kicks = update.effective_user

    if chat.type == ChatType.PRIVATE:
        await send_safe_reply(update, context, text="Mrow? Cannot kick users from a private chat.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to kick users in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /kick for chat {chat.id}: {e}")
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_restrict_members', "Meeeow! You need to be an admin with rights to kick users in this chat."):
        return

    target_user: User | None = None
    reason_list: list[str] = []
    reason: str = "No reason provided."
    args_to_parse_for_reason = list(context.args)

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        if context.args: reason_list = list(context.args)
    elif context.args:
        target_arg = context.args[0]
        args_to_parse_for_reason = list(context.args[1:])
        if target_arg.startswith("@"):
            username_to_find = target_arg[1:]
            target_user = get_user_from_db_by_username(username_to_find)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_arg)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or "",is_bot=getattr(chat_info, 'is_bot', False),username=chat_info.username, last_name=chat_info.last_name)
                except: pass
            if not target_user: await send_safe_reply(update, context, text=f"User @{html.escape(username_to_find)} not found."); return
        else:
            try:
                target_id = int(target_arg)
                try:
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE: target_user = User(id=chat_info.id, first_name=chat_info.first_name or f"User {target_id}", is_bot=getattr(chat_info, 'is_bot',False), username=chat_info.username, last_name=chat_info.last_name)
                    else: await send_safe_reply(update, context, text="Target ID does not seem to be a user."); return
                except: target_user = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError: await send_safe_reply(update, context, text="Invalid user ID."); return
    else:
        await send_safe_reply(update, context, text="Usage: /kick <ID/@username/reply> [reason]")
        return

    if args_to_parse_for_reason: reason = " ".join(args_to_parse_for_reason)

    if not target_user: await send_safe_reply(update, context, text="Could not identify user to kick."); return
    if not isinstance(target_user, User): await send_safe_reply(update, context, text="Kick can only be applied to users."); return
    if target_user.id == context.bot.id: await send_safe_reply(update, context, text="I can't kick myself!"); return
    if target_user.id == user_who_kicks.id: await send_safe_reply(update, context, text="Mrow? You can't kick yourself."); return

    try:
        target_chat_member = await context.bot.get_chat_member(chat.id, target_user.id)
        if target_chat_member.status == "creator":
            await send_safe_reply(update, context, text="Meeeow! The chat Creator is sacred and cannot be kicked by this bot! 😼👑")
            return
    except TelegramError as e:
        if "user not found" in str(e).lower():
             await send_safe_reply(update, context, text=f"User {target_user.mention_html()} is not in this chat, cannot be kicked.", parse_mode=ParseMode.HTML)
             return
        logger.warning(f"Could not get target's chat member status for /kick: {e}")

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_user.id)
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=target_user.id, only_if_banned=True)

        user_display_name = target_user.mention_html() if target_user.username else html.escape(target_user.first_name or str(target_user.id))
        response_lines = ["Meow! User Kicked:", f"<b>• User:</b> {user_display_name} (<code>{target_user.id}</code>)", f"<b>• Reason:</b> {html.escape(reason)}"]
        await send_safe_reply(update, context, text="\n".join(response_lines), parse_mode=ParseMode.HTML)
    except TelegramError as e: await send_safe_reply(update, context, text=f"Failed to kick user: {html.escape(str(e))}")
    except Exception as e: logger.error(f"Unexpected error in /kick: {e}", exc_info=True); await send_safe_reply(update, context, text="An unexpected error occurred.")

async def kickme_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_to_kick = update.effective_user

    if not user_to_kick:
        return

    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text("Meeeow! You can't kick yourself from a private chat with me! Silly human. 😹")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_restrict_members', False)): # Porównanie ze stringiem
            await update.message.reply_text("Meeeow! I can't kick users here because I'm not an admin with ban/kick permissions. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /kickme for chat {chat.id}: {e}")
        await update.message.reply_text("Mrow? Couldn't verify my own permissions to perform this action.")
        return

    try:
        user_chat_member = await context.bot.get_chat_member(chat.id, user_to_kick.id)
        
        if user_chat_member.status == "creator":
            await update.message.reply_text("Meeeow! As the chat Creator, you have ultimate power here! If you wish to leave, you might need to use Telegram's native 'Leave group' option or transfer ownership. This command is for regular members. 😉")
            return
        if user_chat_member.status == "administrator":
            await update.message.reply_text("Meeeow! As a chat Administrator, you can't use /kickme. If you wish to leave, please use Telegram's 'Leave group' option or have another admin remove you. This helps prevent accidental self-remove! 🛡️")
            return
            
    except TelegramError as e:
        if "user not found" in str(e).lower():
            logger.warning(f"User {user_to_kick.id} not found in chat {chat.id} for /kickme, though they sent the command.")
            await update.message.reply_text("Mrow? It seems you're not in this chat anymore.")
            return
        else:
            logger.error(f"Error checking your status in this chat for /kickme: {e}")
            await update.message.reply_text("Mrow? Couldn't verify your status in this chat to perform /kickme.")
            return

    try:
        user_display_name = user_to_kick.mention_html() if user_to_kick.username else html.escape(user_to_kick.first_name or str(user_to_kick.id))
        
        await update.message.reply_text(f"Meeeow! Okay, {user_display_name}, as you wish! Initiating self-kick sequence... Bye bye! 👋", parse_mode=ParseMode.HTML)
        
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=user_to_kick.id)
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=user_to_kick.id, only_if_banned=True)
        
        logger.info(f"User {user_to_kick.id} ({user_display_name}) self-kicked from chat {chat.id} ('{chat.title}')")
        
    except TelegramError as e:
        logger.error(f"Failed to self-kick user {user_to_kick.id} from chat {chat.id}: {e}")
        await update.message.reply_text(f"Mrow? I tried to help you leave, but something went wrong: {html.escape(str(e))}")
    except Exception as e:
        logger.error(f"Unexpected error in /kickme for user {user_to_kick.id}: {e}", exc_info=True)
        await update.message.reply_text("Mrow? An unexpected error occurred while trying to process your /kickme request.")

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if not message: return

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("Mrow? Users can only be promoted in groups and supergroups.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_promote_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to promote members in this chat. 😿")
            return
    except TelegramError:
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(
        update, context, 'can_promote_members',
        "Meeeow! You need to be the chat creator or an admin with 'Promote Members' rights to use this command.",
        allow_bot_privileged_override=False
    ):
        return

    target_user: User | None = None
    provided_custom_title: str | None = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        if context.args: provided_custom_title = " ".join(context.args)
    elif context.args:
        target_arg, parsed_provided_title = parse_promote_args(list(context.args))
        if not target_arg:
            await message.reply_text("Usage: /promote <ID/@username/reply> [optional admin title]")
            return
        provided_custom_title = parsed_provided_title
        
        try:
            if target_arg.startswith("@"):
                chat_info = await context.bot.get_chat(target_arg)
            else:
                chat_info = await context.bot.get_chat(int(target_arg))
            
            if chat_info.type == 'private':
                 target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
            else:
                await message.reply_text("Promotion can only be applied to users.")
                return
        except (ValueError, TelegramError):
            await message.reply_text("Could not find that user.")
            return
    else:
        await message.reply_text("Usage: /promote <ID/@username/reply> [optional admin title]")
        return

    if not target_user: await message.reply_text("Could not identify user to promote."); return
    
    if target_user.id == context.bot.id:
        await message.reply_text("Mrow? I'm a bot, I can't promote myself. 🤖")
        return
        
    if target_user.is_bot: await message.reply_text("Meeeow! Bots are usually promoted with specific, limited rights. This command grants broad admin privileges, which might not be suitable for most bots. Please promote bots manually with care if needed."); return

    try:
        target_chat_member = await context.bot.get_chat_member(chat.id, target_user.id)
        user_display = target_user.mention_html()

        if target_chat_member.status == "creator":
            await message.reply_html(f"{user_display} is the chat Creator and already has ultimate power!")
            return

        if target_chat_member.status == "administrator":
            if target_chat_member.can_be_edited:
                if provided_custom_title:
                    title_to_set = provided_custom_title[:16]
                    try:
                        await context.bot.set_chat_administrator_custom_title(chat.id, target_user.id, title_to_set)
                        await message.reply_html(f"✅ User {user_display}'s title has been updated to '<i>{html.escape(title_to_set)}</i>'.")
                    except TelegramError as e:
                        await message.reply_html(f"❌ Failed to update title for {user_display}. Reason: {html.escape(str(e))}")
                else:
                    await message.reply_html(f"ℹ️ User {user_display} is already an admin (promoted by me). Provide a title to change it.")
            else:
                await message.reply_html(
                    f"ℹ️ User {user_display} is already an administrator, but I do not have sufficient rights to modify their title."
                )
            return

    except TelegramError as e:
        if "user not found" not in str(e).lower():
            logger.warning(f"Could not get target's chat member status for /promote: {e}")

    title_to_set = "Admin"
    if provided_custom_title:
        title_to_set = provided_custom_title[:16]

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id, user_id=target_user.id,
            can_manage_chat=True, can_delete_messages=True, can_manage_video_chats=True,
            can_restrict_members=True, can_change_info=True, can_invite_users=True,
            can_pin_messages=True, can_manage_topics=(chat.is_forum if hasattr(chat, 'is_forum') else None)
        )
        await context.bot.set_chat_administrator_custom_title(chat.id, target_user.id, title_to_set)
        
        user_display = target_user.mention_html()
        await message.reply_html(f"✅ User {user_display} has been promoted with the title '<i>{html.escape(title_to_set)}</i>'.")
    except TelegramError as e:
        await message.reply_text(f"Failed to promote user: {html.escape(str(e))}")

async def demote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if not message: return
    
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("Mrow? Users can only be demoted in groups and supergroups.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_promote_members', False)):
            await send_safe_reply(update, context, text="Meeeow! I need to be an admin with rights to manage admin privileges in this chat. 😿")
            return
    except TelegramError:
        await send_safe_reply(update, context, text="Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(
        update, context, 'can_promote_members',
        "Meeeow! You need to be the chat creator or an admin with 'Promote Members' rights to use this command.",
        allow_bot_privileged_override=False
    ):
        return
    
    target_user: User | None = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    elif context.args:
        target_arg = context.args[0]
        try:
            if target_arg.startswith("@"):
                chat_info = await context.bot.get_chat(target_arg)
            else:
                chat_info = await context.bot.get_chat(int(target_arg))
            
            if chat_info.type == 'private':
                 target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
            else:
                await message.reply_text("Demotion can only be applied to users.")
                return
        except (ValueError, TelegramError):
            await message.reply_text("Could not find that user.")
            return
    else:
        await message.reply_text("Usage: /demote <ID/@username/reply>")
        return

    if not target_user: await message.reply_text("Could not identify user to demote."); return
        
    if target_user.id == context.bot.id:
        await message.reply_text("I can't demote myself! That would be a logical paradox. 😼")
        return

    try:
        target_chat_member = await context.bot.get_chat_member(chat.id, target_user.id)
        user_display = target_user.mention_html()

        if target_chat_member.status == "creator":
            await message.reply_html(f"👑 The chat Creator cannot be demoted!"); return
        
        if target_chat_member.status != "administrator":
            await message.reply_html(f"ℹ️ User {user_display} is not an administrator."); return

        if not target_chat_member.can_be_edited:
            await message.reply_html(f"❌ I do not have sufficient rights to demote {user_display}. This usually means they were promoted by the Creator or by another admin.")
            return

        await context.bot.promote_chat_member(
            chat_id=chat.id, user_id=target_user.id,
            is_anonymous=False, can_manage_chat=False, can_delete_messages=False,
            can_manage_video_chats=False, can_restrict_members=False, can_promote_members=False,
            can_change_info=False, can_invite_users=False, can_pin_messages=False, can_manage_topics=False
        )
        await message.reply_html(f"✅ User {user_display} has been demoted to a regular member.")

    except TelegramError as e:
        if "user not found" in str(e).lower():
            await message.reply_text("User not found in this chat.")
        else:
            logger.error(f"Error during demotion: {e}")
            await message.reply_text(f"Failed to demote user. Reason: {html.escape(str(e))}")
            
async def pin_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_who_pins = update.effective_user
    message_to_pin = update.message.reply_to_message

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        await update.message.reply_text("Mrow? Messages can only be pinned in groups, supergroups, or channels.")
        return

    if not message_to_pin:
        await update.message.reply_text("Meeeow! Please use this command by replying to the message you want to pin. 📌")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_pin_messages', False)):
            await update.message.reply_text("Meeeow! I need to be an admin with the 'Pin Messages' permission in this chat to do that. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /pin for chat {chat.id}: {e}")
        await update.message.reply_text("Mrow? Couldn't verify my own permissions in this chat.")
        return
        
    if not await _can_user_perform_action(update, context, 'can_pin_messages', "Meeeow! You need to be an admin with 'Pin Messages' permission in this chat to use this command."):
        return

    disable_notification = True
    pin_mode_text = ""

    if context.args and context.args[0].lower() in ["loud", "notify"]:
        disable_notification = False
        pin_mode_text = " with notification"
        logger.info(f"User {user_who_pins.id} requested loud pin in chat {chat.id}")
    else:
        logger.info(f"User {user_who_pins.id} requested silent pin (default) in chat {chat.id}")


    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id,
            message_id=message_to_pin.message_id,
            disable_notification=disable_notification
        )
        logger.info(f"User {user_who_pins.id} pinned message {message_to_pin.message_id} in chat {chat.id}. Notification: {'Disabled' if disable_notification else 'Enabled'}")
        
        await send_safe_reply(update, context, text=f"📌 Meow! Message pinned{pin_mode_text}!")

    except TelegramError as e:
        logger.error(f"Failed to pin message in chat {chat.id}: {e}")
        error_message = str(e)
        if "message to pin not found" in error_message.lower():
            await send_safe_reply(update, context, text="Mrow? I can't find the message you replied to. Maybe it was deleted?")
        elif "not enough rights" in error_message.lower() or "not admin" in error_message.lower():
             await send_safe_reply(update, context, text="Meeeow! It seems I don't have enough rights to pin messages, or the target message cannot be pinned by me.")
        else:
            await send_safe_reply(update, context, text=f"Failed to pin message: {html.escape(error_message)}")
    except Exception as e:
        logger.error(f"Unexpected error in /pin: {e}", exc_info=True)
        await send_safe_reply(update, context, text="An unexpected error occurred while trying to pin the message.")

async def unpin_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message_to_unpin = update.message.reply_to_message

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        await update.message.reply_text("Mrow? Messages can only be unpinned in groups, supergroups, or channels.")
        return
        
    if not message_to_unpin:
        await update.message.reply_text("Meeeow! Please reply to a pinned message to unpin it.")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == ChatMemberStatus.ADMINISTRATOR and getattr(bot_member, 'can_pin_messages', False)):
            await update.message.reply_text("Meeeow! I need to be an admin with the 'Pin Messages' permission to do that. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /unpin for chat {chat.id}: {e}")
        await update.message.reply_text("Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_pin_messages', "Meeeow! You need to be an admin with 'Pin Messages' permission to use this command."):
        return

    try:
        await context.bot.unpin_chat_message(
            chat_id=chat.id,
            message_id=message_to_unpin.message_id
        )
        await update.message.reply_text("📌 Meow! Message unpinned successfully!", quote=False)
        
    except TelegramError as e:
        logger.error(f"Failed to unpin message {message_to_unpin.message_id} in chat {chat.id}: {e}")
        error_message = str(e)
        if "message not found" in error_message.lower() or "message to unpin not found" in error_message.lower():
             await update.message.reply_text("Mrow? The message you replied to is not pinned or I can't find it.")
        else:
            await update.message.reply_text(f"Failed to unpin message: {html.escape(error_message)}")
    except Exception as e:
        logger.error(f"Unexpected error in /unpin: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred while trying to unpin the message.")

async def purge_messages_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user_who_purges = update.effective_user
    command_message = update.message
    replied_to_message = update.message.reply_to_message

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await command_message.reply_text("Mrow? Messages can only be purged in groups and supergroups.")
        return

    if not replied_to_message:
        await context.bot.send_message(chat.id, "Meeeow! Please use this command by replying to the message up to which you want to delete (that message will also be deleted).")
        return

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not (bot_member.status == "administrator" and getattr(bot_member, 'can_delete_messages', False)):
            await context.bot.send_message(chat.id, "Meeeow! I need to be an admin with the 'Delete Messages' permission in this chat. 😿")
            return
    except TelegramError as e:
        logger.error(f"Error checking bot's own permissions in /purge for chat {chat.id}: {e}")
        await context.bot.send_message(chat.id, "Mrow? Couldn't verify my own permissions in this chat.")
        return

    if not await _can_user_perform_action(update, context, 'can_delete_messages', "Meeeow! You do not have permission to use this command."):
        return

    is_silent_purge = False
    if context.args and context.args[0].lower() == "silent":
        is_silent_purge = True
        logger.info(f"User {user_who_purges.id} initiated silent purge in chat {chat.id} up to message {replied_to_message.message_id}")
    else:
        logger.info(f"User {user_who_purges.id} initiated purge in chat {chat.id} up to message {replied_to_message.message_id}")

    start_message_id = replied_to_message.message_id
    end_message_id = command_message.message_id
    message_ids_to_delete = list(range(start_message_id, end_message_id + 1))

    if not message_ids_to_delete or len(message_ids_to_delete) < 1:
        if not is_silent_purge:
            await context.bot.send_message(chat.id, "Mrow? No messages found between your reply and this command to delete.")
        return

    errors_occurred = False
    start_time = datetime.now()

    for i in range(0, len(message_ids_to_delete), 100):
        batch_ids = message_ids_to_delete[i:i + 100]
        try:
            success = await context.bot.delete_messages(chat_id=chat.id, message_ids=batch_ids)
            if not success:
                errors_occurred = True
                logger.warning(f"A batch purge in chat {chat.id} failed or partially failed.")
            if len(message_ids_to_delete) > 100 and i + 100 < len(message_ids_to_delete):
                await asyncio.sleep(1.1)
        except TelegramError as e:
            logger.error(f"TelegramError during purge batch in chat {chat.id}: {e}")
            errors_occurred = True
            if not is_silent_purge:
                await context.bot.send_message(chat.id, text=f"Mrow! An error occurred: {html.escape(str(e))}. Purge stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error during purge batch in chat {chat.id}: {e}", exc_info=True)
            errors_occurred = True
            if not is_silent_purge:
                await context.bot.send_message(chat.id, text="Mrow! An unexpected error occurred. Purge stopped.")
            break

    end_time = datetime.now()
    duration_secs = (end_time - start_time).total_seconds()

    if not is_silent_purge:
        final_message_text = f"✅ Meow! Purge completed in <code>{duration_secs:.2f}s</code>."
        if errors_occurred:
            final_message_text += "\nSome messages may not have been deleted (e.g., older than 48h or service messages)."

        try:
            await context.bot.send_message(chat_id=chat.id, text=final_message_text, parse_mode=ParseMode.HTML)
        except Exception as e_send_final:
            logger.error(f"Purge: Failed to send final purge status message: {e_send_final}")
    else:
        logger.info(f"Silent purge completed in chat {chat.id}. Duration: {duration_secs:.2f}s. Errors occurred: {errors_occurred}")

async def resolve_target_entity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> User | Chat | None:
    """
    Resolves the target entity (User or Channel) from a command message.
    Handles replies, @usernames (DB first for users), and IDs.
    """
    message = update.effective_message
    if not message: return None
    
    if message.reply_to_message:
        if message.reply_to_message.sender_chat:
            return message.reply_to_message.sender_chat
        if message.reply_to_message.from_user:
            return message.reply_to_message.from_user
        return None

    if context.args:
        target_id_str = context.args[0]
        
        if target_id_str.startswith('@'):
            user_from_db = get_user_from_db_by_username(target_id_str)
            if user_from_db:
                return user_from_db
            
            try:
                logger.info(f"Querying API for entity {target_id_str}.")
                return await context.bot.get_chat(target_id_str)
            except TelegramError:
                await message.reply_text(f"😿 Could not find any user or channel with the username: {html.escape(target_id_str)}")
                return None

        try:
            entity_id = int(target_id_str)
            return await context.bot.get_chat(entity_id)
        except (ValueError, TelegramError):
            await message.reply_text(f"😿 Could not find any entity with the ID: {html.escape(target_id_str)}")
            return None

    return None

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    reporter = update.effective_user
    message = update.effective_message

    if not message or chat.type == ChatType.PRIVATE:
        await message.reply_text("Meow. This command can only be used in groups.")
        return

    target_entity = await resolve_target_entity(update, context)
    
    if not target_entity:
        if not context.args:
            await message.reply_text("Usage: /report <ID/@user/reply> [reason]")
        return
        
    reason_args = context.args[1:] if context.args and not message.reply_to_message else context.args
    reason = " ".join(reason_args) if reason_args else "No specific reason provided."
    
    reporter_mention = reporter.mention_html()
    
    if isinstance(target_entity, User) or target_entity.type == ChatType.PRIVATE:
        target_display = target_entity.mention_html()
        entity_type_label = "User"
    else:
        target_display = html.escape(target_entity.title or f"User {target_entity.id}")
        entity_type_label = target_entity.type.capitalize()

    report_message = (
        f"📢 <b>Report for Administrators</b>\n\n"
        f"<b>Reported {entity_type_label}:</b> {target_display} (<code>{target_entity.id}</code>)\n"
        f"<b>Reason:</b> {html.escape(reason)}\n"
        f"<b>Reported by:</b> {reporter_mention}"
    )

    await send_safe_reply(update, context, text=report_message, parse_mode=ParseMode.HTML)

# --- Simple Text Command Definitions ---
async def send_random_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text_list: list[str], list_name: str) -> None:
    if not text_list: logger.warning(f"Empty list: '{list_name}'"); await update.message.reply_text("Mrow? Internal error: Text list empty. 😿"); return
    chosen_text = random.choice(text_list)
    try:
        await update.message.reply_html(chosen_text)
    except TelegramError as e_html:
        logger.error(f"TelegramError sending HTML reply for {list_name}: {e_html}. Trying plain text.")
        try:
            await update.message.reply_text(chosen_text)
            logger.info(f"Sent plain text fallback for {list_name}.")
        except Exception as e_plain:
            logger.error(f"Fallback plain text reply also failed for {list_name}: {e_plain}")
    except Exception as e_other:
        logger.error(f"Unexpected error sending HTML reply for {list_name}: {e_other}", exc_info=True)
        try:
            await update.message.reply_text(chosen_text)
            logger.info(f"Sent plain text fallback for {list_name} after unexpected error.")
        except Exception as e_plain_fallback:
            logger.error(f"Fallback plain text reply also failed for {list_name} after unexpected error: {e_plain_fallback}")

async def meow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, MEOW_TEXTS, "MEOW_TEXTS")
async def nap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, NAP_TEXTS, "NAP_TEXTS")
async def play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, PLAY_TEXTS, "PLAY_TEXTS")
async def treat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, TREAT_TEXTS, "TREAT_TEXTS")
async def zoomies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, ZOOMIES_TEXTS, "ZOOMIES_TEXTS")
async def judge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await send_random_text(update, context, JUDGE_TEXTS, "JUDGE_TEXTS")

# --- Helper for Simulation Commands ---
async def _handle_action_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action_texts: list[str], gif_search_terms: list[str], command_name: str, target_required: bool = True, target_required_msg: str = "This command requires a target.", hug_command: bool = False):
    if not action_texts: logger.warning(f"List '{command_name.upper()}_TEXTS' empty!"); await update.message.reply_text(f"Mrow? No texts for /{command_name}. 😿"); return
    target_mention = None; is_protected = False; is_owner = False
    if target_required:
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user; is_protected = await check_target_protection(target_user.id, context); is_owner = (target_user.id == OWNER_ID)
            if is_protected: refusal_list = (CANT_TARGET_OWNER_HUG_TEXTS if is_owner else CANT_TARGET_SELF_HUG_TEXTS) if hug_command else (CANT_TARGET_OWNER_TEXTS if is_owner else CANT_TARGET_SELF_TEXTS); await update.message.reply_html(random.choice(refusal_list)); return
            target_mention = target_user.mention_html()
        elif context.args and context.args[0].startswith('@'):
            target_mention_str = context.args[0].strip(); is_protected, is_owner = await check_username_protection(target_mention_str, context)
            if is_protected: refusal_list = (CANT_TARGET_OWNER_HUG_TEXTS if is_owner else CANT_TARGET_SELF_HUG_TEXTS) if hug_command else (CANT_TARGET_OWNER_TEXTS if is_owner else CANT_TARGET_SELF_TEXTS); await update.message.reply_html(random.choice(refusal_list)); return
            target_mention = target_mention_str
        else: await update.message.reply_text(target_required_msg); return
    gif_url = await get_themed_gif(context, gif_search_terms)
    message_text = random.choice(action_texts)
    if "{target}" in message_text: effective_target = target_mention if target_required else update.effective_user.mention_html(); message_text = message_text.format(target=effective_target) if effective_target else message_text.replace("{target}", "someone")

    try:
        if gif_url: await update.message.reply_animation(animation=gif_url, caption=message_text, parse_mode=ParseMode.HTML)
        else: await update.message.reply_html(message_text)
    except TelegramError as e_primary:
        logger.error(f"TelegramError sending {command_name} (animation/HTML): {e_primary}. Trying HTML fallback.")
        try: await update.message.reply_html(message_text); logger.info(f"Sent fallback HTML for {command_name}.")
        except Exception as e_html_fallback:
            logger.error(f"Fallback HTML failed for {command_name}: {e_html_fallback}. Trying plain text.")
            try: await update.message.reply_text(message_text); logger.info(f"Sent fallback plain text for {command_name}.")
            except Exception as e_plain_fallback: logger.error(f"Fallback plain text also failed for {command_name}: {e_plain_fallback}")
    except Exception as e_other:
        logger.error(f"Unexpected error sending {command_name} (animation/HTML): {e_other}", exc_info=True)
        try: await update.message.reply_html(message_text); logger.info(f"Sent fallback HTML for {command_name} after unexpected error.")
        except Exception as e_html_fallback:
             logger.error(f"Fallback HTML failed for {command_name} after unexpected error: {e_html_fallback}. Trying plain text.")
             try: await update.message.reply_text(message_text); logger.info(f"Sent fallback plain text for {command_name} after unexpected error.")
             except Exception as e_plain_fallback: logger.error(f"Fallback plain text also failed for {command_name} after unexpected error: {e_plain_fallback}")

# Simulation Command Definitions
async def fed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, FED_TEXTS, ["cat eating", "cat food", "cat nom"], "fed", False)
async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, ATTACK_TEXTS, ["cat attack", "cat pounce", "cat fight"], "attack", True, "Who to attack? Reply or use /attack @username.")
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, KILL_TEXTS, ["cat angry", "cat evil", "cat hiss"], "kill", True, "Who to 'kill'? Reply or use /kill @username.")
async def punch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, PUNCH_TEXTS, ["cat punch", "cat bap"], "punch", True, "Who to 'punch'? Reply or use /punch @username.")
async def slap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, SLAP_TEXTS, ["cat slap"], "slap", True, "Who to slap? Reply or use /slap @username.")
async def bite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, BITE_TEXTS, ["cat bite", "cat chomp"], "bite", True, "Who to bite? Reply or use /bite @username.")
async def hug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await _handle_action_command(update, context, HUG_TEXTS, ["cat hug", "cat cuddle"], "hug", True, "Who to hug? Reply or use /hug @username.", hug_command=True)

# --- GIF and Photo Commands ---
async def gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches and sends a random cat GIF."""
    API_URL = "https://api.thecatapi.com/v1/images/search?mime_types=gif&limit=1"
    # Add headers if you have an API key for thecatapi
    # headers = {"x-api-key": "YOUR_CAT_API_KEY"}
    headers = {}
    logger.info("Fetching random cat GIF from thecatapi...")
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0 and 'url' in data[0]:
            await update.message.reply_animation(animation=data[0]['url'], caption="Meow! A random GIF for you! 🐾🖼️")
        else:
            logger.warning(f"No valid GIF data received from thecatapi: {data}")
            await update.message.reply_text("Meow? Couldn't find a GIF right now. 😿")
    except requests.exceptions.Timeout:
        logger.error("Timeout fetching GIF from thecatapi.")
        await update.message.reply_text("Hiss! The cat GIF source is being slow. ⏳ Try again later!")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching GIF from thecatapi: {e}")
        await update.message.reply_text("Hiss! Couldn't connect to the cat GIF source. 😿")
    except Exception as e:
        logger.error(f"Unexpected error processing GIF from thecatapi: {e}", exc_info=True)
        await update.message.reply_text("Mrow! Something weird happened while getting the GIF. 😵‍💫")
        
async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches and sends a random cat photo."""
    API_URL = "https://api.thecatapi.com/v1/images/search?limit=1&mime_types=jpg,png"
    # headers = {"x-api-key": "YOUR_CAT_API_KEY"}
    headers = {}
    logger.info("Fetching random cat photo from thecatapi...")
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0 and 'url' in data[0]:
            await update.message.reply_photo(photo=data[0]['url'], caption="Purrfect! A random photo for you! 🐾📷")
        else:
            logger.warning(f"No valid photo data received from thecatapi: {data}")
            await update.message.reply_text("Meow? Couldn't find a photo right now. 😿")
    except requests.exceptions.Timeout:
        logger.error("Timeout fetching photo from thecatapi.")
        await update.message.reply_text("Hiss! The cat photo source is being slow. ⏳ Try again later!")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching photo from thecatapi: {e}")
        await update.message.reply_text("Hiss! Couldn't connect to the cat photo source. 😿")
    except Exception as e:
        logger.error(f"Unexpected error processing photo from thecatapi: {e}", exc_info=True)
        await update.message.reply_text("Mrow! Something weird happened while getting the photo. 😵‍💫")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /status attempt by user {user.id}. Silently ignoring.")
        return

    uptime_delta = datetime.now() - BOT_START_TIME 
    readable_uptime = get_readable_time_delta(uptime_delta)

    known_users_count = "N/A"
    blacklisted_count = "N/A"
    sudo_users_count = "N/A"
    gban_count = "N/A"
    chat_count = "N/A"

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM users")
            count_result_users = cursor.fetchone()
            if count_result_users:
                known_users_count = str(count_result_users[0])

            cursor.execute("SELECT COUNT(*) FROM blacklist")
            count_result_blacklist = cursor.fetchone()
            if count_result_blacklist:
                blacklisted_count = str(count_result_blacklist[0])
                
            cursor.execute("SELECT COUNT(*) FROM sudo_users")
            count_result_sudo = cursor.fetchone()
            if count_result_sudo:
                sudo_users_count = str(count_result_sudo[0])

            cursor.execute("SELECT COUNT(*) FROM global_bans")
            count_result_gban = cursor.fetchone()
            if count_result_gban:
                gban_count = str(count_result_gban[0])
                
            cursor.execute("SELECT COUNT(*) FROM bot_chats")
            count_result_chats = cursor.fetchone()
            if count_result_chats:
                chat_count = str(count_result_chats[0])
            
    except sqlite3.Error as e:
        logger.error(f"SQLite error fetching counts for /status: {e}", exc_info=True)
        known_users_count = "DB Error"
        blacklisted_count = "DB Error"
        sudo_users_count = "DB Error"
        gban_count = "DB Error"
        chat_count = "DB Error"
    except Exception as e:
        logger.error(f"Unexpected error fetching counts for /status: {e}", exc_info=True)
        known_users_count = "Error"
        blacklisted_count = "Error"
        sudo_users_count = "Error"
        gban_count = "Error"
        chat_count = "Error"

    status_lines = [
        "<b>Purrrr! Bot Status:</b> ✨\n",
        f"<b>• State:</b> Ready & Purring! 🐾",
        f"<b>• Last Nap:</b> <code>{readable_uptime}</code> ago 😴\n",
        "<b>📊 Stats:</b>",
        f" <b>• 💬 Chats:</b> <code>{chat_count}</code>",
        f" <b>• 👀 Known Users:</b> <code>{known_users_count}</code>",
        f" <b>• 🛡 Sudo Users:</b> <code>{sudo_users_count}</code>",
        f" <b>• 🚫 Blacklisted Users:</b> <code>{blacklisted_count}</code>",
        f" <b>• 🌍 Globally Banned Users:</b> <code>{gban_count}</code>"
    ]

    status_msg = "\n".join(status_lines)
    await update.message.reply_html(status_msg)

async def say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /say attempt by user {user.id}.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /say [optional_chat_id] <your message>")
        return

    target_chat_id_str = args[0]
    message_to_say_list = args
    target_chat_id = update.effective_chat.id
    is_remote_send = False

    try:
        potential_chat_id = int(target_chat_id_str)
        if len(target_chat_id_str) > 5 or potential_chat_id >= -1000:
            try:
                 await context.bot.get_chat(potential_chat_id)
                 if len(args) > 1:
                     target_chat_id = potential_chat_id
                     message_to_say_list = args[1:]
                     is_remote_send = True
                     logger.info(f"Privileged user {user.id} remote send detected. Target: {target_chat_id}")
                 else:
                     await update.message.reply_text("Mrow? Target chat ID provided, but no message to send!")
                     return
            except TelegramError:
                 logger.info(f"Argument '{target_chat_id_str}' looks like ID but get_chat failed or not a valid target, sending to current chat.")
                 target_chat_id = update.effective_chat.id
                 message_to_say_list = args
                 is_remote_send = False
            except Exception as e:
                 logger.error(f"Unexpected error checking potential chat ID {potential_chat_id}: {e}")
                 target_chat_id = update.effective_chat.id
                 message_to_say_list = args
                 is_remote_send = False
        else:
             logger.info("First argument doesn't look like a chat ID, sending to current chat.")
             target_chat_id = update.effective_chat.id
             message_to_say_list = args
             is_remote_send = False
    except (ValueError, IndexError):
        logger.info("First argument is not numeric, sending to current chat.")
        target_chat_id = update.effective_chat.id
        message_to_say_list = args
        is_remote_send = False

    message_to_say = ' '.join(message_to_say_list)
    if not message_to_say:
        await update.message.reply_text("Mrow? Cannot send an empty message!")
        return

    chat_title = f"Chat ID {target_chat_id}"
    safe_chat_title = chat_title
    try:
        target_chat_info = await context.bot.get_chat(target_chat_id)
        chat_title = target_chat_info.title or target_chat_info.first_name or f"Chat ID {target_chat_id}"
        safe_chat_title = html.escape(chat_title)
        logger.info(f"Target chat title for /say resolved to: '{chat_title}'")
    except TelegramError as e:
        logger.warning(f"Could not get chat info for {target_chat_id} for /say confirmation: {e}")
    except Exception as e:
         logger.error(f"Unexpected error getting chat info for {target_chat_id} in /say: {e}", exc_info=True)

    logger.info(f"Privileged user ({user.id}) using /say. Target: {target_chat_id} ('{chat_title}'). Is remote: {is_remote_send}. Msg start: '{message_to_say[:50]}...'")

    try:
        await context.bot.send_message(chat_id=target_chat_id, text=message_to_say)
        if is_remote_send:
            await update.message.reply_text(f"✅ Message sent to <b>{safe_chat_title}</b> (<code>{target_chat_id}</code>).", parse_mode=ParseMode.HTML, quote=False)
    except TelegramError as e:
        logger.error(f"Failed to send message via /say to {target_chat_id} ('{chat_title}'): {e}")
        await update.message.reply_text(f"😿 Couldn't send message to <b>{safe_chat_title}</b> (<code>{target_chat_id}</code>): {e}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Unexpected error during /say execution: {e}", exc_info=True)
        await update.message.reply_text(f"💥 Oops! An unexpected error occurred while trying to send the message to <b>{safe_chat_title}</b> (<code>{target_chat_id}</code>). Check logs.", parse_mode=ParseMode.HTML)

async def chat_stat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays basic statistics about the current chat."""
    chat = update.effective_chat
    if not chat:
        await update.message.reply_text("Mrow? Couldn't get chat information for some reason.")
        return

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        await update.message.reply_text("Meow! This command shows stats for groups, supergroups, or channels.")
        return

    try:
        full_chat_object = await context.bot.get_chat(chat_id=chat.id)
    except TelegramError as e:
        logger.error(f"Failed to get full chat info for /chatstats in chat {chat.id}: {e}")
        await update.message.reply_html(f"😿 Mrow! Couldn't fetch detailed stats for this chat. Reason: {html.escape(str(e))}")
        return
    except Exception as e:
        logger.error(f"Unexpected error fetching full chat info for /chatstats in chat {chat.id}: {e}", exc_info=True)
        await update.message.reply_html(f"💥 An unexpected error occurred while fetching chat stats.")
        return

    chat_title_display = full_chat_object.title or full_chat_object.first_name or f"Chat ID {full_chat_object.id}"
    info_lines = [f"🔎 <b>Chat stats for: {html.escape(chat_title_display)}</b>\n"]

    info_lines.append(f"<b>• ID:</b> <code>{full_chat_object.id}</code>")

    chat_description = getattr(full_chat_object, 'description', None)
    if chat_description:
        desc_preview = chat_description[:70]
        info_lines.append(f"<b>• Description:</b> {html.escape(desc_preview)}{'...' if len(chat_description) > 70 else ''}")
    else:
        info_lines.append(f"<b>• Description:</b> Not set")
    
    if getattr(full_chat_object, 'photo', None):
        info_lines.append(f"<b>• Chat Photo:</b> <code>Yes</code>")
    else:
        info_lines.append(f"<b>• Chat Photo:</b> <code>No</code>")

    slow_mode_delay_val = getattr(full_chat_object, 'slow_mode_delay', None)
    if slow_mode_delay_val and slow_mode_delay_val > 0:
        info_lines.append(f"<b>• Slow Mode:</b> <code>Enabled</code> ({slow_mode_delay_val}s)")
    else:
        info_lines.append(f"<b>• Slow Mode:</b> <code>Disabled</code>")
    
    try:
        member_count = await context.bot.get_chat_member_count(chat_id=full_chat_object.id)
        info_lines.append(f"<b>• Total Members:</b> <code>{member_count}</code>")
    except TelegramError as e:
        logger.warning(f"Could not get member count for /chatstats in chat {full_chat_object.id}: {e}")
        info_lines.append(f"<b>• Total Members:</b> N/A (Error fetching)")
    except Exception as e:
        logger.error(f"Unexpected error in get_chat_member_count for /chatstats in {full_chat_object.id}: {e}", exc_info=True)
        info_lines.append(f"<b>• Total Members:</b> N/A (Unexpected error)")

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        status_line = "<b>• Gban Enforcement:</b> "
        
        if not is_gban_enforced(chat.id):
            status_line += "<code>Disabled</code>"
        else:
            try:
                bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
                if bot_member.status == "administrator" and bot_member.can_restrict_members:
                    status_line += "<code>Enabled</code>"
                else:
                    status_line += "<code>Disabled</code>\n<i>Reason: Bot needs 'Ban Users' permission</i>"
            except Exception:
                status_line += "<code>Disabled</code>\n<i>Reason: Could not verify bot permissions</i>"
        
        info_lines.append(status_line)

    message_text = "\n".join(info_lines)
    await update.message.reply_html(message_text, disable_web_page_preview=True)

async def chat_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /cinfo attempt by user {user.id}.")
        return

    target_chat_id: int | None = None
    chat_object_for_details: Chat | None = None

    if context.args:
        try:
            target_chat_id = int(context.args[0])
            logger.info(f"Privileged user {user.id} calling /cinfo with target chat ID: {target_chat_id}")
            try:
                chat_object_for_details = await context.bot.get_chat(chat_id=target_chat_id)
            except TelegramError as e:
                logger.error(f"Failed to get chat info for ID {target_chat_id}: {e}")
                await update.message.reply_html(f"😿 Mrow! Couldn't fetch info for chat ID <code>{target_chat_id}</code>. Reason: {html.escape(str(e))}.")
                return
            except Exception as e:
                logger.error(f"Unexpected error fetching chat info for ID {target_chat_id}: {e}", exc_info=True)
                await update.message.reply_html(f"💥 An unexpected error occurred trying to get info for chat ID <code>{target_chat_id}</code>.")
                return
        except ValueError:
            await update.message.reply_text("Mrow? Invalid chat ID format. Please provide a numeric ID.")
            return
    else:
        effective_chat_obj = update.effective_chat
        if effective_chat_obj:
             target_chat_id = effective_chat_obj.id
             try:
                 chat_object_for_details = await context.bot.get_chat(chat_id=target_chat_id)
                 logger.info(f"Privileged user {user.id} calling /cinfo for current chat: {target_chat_id}")
             except TelegramError as e:
                logger.error(f"Failed to get full chat info for current chat ID {target_chat_id}: {e}")
                await update.message.reply_html(f"😿 Mrow! Couldn't fetch full info for current chat. Reason: {html.escape(str(e))}.")
                return
             except Exception as e:
                logger.error(f"Unexpected error fetching full info for current chat ID {target_chat_id}: {e}", exc_info=True)
                await update.message.reply_html(f"💥 An unexpected error occurred trying to get full info for current chat.")
                return
        else:
             await update.message.reply_text("Mrow? Could not determine current chat.")
             return

    if not chat_object_for_details or target_chat_id is None:
        await update.message.reply_text("Mrow? Couldn't determine the chat to inspect.")
        return

    if chat_object_for_details.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        await update.message.reply_text("Meow! This command provides info about groups, supergroups, or channels.")
        return

    bot_id = context.bot.id
    chat_title_display = chat_object_for_details.title or chat_object_for_details.first_name or f"Chat ID {target_chat_id}"
    info_lines = [f"🔎 <b>Chat Information for: {html.escape(chat_title_display)}</b>\n"]

    info_lines.append(f"<b>• ID:</b> <code>{target_chat_id}</code>")
    info_lines.append(f"<b>• Type:</b> {chat_object_for_details.type.capitalize()}")

    chat_description = getattr(chat_object_for_details, 'description', None)
    if chat_description:
        desc_preview = chat_description[:200]
        info_lines.append(f"<b>• Description:</b> {html.escape(desc_preview)}{'...' if len(chat_description) > 200 else ''}")
    
    if getattr(chat_object_for_details, 'photo', None):
        info_lines.append(f"<b>• Chat Photo:</b> Yes")
    else:
        info_lines.append(f"<b>• Chat Photo:</b> No")

    chat_link_line = ""
    if chat_object_for_details.username:
        chat_link = f"https://t.me/{chat_object_for_details.username}"
        chat_link_line = f"<b>• Link:</b> <a href=\"{chat_link}\">@{chat_object_for_details.username}</a>"
    elif chat_object_for_details.type != ChatType.CHANNEL:
        try:
            bot_member = await context.bot.get_chat_member(chat_id=target_chat_id, user_id=bot_id)
            if bot_member.status == "administrator" and bot_member.can_invite_users:
                link_name = f"cinfo_{str(target_chat_id)[-5:]}_{random.randint(100,999)}"
                invite_link_obj = await context.bot.create_chat_invite_link(chat_id=target_chat_id, name=link_name)
                chat_link_line = f"<b>• Generated Invite Link:</b> {invite_link_obj.invite_link} (temporary)"
            else:
                chat_link_line = "<b>• Link:</b> Private group (no public link, bot cannot generate one)"
        except TelegramError as e:
            logger.warning(f"Could not create/check invite link for private chat {target_chat_id}: {e}")
            chat_link_line = f"<b>• Link:</b> Private group (no public link, error: {html.escape(str(e))})"
        except Exception as e:
            logger.error(f"Unexpected error with invite link for {target_chat_id}: {e}", exc_info=True)
            chat_link_line = "<b>• Link:</b> Private group (no public link, unexpected error)"
    else:
        chat_link_line = "<b>• Link:</b> Private channel (no public/invite link via bot)"
    info_lines.append(chat_link_line)

    pinned_message_obj = getattr(chat_object_for_details, 'pinned_message', None)
    if pinned_message_obj:
        pin_text_preview = pinned_message_obj.text or pinned_message_obj.caption or "[Media/No Text]"
        pin_link = "#" 
        if chat_object_for_details.username:
             pin_link = f"https://t.me/{chat_object_for_details.username}/{pinned_message_obj.message_id}"
        elif str(target_chat_id).startswith("-100"):
             chat_id_for_link = str(target_chat_id).replace("-100","")
             pin_link = f"https://t.me/c/{chat_id_for_link}/{pinned_message_obj.message_id}"
        info_lines.append(f"<b>• Pinned Message:</b> <a href=\"{pin_link}\">'{html.escape(pin_text_preview[:50])}{'...' if len(pin_text_preview) > 50 else ''}'</a>")
    
    linked_chat_id_val = getattr(chat_object_for_details, 'linked_chat_id', None)
    if linked_chat_id_val:
        info_lines.append(f"<b>• Linked Chat ID:</b> <code>{linked_chat_id_val}</code>")
    
    slow_mode_delay_val = getattr(chat_object_for_details, 'slow_mode_delay', None)
    if slow_mode_delay_val and slow_mode_delay_val > 0:
        info_lines.append(f"<b>• Slow Mode:</b> Enabled ({slow_mode_delay_val}s)")

    member_count_val: int | str = "N/A"; admin_count_val: int | str = 0
    try:
        member_count_val = await context.bot.get_chat_member_count(chat_id=target_chat_id)
        info_lines.append(f"<b>• Total Members:</b> {member_count_val}")
    except Exception as e:
        logger.error(f"Error get_chat_member_count for {target_chat_id}: {e}")
        info_lines.append(f"<b>• Total Members:</b> Error fetching")

    admin_list_str_parts = ["<b>• Administrators:</b>"]
    admin_details_list = []
    try:
        administrators = await context.bot.get_chat_administrators(chat_id=target_chat_id)
        admin_count_val = len(administrators)
        admin_list_str_parts.append(f"  <b>• Total:</b> {admin_count_val}")
        for admin_member in administrators:
            admin_user = admin_member.user
            admin_name_display = f"ID: {admin_user.id if admin_user else 'N/A'}"
            if admin_user:
                admin_name_display = admin_user.mention_html() if admin_user.username else html.escape(admin_user.full_name or admin_user.first_name or f"ID: {admin_user.id}")
            detail_line = f"    • {admin_name_display}"
            current_admin_status_str = getattr(admin_member, 'status', None)
            if current_admin_status_str == "creator":
                detail_line += " (Creator 👑)"
            admin_details_list.append(detail_line)
        if admin_details_list:
            admin_list_str_parts.append("  <b>• List:</b>")
            admin_list_str_parts.extend(admin_details_list)
    except Exception as e:
        admin_list_str_parts.append("  <b>• Error fetching admin list.</b>")
        admin_count_val = "Error"
        logger.error(f"Error get_chat_administrators for {target_chat_id}: {e}", exc_info=True)
    info_lines.append("\n".join(admin_list_str_parts))

    if isinstance(member_count_val, int) and isinstance(admin_count_val, int) and admin_count_val >=0:
         other_members_count = member_count_val - admin_count_val
         info_lines.append(f"<b>• Other Members:</b> {other_members_count if other_members_count >= 0 else 'N/A'}")

    bot_status_lines = ["\n<b>• Bot Status in this Chat:</b>"]
    try:
        bot_member_on_chat = await context.bot.get_chat_member(chat_id=target_chat_id, user_id=bot_id)
        bot_current_status_str = bot_member_on_chat.status
        bot_status_lines.append(f"  <b>• Status:</b> {bot_current_status_str.capitalize()}")
        if bot_current_status_str == "administrator":
            bot_status_lines.append(f"  <b>• Can invite users:</b> {'Yes' if bot_member_on_chat.can_invite_users else 'No'}")
            bot_status_lines.append(f"  <b>• Can restrict members:</b> {'Yes' if bot_member_on_chat.can_restrict_members else 'No'}")
            bot_status_lines.append(f"  <b>• Can pin messages:</b> {'Yes' if getattr(bot_member_on_chat, 'can_pin_messages', None) else 'No'}")
            bot_status_lines.append(f"  <b>• Can manage chat:</b> {'Yes' if getattr(bot_member_on_chat, 'can_manage_chat', None) else 'No'}")
        else:
            bot_status_lines.append("  <b>• Note:</b> Bot is not an admin here.")
    except TelegramError as e:
        if "user not found" in str(e).lower() or "member not found" in str(e).lower():
             bot_status_lines.append("  <b>• Status:</b> Not a member")
        else:
            bot_status_lines.append(f"  <b>• Error fetching bot status:</b> {html.escape(str(e))}")
    except Exception as e:
        bot_status_lines.append("  <b>• Unexpected error fetching bot status.")
        logger.error(f"Unexpected error getting bot status in {target_chat_id}: {e}", exc_info=True)
    info_lines.append("\n".join(bot_status_lines))
    
    chat_permissions = getattr(chat_object_for_details, 'permissions', None)
    if chat_permissions:
        perms = chat_permissions
        perm_lines = ["\n<b>• Default Member Permissions:</b>"]
        perm_lines.append(f"  <b>• Send Messages:</b> {'Yes' if getattr(perms, 'can_send_messages', False) else 'No'}")
        
        can_send_any_media = (
            getattr(perms, 'can_send_audios', False) or
            getattr(perms, 'can_send_documents', False) or
            getattr(perms, 'can_send_photos', False) or 
            getattr(perms, 'can_send_videos', False) or
            getattr(perms, 'can_send_video_notes', False) or
            getattr(perms, 'can_send_voice_notes', False) or
            getattr(perms, 'can_send_media_messages', False)
        )
        perm_lines.append(f"  <b>• Send Media:</b> {'Yes' if can_send_any_media else 'No'}")
        perm_lines.append(f"  <b>• Send Polls:</b> {'Yes' if getattr(perms, 'can_send_polls', False) else 'No'}")
        perm_lines.append(f"  <b>• Send Other Messages:</b> {'Yes' if getattr(perms, 'can_send_other_messages', False) else 'No'}")
        perm_lines.append(f"  <b>• Add Web Page Previews:</b> {'Yes' if getattr(perms, 'can_add_web_page_previews', False) else 'No'}")
        perm_lines.append(f"  <b>• Change Info:</b> {'Yes' if getattr(perms, 'can_change_info', False) else 'No'}")
        perm_lines.append(f"  <b>• Invite Users:</b> {'Yes' if getattr(perms, 'can_invite_users', False) else 'No'}")
        perm_lines.append(f"  <b>• Pin Messages:</b> {'Yes' if getattr(perms, 'can_pin_messages', False) else 'No'}")
        if hasattr(perms, 'can_manage_topics'):
            perm_lines.append(f"  <b>• Manage Topics:</b> {'Yes' if perms.can_manage_topics else 'No'}")
        info_lines.extend(perm_lines)

    message_text = "\n".join(info_lines)
    await update.message.reply_html(message_text, disable_web_page_preview=True)

def run_speed_test_blocking():
    try:
        logger.info("Starting blocking speed test...")
        s = speedtest.Speedtest()
        s.get_best_server()
        logger.info("Getting download speed...")
        s.download()
        logger.info("Getting upload speed...")
        s.upload()
        results_dict = s.results.dict()
        logger.info("Speed test finished successfully (blocking part).")
        return results_dict
    except speedtest.ConfigRetrievalError as e:
        logger.error(f"Speedtest config retrieval error: {e}")
        return {"error": f"Config retrieval error: {str(e)}"}
    except speedtest.NoMatchedServers as e:
        logger.error(f"Speedtest no matched servers: {e}")
        return {"error": f"No suitable test servers found: {str(e)}"}
    except Exception as e:
        logger.error(f"General error during blocking speedtest function: {e}", exc_info=True)
        return {"error": f"A general error occurred during test: {type(e).__name__}"}

async def speedtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != OWNER_ID:
        logger.warning(f"Unauthorized /speedtest attempt by user {user.id}.")
        return

    message = await update.message.reply_text("Meeeow! Starting speed test... this might take a moment 🐾💨")
    
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, run_speed_test_blocking)
        await asyncio.sleep(4)

        if results and "error" not in results:
            ping_val = results.get("ping", 0.0)
            download_bps = results.get("download", 0)
            upload_bps = results.get("upload", 0)
            
            download_mbps_val = download_bps / 1000 / 1000
            upload_mbps_val = upload_bps / 1000 / 1000

            bytes_sent_val = results.get("bytes_sent", 0)
            bytes_received_val = results.get("bytes_received", 0)
            data_sent_mb_val = bytes_sent_val / 1024 / 1024
            data_received_mb_val = bytes_received_val / 1024 / 1024
            
            timestamp_str_val = results.get("timestamp", "N/A")
            formatted_time_val = "N/A"
            if timestamp_str_val != "N/A":
                try:
                    dt_obj = datetime.fromisoformat(timestamp_str_val.replace("Z", "+00:00"))
                    formatted_time_val = dt_obj.strftime('%Y-%m-%d %H:%M:%S %Z') 
                except ValueError:
                    formatted_time_val = html.escape(timestamp_str_val)

            server_info_dict = results.get("server", {})
            server_name_val = server_info_dict.get("name", "N/A")
            server_country_val = server_info_dict.get("country", "N/A")
            server_cc_val = server_info_dict.get("cc", "N/A")
            server_sponsor_val = server_info_dict.get("sponsor", "N/A")
            server_lat_val = server_info_dict.get("lat", "N/A")
            server_lon_val = server_info_dict.get("lon", "N/A")

            info_lines = [
                "<b>🌐 Ookla SPEEDTEST:</b>\n",
                "<b>📊 RESULTS:</b>",
                f" <b>• 📤 Upload:</b> <code>{upload_mbps_val:.2f} Mbps</code>",
                f" <b>• 📥 Download:</b> <code>{download_mbps_val:.2f} Mbps</code>",
                f" <b>• ⏳️ Ping:</b> <code>{ping_val:.2f} ms</code>",
                f" <b>• 🕒 Time:</b> <code>{formatted_time_val}</code>",
                f" <b>• 📨 Data Sent:</b> <code>{data_sent_mb_val:.2f} MB</code>",
                f" <b>• 📩 Data Received:</b> <code>{data_received_mb_val:.2f} MB</code>\n",
                "<b>🖥 SERVER INFO:</b>",
                f" <b>• 🪪 Name:</b> <code>{html.escape(server_name_val)}</code>",
                f" <b>• 🌍 Country:</b> <code>{html.escape(server_country_val)} ({html.escape(server_cc_val)})</code>",
                f" <b>• 🛠 Sponsor:</b> <code>{html.escape(server_sponsor_val)}</code>",
                f" <b>• 🧭 Latitude:</b> <code>{server_lat_val}</code>",
                f" <b>• 🧭 Longitude:</b> <code>{server_lon_val}</code>"
            ]
            
            result_message = "\n".join(info_lines)
            await context.bot.edit_message_text(chat_id=message.chat_id, message_id=message.message_id, text=result_message, parse_mode=ParseMode.HTML)
        
        elif results and "error" in results:
            error_msg = results["error"]
            await context.bot.edit_message_text(chat_id=message.chat_id, message_id=message.message_id, text=f"😿 Mrow! Speed test failed: {html.escape(error_msg)}")
        else:
            await context.bot.edit_message_text(chat_id=message.chat_id, message_id=message.message_id, text="😿 Mrow! Speed test failed to return results or returned an unexpected format.")

    except Exception as e:
        logger.error(f"Error in speedtest_command outer try-except: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(chat_id=message.chat_id, message_id=message.message_id, text=f"💥 An unexpected error occurred during the speed test: {html.escape(str(e))}")
        except Exception:
            pass
    
async def leave_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != OWNER_ID:
        logger.warning(f"Unauthorized /leave attempt by user {user.id}.")
        return

    target_chat_id_to_leave: int | None = None
    chat_where_command_was_called_id = update.effective_chat.id
    is_leaving_current_chat = False

    if context.args:
        try:
            target_chat_id_to_leave = int(context.args[0])
            if target_chat_id_to_leave >= -100:
                await update.message.reply_text("Mrow? Invalid Group/Channel ID format for leaving.")
                return
            logger.info(f"Privileged user {user.id} initiated remote leave for chat ID: {target_chat_id_to_leave}")
            if target_chat_id_to_leave == chat_where_command_was_called_id:
                is_leaving_current_chat = True
        except (ValueError, IndexError):
            await update.message.reply_text("Mrow? Invalid chat ID format for leaving.")
            return
    else:
        if update.effective_chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Meow! I can't leave a private chat with you.")
            return
        target_chat_id_to_leave = update.effective_chat.id
        is_leaving_current_chat = True
        logger.info(f"Privileged user {user.id} initiated leave for current chat: {target_chat_id_to_leave}")

    if target_chat_id_to_leave is None:
        await update.message.reply_text("Mrow? Could not determine which chat to leave.")
        return

    owner_mention_for_farewell = f"<code>{OWNER_ID}</code>"
    try:
        owner_chat_info = await context.bot.get_chat(OWNER_ID)
        owner_mention_for_farewell = owner_chat_info.mention_html()
    except Exception as e:
        logger.warning(f"Could not fetch owner mention for /leave farewell message: {e}")

    chat_title_to_leave = f"Chat ID {target_chat_id_to_leave}"
    safe_chat_title_to_leave = chat_title_to_leave
    
    try:
        target_chat_info = await context.bot.get_chat(target_chat_id_to_leave)
        chat_title_to_leave = target_chat_info.title or target_chat_info.first_name or f"Chat ID {target_chat_id_to_leave}"
        safe_chat_title_to_leave = html.escape(chat_title_to_leave)
    except TelegramError as e:
        logger.error(f"Could not get chat info for {target_chat_id_to_leave} before leaving: {e}")
        reply_to_chat_id_for_error = chat_where_command_was_called_id
        if is_leaving_current_chat and OWNER_ID: reply_to_chat_id_for_error = OWNER_ID
        
        error_message_text = f"❌ Cannot interact with chat <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>): {html.escape(str(e))}. I might not be a member there."
        if "bot is not a member" in str(e).lower() or "chat not found" in str(e).lower():
            pass 
        else:
            error_message_text = f"⚠️ Couldn't get chat info for <code>{target_chat_id_to_leave}</code>: {html.escape(str(e))}. Will attempt to leave anyway."
        
        if reply_to_chat_id_for_error:
            try: await context.bot.send_message(chat_id=reply_to_chat_id_for_error, text=error_message_text, parse_mode=ParseMode.HTML)
            except Exception as send_err: logger.error(f"Failed to send error about get_chat to {reply_to_chat_id_for_error}: {send_err}")
        if "bot is not a member" in str(e).lower() or "chat not found" in str(e).lower(): return
        
    except Exception as e:
         logger.error(f"Unexpected error getting chat info for {target_chat_id_to_leave}: {e}", exc_info=True)
         reply_to_chat_id_for_error = chat_where_command_was_called_id
         if is_leaving_current_chat and OWNER_ID: reply_to_chat_id_for_error = OWNER_ID
         if reply_to_chat_id_for_error:
             try: await context.bot.send_message(chat_id=reply_to_chat_id_for_error, text=f"⚠️ Unexpected error getting chat info for <code>{target_chat_id_to_leave}</code>. Will attempt to leave anyway.", parse_mode=ParseMode.HTML)
             except Exception as send_err: logger.error(f"Failed to send error about get_chat to {reply_to_chat_id_for_error}: {send_err}")

    if LEAVE_TEXTS:
        farewell_message = random.choice(LEAVE_TEXTS).format(owner_mention=owner_mention_for_farewell, chat_title=f"<b>{safe_chat_title_to_leave}</b>")
        try:
            await context.bot.send_message(chat_id=target_chat_id_to_leave, text=farewell_message, parse_mode=ParseMode.HTML)
            logger.info(f"Sent farewell message to {target_chat_id_to_leave}")
        except TelegramError as e:
            logger.error(f"Failed to send farewell message to {target_chat_id_to_leave}: {e}.")
            if "forbidden: bot is not a member" in str(e).lower() or "chat not found" in str(e).lower():
                logger.warning(f"Bot is not a member of {target_chat_id_to_leave} or chat not found. Cannot send farewell.")
                reply_to_chat_id_for_error = chat_where_command_was_called_id
                if is_leaving_current_chat and OWNER_ID: reply_to_chat_id_for_error = OWNER_ID
                if reply_to_chat_id_for_error:
                    try: await context.bot.send_message(chat_id=reply_to_chat_id_for_error, text=f"❌ Failed to send farewell to <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>): {html.escape(str(e))}. Bot is not a member.", parse_mode=ParseMode.HTML)
                    except Exception as send_err: logger.error(f"Failed to send error about farewell to {reply_to_chat_id_for_error}: {send_err}")
                return 
        except Exception as e:
             logger.error(f"Unexpected error sending farewell message to {target_chat_id_to_leave}: {e}", exc_info=True)
    elif not LEAVE_TEXTS:
        logger.warning("LEAVE_TEXTS list is empty! Skipping farewell message.")

    try:
        success = await context.bot.leave_chat(chat_id=target_chat_id_to_leave)
        
        confirmation_target_chat_id = chat_where_command_was_called_id
        if is_leaving_current_chat:
            if OWNER_ID:
                confirmation_target_chat_id = OWNER_ID
            else:
                confirmation_target_chat_id = None 

        if success:
            logger.info(f"Successfully left chat {target_chat_id_to_leave} ('{chat_title_to_leave}')")
            if confirmation_target_chat_id:
                await context.bot.send_message(chat_id=confirmation_target_chat_id, 
                                               text=f"✅ Successfully left chat: <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>)", 
                                               parse_mode=ParseMode.HTML)
        else:
            logger.warning(f"leave_chat returned False for {target_chat_id_to_leave}. Bot might not have been a member.")
            if confirmation_target_chat_id:
                await context.bot.send_message(chat_id=confirmation_target_chat_id,
                                               text=f"🤔 Attempted to leave <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>), but the operation indicated I might not have been there or lacked permission.", 
                                               parse_mode=ParseMode.HTML)
    except TelegramError as e:
        logger.error(f"Failed to leave chat {target_chat_id_to_leave}: {e}")
        confirmation_target_chat_id = chat_where_command_was_called_id
        if is_leaving_current_chat:
            if OWNER_ID: confirmation_target_chat_id = OWNER_ID
            else: confirmation_target_chat_id = None
        if confirmation_target_chat_id:
            await context.bot.send_message(chat_id=confirmation_target_chat_id,
                                           text=f"❌ Failed to leave chat <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>): {html.escape(str(e))}", 
                                           parse_mode=ParseMode.HTML)
    except Exception as e:
         logger.error(f"Unexpected error during leave process for {target_chat_id_to_leave}: {e}", exc_info=True)
         confirmation_target_chat_id = chat_where_command_was_called_id
         if is_leaving_current_chat:
            if OWNER_ID: confirmation_target_chat_id = OWNER_ID
            else: confirmation_target_chat_id = None
         if confirmation_target_chat_id:
            await context.bot.send_message(chat_id=confirmation_target_chat_id,
                                           text=f"💥 Unexpected error leaving chat <b>{safe_chat_title_to_leave}</b> (<code>{target_chat_id_to_leave}</code>). Check logs.", 
                                           parse_mode=ParseMode.HTML)

# Handler for welcoming the owner when they join a group and send log to pm
async def handle_new_group_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    
    if any(member.id == context.bot.id for member in update.message.new_chat_members):
        logger.info(f"Bot joined chat: {chat.title} ({chat.id})")
        add_chat_to_db(chat.id, chat.title or f"Untitled Chat {chat.id}")
        
        if OWNER_ID:
            safe_chat_title = html.escape(chat.title or f"Chat ID {chat.id}")
            link_line = f"\n<b>Link:</b> @{chat.username}" if chat.username else ""
            pm_text = (f"<b>#ADDEDTOGROUP</b>\n\n<b>Name:</b> {safe_chat_title}\n<b>ID:</b> <code>{chat.id}</code>{link_line}")
            try:
                await context.bot.send_message(chat_id=OWNER_ID, text=pm_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except Exception as e:
                logger.error(f"Failed to send join notification to owner for group {chat.id}: {e}")

    if not is_gban_enforced(chat.id):
        return

    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue
        
        if OWNER_ID and member.id == OWNER_ID:
            owner_mention = member.mention_html()
            if OWNER_WELCOME_TEXTS:
                 welcome_text = random.choice(OWNER_WELCOME_TEXTS).format(owner_mention=owner_mention)
                 try:
                     await update.message.reply_html(welcome_text)
                 except Exception as e:
                     logger.error(f"Failed to send owner welcome message: {e}")
            continue

        gban_reason = get_gban_reason(member.id)
        if gban_reason:
            logger.info(f"G-banned user {member.id} tried to join {chat.id}. Removing.")
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=member.id)
                await update.message.reply_text(
                    f"User {member.mention_html()} was removed because they are globally banned.\n<b>Reason:</b> {html.escape(gban_reason)}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to enforce gban on new member {member.id} in {chat.id}: {e}")

async def handle_left_group_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.left_chat_member:
        if update.message.left_chat_member.id == context.bot.id:
            chat_id = update.effective_chat.id
            logger.info(f"Bot was removed from chat {chat_id}.")
            remove_chat_from_db(chat_id)

async def send_operational_log(context: ContextTypes.DEFAULT_TYPE, message: str, parse_mode: str = ParseMode.HTML) -> None:
    """
    Sends an operational log message to LOG_CHAT_ID if configured,
    otherwise falls back to OWNER_ID.
    """
    target_id_for_log = LOG_CHAT_ID

    if not target_id_for_log and OWNER_ID:
        target_id_for_log = OWNER_ID
        logger.info("LOG_CHAT_ID not set, sending operational log to OWNER_ID.")
    elif not target_id_for_log and not OWNER_ID:
        logger.error("Neither LOG_CHAT_ID nor OWNER_ID are set. Cannot send operational log.")
        return

    if target_id_for_log:
        try:
            await context.bot.send_message(chat_id=target_id_for_log, text=message, parse_mode=parse_mode)
            logger.info(f"Sent operational log to chat_id: {target_id_for_log}")
        except TelegramError as e:
            logger.error(f"Failed to send operational log to {target_id_for_log}: {e}")
            if LOG_CHAT_ID and target_id_for_log == LOG_CHAT_ID and OWNER_ID and LOG_CHAT_ID != OWNER_ID:
                logger.info(f"Falling back to send operational log to OWNER_ID ({OWNER_ID}) after failure with LOG_CHAT_ID.")
                try:
                    await context.bot.send_message(chat_id=OWNER_ID, text=f"[Fallback from LogChat]\n{message}", parse_mode=parse_mode)
                    logger.info(f"Sent operational log to OWNER_ID as fallback.")
                except Exception as e_owner:
                    logger.error(f"Failed to send operational log to OWNER_ID as fallback: {e_owner}")
        except Exception as e:
            logger.error(f"Unexpected error sending operational log to {target_id_for_log}: {e}", exc_info=True)

# --- Blacklist Commands ---
async def blacklist_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not message: return
    
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /blist attempt by user {user.id}.")
        return

    target_user: User | None = None
    reason: str = "No reason provided."
    
    if message.reply_to_message:
        if message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
        else:
            await message.reply_text("Mrow? You must reply to a user's message.")
            return
        if context.args:
            reason = " ".join(context.args)
    elif context.args:
        target_id_str = context.args[0]
        if target_id_str.startswith('@'):
            target_user = get_user_from_db_by_username(target_id_str)
            if not target_user:
                try:
                    chat_info = await context.bot.get_chat(target_id_str)
                    if chat_info.type == 'private':
                        target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
                    else:
                        await message.reply_text("Blacklist can only be applied to users.")
                        return
                except TelegramError:
                    await message.reply_text(f"Could not find user {html.escape(target_id_str)}.")
                    return
        else:
            try:
                user_id = int(target_id_str)
                try:
                    chat_info = await context.bot.get_chat(user_id)
                    if chat_info.type == 'private':
                        target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
                    else:
                        await message.reply_text("Blacklist can only be applied to users, not channels or groups.")
                        return
                except TelegramError:
                    target_user = User(id=user_id, first_name=f"{user_id}", is_bot=False)
            except ValueError:
                await message.reply_text("Invalid User ID format.")
                return

        if len(context.args) > 1:
            reason = " ".join(context.args[1:])
    else:
        await message.reply_text("Usage: /blist <ID/@user/reply> [reason]")
        return
        
    if not target_user:
        await message.reply_text("Meow. Could not identify the user to blacklist.")
        return

    if isinstance(target_user, Chat):
        if target_user.type == 'private':
            target_user = User(id=target_user.id, first_name=target_user.first_name, is_bot=False, username=target_user.username, last_name=target_user.last_name)
        else:
            await message.reply_text("Meow. Blacklist can only be applied to users.")
            return

    if target_user.id == OWNER_ID:
        await message.reply_text("Meow! My Owner is sacred and cannot be blacklisted. 👑")
        return
    if target_user.id == context.bot.id:
        await message.reply_text("Purrr... I can't blacklist myself, that would be silly!")
        return
    
    if is_sudo_user(target_user.id):
        if user.id == OWNER_ID:
            await message.reply_html(
                f"Meeeow! To blacklist the Sudo user {target_user.mention_html()}, "
                f"you must first revoke their privileges using /delsudo."
            )
        else:
            await message.reply_text("Mrow! Sudo users cannot blacklist each other.")
        return

    if is_user_blacklisted(target_user.id):
        await message.reply_html(f"ℹ️ User {target_user.mention_html()} is already on the blacklist.")
        return

    if add_to_blacklist(target_user.id, user.id, reason):
        user_display = target_user.mention_html()
        await message.reply_html(f"✅ User {user_display} has been added to the blacklist.\nReason: {html.escape(reason)}")
        
        try:
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            pm_message = (f"<b>#BLACKLISTED</b>\n\n<b>User:</b> {user_display} (<code>{target_user.id}</code>)\n<b>Username:</b> @{html.escape(target_user.username) if target_user.username else 'N/A'}\n<b>Reason:</b> {html.escape(reason)}\n<b>Admin:</b> {user.mention_html()}\n<b>Date:</b> <code>{current_time}</code>")
            await send_operational_log(context, pm_message)
        except Exception as e:
            logger.error(f"Error preparing/sending #BLACKLISTED operational log: {e}", exc_info=True)
    else:
        await message.reply_text("Mrow? Failed to add user to the blacklist. Check logs.")

async def unblacklist_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /unblist attempt by user {user.id}.")
        return

    target_user_obj: User | None = None
    target_input_str: str | None = None

    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user:
            target_user_obj = replied_user
        else:
            await update.message.reply_text("Mrow? Please reply to a user's message to unblacklist them.")
            return
    elif context.args:
        target_input_str = context.args[0]
        if target_input_str.startswith("@"):
            username_to_find = target_input_str[1:]
            target_user_obj = get_user_from_db_by_username(username_to_find)
            if not target_user_obj:
                try: 
                    chat_info = await context.bot.get_chat(target_input_str)
                    if chat_info.type == ChatType.PRIVATE:
                        target_user_obj = User(id=chat_info.id, first_name=chat_info.first_name or f"({target_input_str})", is_bot=getattr(chat_info, 'is_bot', False), username=chat_info.username, last_name=chat_info.last_name)
                    else:
                        await update.message.reply_text(f"Mrow? @{username_to_find} resolved to a {chat_info.type}. Unblacklist can only be applied to users.")
                        return
                except TelegramError:
                    await update.message.reply_text(f"Mrow? Could not find user @{html.escape(username_to_find)} via API. Try ID or reply.")
                    return
                except Exception as e:
                    logger.error(f"Unexpected error for @{username_to_find} in unblacklist: {e}", exc_info=True)
                    await update.message.reply_text("Mrow? An error occurred while trying to find the user.")
                    return
        else:
            try:
                target_id = int(target_input_str)
                try: 
                    chat_info = await context.bot.get_chat(target_id)
                    if chat_info.type == ChatType.PRIVATE:
                        target_user_obj = User(id=chat_info.id, first_name=chat_info.first_name or f"{target_id}", is_bot=getattr(chat_info, 'is_bot', False), username=chat_info.username, last_name=chat_info.last_name)
                    else:
                        logger.warning(f"Attempt to unblacklist non-user ID {target_id} (type: {chat_info.type}). Using ID directly.")
                        target_user_obj = User(id=target_id, first_name=f"{target_id}", is_bot=False)
                except TelegramError: 
                    logger.warning(f"Couldn't fully verify user ID {target_id} for unblacklist. Using minimal User object.")
                    target_user_obj = User(id=target_id, first_name=f"User {target_id}", is_bot=False)
            except ValueError:
                await update.message.reply_text("Mrow? Invalid format. Use /unblist <ID/@username> or reply.")
                return
    else:
        await update.message.reply_text("Mrow? Specify a user ID/@username (or reply) to unblacklist.")
        return
        
    if not target_user_obj:
        await update.message.reply_text("Mrow? Could not identify the user to unblacklist.")
        return
    
    if not isinstance(target_user_obj, User) or getattr(target_user_obj, 'type', ChatType.PRIVATE) != ChatType.PRIVATE :
        await update.message.reply_text("Mrow? Unblacklist can only be applied to individual users.")
        return

    if target_user_obj.id == OWNER_ID:
        await update.message.reply_text("Meow! The Owner is never on the blacklist! 😉")
        return

    if not is_user_blacklisted(target_user_obj.id):
        user_display = target_user_obj.mention_html() if target_user_obj.username else html.escape(target_user_obj.first_name or str(target_user_obj.id))
        await update.message.reply_html(f"ℹ️ User {user_display} is not on the blacklist.")
        return

    if remove_from_blacklist(target_user_obj.id):
        logger.info(f"Owner {user.id} unblacklisted user {target_user_obj.id} (@{target_user_obj.username}).")
        user_display = target_user_obj.mention_html() if target_user_obj.username else html.escape(target_user_obj.first_name or str(target_user_obj.id))
        await update.message.reply_html(f"✅ User {user_display} has been removed from the blacklist.")
        
        try:
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            log_message_to_send = (f"<b>#UNBLACKLISTED</b>\n\n<b>User:</b> {user_display} (<code>{target_user_obj.id}</code>)\n<b>Username:</b> @{html.escape(target_user_obj.username) if target_user_obj.username else 'N/A'}\n<b>Admin:</b> {user.mention_html()}\n<b>Date:</b> <code>{current_time}</code>")
            await send_operational_log(context, log_message_to_send)
        except Exception as e:
            logger.error(f"Error preparing/sending #UNBLACKLISTED operational log: {e}", exc_info=True)
    else:
        await update.message.reply_text("Mrow? Failed to remove user from the blacklist. Check logs.")

# --- Global Ban ---
async def check_gban_on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type == ChatType.PRIVATE:
        return
    
    chat = update.effective_chat
    
    if not is_gban_enforced(chat.id):
        return

    user = update.effective_user
    if not user or is_privileged_user(user.id):
        return
        
    gban_reason = get_gban_reason(user.id)
    if gban_reason:
        message = update.effective_message
        
        try:
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            user_member = await context.bot.get_chat_member(chat.id, user.id)

            if user_member.status in ["creator", "administrator"]:
                return

            if bot_member.status == "administrator" and bot_member.can_restrict_members:
                logger.info(f"G-banned user {user.id} detected in {chat.id}. Bot has permissions, enforcing.")
                
                await context.bot.ban_chat_member(chat.id, user.id)
                
                if bot_member.can_delete_messages:
                    try:
                        await message.delete()
                    except Exception: pass
                
                message_text = (
                    f"⚠️ <b>Meow! Alert:</b> This user is globally banned.\n"
                    f"<i>Enforcing ban in this chat.</i>\n\n"
                    f"<b>User ID:</b> <code>{user.id}</code>\n"
                    f"<b>Reason:</b> {html.escape(gban_reason)}"
                )
                await context.bot.send_message(chat.id, text=message_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to take gban action on message for user {user.id} in chat {chat.id}: {e}")
        
        raise ApplicationHandlerStop

async def gban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_who_gbans = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not message: return

    if not is_privileged_user(user_who_gbans.id):
        logger.warning(f"Unauthorized /gban attempt by user {user_who_gbans.id}.")
        return

    target_user: User | None = None
    reason: str = "No reason provided."
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if context.args: reason = " ".join(context.args)
    elif context.args:
        target_id_str = context.args[0]
        if target_id_str.startswith('@'):
            target_user = get_user_from_db_by_username(target_id_str)
            if not target_user:
                try:
                    target_user = await context.bot.get_chat(target_id_str)
                except TelegramError:
                    await message.reply_text(f"😿 User not found in my database. Please use their ID or reply to a message.")
                    return
        else:
            try:
                user_id = int(target_id_str)
                try:
                    target_user = await context.bot.get_chat(user_id)
                except TelegramError:
                    target_user = User(id=user_id, first_name=f"{user_id}", is_bot=False)
            except ValueError:
                await message.reply_text("Mrow? Invalid User ID format.")
                return
        
        if len(context.args) > 1: reason = " ".join(context.args[1:])
    else:
        await message.reply_text("Usage: /gban <ID/@username/reply> [reason]"); return

    if not target_user:
        await message.reply_text("Mrow? Could not identify the user to gban."); return
        
    if isinstance(target_user, Chat):
        if target_user.type == 'private':
            target_user = User(id=target_user.id, first_name=target_user.first_name, is_bot=False, username=target_user.username, last_name=target_user.last_name)
        else:
            await message.reply_text("Mrow? Global bans can only be applied to users."); return
            
    if is_privileged_user(target_user.id) or target_user.id == context.bot.id:
        await message.reply_text("Meow. This user cannot be globally banned."); return
    if get_gban_reason(target_user.id):
        await message.reply_text("Meow. This user is already globally banned."); return

    add_to_gban(target_user.id, user_who_gbans.id, reason)
    
    user_display = target_user.mention_html()
    
    if chat.type != ChatType.PRIVATE:
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_user.id)
        except Exception as e:
            logger.warning(f"Could not ban gbanned user in the current chat ({chat.id}): {e}")

    await message.reply_html(
        f"✅ User {user_display} has been globally banned.\n"
        f"<b>Reason:</b> {html.escape(reason)}"
    )
    
    try:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        target_username = f"@{html.escape(target_user.username)}" if target_user.username else "N/A"
        
        chat_name_display = html.escape(chat.title or f"{user_who_gbans.first_name}")
        
        if chat.type != ChatType.PRIVATE and chat.username:
            message_link = f"https://t.me/{chat.username}/{message.message_id}"
            chat_name_display = f"<a href='{message_link}'>{html.escape(chat.title)}</a>"

        reason_display = html.escape(reason)

        log_message = (
            f"<b>#GBANNED</b>\n"
            f"<b>Initiated From:</b> {chat_name_display} (<code>{chat.id}</code>)\n\n"
            f"<b>User:</b> {user_display} (<code>{target_user.id}</code>)\n"
            f"<b>Username:</b> {target_username}\n"
            f"<b>Reason:</b> {reason_display}\n"
            f"<b>Admin:</b> {user_who_gbans.mention_html()}\n"
            f"<b>Date:</b> <code>{current_time}</code>"
        )
        await send_operational_log(context, log_message)
    except Exception as e:
        logger.error(f"Error preparing/sending #GBANNED operational log: {e}", exc_info=True)

async def ungban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_who_ungbans = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not message: return

    if not is_privileged_user(user_who_ungbans.id):
        logger.warning(f"Unauthorized /ungban attempt by user {user_who_ungbans.id}.")
        return

    target_user: User | None = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif context.args:
        target_id_str = context.args[0]
        try:
            if target_id_str.startswith('@'):
                target_user = get_user_from_db_by_username(target_id_str)
                if not target_user:
                    await message.reply_text(f"😿 User not found in my database. Please use their ID or reply to a message.")
                    return
            else:
                target_user = User(id=int(target_id_str), first_name=f"{int(target_id_str)}", is_bot=False)
        except (ValueError, IndexError):
            await message.reply_text("Mrow? Invalid User ID or format."); return
    else:
        await message.reply_text("Usage: /ungban <ID/@username/reply>"); return
        
    if not target_user:
        await message.reply_text("Meow. Could not identify the user to ungban."); return

    if not get_gban_reason(target_user.id):
        try:
            full_user = await context.bot.get_chat(target_user.id)
            user_display = full_user.mention_html()
        except:
            user_display = f"User <code>{target_user.id}</code>"
        await message.reply_html(f"Meow. User {user_display} is not globally banned.")
        return

    remove_from_gban(target_user.id)
    
    try:
        full_target_user = await context.bot.get_chat(target_user.id)
        user_display = full_target_user.mention_html()
        username_for_log = f"@{html.escape(full_target_user.username)}" if full_target_user.username else "N/A"
    except:
        user_display = target_user.mention_html()
        username_for_log = "N/A"

    await message.reply_html(
        f"✅ User {user_display} has been globally unbanned.\n\n"
        f"<i>Propagating unban across all known chats...</i>"
    )
    
    context.job_queue.run_once(
        propagate_unban,
        when=1,
        data={'target_user_id': target_user.id, 'command_chat_id': chat.id}
    )

    try:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        chat_name = chat.title or f"{user_who_ungbans.first_name}"

        log_message = (
            f"<b>#UNGBANNED</b>\n"
            f"<b>Initiated From:</b> {html.escape(chat_name)} (<code>{chat.id}</code>)\n\n"
            f"<b>User:</b> {user_display} (<code>{target_user.id}</code>)\n"
            f"<b>Username:</b> {username_for_log}\n"
            f"<b>Admin:</b> {user_who_ungbans.mention_html()}\n"
            f"<b>Date:</b> <code>{current_time}</code>"
        )
        await send_operational_log(context, log_message)
    except Exception as e:
        logger.error(f"Error preparing/sending #UNGBANNED operational log: {e}", exc_info=True)

async def propagate_unban(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data
    target_user_id = job_data['target_user_id']
    command_chat_id = job_data['command_chat_id']

    chats_to_scan = []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            chats_to_scan = [row[0] for row in cursor.execute("SELECT chat_id FROM bot_chats")]
    except sqlite3.Error as e:
        logger.error(f"Failed to get chat list for unban propagation: {e}")
        await context.bot.send_message(chat_id=command_chat_id, text="Error fetching chat list from database.")
        return

    if not chats_to_scan:
        await context.bot.send_message(chat_id=command_chat_id, text="I don't seem to be in any chats to propagate the unban.")
        return

    successful_unbans = 0
    
    logger.info(f"Starting unban propagation for {target_user_id} across {len(chats_to_scan)} chats.")
    
    for chat_id in chats_to_scan:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=target_user_id)
            
            if chat_member.status == 'kicked':
                success = await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_user_id)
                if success:
                    successful_unbans += 1
                    logger.info(f"Successfully unbanned {target_user_id} from chat {chat_id}.")
            
        except telegram.error.BadRequest as e:
            if "user not found" not in str(e).lower():
                logger.warning(f"Could not process unban for {target_user_id} in {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during unban propagation in {chat_id}: {e}")
            
        await asyncio.sleep(0.2)

    logger.info(f"Unban propagation finished for {target_user_id}. Succeeded in {successful_unbans} chats.")
    
    final_message = f"✅ Correctly unbanned <code>{target_user_id}</code> on {successful_unbans} chats."
    
    await context.bot.send_message(
        chat_id=command_chat_id,
        text=final_message,
        parse_mode=ParseMode.HTML
    )

async def enforce_gban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    
    if not chat or chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Meow. This command can only be used in groups.")
        return

    try:
        member = await chat.get_member(user.id)
        if member.status != "creator":
            await update.message.reply_text("Meeeow! Only the chat Creator can use this command.")
            return
    except Exception as e:
        logger.error(f"Could not verify creator status for /enforcegban: {e}")
        return

    if not context.args or len(context.args) != 1 or context.args[0].lower() not in ['yes', 'no']:
        await update.message.reply_text("Usage: /enforcegban <yes/no>")
        return
    
    choice = context.args[0].lower()
    current_status_bool = is_gban_enforced(chat.id)

    if choice == 'yes':
        permission_notice = ""
        try:
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if not (bot_member.status == "administrator" and bot_member.can_restrict_members):
                permission_notice = (
                    "\n\n<b>⚠️ Notice:</b> I do not have the 'Ban Users' permission in this chat. "
                    "The feature is enabled in settings, but I cannot enforce it until I'm granted this right."
                )
        except Exception:
            permission_notice = "\n\n<b>⚠️ Notice:</b> Could not verify my own permissions in this chat."

        if current_status_bool:
            await update.message.reply_html(
                f"ℹ️ Mrow? Global Ban enforcement is already <b>ENABLED</b> for this chat."
                f"{permission_notice}"
            )
            return
        
        setting = 1
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE bot_chats SET enforce_gban = ? WHERE chat_id = ?", (setting, chat.id))
                if cursor.rowcount == 0:
                    add_chat_to_db(chat.id, chat.title or f"Chat {chat.id}")
                    cursor.execute("UPDATE bot_chats SET enforce_gban = ? WHERE chat_id = ?", (setting, chat.id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update gban enforcement for chat {chat.id}: {e}")
            await update.message.reply_text("An error occurred while updating the setting.")
            return

        await update.message.reply_html(
            f"✅ <b>Meow! Global Ban enforcement is now ENABLED for this chat.</b>\n\n"
            f"I will now automatically remove any user from the global ban list who tries to join or speak here."
            f"{permission_notice}"
        )
        return

    if choice == 'no':
        if not current_status_bool:
            await update.message.reply_html("ℹ️ Mrow? Global Ban enforcement is already <b>DISABLED</b> for this chat.")
            return
        
        setting = 0
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE bot_chats SET enforce_gban = ? WHERE chat_id = ?", (setting, chat.id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update gban enforcement for chat {chat.id}: {e}")
            await update.message.reply_text("An error occurred while updating the setting.")
            return
        
        await update.message.reply_html(
            "❌ <b>Meow! Global Ban enforcement is now DISABLED for this chat.</b>\n\n"
            "<b>Notice:</b> This means users on the global ban list will be able to join and participate here. "
            "This may expose your community to users banned for severe offenses like spam, harassment, or illegal activities."
        )

# --- Sudo commands ---
async def add_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != OWNER_ID:
        logger.warning(f"Unauthorized /addsudo attempt by user {user.id}.")
        return

    target_user: User | None = None

    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user:
            target_user = update.message.reply_to_message.from_user
        else:
            await update.message.reply_text("Mrow? You must reply to a user's message.")
            return
    elif context.args:
        target_id_str = context.args[0]
        try:
            if target_id_str.startswith('@'):
                target_user = get_user_from_db_by_username(target_id_str)
                if not target_user:
                    chat_info = await context.bot.get_chat(target_id_str)
                    if chat_info.type == 'private':
                        target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
                    else:
                        await update.message.reply_text("Sudo can only be granted to users, not channels or groups.")
                        return
            else:
                chat_info = await context.bot.get_chat(int(target_id_str))
                if chat_info.type == 'private':
                    target_user = User(id=chat_info.id, first_name=chat_info.first_name, is_bot=False, username=chat_info.username, last_name=chat_info.last_name)
                else:
                    await update.message.reply_text("Sudo can only be granted to users, not channels or groups.")
                    return
        except (ValueError, TelegramError):
            await update.message.reply_text("Could not find that user.")
            return
    else:
        await update.message.reply_text("Usage: /addsudo <ID/@username/reply>")
        return

    if not target_user:
        await update.message.reply_text("Mrow? Could not identify the user to add to sudo.")
        return
    
    if not isinstance(target_user, User):
        await update.message.reply_text("Internal error: Target is not a valid User object.")
        return

    if target_user.id == OWNER_ID:
        await update.message.reply_text("Meow! My Owner already has ultimate power and is implicitly sudo! 😼")
        return
    if target_user.id == context.bot.id:
        await update.message.reply_text("Purr... I can't sudo myself, that's a paradox!")
        return
    if target_user.is_bot:
        await update.message.reply_text("Meeeow, I don't think other bots need sudo access.")
        return
    if is_sudo_user(target_user.id):
        user_display = target_user.mention_html()
        await update.message.reply_html(f"User {user_display} already has sudo powers.")
        return

    if add_sudo_user(target_user.id, user.id):
        logger.info(f"Owner {user.id} added sudo user {target_user.id} (@{target_user.username})")
        user_display = target_user.mention_html()
        await update.message.reply_html(f"✅ User {user_display} has been granted sudo powers!")
        
        try:
            await context.bot.send_message(target_user.id, "Meeeow! You have been granted sudo privileges by my Owner! Use them wisely. 🐾")
        except Exception as e:
            logger.warning(f"Failed to send PM to new sudo user {target_user.id}: {e}")
        
        try:
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            log_message_to_send = (
                f"<b>#SUDO</b>\n\n"
                f"<b>User:</b> {user_display} (<code>{target_user.id}</code>)\n"
                f"<b>Username:</b> @{html.escape(target_user.username) if target_user.username else 'N/A'}\n"
                f"<b>Date:</b> <code>{current_time}</code>"
            )
            await send_operational_log(context, log_message_to_send)
        except Exception as e:
            logger.error(f"Error preparing/sending #SUDO_ADDED operational log: {e}", exc_info=True)
    else:
        await update.message.reply_text("Mrow? Failed to add user to sudo list. Check logs.")

async def del_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != OWNER_ID:
        logger.warning(f"Unauthorized /delsudo attempt by user {user.id}.")
        return

    target_user: User | None = None

    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user:
            target_user = update.message.reply_to_message.from_user
        else:
            await update.message.reply_text("Mrow? You must reply to a user's message.")
            return
    elif context.args:
        target_id_str = context.args[0]
        try:
            if target_id_str.startswith('@'):
                target_user = get_user_from_db_by_username(target_id_str)
                if not target_user:
                    await update.message.reply_text(f"User {html.escape(target_id_str)} not found in my database. Please use their ID.")
                    return
            else:
                target_user = User(id=int(target_id_str), first_name=f"User {target_id_str}", is_bot=False)
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid User ID or format.")
            return
    else:
        await update.message.reply_text("Usage: /delsudo <ID/@username/reply>")
        return
        
    if not target_user:
        await update.message.reply_text("Mrow? Could not identify the user to remove from sudo.")
        return

    if not isinstance(target_user, User):
        await update.message.reply_text("Internal error: Target is not a valid User object.")
        return

    if target_user.id == OWNER_ID:
        await update.message.reply_text("Meow! The Owner's powers are inherent and cannot be revoked! 😉")
        return
    
    if not is_sudo_user(target_user.id):
        try:
            full_user = await context.bot.get_chat(target_user.id)
            user_display = full_user.mention_html()
        except:
            user_display = f"User <code>{target_user.id}</code>"
        await update.message.reply_html(f"User {user_display} does not have sudo powers.")
        return

    if remove_sudo_user(target_user.id):
        logger.info(f"Owner {user.id} removed sudo for user {target_user.id} (@{target_user.username})")
        
        try:
            full_user = await context.bot.get_chat(target_user.id)
            user_display = full_user.mention_html()
            username_for_log = f"@{html.escape(full_user.username)}" if full_user.username else "N/A"
        except:
            user_display = f"User <code>{target_user.id}</code>"
            username_for_log = "N/A"

        await update.message.reply_html(f"✅ Sudo powers for user {user_display} have been revoked.")
        
        try:
            await context.bot.send_message(target_user.id, "Meeeow... Your sudo privileges have been revoked by my Owner.")
        except Exception as e:
            logger.warning(f"Failed to send PM to revoked sudo user {target_user.id}: {e}")

        try:
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            log_message_to_send = (
                f"<b>#UNSUDO</b>\n\n"
                f"<b>User:</b> {user_display} (<code>{target_user.id}</code>)\n"
                f"<b>Username:</b> {username_for_log}\n"
                f"<b>Date:</b> <code>{current_time}</code>"
            )
            await send_operational_log(context, log_message_to_send)
        except Exception as e:
            logger.error(f"Error preparing/sending #SUDO_REMOVED operational log: {e}", exc_info=True)
    else:
        await update.message.reply_text("Mrow? Failed to remove user from sudo list. Check logs.")

async def sudo_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    
    if not is_privileged_user(user.id):
        logger.warning(f"Unauthorized /sudocmds attempt by user {user.id}.")
        return

    if chat.type == ChatType.PRIVATE:
        final_sudo_help = SUDO_COMMANDS_TEXT
        if user.id == OWNER_ID:
            final_sudo_help += "\n" + OWNER_COMMANDS_TEXT
        await update.message.reply_html(final_sudo_help, disable_web_page_preview=True)
        return

    bot_username = context.bot.username
    deep_link_url = f"https://t.me/{bot_username}?start=sudocmds"
    
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text="🛡️ Get Privileged Commands (PM)", url=deep_link_url)]
        ]
    )
    
    message_text = "Meeeow! 🐾 I've sent the list of privileged commands to your private chat. Please click the button below to see it."
    
    await send_safe_reply(update, context, text=message_text, reply_markup=keyboard)
        
async def list_sudo_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != OWNER_ID:
        logger.warning(f"Unauthorized /listsudo attempt by user {user.id}.")
        return

    sudo_user_tuples = get_all_sudo_users_from_db()

    if not sudo_user_tuples:
        await update.message.reply_text("Meeeow! There are currently no users with sudo privileges. 😼")
        return

    response_lines = ["<b>🛡️ Sudo Users List:</b>\n"]
    
    for user_id, timestamp_str in sudo_user_tuples:
        user_display_name = f"<code>{user_id}</code>"
        user_obj_from_db = get_user_from_db_by_username(str(user_id))

        if user_obj_from_db:
            display_name_parts = []
            if user_obj_from_db.first_name: display_name_parts.append(html.escape(user_obj_from_db.first_name))
            if user_obj_from_db.last_name: display_name_parts.append(html.escape(user_obj_from_db.last_name))
            if user_obj_from_db.username: display_name_parts.append(f"(@{html.escape(user_obj_from_db.username)})")
            
            if display_name_parts:
                user_display_name = " ".join(display_name_parts) + f" (<code>{user_id}</code>)"
            else:
                user_display_name = f"User (<code>{user_id}</code>)"
        else:
            try:
                chat_info = await context.bot.get_chat(user_id)
                name_parts = []
                if chat_info.first_name: name_parts.append(html.escape(chat_info.first_name))
                if chat_info.last_name: name_parts.append(html.escape(chat_info.last_name))
                if chat_info.username: name_parts.append(f"(@{html.escape(chat_info.username)})")
                
                if name_parts:
                    user_display_name = " ".join(name_parts) + f" (<code>{user_id}</code>)"
            except Exception:
                pass

        formatted_added_time = timestamp_str
        try:
            dt_obj = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            formatted_added_time = dt_obj.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            logger.warning(f"Could not parse timestamp '{timestamp_str}' for sudo user {user_id}")
            pass

        response_lines.append(f"• {user_display_name}\n<b>Added:</b> <code>{formatted_added_time}</code>\n")

    message_text = "\n".join(response_lines)
    if len(message_text) > 4000:
        message_text = "\n".join(response_lines[:15])
        message_text += f"\n\n...and {len(sudo_user_tuples) - 15} more (list too long to display fully)."
        logger.info(f"Sudo list too long, truncated for display. Total: {len(sudo_user_tuples)}")

    await update.message.reply_html(message_text)

# --- Main Function ---
def main() -> None:
    init_db()
    logger.info("Initializing bot application...")
    application = Application.builder().token(BOT_TOKEN).build()

    connect_timeout_val = 20.0
    read_timeout_val = 80.0
    write_timeout_val = 80.0
    pool_timeout_val = 20.0

    custom_request_settings = HTTPXRequest(
        connect_timeout=connect_timeout_val,
        read_timeout=read_timeout_val,
        write_timeout=write_timeout_val,
        pool_timeout=pool_timeout_val
    )

    job_queue = JobQueue()
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(custom_request_settings)
        .job_queue(job_queue)
        .build()
    )
    
    application = Application.builder().token(BOT_TOKEN).request(custom_request_settings).build()
    logger.info(f"Custom request timeouts set for HTTPXRequest: "
                f"Connect={connect_timeout_val}, Read={read_timeout_val}, "
                f"Write={write_timeout_val}, Pool={pool_timeout_val}")
    logger.info("JobQueue has been enabled.")
    
    logger.info("Registering blacklist check handler...")
    application.add_handler(MessageHandler(filters.COMMAND, check_blacklist_handler), group=-1)

    logger.info("Registering user interaction logging handler...")
    application.add_handler(MessageHandler(
        filters.ALL & (~filters.UpdateType.EDITED_MESSAGE),
        log_user_from_interaction
    ), group=10)

    logger.info("Registering global bans handler...")
    application.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND) & filters.ChatType.GROUPS,
        check_gban_on_message
    ), group=-2)

    logger.info("Registering command handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("github", github))
    application.add_handler(CommandHandler("owner", owner_info))
    application.add_handler(CommandHandler("info", entity_info_command))
    application.add_handler(CommandHandler("chatstat", chat_stat_command))
    application.add_handler(CommandHandler("cinfo", chat_info_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("kick", kick_command))
    application.add_handler(CommandHandler("kickme", kickme_command))
    application.add_handler(CommandHandler("promote", promote_command))
    application.add_handler(CommandHandler("demote", demote_command))
    application.add_handler(CommandHandler("pin", pin_message_command))
    application.add_handler(CommandHandler("unpin", unpin_message_command))
    application.add_handler(CommandHandler("purge", purge_messages_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CommandHandler("listadmins", list_admins_command))
    application.add_handler(CommandHandler("admins", list_admins_command))
    application.add_handler(CommandHandler("gif", gif))
    application.add_handler(CommandHandler("photo", photo))
    application.add_handler(CommandHandler("meow", meow))
    application.add_handler(CommandHandler("nap", nap))
    application.add_handler(CommandHandler("play", play))
    application.add_handler(CommandHandler("treat", treat))
    application.add_handler(CommandHandler("zoomies", zoomies))
    application.add_handler(CommandHandler("judge", judge))
    application.add_handler(CommandHandler("fed", fed))
    application.add_handler(CommandHandler("attack", attack))
    application.add_handler(CommandHandler("kill", kill))
    application.add_handler(CommandHandler("punch", punch))
    application.add_handler(CommandHandler("slap", slap))
    application.add_handler(CommandHandler("bite", bite))
    application.add_handler(CommandHandler("hug", hug))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("say", say))
    application.add_handler(CommandHandler("leave", leave_chat))
    application.add_handler(CommandHandler("speedtest", speedtest_command))
    application.add_handler(CommandHandler("blist", blacklist_user_command))
    application.add_handler(CommandHandler("unblist", unblacklist_user_command))
    application.add_handler(CommandHandler("gban", gban_command))
    application.add_handler(CommandHandler("ungban", ungban_command))
    application.add_handler(CommandHandler("enforcegban", enforce_gban_command))
    application.add_handler(CommandHandler("listsudo", list_sudo_users_command))
    application.add_handler(CommandHandler("sudocmds", sudo_commands_command))
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("delsudo", del_sudo_command))

    logger.info("Registering message handlers for group joins and lefts...")
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_group_members))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_left_group_member))

    async def send_simple_startup_message(app: Application) -> None:
            startup_message_text = "<i>Bot Started...</i>"
            
            target_id_for_log = LOG_CHAT_ID
            if not target_id_for_log and OWNER_ID:
                target_id_for_log = OWNER_ID
            
            if target_id_for_log:
                try:
                    await app.bot.send_message(chat_id=target_id_for_log, text=startup_message_text, parse_mode=ParseMode.HTML)
                    logger.info(f"Sent simple startup notification to {target_id_for_log}.")
                except TelegramError as e:
                    logger.error(f"Failed to send simple startup message to {target_id_for_log}: {e}")
                    if LOG_CHAT_ID and target_id_for_log == LOG_CHAT_ID and OWNER_ID and LOG_CHAT_ID != OWNER_ID:
                        logger.info("Falling back to send simple startup message to OWNER_ID.")
                        try:
                            await app.bot.send_message(chat_id=OWNER_ID, text=f"[Fallback] {startup_message_text}", parse_mode=ParseMode.HTML)
                        except Exception as e_owner:
                             logger.error(f"Failed to send simple startup message to OWNER_ID as fallback: {e_owner}")
                except Exception as e_other:
                    logger.error(f"Unexpected error sending simple startup message to {target_id_for_log}: {e_other}", exc_info=True)
    
            else:
                logger.warning("No target (LOG_CHAT_ID or OWNER_ID) to send simple startup message.")

    application.post_init = send_simple_startup_message

    logger.info(f"Bot starting polling... Owner ID configured: {OWNER_ID}")
    print(f"Bot starting polling... Owner ID: {OWNER_ID}")
    try: application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt: logger.info("Bot stopped by user (Ctrl+C)."); print("\nBot stopped by user.")
    except TelegramError as te: logger.critical(f"CRITICAL: TelegramError during polling: {te}"); print(f"\n--- FATAL TELEGRAM ERROR ---\n{te}"); exit(1)
    except Exception as e: logger.critical(f"CRITICAL: Bot crashed unexpectedly: {e}", exc_info=True); print(f"\n--- FATAL ERROR ---\nBot crashed: {e}"); exit(1)
    finally: logger.info("Bot shutdown process initiated."); print("Bot shutting down...")
    logger.info("Bot stopped."); print("Bot stopped.")

# --- Script Execution ---
if __name__ == "__main__":
    try: import requests
    except ImportError: print("\n--- DEPENDENCY ERROR ---\n'requests' required.\nPlease install: pip install requests"); exit(1)
    main()
