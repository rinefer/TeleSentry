"""
Database module for storing and managing bot data.
Handles all database operations including:
- Deleted messages storage
- User data storage
- Profile monitoring snapshots
- Tracked profiles for monitoring
"""

import sqlite3
import datetime

def adapt_datetime(dt):
    """Convert datetime object to ISO format string for database storage"""
    return dt.isoformat()

def convert_datetime(ts):
    """Convert ISO format string from database back to datetime object"""
    return datetime.datetime.fromisoformat(ts.decode())

# Register datetime adapters and converters for SQLite
sqlite3.register_adapter(datetime.datetime, adapt_datetime)
sqlite3.register_converter("datetime", convert_datetime)

# Initialize database connection with datetime support
conn = sqlite3.connect(
    'deleted_messages.db',
    detect_types=sqlite3.PARSE_DECLTYPES
)
cursor = conn.cursor()

# Create table for storing deleted messages with all relevant metadata
cursor.execute('DROP TABLE IF EXISTS deleted_messages')
cursor.execute('''
CREATE TABLE deleted_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    chat_name TEXT,
    sender_id INTEGER,
    sender_name TEXT,
    message_text TEXT,
    message_date datetime,
    deleted_at datetime,
    media_path TEXT,
    media_type TEXT,
    is_view_once BOOLEAN DEFAULT 0
)
''')

# Create table for storing parsed user data with comprehensive user information
cursor.execute('DROP TABLE IF EXISTS parsed_users')
cursor.execute('''
CREATE TABLE parsed_users (
    id INTEGER PRIMARY KEY,
    access_hash INTEGER,
    first_name TEXT,
    last_name TEXT,
    username TEXT,
    phone TEXT,
    is_bot BOOLEAN,
    is_restricted BOOLEAN,
    is_scam BOOLEAN,
    is_fake BOOLEAN,
    is_verified BOOLEAN,
    language TEXT,
    last_seen datetime,
    is_admin BOOLEAN,
    is_deleted BOOLEAN,
    parsed_at datetime DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(id)
)
''')

# Create table for storing profile snapshots for monitoring purposes
cursor.execute('''
CREATE TABLE IF NOT EXISTS profile_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    bio TEXT,
    restricted BOOLEAN,
    verified BOOLEAN,
    premium BOOLEAN,
    last_check datetime,
    created_at datetime DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES parsed_users(id)
)
''')

# Create table for tracking which profiles are being monitored
cursor.execute('''
CREATE TABLE IF NOT EXISTS monitored_profiles (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    created_at datetime DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES parsed_users(id)
)
''')
conn.commit()

def save_user_to_db(user_data):
    """
    Save user data to database with duplicate checking.
    Uses INSERT OR IGNORE to prevent duplicate entries.

    Args:
        user_data (dict): Dictionary containing user information with keys:
            - id: User ID
            - access_hash: User access hash
            - first_name: First name
            - last_name: Last name
            - username: Username
            - phone: Phone number
            - is_bot: Boolean indicating if user is a bot
            - is_restricted: Boolean indicating if user is restricted
            - is_scam: Boolean indicating if user is marked as scam
            - is_fake: Boolean indicating if user is fake
            - is_verified: Boolean indicating if user is verified
            - language: User language code
            - last_seen: Last seen timestamp
            - is_admin: Boolean indicating if user has admin rights
            - is_deleted: Boolean indicating if user is deleted

    Returns:
        bool: True if user was saved or already exists, False on error
    """
    try:
        cursor.execute('''
        INSERT OR IGNORE INTO parsed_users
        (id, access_hash, first_name, last_name, username, phone,
         is_bot, is_restricted, is_scam, is_fake, is_verified, language, last_seen, is_admin, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_data['id'],
            user_data['access_hash'],
            user_data['first_name'],
            user_data['last_name'],
            user_data['username'],
            user_data['phone'],
            user_data.get('is_bot', False),
            user_data.get('is_restricted', False),
            user_data.get('is_scam', False),
            user_data.get('is_fake', False),
            user_data.get('is_verified', False),
            user_data.get('language', ''),
            user_data.get('last_seen', None),
            user_data.get('is_admin', False),
            user_data.get('is_deleted', False)
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving user to database: {e}")
        return False

def save_profile_snapshot(user_id, profile_data):
    """
    Save a snapshot of user profile for monitoring purposes.
    Stores all relevant profile information at a specific point in time.

    Args:
        user_id (int): Telegram user ID
        profile_data (dict): Dictionary containing profile information with keys:
            - username: Current username
            - first_name: Current first name
            - last_name: Current last name
            - phone: Current phone number
            - bio: Current bio/about text
            - restricted: Current restricted status
            - verified: Current verified status
            - premium: Current premium status
            - last_check: Timestamp of when this snapshot was taken

    Returns:
        bool: True if snapshot was saved successfully, False on error
    """
    try:
        cursor.execute('''
        INSERT INTO profile_snapshots
        (user_id, username, first_name, last_name, phone, bio,
         restricted, verified, premium, last_check)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            profile_data['username'],
            profile_data['first_name'],
            profile_data['last_name'],
            profile_data['phone'],
            profile_data['bio'],
            profile_data['restricted'],
            profile_data['verified'],
            profile_data['premium'],
            profile_data['last_check']
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving profile snapshot: {e}")
        return False

def get_last_profile_snapshot(user_id):
    """
    Retrieve the most recent profile snapshot for a user.
    Used to compare current state with previous state for change detection.

    Args:
        user_id (int): Telegram user ID

    Returns:
        tuple: Row containing profile snapshot data or None if not found
    """
    try:
        cursor.execute('''
        SELECT username, first_name, last_name, phone, bio,
               restricted, verified, premium, last_check
        FROM profile_snapshots
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        ''', (user_id,))
        return cursor.fetchone()
    except Exception as e:
        print(f"Error getting last profile snapshot: {e}")
        return None

def add_monitored_profile(user_id, chat_id):
    """
    Add a profile to the monitoring list.
    Profiles in this list will be checked for changes periodically.

    Args:
        user_id (int): Telegram user ID to monitor
        chat_id (int): Chat ID where notifications should be sent

    Returns:
        bool: True if profile was added successfully, False on error
    """
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO monitored_profiles
        (user_id, chat_id)
        VALUES (?, ?)
        ''', (user_id, chat_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding profile to monitoring: {e}")
        return False

def remove_monitored_profile(user_id):
    """
    Remove a profile from the monitoring list.
    Profile will no longer be checked for changes.

    Args:
        user_id (int): Telegram user ID to remove from monitoring

    Returns:
        bool: True if profile was removed successfully, False on error
    """
    try:
        cursor.execute('DELETE FROM monitored_profiles WHERE user_id = ?', (user_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error removing profile from monitoring: {e}")
        return False

def get_monitored_profiles():
    """
    Get list of all profiles currently being monitored.

    Returns:
        list: List of tuples containing (user_id, chat_id) for monitored profiles
    """
    try:
        cursor.execute('SELECT user_id, chat_id FROM monitored_profiles')
        return cursor.fetchall()
    except Exception as e:
        print(f"Error getting monitored profiles: {e}")
        return []

def get_user_count():
    """
    Get count of unique users in the database.
    Used for statistics and monitoring database size.

    Returns:
        int: Count of unique users in the database
    """
    try:
        cursor.execute('SELECT COUNT(*) FROM parsed_users')
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"Error getting user count: {e}")
        return 0
