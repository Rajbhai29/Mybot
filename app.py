from flask import Flask, request
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext

import os

# ---- Config ----
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Telegram bot ka token Render env me daalna hoga
CHANNEL_ID = os.getenv("CHANNEL_ID")  # @channelusername ya numeric ID
INSTAMOJO_PAYMENT_LINK = os.getenv("INSTAMOJO_PAYMENT_LINK")  # Payment link

app = Flask(__name__)

# ---- Telegram Bot ----
def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("💳 ₹2500 Pay Now", url=INSTAMOJO_PAYMENT_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "🙏 Welcome!\n\n"
        "⚡ Exclusive Access to our Premium Channel.\n"
        "💼 Business Insights + Earning Secrets.\n\n"
        "👉 Join only ₹2500 / 30 days.\n\n"
        "Click below to Pay securely 👇",
        reply_markup=reply_markup
    )

def send_invite_link(user_id):
    # Invite link generate (temporary link banega)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    payload = {
        "chat_id": CHANNEL_ID,
        "expire_date": None,
        "member_limit": 1
    }
    r = requests.post(url, json=payload)
    data = r.json()
    if "result" in data:
        invite_link = data["result"]["invite_link"]
        # User ko bhejo
        send_text(user_id, f"🎉 Payment Successful!\n\nYeh rahi aapki Private Channel link (10 min valid):\n{invite_link}")
    else:
        send_text(user_id, "❌ Invite link generate nahi ho paaya. Admin ko contact karo.")

def send_text(user_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": user_id, "text": text}
    requests.post(url, json=payload)

# ---- Flask Webhook (Instamojo) ----
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.form.to_dict()
    print("Webhook data:", data)

    # Agar payment success mila
    if data.get("status") == "Credit":
        buyer_id = data.get("buyer_phone") or data.get("buyer_email")  # tum yahan mapping kar sakte ho
        telegram_id = data.get("purpose")  # customer ka Telegram ID "purpose" me bhejna hoga
        if telegram_id:
            send_invite_link(telegram_id)

    return "OK", 200

# ---- Start Bot Locally ----
def run_bot():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    # Flask + Bot dono ek sath run
    from threading import Thread
    Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=5000)
