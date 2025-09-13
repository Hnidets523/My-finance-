from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Твій токен бота з BotFather
TOKEN = "8420371366:AAG9UfAnEqKyrk5v1DOPHvh7hlp1ZDtHJy8"

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Витрати", "Надходження", "Інвестиції"]
    ]
    reply_markup = {"keyboard": keyboard, "resize_keyboard": True}
    await update.message.reply_text("Привіт! Вибери дію 👇", reply_markup=reply_markup)

# Обробка будь-яких повідомлень
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text(f"Ти вибрав: {text}")

# Запуск бота
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущений ✅")
    app.run_polling()

if __name__ == "__main__":
    main()