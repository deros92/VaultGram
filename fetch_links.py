"""
Telegram Link Inbox — CAPTURE stage (on-demand, local).

Usage:
    python fetch_links.py            # normal poll: reads new messages, filters by
                                      # allowed_user_id, queues the links found and
                                      # regenerates the "Pending Links.md" note in your
                                      # Obsidian vault.
    python fetch_links.py --whoami   # setup mode: prints the from.id of whoever recently
                                      # messaged the bot, without filtering or touching
                                      # state. Only needed once, to discover your own
                                      # allowed_user_id.
    python fetch_links.py --cleanup  # deletes the original Telegram messages for every
                                      # item already marked "processed" or "duplicate" in
                                      # the queue (used by the /process-link-inbox skill
                                      # after archiving a link). Items marked "failed" are
                                      # intentionally never touched — see README.

No external dependencies: standard library only, so it drops into any Python 3
environment without a pip install.
The bot uses polling (getUpdates), never a webhook: no listening server, no open port.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.local.json"
DATA_DIR = BASE_DIR / "data"
QUEUE_PATH = DATA_DIR / "queue.jsonl"
STATE_PATH = DATA_DIR / "state.json"

URL_RE = re.compile(r"https?://\S+")


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Missing {CONFIG_PATH}.\n"
            f"Copy config.example.json to config.local.json and fill it in "
            f"(bot_token, allowed_user_id, vault_path). See README.md."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_update_id": 0}


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def api_call(bot_token, method, params=None, timeout=15):
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"HTTP error from Telegram ({e.code}) on {method}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach Telegram ({method}): {e}")


def get_updates(bot_token, offset=None):
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    data = api_call(bot_token, "getUpdates", params)
    if not data.get("ok"):
        sys.exit(f"getUpdates failed: {data}")
    return data["result"]


def send_message(bot_token, chat_id, text):
    try:
        api_call(
            bot_token,
            "sendMessage",
            {"chat_id": chat_id, "text": text},
        )
    except SystemExit:
        # A failed confirmation message must not fail the whole run.
        print("Warning: could not send the confirmation message on Telegram.", file=sys.stderr)


def delete_message(bot_token, chat_id, message_id):
    """Delete a message in a private chat. Telegram lets bots delete incoming
    messages in private chats (i.e. messages the user sent to the bot).
    Deletion is permanent, on both sides — no trash/undo. Not fatal if it
    fails (e.g. message too old or already deleted): one undeletable item
    must not block the rest."""
    try:
        data = api_call(bot_token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        return bool(data.get("ok"))
    except SystemExit as e:
        print(f"Warning: could not delete message {message_id}: {e}", file=sys.stderr)
        return False


def whoami(bot_token):
    updates = get_updates(bot_token)
    if not updates:
        print(
            "No recent messages found. Send a message to the bot on Telegram "
            "and re-run this command."
        )
        return
    seen = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg or "from" not in msg:
            continue
        frm = msg["from"]
        seen[frm["id"]] = frm
    if not seen:
        print("No sender found in the recent updates.")
        return
    print("Senders found (use the numeric id as allowed_user_id):")
    for uid, frm in seen.items():
        name = frm.get("username") or frm.get("first_name") or "?"
        print(f"  id={uid}  ({name})")


def read_queue():
    if not QUEUE_PATH.exists():
        return []
    items = []
    with open(QUEUE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def append_queue(new_items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, "a", encoding="utf-8") as f:
        for item in new_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_queue(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def regenerate_inbox_note(vault_path):
    inbox_dir = Path(vault_path) / "_Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    note_path = inbox_dir / "Pending Links.md"

    all_items = read_queue()
    pending = [item for item in all_items if item.get("status") == "pending"]
    failed = [item for item in all_items if item.get("status") == "failed"]

    lines = ["# Pending Links", ""]
    if not pending:
        lines.append("_No pending links. ✅_")
    else:
        for item in pending:
            note = item.get("note", "").strip()
            suffix = f" — {note}" if note else ""
            lines.append(f"- [ ] {item['url']}{suffix} ({item['date']})")

    if failed:
        lines.append("")
        lines.append("## Unrecoverable content (needs manual attention)")
        lines.append(
            "_These links were not archived: their content could not be "
            "recovered automatically. They are also kept on the Telegram bot "
            "(not deleted) until you resolve them — e.g. by reading them "
            "manually or clipping them with Obsidian Web Clipper._"
        )
        for item in failed:
            reason = item.get("fail_reason", "").strip()
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- [ ] {item['url']}{suffix} ({item['date']})")

    lines.append("")
    lines.append(
        "> This file is regenerated automatically by `fetch_links.py` "
        "(telegram-obsidian-link-inbox). Do not edit it by hand: changes are "
        "overwritten on the next run. To mark a link as processed, use the "
        "`/process-link-inbox` skill."
    )

    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return note_path, len(pending)


def extract_links(text):
    if not text:
        return [], text or ""
    urls = URL_RE.findall(text)
    remainder = URL_RE.sub("", text).strip()
    remainder = re.sub(r"\s+", " ", remainder)
    return urls, remainder


def poll(config):
    bot_token = config["bot_token"]
    allowed_user_id = config["allowed_user_id"]
    vault_path = config.get("vault_path")

    if not allowed_user_id:
        sys.exit("allowed_user_id is not set in config.local.json. Run --whoami first.")
    if not vault_path:
        sys.exit("vault_path is not set in config.local.json. Point it at your Obsidian vault.")

    state = load_state()
    updates = get_updates(bot_token, offset=state["last_update_id"] + 1)

    # url -> id of the queue item that captured it first (any status:
    # pending/processed/duplicate/failed), to recognize duplicates across runs.
    seen_urls = {item["url"]: item["id"] for item in read_queue()}

    max_update_id = state["last_update_id"]
    new_items = []
    duplicate_count = 0
    last_authorized_chat_id = None
    skipped_unauthorized = 0

    for upd in updates:
        max_update_id = max(max_update_id, upd["update_id"])
        msg = upd.get("message")
        if not msg or "from" not in msg:
            continue

        if msg["from"]["id"] != allowed_user_id:
            skipped_unauthorized += 1
            continue  # silently discarded: no reply, no action

        last_authorized_chat_id = msg["chat"]["id"]
        text = msg.get("text") or msg.get("caption") or ""
        urls, note = extract_links(text)
        if not urls:
            print(f"Message without a link ignored: {text[:80]!r}", file=sys.stderr)
            continue

        msg_date = datetime.fromtimestamp(msg["date"], tz=timezone.utc).isoformat()
        for i, url in enumerate(urls):
            item_id = f"{msg['message_id']}-{i}"
            item = {
                "id": item_id,
                "message_id": msg["message_id"],
                "chat_id": msg["chat"]["id"],
                "date": msg_date,
                "url": url,
                "note": note,
            }
            if url in seen_urls:
                # Already captured before (even earlier in this same run):
                # must not be summarized twice, but the Telegram message
                # still gets cleaned up like a processed one.
                item["status"] = "duplicate"
                item["duplicate_of"] = seen_urls[url]
                duplicate_count += 1
            else:
                item["status"] = "pending"
                seen_urls[url] = item_id
            new_items.append(item)

    if new_items:
        append_queue(new_items)

    state["last_update_id"] = max_update_id
    save_state(state)

    note_path, pending_count = regenerate_inbox_note(vault_path)
    new_pending = len(new_items) - duplicate_count

    print(f"New links queued: {new_pending}")
    if duplicate_count:
        print(f"Duplicates (already seen before, skipped): {duplicate_count}")
    if skipped_unauthorized:
        print(f"Messages discarded (unauthorized sender): {skipped_unauthorized}")
    print(f"Total pending links: {pending_count}  ({note_path})")

    if new_items and last_authorized_chat_id is not None:
        dup_note = f" ({duplicate_count} duplicate(s) skipped)" if duplicate_count else ""
        send_message(
            bot_token,
            last_authorized_chat_id,
            f"✅ {new_pending} new link(s) queued{dup_note} ({pending_count} pending in total).",
        )


# "failed" is deliberately excluded: if a link was never archived with real
# content (fetch impossible, no fallback available), the original Telegram
# message must NOT be deleted — it should stay visible in the chat as a
# reminder of what's still missing, until it's resolved (read manually,
# re-clipped, etc.). See also the dedicated section in Pending Links.md.
CLEANUP_STATUSES = ("processed", "duplicate")


def cleanup(config):
    """Delete on Telegram the original messages for every item already
    'processed' or 'duplicate' (a link already seen, never summarized again
    but still worth clearing from the chat) and not yet deleted. A message
    can contain more than one link (several queue items sharing the same
    message_id): it only gets deleted once."""
    bot_token = config["bot_token"]
    items = read_queue()

    to_delete = {}  # (chat_id, message_id) -> True
    for item in items:
        if item.get("status") in CLEANUP_STATUSES and not item.get("telegram_deleted"):
            if "message_id" in item and "chat_id" in item:
                to_delete[(item["chat_id"], item["message_id"])] = True
            else:
                # Older items captured before message_id/chat_id were saved
                # in the queue: cannot be deleted automatically.
                pass

    if not to_delete:
        print("Nothing to delete on Telegram.")
        return

    deleted_keys = set()
    for chat_id, message_id in to_delete:
        ok = delete_message(bot_token, chat_id, message_id)
        if ok:
            deleted_keys.add((chat_id, message_id))

    for item in items:
        key = (item.get("chat_id"), item.get("message_id"))
        if item.get("status") in CLEANUP_STATUSES and key in deleted_keys:
            item["telegram_deleted"] = True

    write_queue(items)
    print(f"Messages deleted on Telegram: {len(deleted_keys)}/{len(to_delete)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--whoami",
        action="store_true",
        help="Print recent senders' ids, for initial setup.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete on Telegram the original messages of items already processed/duplicate.",
    )
    args = parser.parse_args()

    if args.cleanup:
        config = load_config()
        cleanup(config)
        return

    if args.whoami:
        # --whoami doesn't need a complete config.local.json: bot_token is enough.
        if CONFIG_PATH.exists():
            config = load_config()
        else:
            sys.exit(
                f"Missing {CONFIG_PATH}. Copy config.example.json to config.local.json "
                f"and set at least bot_token (you can leave allowed_user_id at 0 for now)."
            )
        whoami(config["bot_token"])
        return

    config = load_config()
    poll(config)


if __name__ == "__main__":
    main()
