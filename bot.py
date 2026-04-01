"""
💰 Personal Finance Telegram Bot
Writes transactions into the existing "📅 Daily Log 2026" sheet
in your Google Sheets file, matching the pre-built date structure.

Message formats:
  150 lunch CTBC                     → Expense, auto-detected category
  income 40000 ctbc april salary     → Income
  transfer 5000 ctbc post            → Transfer between your accounts
  invest 3300 investment 0050 ETF    → Investment
  balance                            → All 5 account balances this month
  summary                            → Spending breakdown by category
  undo                               → Remove last entry
  help                               → All commands
"""

import os
import re
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (Application, MessageHandler,
                          CommandHandler, filters, ContextTypes)
import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
GOOGLE_CREDS_FILE = os.environ.get("GOOGLE_CREDS_FILE", "credentials.json")
SPREADSHEET_ID    = os.environ["SPREADSHEET_ID"]
YOUR_CHAT_ID      = int(os.environ.get("YOUR_CHAT_ID", "0"))

# Column positions in "📅 Daily Log 2026"  (1-indexed)
# A=1  B=2    C=3     D=4    E=5       F=6    G=7     H=8    I=9    J=10
# #   Date  Desc   Type  Amount   Category SubCat  Need  Account Notes
# K=11      L=12    M=13     N=14    O=15        P=16
# PostOffice CTBC  Wallet   VND    InvCash     BudgetWarn
COL_DATE    = 2
COL_DESC    = 3
COL_TYPE    = 4
COL_AMOUNT  = 5
COL_CAT     = 6
COL_SUBCAT  = 7
COL_NEED    = 8
COL_ACCOUNT = 9
COL_NOTES   = 10
TOTAL_COLS  = 16

ROWS_PER_DAY = 4   # how many data rows exist per day in the sheet

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── Google Sheets ─────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_worksheet():
    creds  = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    ss     = client.open_by_key(SPREADSHEET_ID)
    return ss.worksheet("📅 Daily Log 2026")

def find_date_rows(ws, target_date: str):
    """
    Find the row numbers of the ROWS_PER_DAY data rows for a given date string
    e.g. "2026-04-01".
    The sheet has the date only in the first sub-row of each day (column B).
    Returns list of row numbers (1-indexed), or [] if date not found.
    """
    col_b = ws.col_values(COL_DATE)   # all values in column B
    for i, val in enumerate(col_b):
        if val == target_date:
            first_row = i + 1         # gspread is 1-indexed
            return list(range(first_row, first_row + ROWS_PER_DAY))
    return []

def find_next_empty_row(ws, day_rows: list[int]) -> int | None:
    """
    Among the ROWS_PER_DAY rows for a day, find the first one
    where column E (Amount) is empty.
    Returns the row number, or None if all 4 slots are full.
    """
    if not day_rows:
        return None
    # Fetch column E for those rows in one call
    col_e = ws.col_values(COL_AMOUNT)
    for row in day_rows:
        idx = row - 1   # 0-indexed
        val = col_e[idx] if idx < len(col_e) else ""
        if not val:
            return row
    return None   # all 4 rows already filled

def write_transaction(ws, row: int, tx: dict):
    """Write a parsed transaction into a specific row of the sheet."""
    # We only write to C–J (columns 3–10); balance columns K–P are formulas
    updates = {
        COL_DESC:    tx["notes"] or tx["raw"],
        COL_TYPE:    tx["type"],
        COL_AMOUNT:  tx["amount"],
        COL_CAT:     tx["category"],
        COL_SUBCAT:  tx["subcat"],
        COL_NEED:    tx["need"],
        COL_ACCOUNT: tx["account"],
        COL_NOTES:   tx["notes"],
    }
    # Build a batch update for efficiency (one API call)
    cell_list = []
    for col, value in updates.items():
        cell = ws.cell(row, col)
        cell.value = value
        cell_list.append(cell)
    ws.update_cells(cell_list, value_input_option="USER_ENTERED")
    log.info(f"Written to row {row}: {tx['type']} NT${tx['amount']} — {tx['account']}")

# ── Parsers ───────────────────────────────────────────────────────────────────
CATEGORY_MAP = {
    "lunch":       ("🍽 Food", "Eating Out",        "Want"),
    "dinner":      ("🍽 Food", "Eating Out",        "Want"),
    "breakfast":   ("🍽 Food", "Eating Out",        "Need"),
    "eat":         ("🍽 Food", "Eating Out",        "Want"),
    "cafe":        ("🍽 Food", "Eating Out",        "Want"),
    "coffee":      ("🍽 Food", "Eating Out",        "Want"),
    "bubble tea":  ("🍽 Food", "Eating Out",        "Want"),
    "boba":        ("🍽 Food", "Eating Out",        "Want"),
    "7-11":        ("🍽 Food", "Eating Out",        "Need"),
    "711":         ("🍽 Food", "Eating Out",        "Need"),
    "family mart": ("🍽 Food", "Eating Out",        "Need"),
    "grocery":     ("🍽 Food", "Groceries",         "Need"),
    "groceries":   ("🍽 Food", "Groceries",         "Need"),
    "supermarket": ("🍽 Food", "Groceries",         "Need"),
    "carrefour":   ("🍽 Food", "Groceries",         "Need"),
    "pxmart":      ("🍽 Food", "Groceries",         "Need"),
    "mrt":         ("🚌 Transport", "Daily Commute","Need"),
    "bus":         ("🚌 Transport", "Daily Commute","Need"),
    "taxi":        ("🚌 Transport", "Daily Commute","Need"),
    "uber":        ("🚌 Transport", "Daily Commute","Need"),
    "grab":        ("🚌 Transport", "Daily Commute","Need"),
    "youbike":     ("🚌 Transport", "Daily Commute","Need"),
    "train":       ("🚌 Transport", "Daily Commute","Need"),
    "flight":      ("🚌 Transport", "Travel",       "Want"),
    "hotel":       ("🚌 Transport", "Travel",       "Want"),
    "travel":      ("🚌 Transport", "Travel",       "Want"),
    "rent":        ("🏠 Living", "Rent & Bills",    "Need"),
    "electric":    ("🏠 Living", "Rent & Bills",    "Need"),
    "phone":       ("🏠 Living", "Rent & Bills",    "Need"),
    "internet":    ("🏠 Living", "Rent & Bills",    "Need"),
    "bill":        ("🏠 Living", "Rent & Bills",    "Need"),
    "haircut":     ("🏠 Living", "Home & Personal", "Need"),
    "laundry":     ("🏠 Living", "Home & Personal", "Need"),
    "shopping":    ("🎯 Lifestyle", "Shopping",     "Want"),
    "clothes":     ("🎯 Lifestyle", "Shopping",     "Want"),
    "shoes":       ("🎯 Lifestyle", "Shopping",     "Want"),
    "lazada":      ("🎯 Lifestyle", "Shopping",     "Want"),
    "shopee":      ("🎯 Lifestyle", "Shopping",     "Want"),
    "movie":       ("🎯 Lifestyle", "Entertainment","Want"),
    "netflix":     ("🎯 Lifestyle", "Entertainment","Want"),
    "spotify":     ("🎯 Lifestyle", "Entertainment","Want"),
    "game":        ("🎯 Lifestyle", "Entertainment","Want"),
    "send home":   ("👨‍👩‍👧 People", "Family / Send Home","Need"),
    "remit":       ("👨‍👩‍👧 People", "Family / Send Home","Need"),
    "family":      ("👨‍👩‍👧 People", "Family / Send Home","Need"),
    "gift":        ("👨‍👩‍👧 People", "Friends & Gifts",  "Want"),
    "charity":     ("👨‍👩‍👧 People", "Charity",          "Want"),
    "donate":      ("👨‍👩‍👧 People", "Charity",          "Want"),
    "book":        ("📚 Growth", "Education",       "Need"),
    "course":      ("📚 Growth", "Education",       "Need"),
    "study":       ("📚 Growth", "Education",       "Need"),
    "doctor":      ("📚 Growth", "Health",          "Need"),
    "medicine":    ("📚 Growth", "Health",          "Need"),
    "pharmacy":    ("📚 Growth", "Health",          "Need"),
    "gym":         ("📚 Growth", "Health",          "Want"),
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
    "brokerage":   "Investment Cash",
}

TYPE_KEYWORDS = {
    "income":    "Income",
    "received":  "Income",
    "transfer":  "Transfer",
    "move":      "Transfer",
    "invest":    "Investment",
    "buy etf":   "Investment",
    "buy stock": "Investment",
    "etf":       "Investment",
    "stock":     "Investment",
    "gold":      "Investment",
    "silver":    "Investment",
    "repay":     "Debt",
    "loan":      "Debt",
    "borrow":    "Debt",
    "debt":      "Debt",
}

def detect_type(text: str) -> str:
    t = text.lower()
    # salary is special — it's Income even if "ctbc" appears
    if "salary" in t or "income" in t or "received" in t:
        return "Income"
    for kw, tx_type in TYPE_KEYWORDS.items():
        if kw in t:
            return tx_type
    return "Expense"

def detect_account(text: str) -> str:
    t = text.lower()
    # check multi-word keys first
    for kw in sorted(ACCOUNT_MAP, key=len, reverse=True):
        if kw in t:
            return ACCOUNT_MAP[kw]
    return "CTBC (Spending)"

def detect_category(text: str):
    t = text.lower()
    # check multi-word keys first
    for kw in sorted(CATEGORY_MAP, key=len, reverse=True):
        if kw in t:
            return CATEGORY_MAP[kw]
    return ("💼 Other", "Other", "Want")

def parse_amount(text: str) -> float | None:
    nums = re.findall(r'\d+(?:[.,]\d+)?', text)
    return float(nums[0].replace(",", "")) if nums else None

def extract_notes(text: str) -> str:
    """Remove amount, account keywords, type keywords — leftover = notes."""
    t = re.sub(r'\d+(?:[.,]\d+)?', '', text)
    for kw in list(ACCOUNT_MAP) + list(TYPE_KEYWORDS) + list(CATEGORY_MAP):
        t = re.sub(rf'\b{re.escape(kw)}\b', '', t, flags=re.IGNORECASE)
    return " ".join(t.split()).strip()

def parse_message(text: str) -> dict | None:
    amount = parse_amount(text)
    if amount is None:
        return None
    now     = datetime.now()
    tx_type = detect_type(text)
    account = detect_account(text)
    cat, sub, need = detect_category(text)
    notes   = extract_notes(text)
    return {
        "date":     now.strftime("%Y-%m-%d"),
        "time":     now.strftime("%H:%M"),
        "type":     tx_type,
        "amount":   amount,
        "category": cat if tx_type == "Expense" else "—",
        "subcat":   sub if tx_type == "Expense" else "—",
        "need":     need if tx_type == "Expense" else "—",
        "account":  account,
        "notes":    notes,
        "raw":      text.strip(),
    }

def build_reply(tx: dict, row: int) -> str:
    emoji = {"Expense":"💸","Income":"💰","Transfer":"🔄",
             "Investment":"📈","Debt":"💳"}.get(tx["type"], "💸")
    need_tag = f"  •  {tx['need']}" if tx["need"] != "—" else ""
    cat_line = (f"📂 {tx['category']}  →  {tx['subcat']}{need_tag}\n"
                if tx["type"] == "Expense" else "")
    return (
        f"{emoji} *{tx['type']} logged!*\n\n"
        f"📅 {tx['date']}  {tx['time']}\n"
        f"💵 Amount: *NT${tx['amount']:,.0f}*\n"
        f"🏦 Account: {tx['account']}\n"
        f"{cat_line}"
        f"📝 Notes: {tx['notes'] or '—'}\n"
        f"📍 Sheet row: {row}\n\n"
        f"_Type 'undo' to remove this entry_"
    )

# ── Bot handlers ──────────────────────────────────────────────────────────────
# Store last written row per user for undo
last_row: dict[int, int] = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg     = update.message
    text    = msg.text.strip()
    user_id = msg.from_user.id

    if YOUR_CHAT_ID and user_id != YOUR_CHAT_ID:
        await msg.reply_text("⛔ Unauthorized.")
        return

    cmd = text.lower()
    if cmd == "balance":  await cmd_balance(update, context); return
    if cmd == "summary":  await cmd_summary(update, context); return
    if cmd == "help":     await cmd_help(update, context);    return
    if cmd == "undo":     await cmd_undo(update, context);    return

    tx = parse_message(text)
    if not tx:
        await msg.reply_text(
            "❓ Couldn't find an amount.\n\nTry: `150 lunch CTBC`\nor type `help`",
            parse_mode="Markdown")
        return

    await msg.reply_text("⏳ Logging...", parse_mode="Markdown")

    try:
        ws        = get_worksheet()
        day_rows  = find_date_rows(ws, tx["date"])

        if not day_rows:
            await msg.reply_text(
                f"⚠️ Date `{tx['date']}` not found in the sheet.\n"
                f"Make sure the sheet has rows for today.",
                parse_mode="Markdown")
            return

        target_row = find_next_empty_row(ws, day_rows)
        if target_row is None:
            await msg.reply_text(
                f"⚠️ All {ROWS_PER_DAY} slots for {tx['date']} are full!\n"
                f"Open the sheet and add more rows for today, or clear one.",
                parse_mode="Markdown")
            return

        write_transaction(ws, target_row, tx)
        last_row[user_id] = target_row
        await msg.reply_text(build_reply(tx, target_row), parse_mode="Markdown")

    except gspread.exceptions.APIError as e:
        log.error(f"Sheets API error: {e}")
        await msg.reply_text(
            "⚠️ Google Sheets API error. Wait a moment and try again.\n"
            f"Details: `{e}`", parse_mode="Markdown")
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        await msg.reply_text(f"⚠️ Something went wrong: `{e}`",
                             parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read balance columns K–O from today's row and show all 5 accounts."""
    try:
        ws      = get_worksheet()
        today   = datetime.now().strftime("%Y-%m-%d")
        day_rows = find_date_rows(ws, today)

        if not day_rows:
            await update.message.reply_text(
                f"⚠️ No rows found for today ({today}) in the sheet.")
            return

        # Read last row of the day = most up-to-date balances
        last_day_row = day_rows[-1]
        row_data = ws.row_values(last_day_row)

        def safe(col): # 0-indexed
            v = row_data[col-1] if len(row_data) >= col else "—"
            return v if v else "—"

        acc_lines = [
            f"🏦 Post Office (Saving):  `{safe(11)}`",
            f"💳 CTBC (Spending):       `{safe(12)}`",
            f"👝 Cash Wallet:           `{safe(13)}`",
            f"🇻🇳 VND Account:           `{safe(14)}`",
            f"📈 Investment Cash:       `{safe(15)}`",
        ]
        await update.message.reply_text(
            f"💰 *Account Balances — {today}*\n_(as of last logged transaction)_\n\n"
            + "\n".join(acc_lines),
            parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan this month's rows and show spending by category."""
    try:
        ws      = get_worksheet()
        now     = datetime.now()
        month   = now.strftime("%Y-%m")

        # Get all values — only columns B (date), D (type), E (amount), F (cat)
        all_rows = ws.get_all_values()

        by_cat = {}
        total_expense = 0
        total_income  = 0
        total_invest  = 0
        count = 0

        for row in all_rows[1:]:   # skip header-like rows
            if len(row) < COL_AMOUNT:
                continue
            date_val = row[COL_DATE-1]    if len(row) >= COL_DATE    else ""
            type_val = row[COL_TYPE-1]    if len(row) >= COL_TYPE    else ""
            amt_val  = row[COL_AMOUNT-1]  if len(row) >= COL_AMOUNT  else ""
            cat_val  = row[COL_CAT-1]     if len(row) >= COL_CAT     else ""

            if not date_val.startswith(month):
                continue
            if not amt_val:
                continue
            try:
                amt = float(str(amt_val).replace(",","").replace("NT$",""))
            except ValueError:
                continue

            count += 1
            if type_val == "Expense":
                by_cat[cat_val or "Other"] = by_cat.get(cat_val or "Other", 0) + amt
                total_expense += amt
            elif type_val == "Income":
                total_income += amt
            elif type_val == "Investment":
                total_invest += amt

        daily_budget   = 1300
        days_elapsed   = now.day
        budget_so_far  = days_elapsed * daily_budget
        status = "🔴 Over" if total_expense > budget_so_far else "✅ Under"

        lines = [f"📊 *Summary — {now.strftime('%B %Y')}*\n"]
        if by_cat:
            for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
                pct = (amt / total_expense * 100) if total_expense else 0
                bar = "█" * int(pct/10) + "░" * (10-int(pct/10))
                lines.append(f"{cat or '💼 Other'}\n`{bar}` NT${amt:,.0f} ({pct:.0f}%)")
            lines.append("")
        lines += [
            f"💸 Total spent:    NT${total_expense:,.0f}",
            f"💰 Total income:   NT${total_income:,.0f}",
            f"📈 Total invested: NT${total_invest:,.0f}",
            f"📅 Budget ({days_elapsed} days): NT${budget_so_far:,.0f}",
            f"Status: {status} budget",
            f"_({count} transactions this month)_",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the last written row (columns C–J only, keeps date/formulas)."""
    user_id = update.message.from_user.id
    row = last_row.get(user_id)
    if not row:
        await update.message.reply_text(
            "Nothing to undo — I don't remember a recent entry in this session.")
        return
    try:
        ws = get_worksheet()
        # Clear only the data columns, not date/formulas
        clear_range = f"{ws.title}!C{row}:J{row}"
        ws.spreadsheet.values_clear(
            f"C{row}:J{row}")
        del last_row[user_id]
        await update.message.reply_text(
            f"↩️ *Undone!* Row {row} cleared.",
            parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: `{e}`", parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
📖 *Finance Bot — Quick Guide*

*Log a transaction (type naturally):*
`150 lunch CTBC`
`350 groceries cash`
`income 40000 ctbc salary`
`transfer 5000 ctbc post`
`invest 3300 investment 0050`
`send home 3000 ctbc`

*Always include:*
• A number (the amount)
• The account: `ctbc` · `post` · `cash` · `vnd` · `invest`

*Commands:*
`balance`  — see all 5 account balances today
`summary`  — spending by category this month
`undo`     — clear last entry
`help`     — this message

*Type auto-detection:*
• Default → Expense
• "income" / "salary" / "received" → Income
• "transfer" / "move" → Transfer
• "invest" / "etf" / "gold" → Investment
• "repay" / "loan" / "debt" → Debt
""", parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Finance Bot ready!*\n\n"
        "Writing directly into your *📅 Daily Log 2026* sheet.\n\n"
        "Try it now: `150 lunch CTBC`\n"
        "Or type `help` for all commands.",
        parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("undo",    cmd_undo))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("🤖 Finance bot started — writing to '📅 Daily Log 2026'")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
