"""
Finance Bot — compatible with python-telegram-bot v21+ and Python 3.14
"""
import os
import re
import logging
import httpx
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_URL    = os.environ["WEBHOOK_URL"]
YOUR_CHAT_ID   = int(os.environ.get("YOUR_CHAT_ID", "0"))

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

CATEGORY_MAP = {
    "lunch":       ("🍽 Food", "Eating Out",             "Want"),
    "dinner":      ("🍽 Food", "Eating Out",             "Want"),
    "breakfast":   ("🍽 Food", "Eating Out",             "Need"),
    "eat":         ("🍽 Food", "Eating Out",             "Want"),
    "cafe":        ("🍽 Food", "Eating Out",             "Want"),
    "coffee":      ("🍽 Food", "Eating Out",             "Want"),
    "bubble tea":  ("🍽 Food", "Eating Out",             "Want"),
    "boba":        ("🍽 Food", "Eating Out",             "Want"),
    "7-11":        ("🍽 Food", "Eating Out",             "Need"),
    "711":         ("🍽 Food", "Eating Out",             "Need"),
    "family mart": ("🍽 Food", "Eating Out",             "Need"),
    "grocery":     ("🍽 Food", "Groceries",              "Need"),
    "groceries":   ("🍽 Food", "Groceries",              "Need"),
    "supermarket": ("🍽 Food", "Groceries",              "Need"),
    "carrefour":   ("🍽 Food", "Groceries",              "Need"),
    "mrt":         ("🚌 Transport", "Daily Commute",     "Need"),
    "bus":         ("🚌 Transport", "Daily Commute",     "Need"),
    "taxi":        ("🚌 Transport", "Daily Commute",     "Need"),
    "uber":        ("🚌 Transport", "Daily Commute",     "Need"),
    "grab":        ("🚌 Transport", "Daily Commute",     "Need"),
    "youbike":     ("🚌 Transport", "Daily Commute",     "Need"),
    "train":       ("🚌 Transport", "Daily Commute",     "Need"),
    "flight":      ("🚌 Transport", "Travel",            "Want"),
    "hotel":       ("🚌 Transport", "Travel",            "Want"),
    "travel":      ("🚌 Transport", "Travel",            "Want"),
    "rent":        ("🏠 Living", "Rent & Bills",         "Need"),
    "electric":    ("🏠 Living", "Rent & Bills",         "Need"),
    "phone":       ("🏠 Living", "Rent & Bills",         "Need"),
    "internet":    ("🏠 Living", "Rent & Bills",         "Need"),
    "bill":        ("🏠 Living", "Rent & Bills",         "Need"),
    "haircut":     ("🏠 Living", "Home & Personal",      "Need"),
    "laundry":     ("🏠 Living", "Home & Personal",      "Need"),
    "shopping":    ("🎯 Lifestyle", "Shopping",          "Want"),
    "clothes":     ("🎯 Lifestyle", "Shopping",          "Want"),
    "shopee":      ("🎯 Lifestyle", "Shopping",          "Want"),
    "lazada":      ("🎯 Lifestyle", "Shopping",          "Want"),
    "movie":       ("🎯 Lifestyle", "Entertainment",     "Want"),
    "netflix":     ("🎯 Lifestyle", "Entertainment",     "Want"),
    "spotify":     ("🎯 Lifestyle", "Entertainment",     "Want"),
    "send home":   ("👨‍👩‍👧 People", "Family / Send Home", "Need"),
    "remit":       ("👨‍👩‍👧 People", "Family / Send Home", "Need"),
    "family":      ("👨‍👩‍👧 People", "Family / Send Home", "Need"),
    "gift":        ("👨‍👩‍👧 People", "Friends & Gifts",   "Want"),
    "charity":     ("👨‍👩‍👧 People", "Charity",           "Want"),
    "book":        ("📚 Growth", "Education",            "Need"),
    "course":      ("📚 Growth", "Education",            "Need"),
    "doctor":      ("📚 Growth", "Health",               "Need"),
    "medicine":    ("📚 Growth", "Health",               "Need"),
    "pharmacy":    ("📚 Growth", "Health",               "Need"),
    "gym":         ("📚 Growth", "Health",               "Want"),
}

ACCOUNT_MAP = {
    "post office": "Post Office (Saving)",
    "postoffice":  "Post Office (Saving)",
    "post":        "Post Office (Saving)",
    "saving":      "Post Office (Saving)",
    "ctbc":        "CTBC (Spending)",
    "spending":    "CTBC (Spending)",
    "cash":        "Cash Wallet",
    "wallet":      "Cash Wallet",
    "vnd":         "VND Account",
    "vietnam":     "VND Account",
    "invest":      "Investment Cash",
    "investment":  "Investment Cash",
}

TYPE_KEYWORDS = {
    "income":   "Income",
    "salary":   "Income",
    "received": "Income",
    "transfer": "Transfer",
    "move":     "Transfer",
    "invest":   "Investment",
    "etf":      "Investment",
    "stock":    "Investment",
    "gold":     "Investment",
    "silver":   "Investment",
    "repay":    "Debt",
    "loan":     "Debt",
    "debt":     "Debt",
    "borrow":   "Debt",
}

def detect_type(text):
    t = text.lower()
    if any(k in t for k in ["salary", "income", "received"]):
        return "Income"
    for kw, val in TYPE_KEYWORDS.items():
        if kw in t:
            return val
    return "Expense"

def detect_account(text):
    t = text.lower()
    for kw in sorted(ACCOUNT_MAP, key=len, reverse=True):
        if kw in t:
            return ACCOUNT_MAP[kw]
    return "CTBC (Spending)"

def detect_category(text):
    t = text.lower()
    for kw in sorted(CATEGORY_MAP, key=len, reverse=True):
        if kw in t:
            return CATEGORY_MAP[kw]
    return ("💼 Other", "Other", "Want")

def parse_amount(text):
    nums = re.findall(r'\d+(?:[.,]\d+)?', text)
    return float(nums[0].replace(",", "")) if nums else None

def extract_notes(text):
    t = re.sub(r'\d+(?:[.,]\d+)?', '', text)
    for kw in list(ACCOUNT_MAP) + list(TYPE_KEYWORDS) + list(CATEGORY_MAP):
        t = re.sub(rf'\b{re.escape(kw)}\b', '', t, flags=re.IGNORECASE)
    return " ".join(t.split()).strip()

def parse_message(text):
    amount = parse_amount(text)
    if amount is None:
        return None
    now     = datetime.now()
    tx_type = detect_type(text)
    account = detect_account(text)
    cat, sub, need = detect_category(text)
    notes   = extract_notes(text)
    return {
        "action":   "log",
        "date":     now.strftime("%Y-%m-%d"),
        "time":     now.strftime("%H:%M"),
        "type":     tx_type,
        "amount":   amount,
        "category": cat if tx_type == "Expense" else "",
        "subcat":   sub if tx_type == "Expense" else "",
        "need":     need if tx_type == "Expense" else "",
        "account":  account,
        "notes":    notes,
        "desc":     notes or text.strip(),
        "raw":      text.strip(),
    }

async def call_script(payload):
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(WEBHOOK_URL, json=payload, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

def build_reply(tx, row):
    emoji = {"Expense":"💸","Income":"💰","Transfer":"🔄",
             "Investment":"📈","Debt":"💳"}.get(tx["type"], "💸")
    cat_line = (f"📂 {tx['category']}  →  {tx['subcat']}  •  {tx['need']}\n"
                if tx["type"] == "Expense" else "")
    return (
        f"{emoji} *{tx['type']} logged!*\n\n"
        f"📅 {tx['date']}  {tx['time']}\n"
        f"💵 Amount: *NT${tx['amount']:,.0f}*\n"
        f"🏦 Account: {tx['account']}\n"
        f"{cat_line}"
        f"📝 Notes: {tx['notes'] or '—'}\n"
        f"📍 Sheet row: {row}\n\n"
        f"_Type 'undo' to remove_"
    )

last_row = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg     = update.message
    text    = msg.text.strip()
    user_id = msg.from_user.id

    if YOUR_CHAT_ID and user_id != YOUR_CHAT_ID:
        await msg.reply_text("⛔ Unauthorized.")
        return

    cmd = text.lower()
    if cmd == "balance": await cmd_balance(update, context); return
    if cmd == "summary": await cmd_summary(update, context); return
    if cmd == "help":    await cmd_help(update, context);    return
    if cmd == "undo":    await cmd_undo(update, context);    return

    tx = parse_message(text)
    if not tx:
        await msg.reply_text(
            "❓ No amount found.\n\nTry: `150 lunch CTBC`\nor type `help`",
            parse_mode="Markdown")
        return

    await msg.reply_text("⏳ Logging to your sheet...", parse_mode="Markdown")
    try:
        result = await call_script(tx)
        if not result.get("ok"):
            await msg.reply_text(f"⚠️ Sheet error: {result.get('error')}",
                                 parse_mode="Markdown")
            return
        row = result.get("row", "?")
        last_row[user_id] = row
        await msg.reply_text(build_reply(tx, row), parse_mode="Markdown")
    except Exception as e:
        log.error(f"Error: {e}")
        await msg.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    await update.message.reply_text("⏳ Fetching balances...")
    try:
        result = await call_script({"action": "balance", "date": today})
        if not result.get("ok"):
            await update.message.reply_text(f"⚠️ {result.get('error')}")
            return
        bal = result.get("balances", {})
        emojis = {"Post Office (Saving)":"🏦","CTBC (Spending)":"💳",
                  "Cash Wallet":"👝","VND Account":"🇻🇳","Investment Cash":"📈"}
        lines = [f"💰 *Account Balances — {today}*\n"]
        for acc, amt in bal.items():
            e = emojis.get(acc, "🏦")
            lines.append(f"{e} {acc}\n   `NT${float(amt):,.0f}`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now   = datetime.now()
    month = now.strftime("%Y-%m")
    await update.message.reply_text("⏳ Calculating summary...")
    try:
        result = await call_script({"action": "summary", "month": month})
        if not result.get("ok"):
            await update.message.reply_text(f"⚠️ {result.get('error')}")
            return
        d         = result.get("data", {})
        total_exp = d.get("totalExpense", 0)
        by_cat    = d.get("byCategory", {})
        days      = now.day
        budget    = days * 1300
        status    = "🔴 Over" if total_exp > budget else "✅ Under"
        lines     = [f"📊 *{now.strftime('%B %Y')} Summary*\n"]
        for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
            pct = (amt / total_exp * 100) if total_exp else 0
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(f"{cat}\n`{bar}` NT${amt:,.0f} ({pct:.0f}%)")
        lines += [
            f"\n💸 Total spent:    NT${total_exp:,.0f}",
            f"💰 Total income:   NT${d.get('totalIncome', 0):,.0f}",
            f"📈 Total invested: NT${d.get('totalInvest', 0):,.0f}",
            f"📅 Budget ({days}d):  NT${budget:,.0f}",
            f"Status: {status}",
            f"_({d.get('count', 0)} transactions)_",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    row = last_row.get(user_id)
    if not row:
        await update.message.reply_text(
            "Nothing to undo — no recent entry in this session.")
        return
    try:
        result = await call_script({"action": "undo", "row": row})
        if result.get("ok"):
            del last_row[user_id]
            await update.message.reply_text(
                f"↩️ *Undone!* Row {row} cleared.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ {result.get('error')}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
📖 *Finance Bot — Quick Guide*

*Log a transaction:*
`150 lunch CTBC`
`350 groceries cash`
`income 40000 ctbc salary`
`transfer 5000 ctbc post`
`invest 3300 investment 0050`
`send home 3000 ctbc`

*Commands:*
`balance`  — all 5 account balances
`summary`  — spending by category
`undo`     — remove last entry
`help`     — this message
""", parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Finance Bot ready!*\n\nTry: `150 lunch CTBC`\nOr type `help`",
        parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("undo",    cmd_undo))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("🤖 Finance bot started!")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
