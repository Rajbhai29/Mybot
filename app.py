import os, json, time, threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, abort, redirect
import requests

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
from apscheduler.schedulers.background import BackgroundScheduler

# ---------- ENV / CONFIG ----------
IST = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]           # e.g. -100xxxxxxxxxx
BASE_URL = os.environ["BASE_URL"].rstrip("/")
PRICE_INR = int(os.environ.get("PRICE_INR", "2500"))
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))
INVITE_LINK_TTL_SECONDS = int(os.environ.get("INVITE_LINK_TTL_SECONDS", "600"))
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# Instamojo
IM_API_BASE = "https://www.instamojo.com/api/1.1"
IM_BEARER = os.environ.get("INSTAMOJO_AUTH_TOKEN", "").strip()
IM_KEY = os.environ.get("INSTAMOJO_API_KEY", "").strip()
IM_TOKEN = os.environ.get("INSTAMOJO_API_TOKEN", "").strip()

def im_headers():
    if IM_BEARER:
        return {
            "Authorization": f"Bearer {IM_BEARER}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    return {
        "X-Api-Key": IM_KEY,
        "X-Auth-Token": IM_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded",
    }

# ---------- LIGHT DB ----------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "subscribers.json")

def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(db):
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)

DB = load_db()  # { "<tg_id>": {expiry_ts:int, status:"active|expired", last_payment:"iso"} }

# ---------- TELEGRAM (WEBHOOK MODE) ----------
bot = Bot(BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=0)

WELCOME = (
    "🙏 *Welcome!*\n\n"
    "एक सही फैसला आपकी दिशा बदल सकता है.\n"
    "हमारी *premium community* में रोज curated insights, discipline और guidance—\n"
    "ताकि अगले 30 दिनों में आप लगातार बेहतर decisions ले सकें.\n\n"
    f"💰 *Fee:* ₹{PRICE_INR}/month\n"
    "👇 सुरक्षित भुगतान करें और तुरंत जुड़ें:"
)

def pay_button(uid: int):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"💳 Pay ₹{PRICE_INR} & Join", url=f"{BASE_URL}/pay?tg={uid}")]]
    )

def cmd_start(update: Update, ctx):
    uid = update.effective_user.id
    update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=pay_button(uid))

dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, lambda u,c: u.message.reply_text("Pay button दबाकर subscribe करें.")))

# ---------- FLASK APP ----------
app = Flask(__name__)

@app.get("/")
def health():
    return {"ok": True, "time": datetime.now(IST).isoformat()}

# Telegram webhook endpoint
@app.post(f"/{BOT_TOKEN}")
def tg_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

# helper to set webhook
@app.get("/set-webhook")
def set_webhook():
    url = f"{BASE_URL}/{BOT_TOKEN}"
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook", params={"url": url}, timeout=20)
    return r.json(), 200

# Create Instamojo payment request and redirect user to checkout
@app.get("/pay")
def create_payment():
    tg = request.args.get("tg", "").strip()
    if not tg.isdigit(): return "Invalid user", 400
    payload = {
        "purpose": "Premium Membership",
        "amount": str(PRICE_INR),
        "redirect_url": f"{BASE_URL}/payment-return",
        "webhook": f"{BASE_URL}/instamojo-webhook",
        "allow_repeated_payments": "false",
        "metadata": json.dumps({"telegram_user_id": tg}),
    }
    body = "&".join([f"{k}={requests.utils.quote(v)}" for k, v in payload.items()])
    r = requests.post(f"{IM_API_BASE}/payment-requests/", data=body, headers=im_headers(), timeout=20)
    r.raise_for_status()
    pr = r.json()["payment_request"]
    return redirect(pr["longurl"], code=302)

@app.get("/payment-return")
def payment_return():
    return "<h3>Thanks! Check your Telegram for the invite link.</h3>"

# Instamojo webhook → verify & DM invite
@app.post("/instamojo-webhook")
def instamojo_webhook():
    form = request.form.to_dict()
    req_id = form.get("payment_request_id") or form.get("payment_request") or ""
    if not req_id: return "missing request id", 200

    try:
        ver = requests.get(f"{IM_API_BASE}/payment-requests/{req_id}/", headers=im_headers(), timeout=20)
        ver.raise_for_status()
        pr = ver.json().get("payment_request", {})
    except Exception:
        return "verify failed", 200

    status = pr.get("status", "")
    if status not in ("Completed", "Credit", "Success"):
        return "ignored", 200

    meta = pr.get("metadata") or {}
    if isinstance(meta, str):
        try: meta = json.loads(meta)
        except Exception: meta = {}
    tg_id = str(meta.get("telegram_user_id", "")).strip()
    if not tg_id.isdigit(): return "no user", 200

    # Success → invite + record
    try:
        invite = create_single_use_invite(INVITE_LINK_TTL_SECONDS)
        expiry = datetime.now(IST) + timedelta(days=SUBSCRIPTION_DAYS)
        DB[tg_id] = {"expiry_ts": int(expiry.timestamp()), "last_payment": datetime.now(IST).isoformat(), "status": "active"}
        save_db(DB)
        text = (f"✅ *Payment Successful!*\n\n"
                f"यह आपकी *private invite link* है (1 बार valid, {INVITE_LINK_TTL_SECONDS//60} मिनट में expire):\n"
                f"{invite}\n\n"
                f"_Access valid for {SUBSCRIPTION_DAYS} days._")
        safe_dm(int(tg_id), text)
    except Exception:
        pass

    return "ok", 200

# manual expiry trigger (Render Cron)
@app.get("/run-expiry")
def run_expiry():
    if CRON_SECRET and request.headers.get("X-CRON-SECRET") != CRON_SECRET:
        abort(401)
    count = do_expiry()
    return jsonify({"expired": count, "ts": int(datetime.now(IST).timestamp())})

# ---------- HELPERS ----------
def create_single_use_invite(ttl_seconds: int) -> str:
    expire_unix = int(time.time()) + max(60, ttl_seconds)
    res = bot.create_chat_invite_link(chat_id=CHANNEL_ID, expire_date=expire_unix, member_limit=1)
    return res.invite_link

def safe_dm(user_id: int, text: str):
    try:
        bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

def do_expiry() -> int:
    now_ts = int(datetime.now(IST).timestamp())
    changed = 0
    for uid, rec in list(DB.items()):
        if rec.get("status") == "active" and int(rec.get("expiry_ts", 0)) <= now_ts:
            try:
                bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=int(uid))
                bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(uid), only_if_banned=True)
            except Exception:
                pass
            DB[uid]["status"] = "expired"
            DB[uid]["expired_at"] = datetime.now(IST).isoformat()
            changed += 1
            # rejoin DM
            try:
                safe_dm(int(uid), f"🚫 आपकी subscription खत्म हो गई है.\nदोबारा जुड़ने के लिए पेमेंट करें:\n{BASE_URL}/pay?tg={uid}")
            except Exception:
                pass
    if changed:
        save_db(DB)
    return changed

# Optional: in-process daily schedule (best-effort; use Render Cron for reliability)
scheduler = BackgroundScheduler(timezone=str(IST))
scheduler.add_job(do_expiry, "cron", hour=2, minute=5)
scheduler.start()
