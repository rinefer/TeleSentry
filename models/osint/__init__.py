"""
OSINT module for the Telegram bot.
Contains functions for searching information by usernames, phone numbers and emails.
"""

from telethon import events
from .username_search import handle_username_search
from .phone_search import handle_number_user
from .email_search import handle_email_search

def register_handlers(client):
    """Registers handlers for OSINT commands"""

    @client.on(events.NewMessage(pattern='/username_search'))
    async def handle_username_search_event(event):
        """Handler for /username_search command"""
        await handle_username_search(event, client)

    @client.on(events.NewMessage(pattern='/number_user'))
    async def handle_number_user_event(event):
        """Handler for /number_user command"""
        await handle_number_user(event, client)

    @client.on(events.NewMessage(pattern='/email_search'))
    async def handle_email_search_event(event):
        """Handler for /email_search command"""
        await handle_email_search(event, client)
