import subprocess
import re
import time
from datetime import datetime, timedelta
import telebot
from telebot import types
import threading

# Загрузка токена из файла
bot_token = open('token.txt', 'r').read().strip()
bot = telebot.TeleBot(token=bot_token)

# Ожидаемый chat_id
expected_chat_id = 416541312

# Состояния для обработки разных шагов
CHOOSING, TYPING_REPLY = range(2)

def get_ssh_logs(period):
    try:
        # Определение временного интервала для анализа
        now = datetime.now()
        if period == 'День':
            start_time = now - timedelta(days=1)
        elif period == 'Неделя':
            start_time = now - timedelta(weeks=1)
        elif period == 'Месяц':
            start_time = now - timedelta(days=30)
        else:
            raise ValueError("Неверный период. Используйте 'day', 'week' или 'month'.")

        # Форматирование временного интервала для поиска в логах
        time_format = start_time.strftime('%b %e')

        # Чтение логов SSH за указанный период
        command = f"grep '{time_format}' /var/log/auth.log"
        result = subprocess.check_output(command, shell=True).decode('utf-8')

        # Поиск успешных и неудачных попыток входа
        successful_logins = re.findall(r'session opened for user (.*) by', result)
        failed_logins = re.findall(r'Failed password for (.*) from', result)

        # Составление сообщения о попытках входа
        message = f"Попытки входа за последний {period}:\n"
        if successful_logins:
            message += f"Успешные входы: {', '.join(successful_logins)}\n"
        if failed_logins:
            message += f"Неудачные входы: {', '.join(failed_logins)}\n"

        return message
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        print(f'Error: {e}')


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
    markup.add('День', 'Неделя', 'Месяц')
    bot.send_message(message.chat.id, 'Выберите период:', reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_period_choice(message):
    if message.chat.id == expected_chat_id:
        period = message.text.lower()

        # Проверяем корректность выбранного периода
        if period not in ['day', 'week', 'month']:
            bot.send_message(message.chat.id, 'Неверный период. Используйте \'day\', \'week\' или \'month\'.')
            return

        # Если период корректен, вызываем функцию get_ssh_logs
        logs_message = get_ssh_logs(period)

        if logs_message:
            bot.send_message(message.chat.id, logs_message)
            markup = types.ReplyKeyboardRemove()
            bot.send_message(message.chat.id, 'Статистика отправлена.', reply_markup=markup)
        else:
            bot.send_message(message.chat.id, 'Не удалось получить статистику за выбранный период.')
    else:
        bot.send_message(message.chat.id, 'Вы не имеете доступа к этому боту.')


def monitor_ssh_logs():
    while True:
        try:
            # Мониторинг логов SSH
            result = subprocess.check_output(['tail', '/var/log/auth.log']).decode('utf-8')
            failed_logins = re.findall(r'Failed password for (.*) from', result)

            # Отправка уведомлений о неудачных попытках входа
            if failed_logins:
                message = f"Новые неудачные попытки входа: {', '.join(failed_logins)}"
                bot.send_message(expected_chat_id, message)
        except Exception as e:
            print(f'Error: {e}')
        time.sleep(60)

if __name__ == '__main__':
    # Добавляем задачу на мониторинг SSH логов в фоновом режиме
    monitor_thread = threading.Thread(target=monitor_ssh_logs)
    monitor_thread.start()

    # Запускаем бота
    bot.polling(none_stop=True)
