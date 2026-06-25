#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram medication reminder bot.

Supports multiple medications at different times of day, some daily and some
only on specific weekdays. Sends a reminder, resends every N minutes if the
user does not confirm (up to a max), and logs every confirmation to a CSV file.

Code/comments in English. User-facing messages in Spanish.

Requires: Python 3 and the 'requests' library.
"""

import json
import time
import csv
import os
import logging
import datetime as dt
import requests

# ============================ CONFIG ============================
# Directory where this script lives (src/). The .env file sits next to it.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SRC_DIR, ".env")


def load_env(path):
    """
    Minimal .env loader (no external dependency).
    Reads KEY=VALUE lines, ignoring blanks and lines starting with '#'.
    Surrounding single/double quotes around the value are stripped.
    """
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            values[key] = val
    return values


_env = load_env(ENV_FILE)

# Token from BotFather and recipient chat ID, both read from src/.env:
TOKEN = _env.get("TELEGRAM_TOKEN", "")
CHAT_ID = _env.get("TELEGRAM_CHAT_ID", "")

# Fail early with a clear message if either is missing.
if not TOKEN or not CHAT_ID:
    raise SystemExit(
        "Faltan credenciales. Crea el archivo 'src/.env' con:\n"
        "  TELEGRAM_TOKEN=tu_token_de_botfather\n"
        "  TELEGRAM_CHAT_ID=el_chat_id\n"
        f"(se buscó en: {ENV_FILE})"
    )

# Resend behavior when not confirmed:
RESEND_INTERVAL_MIN = 2    # minutes between resends
MAX_RESENDS = 5            # how many times to resend before giving up

# ---------------------------------------------------------------
# Paths. The script lives in src/, so the project root is one level up.
# Layout:   <root>/src/pillbot.py
#           <root>/data/medication_history.csv
#           <root>/logs/pillbot.log
# ---------------------------------------------------------------
BASE_DIR = os.path.dirname(SRC_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Ensure the directories exist (no-op if already there).
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(DATA_DIR, "medication_history.csv")
LOG_FILE = os.path.join(LOGS_DIR, "pillbot.log")

# Weekday constants for readability (Python: Monday=0 ... Sunday=6):
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# ---------------------------------------------------------------
# Medication schedule.
# Each entry is a scheduled "dose event" at a given time.
#   hour, minute : when to send the reminder (24h, phone local time)
#   meds         : list of medication names taken at that time
#   days         : set of weekdays it applies to (None = every day)
# Doses sharing the same time are grouped into a single reminder.
# ---------------------------------------------------------------
SCHEDULE = [
    {"hour": 5,  "minute": 45, "meds": ["Lansoprazol"],                         "days": None},
    {"hour": 5,  "minute": 45, "meds": ["Vitamina D"],                          "days": {MON, THU}},
    {"hour": 6,  "minute": 15, "meds": ["Clopidogrel", "ASA", "Bisoprolol"],    "days": None},
    {"hour": 13, "minute": 15, "meds": ["Empagliflozina"],                      "days": None},
    {"hour": 19, "minute": 0,  "meds": ["Atorvastatina"],                       "days": None},
]
# ================================================================

API = f"https://api.telegram.org/bot{TOKEN}"

# Logging: write to logs/pillbot.log AND to the console.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pillbot")


def send_message(text, with_button=True, callback_data="taken"):
    """Send a Telegram message, optionally with a 'confirm' inline button."""
    payload = {"chat_id": CHAT_ID, "text": text}
    if with_button:
        keyboard = {
            "inline_keyboard": [[{"text": "✅ Ya las tomé", "callback_data": callback_data}]]
        }
        payload["reply_markup"] = json.dumps(keyboard)
    try:
        r = requests.post(f"{API}/sendMessage", data=payload, timeout=30)
        return r.json()
    except Exception as e:
        log.error(f"send_message: {e}")
        return None


def get_updates(offset=None, timeout=20):
    """Poll Telegram for new updates (messages / button taps)."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params, timeout=timeout + 10)
        return r.json()
    except Exception as e:
        log.error(f"get_updates: {e}")
        return {"ok": False, "result": []}


def answer_callback(callback_id, text="¡Registrado!"):
    """Acknowledge a button tap so the loading spinner clears."""
    try:
        requests.post(f"{API}/answerCallbackQuery",
                      data={"callback_query_id": callback_id, "text": text},
                      timeout=30)
    except Exception as e:
        log.error(f"answer_callback: {e}")


def log_taken(meds):
    """Append a confirmation row to the CSV: date, time, medications."""
    now = dt.datetime.now()
    is_new = not os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["fecha", "hora", "medicamentos"])
        w.writerow([now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    ", ".join(meds)])
    log.info(f"logged: {now} -> {meds}")


def build_reminder_text(meds):
    """Build the Spanish reminder message listing the medications."""
    if len(meds) == 1:
        body = f"💊 Es hora de tomar tu medicamento:\n\n• {meds[0]}"
    else:
        lines = "\n".join(f"• {m}" for m in meds)
        body = f"💊 Es hora de tomar tus medicamentos:\n\n{lines}"
    return body + "\n\nCuando los tomes, toca el botón de abajo."


def wait_for_confirmation(offset, meds):
    """
    After sending a reminder, wait for the user to confirm.
    Resend every RESEND_INTERVAL_MIN minutes, up to MAX_RESENDS.
    Returns the updated offset.
    """
    resends = 0
    next_resend = time.time() + RESEND_INTERVAL_MIN * 60

    while True:
        data = get_updates(offset=offset, timeout=20)
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            cq = upd.get("callback_query")
            if cq and cq.get("data") == "taken":
                answer_callback(cq["id"])
                log_taken(meds)
                send_message("✅ ¡Perfecto! Registrado. Gracias.", with_button=False)
                return offset

        if time.time() >= next_resend:
            if resends < MAX_RESENDS:
                resends += 1
                send_message("💊 Recordatorio: aún no confirmas tu toma.\n\n"
                             + build_reminder_text(meds), with_button=True)
                log.info(f"resend {resends}/{MAX_RESENDS}")
                next_resend = time.time() + RESEND_INTERVAL_MIN * 60
            else:
                send_message("⚠️ No recibimos confirmación de esta toma. "
                             "Por favor recuerda tomar tu medicamento.",
                             with_button=False)
                log.info("gave up on this dose")
                return offset


def dose_applies_today(dose, weekday):
    """True if this dose should fire on the given weekday."""
    return dose["days"] is None or weekday in dose["days"]


def next_occurrence(dose, now):
    """Return the next datetime this dose should fire, at or after 'now'."""
    candidate = now.replace(hour=dose["hour"], minute=dose["minute"],
                            second=0, microsecond=0)
    # Move forward day by day until it's in the future AND applies that weekday.
    while candidate <= now or not dose_applies_today(dose, candidate.weekday()):
        candidate += dt.timedelta(days=1)
        candidate = candidate.replace(hour=dose["hour"], minute=dose["minute"],
                                      second=0, microsecond=0)
    return candidate


def get_current_offset():
    """Drop any pending old updates at startup so we don't process stale taps."""
    data = get_updates(timeout=1)
    offset = None
    for upd in data.get("result", []):
        offset = upd["update_id"] + 1
    return offset


def main():
    log.info("PillBot running.")
    for d in SCHEDULE:
        days = "todos los días" if d["days"] is None else f"días {sorted(d['days'])}"
        log.info(f"schedule {d['hour']:02d}:{d['minute']:02d} {d['meds']} ({days})")

    offset = get_current_offset()

    while True:
        now = dt.datetime.now()
        # Compute the next occurrence for every dose.
        upcoming = [(next_occurrence(d, now), d) for d in SCHEDULE]
        fire_time = min(t for t, _ in upcoming)

        # Group ALL doses that fire at that same moment (e.g. 5:45 Mon has
        # both Lansoprazol and Vitamina D). Merge their meds into one reminder.
        meds = []
        for t, d in upcoming:
            if t == fire_time:
                meds.extend(d["meds"])

        wait_s = (fire_time - now).total_seconds()
        log.info(f"next: {meds} at {fire_time} "
                 f"(in {int(wait_s // 3600)}h {int((wait_s % 3600) // 60)}m)")
        time.sleep(max(1, wait_s))

        send_message(build_reminder_text(meds), with_button=True)
        log.info(f"reminder sent for {meds}")
        offset = wait_for_confirmation(offset, meds)

        # Sleep past this minute so we don't immediately re-trigger the same dose.
        time.sleep(60)


if __name__ == "__main__":
    main()