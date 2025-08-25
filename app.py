import os
from flask import Flask, request
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Updater, CommandHandler, CallbackContext
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
INSTAMOJO_API_KEY = os.getenv("INSTAMOJO_API_KEY")
INSTAMOJO_AUTH_TOKEN = os.getenv("INSTAMOJO_AUTH_TOKEN")
BASE_URL = os.getenv("BASE_URL")

app = Flask(__name__)

# ======================= Telegram Bot ======================
def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("₹2500 Pay Now", url="https://www.instamojo.com/@yourlink")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "🙏 Welcome! \n\n🌟 Exclusive Business Service for You 🌟\n\n"
        "⚡ Sirf ₹2500 me aapko 30 din ke liye premium access milega.\n"
        "👇 Niche button dabakar turant payment kijiye 👇",
        reply_markup=reply_markup
    )

# ======================= Flask Webhook ======================
@app.route('/instamojo-webhook', methods=['POST'])
def instamojo_webhook():
    data = request.form.to_dict()
    if data.get("status") == "Credit":
        user_id = data.get("buyer_phone")  # Yaha aap apna unique identifier rakhna hoga
        # Telegram par invite link bhejo
        invite_link = f"https://t.me/{CHANNEL_ID}?start={user_id}"
        send_message(user_id, f"✅ Payment Successful!\n\nJoin here: {invite_link}\n(Link valid 10 min only)")
    return "OK", 200

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

# ======================= Main ======================
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
