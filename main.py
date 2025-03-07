import os
import re
import time
import threading
import subprocess
import telebot
from datetime import datetime, timedelta
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot_token = open('token.txt', 'r').read().strip()
bot = telebot.TeleBot(token=bot_token)
expected_chat_id = 416541312

# Создание клавиатуры
markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
item_day = telebot.types.KeyboardButton('Day')
item_week = telebot.types.KeyboardButton('Week')
item_month = telebot.types.KeyboardButton('Month')
item_year = telebot.types.KeyboardButton('Year')
active_connections = telebot.types.KeyboardButton('/connections')
markup.add(item_day, item_week, item_month, item_year, active_connections)


def send_startup_message():
    startup_message = "Привет! Я был заново запущен. Для получения статистики по подключениям используйте кнопки снизу."
    bot.send_message(expected_chat_id, startup_message, reply_markup=markup)


def handle_period_choice(message):
    if message.chat.id == expected_chat_id:
        period = message.text.lower()
        if period not in ['day', 'week', 'month', 'year']:
            bot.send_message(message.chat.id, 'Неверный период. Используйте \'day\', \'week\' или \'month\'.')
            return
        if period in ['week', 'month', 'year']:
            send_ssh_logs_file(period, message.chat.id)
        else:
            logs_message = get_ssh_logs(period)
            if logs_message:
                if len(logs_message) > 4095:
                    for x in range(0, len(logs_message), 4095):                                                                            
                        bot.send_message(message.chat.id, text=logs_message[x:x+4095])
                else:
                    bot.send_message(message.chat.id, logs_message)
            else:
                bot.send_message(message.chat.id, f'За выбранный период ({period}) попыток входа не найдено.')
    else:
        bot.send_message(message.chat.id, 'Вы не имеете доступа к этому боту.')


def get_ssh_logs(period):
    try:
        now = datetime.now()
        if period == 'day':
            start_time = now - timedelta(days=1)
        elif period == 'week':
            start_time = now - timedelta(weeks=1)
        elif period == 'month':
            start_time = now - timedelta(days=30)
        elif period == 'year':
            start_time = now - timedelta(days=365)
        command = ["journalctl", "_COMM=sshd", f"--since={start_time.strftime('%Y-%m-%d %H:%M:%S')}", f"--until={now.strftime('%Y-%m-%d %H:%M:%S')}", "--no-pager"]
        result = subprocess.check_output(command).decode('utf-8')
        message = f"Попытки входа за последний {period} с {start_time.strftime('%Y-%m-%d %H:%M:%S')} по {now.strftime('%Y-%m-%d %H:%M:%S')}:\n"
        successful_logins = re.findall(r'(\w+ \d+ \d+:\d+:\d+) .* Accepted password for (\S+) from (\S+) port \d+ ssh2', result)
        failed_logins = re.findall(r'(\w+ \d+ \d+:\d+:\d+) .* Failed password for (\S+) from (\S+) port \d+ ssh2', result)
        if successful_logins:
            message += "Успешные входы:\n"
            for time, login, ip_address in successful_logins:
                message += f"- {login} с IP-адреса {ip_address} в {time}\n"
        if failed_logins:
            message += "Неудачные входы:\n"
            for time, login, ip_address in failed_logins:
                message += f"- {login} с IP-адреса {ip_address} в {time}\n"
        return message
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при выполнении команды journalctl: {e}")
        return f"Ошибка при получении логов: {e}"
    except ValueError as ve:
        logger.error(f"Ошибка значения: {ve}")
        return str(ve)
    except Exception as e:
        logger.error(f"Неожиданная ошибка в get_ssh_logs: {e}")
        return f"Произошла неожиданная ошибка: {e}"


def send_ssh_logs_file(period, chat_id):
    try:
        logs_message = get_ssh_logs(period)
        if logs_message:
            # Сохраняем данные в файл с кодировкой UTF-8
            file_path = f"ssh_logs_{period}.txt"
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(logs_message)
            # Отправляем файл в Telegram
            with open(file_path, "rb") as file:
                bot.send_document(chat_id, file)
            # Удаляем файл после отправки
            os.remove(file_path)
        else:
            bot.send_message(chat_id, f'За выбранный период ({period}) попыток входа не найдено.')
    except ValueError as ve:
        return str(ve)
    except telebot.apihelper.ApiException as te:
        return f'TelegramError: {te}'
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при отправке файла: {e}")
        time.sleep(5)
        send_ssh_logs_file(period, chat_id)  # Повторная попытка
    except Exception as e:
        error_message = f'Error: {e}'
        if "Read timed out" in str(e):
            # Если таймаут, подождите и повторите попытку
            time.sleep(5)
            send_ssh_logs_file(chat_id, logs_message)
        print(error_message)
        return error_message


def monitor_ssh_logs():
    while True:
        try:
            last_log_time = datetime.now() - timedelta(seconds=1)
            while True:
                logs = get_new_ssh_logs(last_log_time)
                if logs:
                    last_log_time = datetime.now()
                    process_ssh_logs(logs)
                time.sleep(1)  # Добавляем небольшую задержку
        except Exception as e:
            logger.error(f'Ошибка в monitor_ssh_logs: {e}')
            time.sleep(10)  # Ждем 10 секунд перед повторной попыткой


def process_ssh_logs(logs):
    try:
        for log in logs:
            match_accepted = re.search(r'(\w+ \d+ \d+:\d+:\d+) .* Accepted password for (\S+) from (\S+) port \d+ ssh2', log)
            match_failed = re.search(r'(\w+ \d+ \d+:\d+:\d+) .* Failed password for (\S+) from (\S+) port \d+ ssh2', log)
            match_disconnected = re.search(r'(\w+ \d+ \d+:\d+:\d+) .* Disconnected from user (\S+) (\S+)', log)
            if match_accepted:
                log_time = match_accepted.group(1)
                username = match_accepted.group(2)
                ip_address = match_accepted.group(3)
                message = f"Пользователь {username} подключился в {log_time} с IP {ip_address}"
                bot.send_message(expected_chat_id, message)
                # TO-DO: Добавьть код обработки успешного входа здесь
            elif match_failed:
                log_time = match_failed.group(1)
                username = match_failed.group(2)
                ip_address = match_failed.group(3)
                message = f"Неудачная попытка входа в систему для пользователя {username} в {log_time} с IP {ip_address}"
                bot.send_message(expected_chat_id, message)
                # TO-DO: Добавьть код обработки неудачного входа здесь
            elif match_disconnected:
                log_time_str = match_disconnected.group(1)
                username = match_disconnected.group(2)
                ip_address = match_disconnected.group(3)
                log_time = datetime.strptime(log_time_str, '%b %d %H:%M:%S')
                formatted_log_time = log_time.strftime('%b %d %H:%M:%S')
                message = f"Пользователь {username} отключился в {formatted_log_time}"
                if ip_address:
                    message += f" from IP {ip_address}"
                bot.send_message(expected_chat_id, message)
                # TO-DO: Добавьть код обработки отключения пользователя здесь
    except Exception as e:
        logger.error(f'Error in process_ssh_logs: {e}')
        bot.send_message(expected_chat_id, f'Error in process_ssh_logs: {e}')


def get_new_ssh_logs(last_log_time):
    try:
        command = ["journalctl", "_COMM=sshd", f"--since={last_log_time.strftime('%Y-%m-%d %H:%M:%S')}", "--no-pager"]
        result = subprocess.check_output(command, timeout=30).decode('utf-8')
        logs = result.split('\n')
        return [log for log in logs if log.strip()]  # Удаляем пустые строки
    except subprocess.TimeoutExpired:
        logger.info("Превышено время ожидания при получении новых логов SSH.")
        return None
    except Exception as e:
        logger.error(f'Ошибка в get_new_ssh_logs: {e}')
        return None


# Запуск потока мониторинга
monitor_thread = threading.Thread(target=monitor_ssh_logs)
monitor_thread.start()

# Отправка приветственного сообщения
send_startup_message()


def get_active_connections():
    try:
        # Код для получения информации о текущих подключениях
        command = ["who"]
        result = subprocess.check_output(command).decode('utf-8')
        if not result.strip():  # Если нет активных подключений
            return "Нет активных подключений в данный момент."
        else:
            return result
    except Exception as e:
        return f"Error getting active connections: {e}"


@bot.message_handler(commands=['connections'])
def handle_active_connections(message):
    if message.chat.id == expected_chat_id:
        active_connections_info = get_active_connections()
        bot.send_message(message.chat.id, active_connections_info)
    else:
        bot.send_message(message.chat.id, 'Вы не имеете доступа к этой команде.')


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        if message.text:
            handle_period_choice(message)
    except Exception as e:
        logger.error(f'Error in handle_all_messages: {e}')
        bot.send_message(message.chat.id, "Произошла ошибка при обработке вашего сообщения. Пожалуйста, попробуйте еще раз.")


def check_telegram_connection():
    try:
        bot.get_me()
        return True
    except Exception as e:
        logger.error(f"Ошибка подключения к Telegram API: {e}")
        return False


if __name__ == "__main__":
    while True:
        try:
            if check_telegram_connection():
                bot.polling(none_stop=True, timeout=60)
            else:
                logger.info("Не удалось подключиться к Telegram API. Повторная попытка через 60 секунд.")
                time.sleep(60)
        except Exception as e:
            logger.error(f"Произошла ошибка в основном цикле бота: {e}")
            time.sleep(10)