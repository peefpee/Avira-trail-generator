#!/usr/bin/env python3

import time
import logging
import sys
import os
import re
import random
import requests
import hashlib
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class TempMailProvider:
    """Temporary email client: Mail.tm → Temp-Mail.org → Maildrop"""
    def __init__(self):
        self.provider = None
        self.email = None
        self.token = None
        self.password = None

    def create_email(self):
        # 1) Mail.tm via Web API
        try:
            self._create_mailtm_account()
            logging.info(f"📧 Created Mail.tm address: {self.email}")
            self.provider = "mailtm"
            return self.email
        except Exception as e:
            logging.warning(f"⚠️ Mail.tm failed: {e}")

        # 2) Temp-Mail.org fallback
        try:
            resp = requests.get("https://api.temp-mail.org/request/domains/format/json/")
            domains = resp.json() if resp.ok else ["temp-mail.org", "mailtemp.net"]
            user = ''.join(random.choices('abcdefghijkmnpqrstuvwxyz23456789', k=10))
            domain = random.choice(domains)
            self.email = f"{user}@{domain}"
            self.provider = "tempmail_org"
            logging.info(f"📧 Created Temp-Mail.org address: {self.email}")
            return self.email
        except Exception as e:
            logging.warning(f"⚠️ Temp-Mail.org failed: {e}")

        # 3) Maildrop fallback
        user = ''.join(random.choices('abcdefghijkmnpqrstuvwxyz23456789', k=12))
        self.email = f"{user}@maildrop.cc"
        self.provider = "maildrop"
        logging.info(f"📧 Created Maildrop address: {self.email}")
        return self.email

    def _create_mailtm_account(self):
        resp = requests.get("https://api.mail.tm/domains")
        resp.raise_for_status()
        domains = resp.json().get("hydra:member", [])
        domain = random.choice(domains).get("domain")
        user = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
        self.email = f"{user}@{domain}"
        self.password = ''.join(random.choices(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=16
        ))
        acct = requests.post(
            "https://api.mail.tm/accounts",
            json={"address": self.email, "password": self.password}
        )
        acct.raise_for_status()
        token_resp = requests.post(
            "https://api.mail.tm/token",
            json={"address": self.email, "password": self.password}
        )
        token_resp.raise_for_status()
        self.token = token_resp.json().get("token")

    def get_messages(self):
        if self.provider == "mailtm":
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.get("https://api.mail.tm/messages", headers=headers)
            return resp.json().get("hydra:member", [])
        elif self.provider == "tempmail_org":
            md5_hash = hashlib.md5(self.email.encode()).hexdigest()
            url = f"https://api.temp-mail.org/request/mail/id/{md5_hash}/format/json/"
            resp = requests.get(url)
            return resp.json() if resp.ok else []
        else:
            inbox = self.email.split("@")[0]
            query = {"query": f'''query GetInbox {{ inbox(mailbox: "{inbox}") {{ id headerFrom subject date }} }}''' }
            resp = requests.post("https://api.maildrop.cc/graphql", json=query)
            return resp.json().get("data", {}).get("inbox", [])

    def read_message(self, msg_id):
        if self.provider == "mailtm":
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.get(f"https://api.mail.tm/messages/{msg_id}", headers=headers)
            data = resp.json()
            text = data.get("text") or ""
            html = data.get("html") or ""
            if isinstance(text, list):
                text = "".join(text)
            if isinstance(html, list):
                html = "".join(html)
            return text + "\n" + html
        elif self.provider == "tempmail_org":
            for m in self.get_messages():
                if m.get("id") == msg_id:
                    return m.get("mail_text") or m.get("text") or m.get("body", "")
            return ""
        else:
            inbox = self.email.split("@")[0]
            query = {"query": f'''query GetMessage {{ message(mailbox: "{inbox}", id: "{msg_id}") {{ data html }} }}''' }
            resp = requests.post("https://api.maildrop.cc/graphql", json=query)
            msg = resp.json().get("data", {}).get("message", {})
            return (msg.get("data") or "") + "\n" + (msg.get("html") or "")


class AviraAutomation:
    def __init__(self):
        self.driver = None
        self.temp_mail = TempMailProvider()
        self.email_address = None
        self.logger = self.setup_logging()

    def setup_logging(self):
        os.makedirs("logs", exist_ok=True)
        fn = f"logs/avira_{datetime.now():%Y%m%d_%H%M%S}.log"
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(fn, encoding="utf-8"), logging.StreamHandler(sys.stdout)]
        )
        return logging.getLogger()

    def setup_driver(self):
        opts = Options()
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.logger.info("✅ WebDriver initialized.")

    def handle_cookies(self):
        for sel in ['button[id*="accept"]', 'button[class*="accept"]', '//button[contains(text(),"Accept")]']:
            try:
                elems = (self.driver.find_elements(By.XPATH, sel) if sel.startswith("//") else self.driver.find_elements(By.CSS_SELECTOR, sel))
                for e in elems:
                    if e.is_displayed():
                        e.click()
                        self.logger.info(f"🍪 Clicked cookie button: {sel}")
                        return
            except:
                continue

    def detect_captcha(self):
        for sel in ["iframe[src*='recaptcha']", ".g-recaptcha", "#recaptcha"]:
            try:
                if any(e.is_displayed() for e in self.driver.find_elements(By.CSS_SELECTOR, sel)):
                    return True
            except:
                continue
        return False

    def wait_for_captcha(self, timeout=300):
        if not self.detect_captcha():
            return True
        self.logger.info("🤖 CAPTCHA detected; please solve it manually…")
        start = time.time()
        while time.time() - start < timeout:
            if not self.detect_captcha():
                self.logger.info("✅ CAPTCHA solved.")
                return True
            time.sleep(2)
        self.logger.warning("⏰ CAPTCHA wait timed out.")
        return False

    def submit_email_form(self):
        self.driver.get("https://campaigns.avira.com/en/crm/trial/prime-trial-3m")
        time.sleep(5)
        self.handle_cookies()
        input_el = None
        for sel in ["input[type='email']", "#email", "[name*=email]"]:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    input_el = el
                    break
            except:
                continue
        if not input_el:
            raise Exception("❌ Email input not found.")
        input_el.clear()
        input_el.send_keys(self.email_address)
        self.logger.info(f"✅ Entered email: {self.email_address}")
        for sel in ["button[type='submit']", "//button[contains(text(),'Email')]"]:
            try:
                btn = (self.driver.find_element(By.XPATH, sel) if sel.startswith("//") else self.driver.find_element(By.CSS_SELECTOR, sel))
                if btn.is_displayed():
                    btn.click()
                    self.logger.info("📤 Form submitted.")
                    break
            except:
                continue
        self.wait_for_captcha()

    def get_activation_link(self):
        self.logger.info("📨 Polling for activation email…")
        start = time.time()
        while time.time() - start < 300:
            msgs = self.temp_mail.get_messages()
            self.logger.debug(f"🔍 Inbox ({self.temp_mail.provider}): {json.dumps(msgs, indent=2)}")
            for m in msgs:
                msg_id = m.get("id")
                content = self.temp_mail.read_message(msg_id)
                if link := re.search(r'https://my\.avira\.com/en/auth/login\?[^\s"<>]+', content):
                    link = link.group(0).rstrip('.,);')
                    self.logger.info(f"🔗 Activation link found: {link}")
                    return link
            time.sleep(5)
        raise Exception("❌ Activation email not received within timeout.")

    def save_link(self, link):
        with open("activation_links.txt", "a", encoding="utf-8") as f:
            f.write(f"{self.email_address}:{link}\n")
        self.logger.info("💾 Activation link saved.")

    def cleanup(self):
        if self.driver:
            self.driver.quit()
        self.logger.info("🧹 Cleanup done.")

    def run(self):
        try:
            self.setup_driver()
            self.email_address = self.temp_mail.create_email()
            self.submit_email_form()
            link = self.get_activation_link()
            self.save_link(link)
            return True
        except Exception as e:
            self.logger.error(e, exc_info=True)
            return False
        finally:
            self.cleanup()


def main():
    print("1. Generate a fixed number of trials")
    print("2. Run until stopped")
    mode = None
    while mode not in ("1", "2"):
        mode = input("Choose (1 or 2): ").strip()
    count = int(input("How many trials? ").strip()) if mode == "1" else None
    i = 0
    while True:
        print(f"⚙️ Running automation #{i+1}")
        bot = AviraAutomation()
        bot.run()
        i += 1
        if count and i >= count:
            break
        time.sleep(random.uniform(5, 15))


if __name__ == "__main__":
    main()
