import os
import phonenumbers
import random
import string

# Telegram API credentials
api_id =   # Your API ID (get it from my.telegram.org)
api_hash = ''  # Your API Hash

# Device masking settings to avoid detection
DEVICE_SETTINGS = {
    'device_model': "HP Pavilion 15",  # Device model
    'app_version': "Telegram Desktop 4.16.7",  # Telegram version for Windows
    'system_version': "Windows 11 23H2",  # OS version
    'lang_code': "en",  # Interface language
    'system_lang_code': "en-US",  # System language
    'flood_sleep_threshold': 60  # Flood protection threshold
}

# Fixed session name
session_name = 'telesentry_session'

# Directory paths
media_folder = 'saved_media'
txt_logs_folder = 'deleted_messages_logs'
BOT_VERSION = '2.1'

# Admin IDs (can be multiple)
# To get your ID, send /myid command to the bot
ADMIN_IDS = []  # Replace with your IDs

# Notification chat IDs (None to disable)
NOTIFY_CHAT_ID = []  # Can specify group (-100...)

# Log chat ID (None to disable)
LOG_CHAT_ID = []  # Replace with your log chat ID (-100...)

# API keys for OSINT services
INTELX_API_KEY = ""  # Get from https://intelx.io/
LEAKLOOKUP_API_KEY = ""  # Get from https://leak-lookup.com/
LEAKIX_API_KEY = ""  # Get from https://leakix.net/

# Security settings
SECURITY_SETTINGS = {
    'session_masking': True,  # Session name masking
    'rate_limit': 30,  # Delay between requests in seconds
    'max_retries': 3,  # Maximum retry attempts on errors
    'log_sensitive_data': False,  # Whether to log sensitive data
    'auto_update_check': True  # Check for updates
}

# Create necessary directories
os.makedirs(media_folder, exist_ok=True)
os.makedirs(txt_logs_folder, exist_ok=True)
os.makedirs(os.path.join(media_folder, 'temp'), exist_ok=True)

# Set default region for phonenumbers
try:
    phonenumbers.example_number_for_type("RU", phonenumbers.PhoneNumberType.MOBILE)
except:
    phonenumbers.set_default_region("RU")
