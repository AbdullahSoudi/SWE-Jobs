"""
Cleanup: deletes join/leave service messages from the Telegram group.
Runs every cycle to keep the group clean.
"""

import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID

log = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def cleanup_join_messages():
    """Fetch recent updates and delete any join/leave service messages."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_GROUP_ID:
        return

    try:
        # Get recent updates
        resp = requests.get(
            f"{TELEGRAM_API}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]'},
            timeout=10,
        )
        if resp.status_code != 200:
            return

        data = resp.json()
        if not data.get("ok"):
            return

        deleted = 0
        max_update_id = None

        for update in data.get("result", []):
            max_update_id = update.get("update_id")
            msg = update.get("message", {})

            # Check if it's from our group
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != str(TELEGRAM_GROUP_ID):
                continue

            # Check if it's a service message (join/leave)
            is_service = (
                msg.get("new_chat_members")
                or msg.get("left_chat_member")
                or msg.get("new_chat_participant")
                or msg.get("left_chat_participant")
                or msg.get("new_chat_title")
                or msg.get("new_chat_photo")
                or msg.get("group_chat_created")
                or msg.get("supergroup_chat_created")
            )

            if is_service and msg.get("message_id"):
                success = _delete_message(chat_id, msg["message_id"])
                if success:
                    deleted += 1

        # Mark updates as read so we don't process them again
        if max_update_id is not None:
            requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": max_update_id + 1, "timeout": 0},
                timeout=5,
            )

        if deleted > 0:
            log.info(f"🧹 Cleaned up {deleted} join/leave messages.")

    except requests.RequestException as e:
        log.warning(f"Cleanup failed: {e}")


def _delete_message(chat_id: str, message_id: int) -> bool:
    """Delete a single message."""
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False
