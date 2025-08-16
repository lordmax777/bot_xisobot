from flask import Flask
import threading
import zarina_bot  # fayl nomi: zarina_bot.py

app = Flask(__name__)   # Flask obyektining nomi "app" bo‘lishi shart

@app.route('/')
def home():
    return "ZarinaBot CRM ishlayapti 🚀"

def run_bot():
    zarina_bot.run()  # zarina_bot.py ichidagi run() funksiyasini chaqiramiz

# Flask server ishga tushayotganda bot ham parallel ishlaydi
threading.Thread(target=run_bot, daemon=True).start()
