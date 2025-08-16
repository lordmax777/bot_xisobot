# pastel_bot_full.py
import os
import re
import math
import traceback
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler

import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================
# CONFIG
# ==========================
BOT_TOKEN = "8006607092:AAFYn1bRzWv__A-5lu4GXQ38-P_EjHdWPQ0"   # <--- o'zingizni tokenni shu yerga qo'ying
ADMINS = [123456789]  # <--- o'z Telegram ID'ingizni shu yerga qo'shing (int), bir nechta bo'lsa vergul bilan qo'shing
SHEET_NAME = "Pastel_Mijozlar"
CLIENTS_SHEET = "Mijozlar"
PAYMENTS_SHEET = "To‘lovlar"
PER_PAGE = 10   # sahifalash uchun nechta mijoz bir sahifada
DAILY_NOTIFY_HOUR = 9   # 24h formatda — eslatma yuborish soati
DAILY_NOTIFY_MINUTE = 0

# ==========================
# INIT BOT + SHEETS
# ==========================
bot = telebot.TeleBot(BOT_TOKEN)

# Google Sheets auth
CREDS_FILE = "credentials.json"
if not os.path.exists(CREDS_FILE):
    raise SystemExit("credentials.json topilmadi. Google Service Account credentials faylini joylang.")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
gc = gspread.authorize(creds)

try:
    workbook = gc.open(SHEET_NAME)
    sheet = workbook.worksheet(CLIENTS_SHEET)
    payments_sheet = workbook.worksheet(PAYMENTS_SHEET)
except Exception as e:
    raise SystemExit(f"Google Sheet ochishda xato: {e}")

# Temporary user state storage
user_state = {}  # chat_id -> dict

# ==========================
# HELPERS
# ==========================
def normalize_phone(p: str) -> str:
    """Telefon raqamni normalize qilish — + va raqamlar qoladi, leading zeros handled."""
    if not p:
        return ""
    p = str(p).strip()
    # remove spaces, parentheses, dashes etc
    cleaned = re.sub(r"[^\d+]", "", p)
    # If multiple +, keep first
    if cleaned.count("+") > 1:
        cleaned = cleaned.replace("+", "")
        cleaned = "+" + cleaned
    # If no plus and looks like local (starts with 998...), add +
    if not cleaned.startswith("+") and len(cleaned) >= 9:
        cleaned = "+" + cleaned
    return cleaned

def safe_int(val, default=0):
    try:
        return int(val)
    except:
        return default

def get_headers_map():
    """Return dict mapping header name -> column index (1-based)."""
    try:
        headers = sheet.row_values(1)
        return {h: idx+1 for idx, h in enumerate(headers)}
    except Exception:
        return {}

def get_all_clients():
    try:
        return sheet.get_all_records()
    except Exception:
        traceback.print_exc()
        return []

def find_client_row_by_phone(phone: str):
    phone_n = normalize_phone(phone)
    records = get_all_clients()
    for i, rec in enumerate(records, start=2):
        rec_phone = normalize_phone(str(rec.get("Telefon", "")))
        if rec_phone and rec_phone == phone_n:
            return i, rec
    return None, None

def find_clients_by_query(q: str):
    """Search by name, phone or product (case-insensitive, substring). Returns list of (row,rec)."""
    ql = q.strip().lower()
    out = []
    records = get_all_clients()
    for i, rec in enumerate(records, start=2):
        name = str(rec.get("Ism", "")).lower()
        phone = str(rec.get("Telefon", "")).lower()
        prod = str(rec.get("Mahsulot", "")).lower()
        if ql in name or ql in phone or ql in prod:
            out.append((i, rec))
    return out

def client_to_text(rec):
    name = rec.get("Ism", "Noma'lum")
    phone = rec.get("Telefon", "")
    addr = rec.get("Manzil", "")
    prod = rec.get("Mahsulot", "")
    debt = rec.get("Qarz", 0)
    pay_date = rec.get("To'lov kuni") or rec.get("To‘lov kuni") or "-"
    history = rec.get("To'lovlar tarixi") or rec.get("To‘lovlar tarixi") or ""
    text = f"👤 <b>{name}</b>\n📞 {phone}\n📍 {addr}\n🛒 Mahsulotlar: {prod}\n💰 Qarz: {debt} so'm\n📅 To'lov kuni: {pay_date}\n"
    if history:
        text += f"\n📄 To'lovlar:\n{history}"
    return text

# ==========================
# KEYBOARDS (UI)
# ==========================
def main_reply_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🆕 Mijoz qo‘shish", "💰 To‘lov kiritish")
    kb.row("📋 Mijozlar ro‘yxati", "👥 Mijozlar")
    kb.row("🔎 Qidiruv", "⚠️ Muddati o‘tganlar")
    return kb

def back_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("🔙 Orqaga")
    return kb

# ==========================
# SCHEDULER: DAILY NOTIFY
# ==========================
def check_overdue_clients():
    expired = []
    records = get_all_clients()
    today = date.today()
    for i, rec in enumerate(records, start=2):
        # try several header variants
        pay_date = rec.get("To'lov kuni") or rec.get("To‘lov kuni") or rec.get("To'lov kuni", "")
        if not pay_date:
            continue
        try:
            pd = datetime.strptime(str(pay_date).strip(), "%Y-%m-%d").date()
        except:
            # ignore unparsable dates
            continue
        if pd < today and safe_int(rec.get("Qarz", 0)) > 0:
            expired.append((i, rec))
    return expired

def notify_admins_overdue():
    expired = check_overdue_clients()
    if not expired:
        return
    text = "⚠️ <b>Muddati o‘tgan mijozlar</b>:\n\n"
    for row, rec in expired:
        text += f"• {rec.get('Ism','')} | {rec.get('Telefon','')} | Qarz: {rec.get('Qarz',0)} so'm\n"
    for admin in ADMINS:
        try:
            bot.send_message(admin, text, parse_mode='HTML')
        except Exception:
            traceback.print_exc()

scheduler = BackgroundScheduler()
scheduler.add_job(notify_admins_overdue, 'cron', hour=DAILY_NOTIFY_HOUR, minute=DAILY_NOTIFY_MINUTE)
scheduler.start()

# ==========================
# COMMANDS & FLOWS
# ==========================
@bot.message_handler(commands=['start', 'menu'])
def cmd_start(message):
    bot.send_message(message.chat.id,
                     "Assalomu alaykum! Pastel magazin boshqaruv botiga xush kelibsiz.\n"
                     "Quyidagilardan birini tanlang:",
                     reply_markup=main_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🆕 Mijoz qo‘shish")
def start_add_client(message):
    user_state[message.chat.id] = {"mode": "add_client", "step": "name", "products": []}
    bot.send_message(message.chat.id, "🔸 Mijoz ismini kiriting:", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("mode") == "add_client")
def flow_add_client(message):
    state = user_state[message.chat.id]
    step = state.get("step")
    text = message.text

    if text == "🔙 Orqaga":
        user_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_reply_keyboard())
        return

    try:
        if step == "name":
            state["name"] = text.strip()
            state["step"] = "phone"
            bot.send_message(message.chat.id, "🔸 Telefon raqamini kiriting (misol: +998901234567):", reply_markup=back_keyboard())
            return

        if step == "phone":
            phone = normalize_phone(text)
            if not re.match(r'^\+\d{9,15}$', phone):
                bot.send_message(message.chat.id, "❌ Telefon formati noto‘g‘ri. +998901234567 ko‘rinishda kiriting:")
                return
            state["phone"] = phone
            state["step"] = "address"
            bot.send_message(message.chat.id, "🔸 Yashash manzilini kiriting:", reply_markup=back_keyboard())
            return

        if step == "address":
            state["address"] = text.strip()
            state["step"] = "prod_name"
            bot.send_message(message.chat.id, "🔸 Mahsulot nomini kiriting:", reply_markup=back_keyboard())
            return

        if step == "prod_name":
            state["products"].append({"name": text.strip()})
            state["step"] = "prod_sum"
            bot.send_message(message.chat.id, f"🔸 {text.strip()} uchun summa (so'm) kiriting:", reply_markup=back_keyboard())
            return

        if step == "prod_sum":
            try:
                val = int(text.strip())
                if val < 0:
                    raise ValueError
            except:
                bot.send_message(message.chat.id, "❌ Iltimos, butun son kiriting (so'mda):")
                return
            state["products"][-1]["debt"] = val
            # ask add more?
            state["step"] = "ask_more"
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            kb.add("Ha", "Yo'q")
            bot.send_message(message.chat.id, "Yana mahsulot qo‘shasizmi?", reply_markup=kb)
            return

        if step == "ask_more":
            if text.lower() in ("ha", "yes"):
                state["step"] = "prod_name"
                bot.send_message(message.chat.id, "🔸 Keyingi mahsulot nomini kiriting:", reply_markup=back_keyboard())
                return
            # else finish -> ask pay_date
            state["step"] = "pay_date"
            state["created_at"] = datetime.today().strftime("%Y-%m-%d")
            bot.send_message(message.chat.id, "🔸 To'lov kuni (YYYY-MM-DD) kiriting (agar yo'q bo'lsa '-' deb yozing):", reply_markup=back_keyboard())
            return

        if step == "pay_date":
            pd = text.strip()
            if pd != "-":
                try:
                    datetime.strptime(pd, "%Y-%m-%d")
                except:
                    bot.send_message(message.chat.id, "❌ Sana format xato. YYYY-MM-DD ko'rinishida kiriting yoki '-' deb yozing:")
                    return
            state["pay_date"] = pd
            # Save or update in sheet
            try:
                _save_or_update_client(state)
                bot.send_message(message.chat.id, "✅ Mijoz muvaffaqiyatli saqlandi.", reply_markup=main_reply_keyboard())
            except Exception as e:
                traceback.print_exc()
                bot.send_message(message.chat.id, f"Xatolik: {e}")
            user_state.pop(message.chat.id, None)
            return
    except Exception as e:
        traceback.print_exc()
        bot.send_message(message.chat.id, f"Xato yuz berdi: {e}")

def _save_or_update_client(state):
    """Save new client or update existing by phone. state contains name, phone, address, products(list), created_at, pay_date"""
    phone = state["phone"]
    name = state.get("name", "")
    address = state.get("address", "")
    products = state.get("products", [])
    created_at = state.get("created_at", datetime.today().strftime("%Y-%m-%d"))
    pay_date = state.get("pay_date", "")

    row, rec = find_client_row_by_phone(phone)
    if row:
        # update
        old_products = rec.get("Mahsulot", "") or ""
        old_list = [p for p in old_products.split(" | ") if p] if old_products else []
        old_debt = safe_int(rec.get("Qarz", 0))
        add_sum = sum([p["debt"] for p in products])
        for p in products:
            old_list.append(p["name"])
        new_products = " | ".join(old_list)
        new_debt = old_debt + add_sum
        # columns: Manzil=3, Mahsulot=4, Qarz=5, Qo'shilgan sana=6, To'lov kuni=7, To'lovlar tarixi=8
        sheet.update_cell(row, 3, address)
        sheet.update_cell(row, 4, new_products)
        sheet.update_cell(row, 5, new_debt)
        sheet.update_cell(row, 6, created_at)
        sheet.update_cell(row, 7, pay_date)
    else:
        product_names = " | ".join([p["name"] for p in products])
        total_debt = sum([p["debt"] for p in products])
        sheet.append_row([name, phone, address, product_names, total_debt, created_at, pay_date, ""])

# ==========================
# MIJOZLAR (existing -> add product)
# ==========================
@bot.message_handler(func=lambda m: m.text == "👥 Mijozlar")
def show_clients_for_addprod(message):
    records = get_all_clients()
    if not records:
        bot.send_message(message.chat.id, "Mavjud mijozlar yo'q.", reply_markup=main_reply_keyboard())
        return
    markup = types.InlineKeyboardMarkup()
    # pagination: show up to PER_PAGE first
    for i, rec in enumerate(records, start=2):
        btn = types.InlineKeyboardButton(f"{rec.get('Ism','')} | {rec.get('Telefon','')}", callback_data=f"addprod_{i}")
        markup.add(btn)
    bot.send_message(message.chat.id, "Mijozni tanlang (yangi mahsulot qo'shish uchun):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("addprod_"))
def cb_addprod(call):
    try:
        row = int(call.data.split("_")[1])
        user_state[call.message.chat.id] = {"mode": "add_product_existing", "row": row, "step": "name", "products": []}
        bot.send_message(call.message.chat.id, "🔸 Qo'shmoqchi bo'lgan mahsulot nomini kiriting:", reply_markup=back_keyboard())
    except Exception:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, "Xato bo'ldi.")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("mode") == "add_product_existing")
def flow_add_product_existing(message):
    state = user_state[message.chat.id]
    if message.text == "🔙 Orqaga":
        user_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_reply_keyboard())
        return
    step = state.get("step")
    text = message.text
    try:
        if step == "name":
            state["products"].append({"name": text.strip()})
            state["step"] = "debt"
            bot.send_message(message.chat.id, f"🔸 {text.strip()} uchun summa (so'm) kiriting:", reply_markup=back_keyboard())
            return
        if step == "debt":
            try:
                v = int(text.strip())
                if v < 0:
                    raise ValueError
            except:
                bot.send_message(message.chat.id, "❌ Iltimos, butun son kiriting (so'm):")
                return
            row = state["row"]
            old_products = sheet.cell(row, 4).value or ""
            old_list = [p for p in old_products.split(" | ") if p] if old_products else []
            old_list.append(state["products"][-1]["name"])
            sheet.update_cell(row, 4, " | ".join(old_list))
            old_debt = safe_int(sheet.cell(row, 5).value)
            new_debt = old_debt + v
            sheet.update_cell(row, 5, new_debt)
            sheet.update_cell(row, 6, datetime.today().strftime("%Y-%m-%d"))
            bot.send_message(message.chat.id, f"✅ Mahsulot qo'shildi. Umumiy qarz: {new_debt} so'm", reply_markup=main_reply_keyboard())
            user_state.pop(message.chat.id, None)
            return
    except Exception:
        traceback.print_exc()
        bot.send_message(message.chat.id, "Xato yuz berdi.")

# ==========================
# TO'LOV KIRITISH (inline select + flow)
# ==========================
@bot.message_handler(func=lambda m: m.text == "💰 To‘lov kiritish")
def show_pay_clients(message):
    records = get_all_clients()
    if not records:
        bot.send_message(message.chat.id, "Mijozlar ro'yxati bo'sh.", reply_markup=main_reply_keyboard())
        return
    markup = types.InlineKeyboardMarkup()
    for i, rec in enumerate(records, start=2):
        markup.add(types.InlineKeyboardButton(f"{rec.get('Ism','')} | {rec.get('Telefon','')}", callback_data=f"pay_{i}"))
    bot.send_message(message.chat.id, "To'lov qilmoqchi bo'lgan mijozni tanlang:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def cb_pay_select(call):
    try:
        row = int(call.data.split("_")[1])
        name = sheet.cell(row, 1).value
        debt = safe_int(sheet.cell(row, 5).value)
        bot.send_message(call.message.chat.id, f"{name}ning umumiy qarzi: {debt} so'm\nTo'lov summasini kiriting (so'm):", reply_markup=back_keyboard())
        user_state[call.message.chat.id] = {"mode": "payment", "row": row}
    except Exception:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, "Xatolik yuz berdi.")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("mode") == "payment")
def flow_payment(message):
    if message.text == "🔙 Orqaga":
        user_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_reply_keyboard())
        return
    try:
        amt = int(message.text.strip())
    except:
        bot.send_message(message.chat.id, "❌ Iltimos, butun son kiriting (so'mda).")
        return
    state = user_state[message.chat.id]
    row = state["row"]
    old_debt = safe_int(sheet.cell(row, 5).value)
    new_debt = old_debt - amt
    sheet.update_cell(row, 5, new_debt)
    history = sheet.cell(row, 8).value or ""
    today = datetime.today().strftime("%Y-%m-%d")
    new_history = (history + f"\n{today}: -{amt}") if history else f"{today}: -{amt}"
    sheet.update_cell(row, 8, new_history)
    payments_sheet.append_row([sheet.cell(row,1).value, sheet.cell(row,2).value, amt, today, new_debt])
    bot.send_message(message.chat.id, f"✅ To'lov qabul qilindi. Qolgan qarz: {new_debt} so'm", reply_markup=main_reply_keyboard())
    user_state.pop(message.chat.id, None)

# ==========================
# MIJOZLAR RO'YXATI (sahifalash + view)
# ==========================
@bot.message_handler(func=lambda m: m.text == "📋 Mijozlar ro‘yxati")
def clients_paged(message):
    records = get_all_clients()
    if not records:
        bot.send_message(message.chat.id, "Mijozlar ro'yxati bo'sh.", reply_markup=main_reply_keyboard())
        return
    # initialize page state
    user_state[message.chat.id] = {"mode":"list_pages", "page":1}
    send_clients_page(message.chat.id, 1)

def send_clients_page(chat_id, page):
    records = get_all_clients()
    total = len(records)
    pages = max(1, math.ceil(total / PER_PAGE))
    if page < 1:
        page = 1
    if page > pages:
        page = pages
    start = (page-1) * PER_PAGE
    end = start + PER_PAGE
    chunk = records[start:end]
    text = f"📋 Mijozlar — sahifa {page}/{pages}\n\n"
    for idx, rec in enumerate(chunk, start=start+1):
        text += f"{idx}. {rec.get('Ism','')} | 📞 {rec.get('Telefon','')} | Qarz: {rec.get('Qarz',0)} so'm\n"
    markup = types.InlineKeyboardMarkup()
    if page > 1:
        markup.add(types.InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{page-1}"))
    if page < pages:
        markup.add(types.InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{page+1}"))
    # add view buttons for chunk
    for i, rec in enumerate(chunk, start=start+2):
        markup.add(types.InlineKeyboardButton(f"Ko'rish: {rec.get('Ism','')}", callback_data=f"view_{i}"))
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
def cb_page(call):
    try:
        page = int(call.data.split("_")[1])
        user_state[call.message.chat.id] = {"mode":"list_pages", "page":page}
        send_clients_page(call.message.chat.id, page)
    except:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, "Xato.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
def cb_view(call):
    try:
        row = int(call.data.split("_")[1])
        headers = sheet.row_values(1)
        row_vals = sheet.row_values(row)
        rec = {}
        for idx, val in enumerate(row_vals, start=1):
            if idx <= len(headers):
                rec[headers[idx-1]] = val
        text = client_to_text(rec)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ Yangi mahsulot", callback_data=f"addprod_{row}"))
        kb.add(types.InlineKeyboardButton("💸 To'lov", callback_data=f"pay_{row}"))
        if message := call.from_user:
            if message.id in ADMINS:
                kb.add(types.InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_{row}"),
                       types.InlineKeyboardButton("🗑 O'chirish", callback_data=f"del_{row}"))
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
    except:
        traceback.print_exc()
        bot.send_message(call.message.chat.id, "Xato.")

# ==========================
# SEARCH and OVERDUE QUICK HANDLERS
# ==========================
@bot.message_handler(func=lambda m: m.text == "🔎 Qidiruv")
def cmd_search_button(message):
    sent = bot.send_message(message.chat.id, "🔍 Qidirish uchun ism, telefon yoki mahsulot nomini kiriting:")
    bot.register_next_step_handler(sent, do_search)

def do_search(message):
    q = message.text.strip()
    results = find_clients_by_query(q)
    if not results:
        bot.send_message(message.chat.id, "Topilmadi.", reply_markup=main_reply_keyboard())
        return
    kb = types.InlineKeyboardMarkup()
    for row, rec in results[:50]:
        kb.add(types.InlineKeyboardButton(f"{rec.get('Ism','')} | {rec.get('Telefon','')}", callback_data=f"view_{row}"))
    bot.send_message(message.chat.id, f"Topildi: {len(results)} (birinchi 50 ko'rsatildi). Tanlang:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "⚠️ Muddati o‘tganlar")
def cmd_overdue_button(message):
    expired = check_overdue_clients()
    if not expired:
        bot.send_message(message.chat.id, "Muddati o‘tgan mijozlar topilmadi.", reply_markup=main_reply_keyboard())
        return
    text = "⚠️ Muddati o‘tgan mijozlar:\n\n"
    for row, rec in expired:
        text += f"• {rec.get('Ism','')} | {rec.get('Telefon','')} | Qarz: {rec.get('Qarz',0)} so'm\n"
    bot.send_message(message.chat.id, text, reply_markup=main_reply_keyboard())

# ==========================
# ADMIN STATS COMMAND
# ==========================
@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if message.from_user.id not in ADMINS:
        bot.send_message(message.chat.id, "Bu buyruq faqat adminlar uchun.")
        return
    recs = get_all_clients()
    total = len(recs)
    total_debt = sum([safe_int(r.get("Qarz",0)) for r in recs])
    top5 = sorted(recs, key=lambda r: safe_int(r.get("Qarz",0)), reverse=True)[:5]
    text = f"📊 Statistika\nMijozlar: {total}\nUmumiy qarz: {total_debt} so'm\n\nTop 5 qarzdor:\n"
    for r in top5:
        text += f"• {r.get('Ism','')} | {r.get('Telefon','')} — {r.get('Qarz',0)} so'm\n"
    bot.send_message(message.chat.id, text)

# ==========================
# CLEAN SHUTDOWN SAFE (optional)
# ==========================
def stop_scheduler():
    try:
        scheduler.shutdown(wait=False)
    except:
        pass

# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    print("Bot ishga tushdi. Scheduler ham boshlangan.")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        stop_scheduler()
        print("Stopped by user.")
    except Exception:
        traceback.print_exc()
