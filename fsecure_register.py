import contextlib
import logging
import pathlib
import json
import sys
import io
import os
import traceback
import colorama
import platform
import datetime
import argparse
import re
import time
import random
import string
import threading
from typing import Optional, Tuple

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from colorama import Fore, Back, Style

colorama.init()

# ----------------------------------------------------------------------------
# Constants / logging (mirrored from EKey)
# ----------------------------------------------------------------------------
I_AM_EXECUTABLE = (True if (getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')) else False)
PATH_TO_SELF = sys.executable if I_AM_EXECUTABLE else __file__
LOG_PATH = pathlib.Path(PATH_TO_SELF).parent.resolve().joinpath('F-Secure-Register.log')

VERSION = 'v1.0.0'
LOGO = f"""
███████╗   ███████╗███████╗ ██████╗██╗   ██╗██████╗ ███████╗
██╔════╝   ██╔════╝██╔════╝██╔════╝██║   ██║██╔══██╗██╔════╝
█████╗     ███████╗█████╗  ██║     ██║   ██║██████╔╝█████╗  
██╔══╝     ╚════██║██╔══╝  ██║     ██║   ██║██╔══██╗██╔══╝  
██║        ███████║███████╗╚██████╗╚██████╔╝██║  ██║███████╗
╚═╝        ╚══════╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝
                        F-Secure Auto Register (EKey style)
                        Version: {VERSION}
"""

INFO = f'{Fore.CYAN}[INFO]{Style.RESET_ALL}'
OK = f'{Fore.GREEN}[OK]{Style.RESET_ALL}'
WARN = f'{Fore.YELLOW}[WARN]{Style.RESET_ALL}'
ERROR = f'{Fore.RED}[ERROR]{Style.RESET_ALL}'
INPT = f'{Fore.YELLOW}[INPT]{Style.RESET_ALL}'

DEFAULT_MAX_ITER = 30
DEFAULT_DELAY = 1

def console_log(message, status=INFO):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    print(f'[{Fore.LIGHTBLACK_EX}{timestamp}{Style.RESET_ALL}] {status} {message}')

def enable_logging():
    logging.basicConfig(
        level=logging.INFO,
        filemode='w',
        filename=LOG_PATH,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def data_generator(length, only_numbers=False):
    if only_numbers:
        return ''.join(random.choice(string.digits) for _ in range(length))
    length += random.randint(1, 10)
    data = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("""!"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~""")
    ]
    chars = string.ascii_letters + string.digits + string.punctuation
    data += [random.choice(chars) for _ in range(length - 3)]
    random.shuffle(data)
    return ''.join(data)

# ----------------------------------------------------------------------------
# Email APIs (request based, like EKey)
# ----------------------------------------------------------------------------
class MailTmAPI:
    """Temporary email via mail.tm (no browser required)."""
    def __init__(self):
        self.class_name = 'mailtm'
        self.email = None
        self.password = None
        self.token = None

    def init(self):
        domains_resp = requests.get('https://api.mail.tm/domains')
        if domains_resp.status_code != 200:
            raise RuntimeError('MailTmAPI: cannot get domains')
        domains = domains_resp.json().get('hydra:member', domains_resp.json())
        domain = domains[0]['domain'] if domains else 'mail.tm'
        login = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}{random.randint(1000, 9999)}"
        self.email = f"{login}@{domain}"
        self.password = data_generator(12)
        r = requests.post('https://api.mail.tm/accounts',
                          json={'address': self.email, 'password': self.password})
        if r.status_code not in (200, 201):
            self.email = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}{random.randint(10000, 99999)}@{domain}"
            r = requests.post('https://api.mail.tm/accounts',
                              json={'address': self.email, 'password': self.password})
            if r.status_code not in (200, 201):
                raise RuntimeError('MailTmAPI: account creation failed')
        t = requests.post('https://api.mail.tm/token',
                          json={'address': self.email, 'password': self.password})
        if t.status_code != 200:
            raise RuntimeError('MailTmAPI: token failed')
        self.token = t.json()['token']

    def get_messages(self):
        headers = {'Authorization': f'Bearer {self.token}'}
        r = requests.get('https://api.mail.tm/messages', headers=headers)
        if r.status_code != 200:
            return []
        ids = [m['id'] for m in r.json().get('hydra:member', [])]
        messages = []
        for mid in ids:
            mr = requests.get(f'https://api.mail.tm/messages/{mid}', headers=headers)
            if mr.status_code != 200:
                continue
            msg = mr.json()
            html = msg.get('html', [])
            if isinstance(html, list):
                html = html[0] if html else ''
            text = msg.get('text', '')
            messages.append({
                'from': msg.get('from', {}).get('address', ''),
                'subject': msg.get('subject', ''),
                'body': (html or text or ''),
            })
        return messages


class OneSecMailAPI:
    """Temporary email via 1secmail.com (EKey default)."""
    def __init__(self):
        self.class_name = '1secmail'
        self.__login = None
        self.__domain = None
        self.email = None
        self.__api = 'https://www.1secmail.com/api/v1/'

    def init(self):
        r = requests.get(f'{self.__api}?action=genRandomMailbox&count=1')
        if r.status_code != 200:
            raise RuntimeError('OneSecMailAPI: API access error!')
        self.__login, self.__domain = r.text[2:-2].split('@')
        self.email = f'{self.__login}@{self.__domain}'

    def read_email(self):
        url = f'{self.__api}?action=getMessages&login={self.__login}&domain={self.__domain}'
        r = requests.get(url)
        if r.status_code != 200:
            return []
        return r.json()

    def get_message(self, message_id):
        url = f'{self.__api}?action=readMessage&login={self.__login}&domain={self.__domain}&id={message_id}'
        r = requests.get(url)
        if r.status_code != 200:
            return {}
        return r.json()

    def get_messages(self):
        messages = []
        for m in self.read_email():
            body = self.get_message(m['id'])
            messages.append({
                'from': body.get('from', ''),
                'subject': body.get('subject', ''),
                'body': body.get('body', ''),
            })
        return messages


EMAIL_API_CLASSES = {
    'mailtm': MailTmAPI,
    '1secmail': OneSecMailAPI,
}
AVAILABLE_EMAIL_APIS = tuple(EMAIL_API_CLASSES.keys())

# ----------------------------------------------------------------------------
# Confirmation link extraction (F-Secure)
# ----------------------------------------------------------------------------
def get_confirmation_link(email_obj, max_attempts: int = 12, delay: int = 5) -> Optional[str]:
    for attempt in range(max_attempts):
        try:
            console_log(f'Checking mail (attempt {attempt + 1}/{max_attempts})...', INFO)
            messages = email_obj.get_messages()
            for msg in messages:
                body = str(msg.get('body', ''))
                match = re.search(r'href="(https://[^"]*f-secure[^"]*)"', body)
                if not match:
                    match = re.search(r'(https://[^\s"<>]*f-secure[^\s"<>]*)', body)
                if match:
                    link = match.group(1)
                    console_log(f'Confirmation link found: {link}', OK)
                    return link
            time.sleep(delay)
        except Exception as e:
            console_log(f'Mail check error: {e}', WARN)
            time.sleep(delay)
    console_log('Confirmation link not found', ERROR)
    return None


# ----------------------------------------------------------------------------
# F-Secure Register (mirrored from EKey EsetTools layout)
# ----------------------------------------------------------------------------
class FsecureRegister:
    def __init__(self, email_obj, password, first_name, last_name, driver):
        self.email_obj = email_obj
        self.password = password
        self.first_name = first_name
        self.last_name = last_name
        self.driver = driver

    def create_account(self):
        console_log('Opening registration page...', INFO)
        self.driver.get('https://my.f-secure.com/register')
        console_log(f'Current URL: {self.driver.current_url}', INFO)
        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, 'user.firstName'))
            )
        except Exception as e:
            dbg = f"debug_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            try:
                with open(dbg, 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)
                console_log(f'Page source saved to {dbg}', WARN)
            except Exception:
                pass
            console_log(f'Registration form not found! URL={self.driver.current_url}', ERROR)
            raise
        console_log('Filling form...', INFO)
        self.driver.find_element(By.ID, 'user.firstName').send_keys(self.first_name)
        self.driver.find_element(By.ID, 'user.familyName').send_keys(self.last_name)
        self.driver.find_element(By.ID, 'user.email').send_keys(self.email_obj.email)
        self.driver.find_element(By.ID, 'user.password').send_keys(self.password)
        console_log('Submitting form...', INFO)
        self.driver.find_element(By.ID, 'button-continue').click()
        console_log('Form submitted, waiting for confirmation email...', OK)
        return True

    def confirm_account(self):
        link = get_confirmation_link(self.email_obj)
        if not link:
            return False
        console_log('Navigating to confirmation link...', INFO)
        self.driver.get(link)
        time.sleep(5)
        console_log('Account successfully confirmed!', OK)
        return True


# ----------------------------------------------------------------------------
# WebDriver setup
# ----------------------------------------------------------------------------
def setup_driver(headless=True) -> webdriver.Chrome:
    options = Options()
    options.page_load_strategy = 'normal'
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument('--log-level=3')
    options.add_argument('--lang=en-US')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    return driver


# ----------------------------------------------------------------------------
# Single generation routine
# ----------------------------------------------------------------------------
def generate(email_api_name: str, headless: bool, disable_output_file: bool) -> Optional[str]:
    email_obj = EMAIL_API_CLASSES[email_api_name]()
    driver = None
    try:
        console_log(f'[{email_api_name}] Mail registration...', INFO)
        email_obj.init()
        if email_obj.email is None:
            raise RuntimeError('Mail registration failed!')
        console_log(f'Mail: {email_obj.email}', OK)

        first_name = ''.join(random.choices(string.ascii_letters, k=random.randint(4, 9))).capitalize()
        last_name = ''.join(random.choices(string.ascii_letters, k=random.randint(4, 9))).capitalize()
        password = data_generator(12)
        console_log(f'Name: {first_name} {last_name}', INFO)

        driver = setup_driver(headless)
        reg = FsecureRegister(email_obj, password, first_name, last_name, driver)
        reg.create_account()
        confirmed = reg.confirm_account()
        if not confirmed:
            return None

        output_line = '\n'.join([
            '', '-------------------------------------------------',
            f'Account Email: {email_obj.email}',
            f'Account Password: {password}',
            '-------------------------------------------------', ''
        ])
        console_log(output_line, OK)
        if not disable_output_file:
            date = datetime.datetime.now()
            filename = f"{date.day}.{date.month}.{date.year} - F-Secure ACCOUNTS.txt"
            with open(filename, 'a', encoding='utf-8') as f:
                f.write(output_line + '\n')
        return output_line
    except Exception as e:
        console_log(f'Error: {e}', ERROR)
        return None
    finally:
        if driver:
            driver.quit()


# ----------------------------------------------------------------------------
# CLI (mirrored from EKey main.py argparse)
# ----------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description='F-Secure Auto Register (EKey style)')
    parser.add_argument('--account', action='store_true', required=True,
                        help='Create F-Secure account')
    parser.add_argument('--email-api', choices=AVAILABLE_EMAIL_APIS, default='mailtm',
                        help='Email API to use')
    parser.add_argument('--no-headless', action='store_true', help='Show browser window')
    parser.add_argument('--repeat', type=int, default=1, help='How many times to repeat')
    parser.add_argument('--disable-output-file', action='store_true', help='Disable txt output')
    parser.add_argument('--disable-logging', action='store_true', help='Disable logging')
    return vars(parser.parse_args())


def main():
    print(LOGO)
    args = parse_args()
    if not args['disable_logging']:
        enable_logging()
        logging.info(f'F-Secure Auto Register {VERSION}')

    headless = not args['no_headless']
    repeat = max(1, abs(args['repeat']))

    successful = 0
    failed = 0
    for i in range(1, repeat + 1):
        console_log(f'\n{Fore.MAGENTA}====== Generation {i}/{repeat} ======{Style.RESET_ALL}\n', INFO)
        try:
            result = generate(args['email_api'], headless, args['disable_output_file'])
        except Exception as e:
            logging.critical("EXC_INFO:", exc_info=True)
            console_log(f'Critical error: {e}', ERROR)
            result = None
        if result:
            successful += 1
        else:
            failed += 1
        if i < repeat:
            console_log('Pause 10 seconds...', INFO)
            time.sleep(10)

    console_log(f'\n{Fore.MAGENTA}====== SUMMARY ======{Style.RESET_ALL}', INFO)
    console_log(f'Successful: {Fore.GREEN}{successful}{Style.RESET_ALL}', OK if successful else INFO)
    console_log(f'Failed: {Fore.RED}{failed}{Style.RESET_ALL}', OK if failed == 0 else WARN)
    if successful and not args['disable_output_file']:
        console_log('Data saved to F-Secure ACCOUNTS.txt', OK)

    try:
        input(f'\n{INPT} Press Enter to exit...')
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console_log('Interrupted by user', WARN)
        sys.exit(0)
