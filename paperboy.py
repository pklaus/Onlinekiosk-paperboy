#!/usr/bin/env python

"""
Onlinekiosk-paperboy delivers your newspapers and magazines freshly every day.
"""

try:
    from bs4 import BeautifulSoup
    import requests
    ext_deps = True
except ImportError:
    ext_deps = False
import random
import http.cookiejar
import time
import os
import sys
import stat
import logging
from urllib.parse import urljoin
import re

BASE_URL = 'https://www.onlinekiosk.de/index.php'

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-agent', '-ua', required=True, help='User agent you want paperboy to use.')
    parser.add_argument('--output-directory', '-o', required=True, help='Directory to store the PDFs of the downloaded newspaper issues.')
    parser.add_argument('--email', '-e', required=True, help='Email address of your account at onlinekiosk.de')
    parser.add_argument('--password', '-p', required=True, help='Password for your account at onlinekiosk.de')
    parser.add_argument('--cookie-file', '-c', help='File to store the cookies in.', default='~/.Onlinekiosk-paperboy_cookies.txt')
    parser.add_argument('--debug', '-d', action='store_true', help='Increase verbosity.')

    if not ext_deps: parser.error("Missing at least one of the python modules 'requests' or 'beautifulsoup4'.")

    args = parser.parse_args()

    if args.debug: level = logging.DEBUG
    else: level = logging.INFO
    logging.basicConfig(level=level, format='%(levelname)-8s %(message)s')
    logging.getLogger("requests").setLevel(logging.WARNING)

    browser = Browser(args.user_agent, os.path.expanduser(args.cookie_file))

    random_sleep()
    index_page = browser.get('https://www.onlinekiosk.de/')
    random_sleep()
    index_page = browser.get(BASE_URL)
    random_sleep()

    if BeautifulSoup(index_page.text).find('a', text='Logout'):
        logging.info("Already logged in.")
        download_page = browser.get('https://www.onlinekiosk.de/index.php/customer/downloads.html')
    else:
        login_form = BeautifulSoup(index_page.text).find(id='login-dialog-form')
        csrf_field = login_form.find('input', type='hidden')
        form_data = {csrf_field['name']: csrf_field['value']}

        login_data = {
          'username': args.email,
          'passwort': args.password
        }
        login_data.update(form_data)
        logging.info("Trying to log in.")
        login_answer = browser.post('https://www.onlinekiosk.de/index.php/customer/login.html', data=login_data)
        random_sleep()

        if not BeautifulSoup(login_answer.text).find('a', text='Logout'):
            logging.error('Incorrect credentials?')
            sys.exit(1)

        download_page = login_answer

    # Create output directory if it doesn't exist:
    if not os.path.isdir(args.output_directory):
        os.makedirs(args.output_directory)

    list_headers = {
      'Accept': 'application/json, text/javascript, */*; q=0.01',
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'X-Requested-With': 'XMLHttpRequest',
      'Connection': 'keep-alive',
      'Pragma': 'no-cache',
      'Cache-Control': 'no-cache'
    }

    # Download all issues:
    cd_re = re.compile('filename=(.*)') # Content-Disposition regex
    products = BeautifulSoup(download_page.text).select('article.product')
    for product in products:
        random_sleep()
        name = product.find('h2').text
        list_data = {
          'action': 'customer:getEditions',
          'id': product['data-ok-id']
        }
        list_data.update(form_data)
        logging.info('Asking for issues of "{}".'.format(name))
        list_answer = browser.post(BASE_URL, data=list_data, headers=list_headers)
        random_sleep()
        # Create output directory for product if it doesn't exist:
        product_directory = os.path.join(args.output_directory, name)
        if not os.path.isdir(product_directory):
            os.makedirs(product_directory)
        for issue in list_answer.json()['result']:
            random_sleep()
            issue_data = {
              'action': 'customer:gotoDownload',
              'type': 'edition',
              'id': issue['id']
            }
            issue_data.update(form_data)
            issue_response = browser.post(BASE_URL, data=issue_data, stream=True)
            try:
                filename = cd_re.search(issue_response.headers['Content-Disposition']).group(1)
            except (IndexError, AttributeError, KeyError):
                logging.warning('Something wrong with this issue: {} ?'.format(issue['title']))
                issue_response.close()
                continue
            # But we don't want the default file name (like `HB_1201_Download.pdf`)
            # Rather construct a file name like `Ausgabe vom 21.11.2014.pdf`:
            filename = "{title}.{formatText}".format(**issue)
            fullpath = os.path.join(product_directory, filename)
            if os.path.exists(fullpath):
                logging.info("{} already downloaded... ".format(filename))
                issue_response.close()
                continue
            logging.info("Downloading {}...".format(filename))
            with open(fullpath, 'wb') as f:
                for chunk in issue_response.iter_content(1024):
                    f.write(chunk)

    browser.close()

class Browser(object):
    def __init__(self, user_agent, cookie_file, store_any_cookie=False):
        self.s = requests.Session()
        self.store_any_cookie = store_any_cookie
        self.cookie_file = cookie_file
        if cookie_file:
            self.s.cookies = http.cookiejar.LWPCookieJar()
            try:
                self.s.cookies.load(cookie_file, ignore_discard=self.store_any_cookie)
            except FileNotFoundError:
                pass
        headers = {
          'User-Agent': user_agent,
          'Dnt': '1',
          'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          'Accept-Encoding': "gzip, deflate",
          'Accept-Language': "en,en-gb;q=0.8,en-us;q=0.5,de;q=0.3"
        }
        self.s.headers.update(headers)
        self.last = None

    def close(self):
        logging.debug("saving cookies")
        try:
            self.s.cookies.save(self.cookie_file, ignore_discard=self.store_any_cookie)
        except:
            pass

    def get_json(self, *args, **kwargs):
        # Different headers for json requests:
        headers = {
          'Accept': 'application/json, text/javascript, */*; q=0.01',
          'X-Requested-With': 'XMLHttpRequest',
          'Referer': 'http://www.faz.net/e-paper/',
          'Connection': 'keep-alive',
        }
        try:
            kwargs['headers'].update(headers)
        except KeyError:
            kwargs['headers'] = headers
        return self.s.get(*args, **kwargs).json()

    def set_referer(self, func, *args, **kwargs):

        if self.last:
            headers = { 'Referer': self.last }
            try:
                kwargs['headers'].update(headers)
            except KeyError:
                kwargs['headers'] = headers
        self.last = args[0]
        return func(*args, **kwargs)

    def get(self, *args, **kwargs):
        logging.debug('Browser GET {}'.format(args[0]))
        return self.set_referer(self.s.get, *args, **kwargs)

    def post(self, *args, **kwargs):
        logging.debug('Browser POST {}'.format(args[0]))
        return self.set_referer(self.s.post, *args, **kwargs)

def random_sleep(min_sec=0.6, max_sec=5.3):
    st = random.uniform(min_sec, max_sec)
    logging.debug('Sleep time: {}'.format(st))
    time.sleep(st)

if __name__ == "__main__":
    main()

