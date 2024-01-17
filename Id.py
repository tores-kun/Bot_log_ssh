from telegram import Bot

bot = Bot(token=open('token.txt', 'r').read().strip())


def get_chat_id():
    updates = bot.get_updates()
    if updates:
        return updates[-1].message.chat_id

# Вывести ID чата
print(get_chat_id())
