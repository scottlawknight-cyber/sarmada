import sys
import os
import json
import asyncio
import threading
import urllib.parse
import urllib.request
import time
import winsound
import shutil
import socket
import subprocess
import base64
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QTextEdit, QGroupBox,
                             QFormLayout, QDialog, QMessageBox, QScrollArea, QGridLayout,
                             QInputDialog, QCheckBox, QComboBox, QSpinBox, QRadioButton,
                             QButtonGroup)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from curl_cffi.requests import AsyncSession
from Crypto.Cipher import AES

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

GLOBAL_BROWSER_LOCK = threading.Lock()
GLOBAL_SOUND_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
DATA_FILE = "sarmada_data.json"
SHAMCASH_MASTER_KEY = b"g0Zrgp8XRK/BN2ZAtUfJDQ=="  # مفتاح AES-192


def load_all_data():
    with FILE_LOCK:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}


def save_all_data(data):
    with FILE_LOCK:
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[!] خطأ حفظ: {e}")


def get_chrome_main_version():
    try:
        if sys.platform == 'win32':
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Google\Chrome\BLBeacon')
                version, _ = winreg.QueryValueEx(key, 'version')
                return int(version.split('.')[0])
            except:
                pass
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome')
                version, _ = winreg.QueryValueEx(key, 'version')
                return int(version.split('.')[0])
            except:
                pass
    except:
        pass
    return None


def parse_proxy_string(proxy_str, proxy_type="http"):
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None
    if proxy_str.startswith(("http://", "https://", "socks5://", "socks4://")):
        return proxy_str
    if proxy_type == "socks5":
        return f"socks5://{proxy_str}"
    return f"http://{proxy_str}"


def send_telegram_message(token, chat_id, text, retries=3):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return
        except:
            time.sleep(3)



# =============================================
# نظام شام كاش - تشفير ودفع
# =============================================
def shamcash_get_session_key(forge_cookie):
    """استخراج مفتاح الجلسة من كوكي forge"""
    parts = forge_cookie.split('.')
    encrypted_data = base64.b64decode(parts[0])
    iv = base64.b64decode(parts[1])
    tag = encrypted_data[-16:]
    ciphertext = encrypted_data[:-16]
    cipher = AES.new(SHAMCASH_MASTER_KEY, AES.MODE_GCM, nonce=iv)
    cipher.update(b"")
    return cipher.decrypt_and_verify(ciphertext, tag)


def shamcash_encrypt_payload(payload_dict, auth_token, access_token, session_key):
    """تشفير payload لشام كاش"""
    # استخراج SessionId من JWT
    jwt_payload = auth_token.split('.')[1]
    jwt_payload += '=' * (4 - len(jwt_payload) % 4)
    session_id = json.loads(base64.b64decode(jwt_payload).decode('utf-8'))['SessionId']

    payload_dict['accessToken'] = access_token
    payload_dict['SessionId'] = session_id

    json_data = json.dumps(payload_dict, separators=(',', ':'))
    iv = os.urandom(12)
    cipher = AES.new(session_key, AES.MODE_GCM, nonce=iv)
    cipher.update(b"")
    ciphertext, tag = cipher.encrypt_and_digest(json_data.encode('utf-8'))
    encrypted = ciphertext + tag
    return base64.b64encode(encrypted).decode('utf-8') + "." + base64.b64encode(iv).decode('utf-8')


class ShamcashPayWorker(QThread):
    """خيط دفع شام كاش - بدون بروكسي مطلقاً"""
    log_signal = pyqtSignal(str)
    pay_result_signal = pyqtSignal(bool, str)  # success, message

    def __init__(self, session_id, payment_code, shamcash_tokens):
        super().__init__()
        self.session_id = session_id
        self.payment_code = payment_code
        self.shamcash_tokens = shamcash_tokens  # dict with auth_token, access_token, forge_cookie

    def run(self):
        try:
            auth_token = self.shamcash_tokens['auth_token']
            access_token = self.shamcash_tokens['access_token']
            forge_cookie = self.shamcash_tokens['forge_cookie']

            session_key = shamcash_get_session_key(forge_cookie)

            # 1. استعلام الفاتورة
            self.log_signal.emit(f"🏦 [{self.session_id}] شام كاش: جاري الاستعلام عن {self.payment_code}...")
            check_payload = {"values": [{"key": "process_number", "value": self.payment_code}]}
            enc_data = shamcash_encrypt_payload(check_payload, auth_token, access_token, session_key)

            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Bearer {auth_token}",
                "e": "true",
                "x-requested-with": "XMLHttpRequest",
                "lang": "ar",
                "origin": "https://shamcash.sy",
                "referer": "https://shamcash.sy/ar/application/home",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            import requests
            resp = requests.post(
                "https://payment.shamcash.sy/v4/api/Billing/presentment?serviceId=37",
                json={"encData": enc_data}, headers=headers, timeout=30
            )
            data = resp.json()

            if not data.get("succeeded") or not data.get("data"):
                msg = data.get("message", "فشل الاستعلام")
                self.log_signal.emit(f"❌ [{self.session_id}] شام كاش استعلام فشل: {msg}")
                self.pay_result_signal.emit(False, msg)
                return

            fields = data["data"][0]
            process_no = next((item["value"] for item in fields if item["key"] == "process_no"), None)
            due_amount = next((item["value"] for item in fields if item["key"] == "due_amount"), None)

            if not process_no or not due_amount:
                self.log_signal.emit(f"❌ [{self.session_id}] شام كاش: لم يُعثر على بيانات الدفع.")
                self.pay_result_signal.emit(False, "لم يُعثر على بيانات")
                return

            self.log_signal.emit(
                f"✅ [{self.session_id}] شام كاش: جاهز للدفع - المبلغ: {due_amount} ل.س")

            # 2. تنفيذ الدفع
            self.log_signal.emit(f"💳 [{self.session_id}] شام كاش: جاري الدفع...")
            pay_payload = {"values": [
                {"key": "process_no", "value": process_no},
                {"key": "due_amount", "value": due_amount}
            ]}
            enc_pay = shamcash_encrypt_payload(pay_payload, auth_token, access_token, session_key)

            pay_resp = requests.post(
                "https://payment.shamcash.sy/v4/api/Billing/pay?serviceId=37",
                json={"encData": enc_pay}, headers=headers, timeout=30
            )
            pay_data = pay_resp.json()

            if pay_data.get("succeeded"):
                self.log_signal.emit(
                    f"🎉 [{self.session_id}] شام كاش: تم الدفع بنجاح! المبلغ: {due_amount}")
                self.pay_result_signal.emit(True, f"تم الدفع {due_amount} ل.س")
            else:
                msg = pay_data.get("message", "فشل الدفع")
                self.log_signal.emit(f"❌ [{self.session_id}] شام كاش دفع فشل: {msg}")
                self.pay_result_signal.emit(False, msg)

        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}] خطأ شام كاش: {e}")
            self.pay_result_signal.emit(False, str(e))



class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("سجلات النظام المركزية")
        self.resize(800, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #0d1117; color: #58a6ff; font-family: Consolas; font-size: 13px;")
        layout.addWidget(self.log_area)
        clear_btn = QPushButton("🧹 مسح السجلات")
        clear_btn.setStyleSheet("background-color: #21262d; color: white; padding: 5px;")
        clear_btn.clicked.connect(self.log_area.clear)
        layout.addWidget(clear_btn)

    def append_log(self, text):
        self.log_area.append(text)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())


class HiddenSessionsDialog(QDialog):
    def __init__(self, mw, parent=None):
        super().__init__(parent)
        self.mw = mw
        self.setWindowTitle("الجلسات المطفأة")
        self.resize(400, 300)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet("QDialog{background:#0d1117;color:#c9d1d9;} QLabel{font-weight:bold;} QPushButton{background:#238636;color:white;border-radius:4px;padding:5px;}")
        self.layout = QVBoxLayout(self)
        self.populate()

    def populate(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        hidden = [c for c in self.mw.sessions if c.isHidden()]
        if not hidden:
            self.layout.addWidget(QLabel("✅ لا توجد جلسات مطفأة."))
            return
        for card in hidden:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"جلسة: {card.session_id}"))
            row.addStretch()
            btn = QPushButton("🔄 استعادة")
            btn.clicked.connect(lambda ch, c=card: (c.show(), self.populate()))
            row.addWidget(btn)
            self.layout.addLayout(row)


class GroupActionDialog(QDialog):
    def __init__(self, mw, parent=None):
        super().__init__(parent)
        self.mw = mw
        self.setWindowTitle("إدارة المجموعات")
        self.resize(850, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("QDialog{background:#0d1117;color:#c9d1d9;} QCheckBox{color:#58a6ff;font-weight:bold;} QPushButton{border-radius:4px;padding:6px;font-weight:bold;}")
        self.rows = []
        self.conns = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        b1 = QPushButton("☑️ الكل"); b1.clicked.connect(lambda: [r['chk'].setChecked(True) for r in self.rows])
        b2 = QPushButton("☐ إلغاء"); b2.clicked.connect(lambda: [r['chk'].setChecked(False) for r in self.rows])
        top.addWidget(b1); top.addWidget(b2); top.addStretch()
        lay.addLayout(top)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        cont = QWidget(); self.ll = QVBoxLayout(cont); self.ll.setAlignment(Qt.AlignmentFlag.AlignTop)
        for card in [c for c in self.mw.sessions if not c.isHidden()]:
            row = QHBoxLayout()
            chk = QCheckBox(card.session_id); row.addWidget(chk, 2)
            row.addWidget(QLabel(card.inp_plate.text()), 1)
            row.addWidget(QLabel(card.inp_date.text()), 1)
            ls = QLabel(card.lbl_status.text()); row.addWidget(ls, 2)
            inp = QLineEdit(card.inp_payment.text()); inp.setReadOnly(True); row.addWidget(inp, 2)
            bp = QPushButton("📋"); bp.clicked.connect(lambda ch, i=inp: QApplication.clipboard().setText(i.text()) if i.text() else None)
            row.addWidget(bp, 1)
            self.ll.addLayout(row)
            self.rows.append({'card': card, 'chk': chk})
        scroll.setWidget(cont); lay.addWidget(scroll)
        acts = QHBoxLayout()
        a1 = QPushButton("⚡ إرسال"); a1.setStyleSheet("background:#d29922;color:white;"); a1.clicked.connect(lambda: self._do("single"))
        a2 = QPushButton("🚀 قنص"); a2.setStyleSheet("background:#1f6feb;color:white;"); a2.clicked.connect(lambda: self._do("snipe"))
        a3 = QPushButton("🛑 إيقاف"); a3.setStyleSheet("background:#da3633;color:white;"); a3.clicked.connect(self._stp)
        acts.addWidget(a1); acts.addWidget(a2); acts.addWidget(a3)
        lay.addLayout(acts)

    def _do(self, mode):
        for r in self.rows:
            if r['chk'].isChecked() and r['card'].xsrf_token:
                r['card'].start_request(mode)

    def _stp(self):
        for r in self.rows:
            if r['chk'].isChecked(): r['card'].stop_request()

    def closeEvent(self, ev):
        for s, c in self.conns:
            try: s.disconnect(c)
            except: pass
        super().closeEvent(ev)



class RequestWorker(QThread):
    log_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str, str, str, int)  # code, fee, appt_id, tid
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(int)
    response_signal = pyqtSignal(int, int, str)

    def __init__(self, session_id, payload, headers, cookies, mode="snipe", thread_id=0, proxy_url=None):
        super().__init__()
        self.session_id = session_id
        self.payload = payload
        self.headers = headers
        self.cookies = cookies
        self.mode = mode
        self.thread_id = thread_id
        self.proxy_url = proxy_url
        self.is_running = True

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._exec())
        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] خطأ: {e}")
        finally:
            try: loop.close()
            except: pass
            self.finished_signal.emit(self.thread_id)

    async def _exec(self):
        try: tip = socket.gethostbyname("api.mot.gov.sy")
        except: tip = "api.mot.gov.sy"
        mon_url = f"https://{tip}/api/provinces/804e7642-6798-4353-a556-f11d9aad2637/weeks/active"
        post_url = f"https://{tip}/api/appointments/book"
        if self.proxy_url:
            self.log_signal.emit(f"🔗 [{self.session_id}][T{self.thread_id}] بروكسي: {self.proxy_url}")
        async with AsyncSession(verify=False, proxy=self.proxy_url) as s:
            att = 0
            while self.is_running:
                att += 1
                if self.mode == "snipe":
                    try:
                        r = await s.get(mon_url, headers=self.headers, cookies=self.cookies, timeout=30)
                        if r.status_code == 200:
                            st = r.json().get("data",{}).get("registration",{}).get("state","")
                            if st != "open":
                                if att % 3 == 1: self.log_signal.emit(f"⏳ [{self.session_id}][T{self.thread_id}] مغلقة...")
                                await asyncio.sleep(1.5); continue
                    except Exception as e:
                        self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] مراقب: {e}")
                        await asyncio.sleep(1); continue
                try:
                    resp = await s.post(post_url, json=self.payload, headers=self.headers, cookies=self.cookies, timeout=30)
                    body = resp.text[:200] if resp.text else ""
                    self.response_signal.emit(self.thread_id, resp.status_code, body)
                    if resp.status_code in [200, 201]:
                        d = resp.json()
                        code = d.get('data',{}).get('payment_code','')
                        fee = str(d.get('data',{}).get('fee_amount',''))
                        aid = d.get('data',{}).get('appointment_id','')
                        self.success_signal.emit(code, fee, aid, self.thread_id)
                        with GLOBAL_SOUND_LOCK:
                            try: winsound.Beep(1000, 1500)
                            except: pass
                        break
                    elif resp.status_code == 422:
                        if self.mode == "single": break
                    elif resp.status_code in [401, 419]:
                        self.error_signal.emit("انتهت الجلسة."); break
                except Exception as e:
                    self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] {e}")
                if self.mode == "single": break
                await asyncio.sleep(0.3)

    def stop(self):
        self.is_running = False


class PaymentStatusWorker(QThread):
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(dict)

    def __init__(self, sid, appt_id, headers, cookies, proxy_url=None):
        super().__init__()
        self.sid = sid; self.appt_id = appt_id; self.headers = headers
        self.cookies = cookies; self.proxy_url = proxy_url

    def run(self):
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        try: loop.run_until_complete(self._check())
        except Exception as e: self.log_signal.emit(f"❌ [{self.sid}] {e}")
        finally: loop.close()

    async def _check(self):
        url = f"https://api.mot.gov.sy/api/appointments/{self.appt_id}/payment-status"
        h = dict(self.headers); h["Accept"] = "application/json, text/plain, */*"; h["Accept-Language"] = "ar"
        h.pop("Content-Type", None)
        async with AsyncSession(verify=False, proxy=self.proxy_url) as s:
            try:
                r = await s.get(url, headers=h, cookies=self.cookies, timeout=30)
                if r.status_code == 200:
                    self.result_signal.emit(r.json())
                else:
                    self.result_signal.emit({})
            except:
                self.result_signal.emit({})



class SessionCard(QGroupBox):
    payment_received = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    _log_signal = pyqtSignal(str)
    _ui_browser_btn_signal = pyqtSignal(str, bool)
    _ui_renew_btn_signal = pyqtSignal(bool)
    _ui_status_signal = pyqtSignal(str, str)

    def __init__(self, session_id, log_callback, rename_cb, delete_cb, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.log_callback = log_callback
        self.rename_callback = rename_cb
        self.delete_callback = delete_cb
        self.driver = None
        self.driver_lock = threading.Lock()
        self.xsrf_token = ""
        self.accurate_session = ""
        self.remember_token_name = ""
        self.remember_token_value = ""
        self.user_agent = ""
        self.workers = []
        self.last_appointment_id = ""
        # شام كاش
        self.shamcash_auth_token = ""
        self.shamcash_access_token = ""
        self.shamcash_forge_cookie = ""

        self._log_signal.connect(self.log_callback)
        self._ui_browser_btn_signal.connect(self._upd_br_btn)
        self._ui_renew_btn_signal.connect(self._upd_ren_btn)
        self._ui_status_signal.connect(self._upd_status_ui)

        self.setTitle(f"جلسة: {self.session_id}")
        self.setStyleSheet(
            "QGroupBox{border:2px solid #30363d;border-radius:8px;margin-top:10px;font-weight:bold;}"
            " QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 5px;color:#58a6ff;}")
        self.setup_ui()
        self.load_session_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # متصفح
        br = QHBoxLayout()
        self.btn_browser = QPushButton("🌐 فتح المتصفح")
        self.btn_browser.clicked.connect(self.launch_browser)
        self.btn_extract = QPushButton("🔄 سحب التوكن")
        self.btn_extract.clicked.connect(self.extract_tokens)
        self.btn_close_br = QPushButton("❌ إغلاق")
        self.btn_close_br.clicked.connect(self.close_browser)
        self.btn_close_br.setStyleSheet("color:#ff7b72;")
        br.addWidget(self.btn_browser); br.addWidget(self.btn_extract); br.addWidget(self.btn_close_br)
        layout.addLayout(br)

        # بيانات
        dl = QGridLayout()
        self.inp_name = QLineEdit("محمد بكور زنجي")
        self.inp_plate = QLineEdit("5138855")
        self.inp_date = QLineEdit("2026-07-06")
        self.cmb_transaction = QComboBox()
        self.cmb_transaction.addItem("تسجيل مركبة", "4a33195e-381c-4a9a-aeed-904a84ec2e01")
        self.cmb_transaction.addItem("فراغة", "9b6962c9-ae8f-4acd-86e3-e4e87af57e31")
        self.cmb_transaction.addItem("تسجيل دراجة", "cd98b615-6b25-4e6f-8969-e6df554bc1d8")
        self.cmb_transaction.addItem("حكم قضائي", "8f795e58-bbf0-4cb7-b1e8-cfc1b60038d6")
        self.cmb_transaction.addItem("تجديد ترخيص", "fd0df26f-9cf8-4f92-988a-83f09c70fcff")
        self.cmb_transaction.addItem("تسوية مقفل", "486ddf06-e59f-40e1-8408-a65a058e0003")
        self.cmb_transaction.setStyleSheet("background:#21262d;border:1px solid #30363d;color:#58a6ff;font-weight:bold;border-radius:4px;padding:4px;")
        dl.addWidget(QLabel("الاسم:"),0,0); dl.addWidget(self.inp_name,0,1)
        dl.addWidget(QLabel("اللوحة:"),0,2); dl.addWidget(self.inp_plate,0,3)
        dl.addWidget(QLabel("التاريخ:"),1,0); dl.addWidget(self.inp_date,1,1)
        dl.addWidget(QLabel("المعاملة:"),1,2); dl.addWidget(self.cmb_transaction,1,3)
        layout.addLayout(dl)

        # بروكسي
        pl = QHBoxLayout()
        self.chk_proxy = QCheckBox("تفعيل بروكسي"); self.chk_proxy.setStyleSheet("color:#f0883e;font-weight:bold;")
        self.radio_http = QRadioButton("HTTP"); self.radio_http.setChecked(True); self.radio_http.setStyleSheet("color:#58a6ff;")
        self.radio_socks = QRadioButton("SOCKS5"); self.radio_socks.setStyleSheet("color:#58a6ff;")
        self.proxy_grp = QButtonGroup(self); self.proxy_grp.addButton(self.radio_http); self.proxy_grp.addButton(self.radio_socks)
        self.inp_proxy = QLineEdit(); self.inp_proxy.setPlaceholderText("user:pass@host:port")
        pl.addWidget(self.chk_proxy); pl.addWidget(self.radio_http); pl.addWidget(self.radio_socks); pl.addWidget(self.inp_proxy, 1)
        layout.addLayout(pl)

        # خيوط
        tl = QHBoxLayout()
        tl.addWidget(QLabel("خيوط:"))
        self.spn_threads = QSpinBox(); self.spn_threads.setRange(1, 20); self.spn_threads.setValue(1)
        self.spn_threads.setStyleSheet("background:#21262d;border:1px solid #30363d;color:#58a6ff;font-weight:bold;padding:3px;")
        tl.addWidget(self.spn_threads); tl.addStretch()
        layout.addLayout(tl)

        # أدوات
        tools = QHBoxLayout()
        self.btn_fill = QPushButton("✍️ تعبئة"); self.btn_fill.clicked.connect(lambda: self.fill_browser(False))
        self.btn_renew = QPushButton("♻️ تجديد"); self.btn_renew.setStyleSheet("background:#2ea043;color:white;"); self.btn_renew.clicked.connect(self.renew_session)
        self.btn_save = QPushButton("💾 حفظ"); self.btn_save.setStyleSheet("background:#238636;color:white;"); self.btn_save.clicked.connect(self.save_session_data)
        tools.addWidget(self.btn_fill); tools.addWidget(self.btn_renew); tools.addWidget(self.btn_save)
        layout.addLayout(tools)

        # إجراءات
        al = QHBoxLayout()
        self.ds = "background:#d29922;color:white;font-weight:bold;"
        self.as_ = "background:#9c7319;color:white;font-weight:bold;border:1px solid white;"
        self.btn_single = QPushButton("⚡ إرسال"); self.btn_single.setStyleSheet(self.ds); self.btn_single.clicked.connect(lambda: self.start_request("single"))
        self.dsnp = "background:#1f6feb;color:white;font-weight:bold;"
        self.asnp = "background:#11428f;color:white;font-weight:bold;border:1px solid white;"
        self.btn_snipe = QPushButton("🚀 قنص"); self.btn_snipe.setStyleSheet(self.dsnp); self.btn_snipe.clicked.connect(lambda: self.start_request("snipe"))
        self.btn_stop = QPushButton("🛑 إيقاف"); self.btn_stop.setStyleSheet("background:#da3633;color:white;font-weight:bold;"); self.btn_stop.clicked.connect(self.stop_request); self.btn_stop.setEnabled(False)
        al.addWidget(self.btn_single); al.addWidget(self.btn_snipe); al.addWidget(self.btn_stop)
        layout.addLayout(al)

        # نتائج
        rl = QHBoxLayout()
        self.lbl_status = QLabel("جاهز"); self.lbl_status.setStyleSheet("color:#8b949e;")
        self.inp_payment = QLineEdit(); self.inp_payment.setPlaceholderText("رمز الدفع"); self.inp_payment.setReadOnly(True)
        self.inp_payment.setStyleSheet("color:#58a6ff;font-weight:bold;font-size:14px;")
        self.btn_copy = QPushButton("📋"); self.btn_copy.clicked.connect(self.copy_payment)
        self.btn_check = QPushButton("🔍 استعلام"); self.btn_check.setStyleSheet("background:#6f42c1;color:white;font-weight:bold;"); self.btn_check.clicked.connect(self.check_payment_status)
        rl.addWidget(self.lbl_status); rl.addStretch(); rl.addWidget(QLabel("الرمز:")); rl.addWidget(self.inp_payment)
        rl.addWidget(self.btn_copy); rl.addWidget(self.btn_check)
        layout.addLayout(rl)

        self.lbl_threads = QLabel("خيوط: 0"); self.lbl_threads.setStyleSheet("color:#8b949e;font-size:11px;")
        layout.addWidget(self.lbl_threads)

        # ===== تبويبة شام كاش =====
        sc_grp = QGroupBox("🏦 شام كاش - الدفع المباشر")
        sc_grp.setStyleSheet(
            "QGroupBox{border:2px solid #10b981;border-radius:6px;margin-top:8px;padding-top:8px;}"
            " QGroupBox::title{color:#10b981;font-size:12px;font-weight:bold;}")
        sc_lay = QVBoxLayout(sc_grp)

        # صف أزرار شام كاش
        sc_btns = QHBoxLayout()
        self.btn_sc_open = QPushButton("🌐 فتح شام كاش")
        self.btn_sc_open.setStyleSheet("background:#10b981;color:white;font-weight:bold;")
        self.btn_sc_open.clicked.connect(self.shamcash_open_tab)
        self.btn_sc_extract = QPushButton("🔑 سحب توكنات شام كاش")
        self.btn_sc_extract.setStyleSheet("background:#0ea5e9;color:white;font-weight:bold;")
        self.btn_sc_extract.clicked.connect(self.shamcash_extract_tokens)
        self.btn_sc_pay = QPushButton("💳 دفع شام كاش الآن")
        self.btn_sc_pay.setStyleSheet("background:#f59e0b;color:black;font-weight:bold;")
        self.btn_sc_pay.clicked.connect(self.shamcash_pay_now)
        sc_btns.addWidget(self.btn_sc_open); sc_btns.addWidget(self.btn_sc_extract); sc_btns.addWidget(self.btn_sc_pay)
        sc_lay.addLayout(sc_btns)

        # حالة شام كاش
        self.lbl_sc_status = QLabel("🔴 غير مربوط")
        self.lbl_sc_status.setStyleSheet("color:#da3633;font-weight:bold;")
        # خيار دفع تلقائي
        self.chk_auto_pay = QCheckBox("دفع تلقائي عند الحجز")
        self.chk_auto_pay.setStyleSheet("color:#10b981;font-weight:bold;")
        sc_status_lay = QHBoxLayout()
        sc_status_lay.addWidget(self.lbl_sc_status); sc_status_lay.addStretch(); sc_status_lay.addWidget(self.chk_auto_pay)
        sc_lay.addLayout(sc_status_lay)

        layout.addWidget(sc_grp)

        # إدارة
        ml = QHBoxLayout()
        self.btn_rename = QPushButton("✏️ تسمية"); self.btn_rename.setStyleSheet("background:#3b3b3b;color:white;"); self.btn_rename.clicked.connect(self.on_rename)
        self.btn_hide = QPushButton("👁️ إخفاء"); self.btn_hide.setStyleSheet("background:#6e7681;color:white;"); self.btn_hide.clicked.connect(lambda: (self.hide(), self.log(f"[*] [{self.session_id}] أُخفيت.")))
        self.btn_del = QPushButton("🗑️ حذف"); self.btn_del.setStyleSheet("background:#8b0000;color:white;"); self.btn_del.clicked.connect(self.on_delete)
        ml.addWidget(self.btn_rename); ml.addWidget(self.btn_hide); ml.addWidget(self.btn_del)
        layout.addLayout(ml)


    # ===== شام كاش =====
    def shamcash_open_tab(self):
        """فتح تبويب شام كاش في نفس متصفح الجلسة"""
        with self.driver_lock:
            if not self.driver:
                QMessageBox.warning(self, "تنبيه", "افتح المتصفح أولاً!")
                return
            try:
                self.driver.execute_script("window.open('https://shamcash.sy/ar/application/home', '_blank');")
                self.log(f"[+] [{self.session_id}] تم فتح تبويب شام كاش - سجّل دخولك ثم اسحب التوكنات.")
            except Exception as e:
                self.log(f"[!] [{self.session_id}] خطأ فتح شام كاش: {e}")

    def shamcash_extract_tokens(self):
        """سحب توكنات شام كاش من كوكيز المتصفح وحفظها"""
        with self.driver_lock:
            if not self.driver:
                QMessageBox.warning(self, "خطأ", "افتح المتصفح أولاً!")
                return
            try:
                # الانتقال لتبويب شام كاش إن وُجد
                handles = self.driver.window_handles
                shamcash_handle = None
                for h in handles:
                    self.driver.switch_to.window(h)
                    if "shamcash" in self.driver.current_url:
                        shamcash_handle = h
                        break

                if not shamcash_handle:
                    self.log(f"[-] [{self.session_id}] لم يُعثر على تبويب شام كاش مفتوح.")
                    # العودة لأول تبويب
                    self.driver.switch_to.window(handles[0])
                    return

                # سحب الكوكيز
                cookies = self.driver.get_cookies()
                auth_token = ""
                access_token = ""
                forge_cookie = ""

                for c in cookies:
                    if c['name'] == 'authToken':
                        auth_token = c['value']
                    elif c['name'] == 'accessToken':
                        access_token = c['value']
                    elif c['name'] == 'forge':
                        forge_cookie = c['value']

                # العودة لتبويب دقيق
                self.driver.switch_to.window(handles[0])

                if auth_token and access_token and forge_cookie:
                    self.shamcash_auth_token = auth_token
                    self.shamcash_access_token = access_token
                    self.shamcash_forge_cookie = forge_cookie
                    self.lbl_sc_status.setText("🟢 مربوط وجاهز للدفع")
                    self.lbl_sc_status.setStyleSheet("color:#10b981;font-weight:bold;")
                    self._save_data_internal(False)
                    self.log(f"[+] [{self.session_id}] ✅ تم سحب توكنات شام كاش بنجاح وحفظها!")
                else:
                    missing = []
                    if not auth_token: missing.append("authToken")
                    if not access_token: missing.append("accessToken")
                    if not forge_cookie: missing.append("forge")
                    self.log(f"[-] [{self.session_id}] شام كاش: ناقص: {', '.join(missing)}. هل سجلت الدخول؟")
            except Exception as e:
                self.log(f"[!] [{self.session_id}] خطأ سحب شام كاش: {e}")
                # محاولة العودة لأول تبويب
                try:
                    self.driver.switch_to.window(self.driver.window_handles[0])
                except:
                    pass

    def shamcash_pay_now(self):
        """دفع يدوي عبر شام كاش لرمز الدفع الحالي"""
        code = self.inp_payment.text().strip()
        if not code:
            QMessageBox.warning(self, "تنبيه", "لا يوجد رمز دفع! احجز أولاً.")
            return
        self._do_shamcash_pay(code)

    def _do_shamcash_pay(self, payment_code):
        """تنفيذ الدفع - بدون بروكسي"""
        if not self.shamcash_auth_token or not self.shamcash_access_token or not self.shamcash_forge_cookie:
            self.log(f"[-] [{self.session_id}] شام كاش غير مربوط! اسحب التوكنات أولاً.")
            QMessageBox.warning(self, "شام كاش", "يجب سحب توكنات شام كاش أولاً!")
            return

        self.btn_sc_pay.setEnabled(False)
        self.btn_sc_pay.setText("⏳ جاري الدفع...")

        tokens = {
            'auth_token': self.shamcash_auth_token,
            'access_token': self.shamcash_access_token,
            'forge_cookie': self.shamcash_forge_cookie
        }
        self._sc_worker = ShamcashPayWorker(self.session_id, payment_code, tokens)
        self._sc_worker.log_signal.connect(self.log)
        self._sc_worker.pay_result_signal.connect(self._on_sc_pay_result)
        self._sc_worker.finished.connect(self._on_sc_pay_done)
        self._sc_worker.start()

    def _on_sc_pay_result(self, success, msg):
        if success:
            self.lbl_sc_status.setText(f"🟢 تم الدفع! {msg}")
            self.lbl_sc_status.setStyleSheet("color:#10b981;font-weight:bold;")
            # تلجرام
            all_data = load_all_data()
            tg = all_data.get("TELEGRAM_CONFIG", {})
            if tg.get("token") and tg.get("chat_id"):
                threading.Thread(target=send_telegram_message,
                    args=(tg["token"], tg["chat_id"],
                          f"💰 <b>تم الدفع عبر شام كاش!</b>\n🚗 {self.session_id}\n{msg}"),
                    daemon=True).start()
        else:
            self.lbl_sc_status.setText(f"🔴 فشل: {msg[:40]}")
            self.lbl_sc_status.setStyleSheet("color:#da3633;font-weight:bold;")

    def _on_sc_pay_done(self):
        self.btn_sc_pay.setEnabled(True)
        self.btn_sc_pay.setText("💳 دفع شام كاش الآن")


    # ===== المنطق الأساسي =====
    def get_proxy_url(self):
        if not self.chk_proxy.isChecked(): return None
        p = self.inp_proxy.text().strip()
        if not p: return None
        return parse_proxy_string(p, "socks5" if self.radio_socks.isChecked() else "http")

    def load_session_data(self):
        all_data = load_all_data()
        if self.session_id in all_data:
            d = all_data[self.session_id]
            self.inp_name.setText(d.get("name",""))
            self.inp_plate.setText(d.get("plate",""))
            self.inp_date.setText(d.get("date",""))
            tid = d.get("transaction_id","")
            if tid:
                idx = self.cmb_transaction.findData(tid)
                if idx >= 0: self.cmb_transaction.setCurrentIndex(idx)
            self.xsrf_token = d.get("xsrf_token","")
            self.accurate_session = d.get("accurate_session","")
            self.remember_token_name = d.get("remember_token_name","")
            self.remember_token_value = d.get("remember_token_value","")
            self.user_agent = d.get("user_agent","")
            self.last_appointment_id = d.get("last_appointment_id","")
            self.inp_proxy.setText(d.get("proxy",""))
            self.chk_proxy.setChecked(d.get("proxy_enabled", False))
            if d.get("proxy_type","http") == "socks5": self.radio_socks.setChecked(True)
            else: self.radio_http.setChecked(True)
            self.spn_threads.setValue(d.get("thread_count", 1))
            # شام كاش
            self.shamcash_auth_token = d.get("shamcash_auth_token","")
            self.shamcash_access_token = d.get("shamcash_access_token","")
            self.shamcash_forge_cookie = d.get("shamcash_forge_cookie","")
            self.chk_auto_pay.setChecked(d.get("shamcash_auto_pay", False))
            if self.shamcash_auth_token and self.shamcash_forge_cookie:
                self.lbl_sc_status.setText("🟢 مربوط (محفوظ)")
                self.lbl_sc_status.setStyleSheet("color:#10b981;font-weight:bold;")
            if self.xsrf_token and self.accurate_session:
                self.update_status("مستعد ✔️", "#238636")

    def save_session_data(self):
        self._save_data_internal(True)

    def _save_data_internal(self, show_msg=True):
        all_data = load_all_data()
        all_data[self.session_id] = {
            "name": self.inp_name.text(), "plate": self.inp_plate.text(),
            "date": self.inp_date.text(), "transaction_id": self.cmb_transaction.currentData(),
            "xsrf_token": self.xsrf_token, "accurate_session": self.accurate_session,
            "remember_token_name": self.remember_token_name,
            "remember_token_value": self.remember_token_value,
            "user_agent": self.user_agent, "last_appointment_id": self.last_appointment_id,
            "proxy": self.inp_proxy.text().strip(),
            "proxy_enabled": self.chk_proxy.isChecked(),
            "proxy_type": "socks5" if self.radio_socks.isChecked() else "http",
            "thread_count": self.spn_threads.value(),
            "shamcash_auth_token": self.shamcash_auth_token,
            "shamcash_access_token": self.shamcash_access_token,
            "shamcash_forge_cookie": self.shamcash_forge_cookie,
            "shamcash_auto_pay": self.chk_auto_pay.isChecked()
        }
        save_all_data(all_data)
        if show_msg: QMessageBox.information(self, "✅", "تم الحفظ.")

    def log(self, msg): self._log_signal.emit(msg)
    def _upd_br_btn(self, t, e): self.btn_browser.setText(t); self.btn_browser.setEnabled(e)
    def _upd_ren_btn(self, e): self.btn_renew.setEnabled(e); self.btn_renew.setText("♻️ تجديد" if e else "⏳...")
    def _upd_status_ui(self, t, c): self.lbl_status.setText(t); self.lbl_status.setStyleSheet(f"color:{c};"); self.status_changed.emit(t,c)
    def update_status(self, t, c="#8b949e"): self._ui_status_signal.emit(t,c)

    def launch_browser(self):
        self.btn_browser.setEnabled(False); self.btn_browser.setText("⏳...")
        threading.Thread(target=self._browser_thread, daemon=True).start()

    def _browser_thread(self):
        try:
            pdir = os.path.join(os.getcwd(), "Profiles", f"Profile_{self.session_id}")
            os.makedirs(pdir, exist_ok=True)
            with GLOBAL_BROWSER_LOCK:
                for att in range(3):
                    try:
                        if sys.platform == 'win32':
                            try: subprocess.run(f'wmic process where "name=\'chrome.exe\' and commandline like \'%Profile_{self.session_id.replace(chr(39),"")}%\'" call terminate', shell=True, capture_output=True); time.sleep(0.5)
                            except: pass
                        for lk in ["SingletonLock","SingletonCookie","SingletonSocket"]:
                            p = os.path.join(pdir, lk)
                            if os.path.exists(p):
                                try: os.remove(p)
                                except: pass
                        opts = uc.ChromeOptions()
                        opts.add_argument('--no-sandbox'); opts.add_argument('--disable-dev-shm-usage'); opts.add_argument('--disable-gpu')
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.bind(('127.0.0.1',0)); fp = s.getsockname()[1]
                        self.driver = uc.Chrome(user_data_dir=pdir, options=opts, use_subprocess=True, port=fp, version_main=get_chrome_main_version())
                        break
                    except Exception as e:
                        if att < 2: time.sleep(2)
                        else: raise e
            time.sleep(1.5)
            js = r"""window.sarmadaSelectedDate='';const o=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){if(typeof u==='string'&&u.includes('date=')){let x=u.match(/date=(20\d{2}-\d{2}-\d{2})/);if(x)window.sarmadaSelectedDate=x[1];}return o.apply(this,arguments);};const f=window.fetch;window.fetch=async function(){let u=arguments[0] instanceof Request?arguments[0].url:arguments[0];if(typeof u==='string'&&u.includes('date=')){let x=u.match(/date=(20\d{2}-\d{2}-\d{2})/);if(x)window.sarmadaSelectedDate=x[1];}return f.apply(this,arguments);};"""
            with self.driver_lock:
                if self.driver:
                    self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':js})
                    self.driver.set_page_load_timeout(45)
                    self.driver.get("https://accurate.mot.gov.sy/reviewer/availability")
            self.log(f"[+] [{self.session_id}] تم فتح المتصفح.")
            self._ui_browser_btn_signal.emit("🌐 مفتوح", False)
            self.update_status("المتصفح يعمل", "#e3b341")
        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ: {e}")
            self._ui_browser_btn_signal.emit("🌐 فتح", True)

    def extract_tokens(self):
        with self.driver_lock:
            if not self.driver: QMessageBox.warning(self,"خطأ","افتح المتصفح!"); return
            try:
                self.user_agent = self.driver.execute_script("return navigator.userAgent;")
                pd = self.driver.execute_script("if(window.sarmadaSelectedDate)return window.sarmadaSelectedDate;let m=document.body.innerText.match(/20\\d{2}-\\d{2}-\\d{2}/);return m?m[0]:'';")
                if pd: self.inp_date.setText(pd)
                for c in self.driver.get_cookies():
                    if c['name']=='XSRF-TOKEN': self.xsrf_token=urllib.parse.unquote(c['value'])
                    elif c['name']=='accurate_session': self.accurate_session=c['value']
                    elif c['name'].startswith('remember_web_'): self.remember_token_name=c['name']; self.remember_token_value=c['value']
                if self.xsrf_token and self.accurate_session:
                    self.log(f"[+] [{self.session_id}] تم سحب التوكن ✔️"); self.update_status("مستعد ✔️","#238636"); self._save_data_internal(False)
                else: self.log(f"[-] [{self.session_id}] لم يُعثر على التوكن.")
            except Exception as e: self.log(f"[!] [{self.session_id}] {e}")

    def close_browser(self):
        with self.driver_lock:
            if self.driver:
                try: self.driver.quit()
                except: pass
                finally: self.driver=None; self._ui_browser_btn_signal.emit("🌐 فتح",True); self.update_status("مغلق","#8b949e")

    def fill_browser(self, auto_submit=False):
        with self.driver_lock:
            if not self.driver: return
        threading.Thread(target=self._fill, args=(auto_submit,), daemon=True).start()

    def _fill(self, auto):
        try:
            n, p = self.inp_name.text(), self.inp_plate.text()
            with self.driver_lock:
                if not self.driver: return
                inps = self.driver.find_elements(By.TAG_NAME,'input')
            vis = [i for i in inps if i.is_displayed() and i.is_enabled() and i.get_attribute('type') in ['text','number','tel','']]
            if len(vis)>=2:
                with self.driver_lock:
                    for i,v in enumerate([n,p]):
                        vis[i].send_keys(Keys.CONTROL+"a"); vis[i].send_keys(Keys.DELETE); time.sleep(0.1); vis[i].send_keys(v); time.sleep(0.1)
                if auto:
                    time.sleep(0.5)
                    with self.driver_lock:
                        if not self.driver: return
                        for b in self.driver.find_elements(By.TAG_NAME,'button'):
                            if b.is_displayed() and ("حجز" in b.text or "تأكيد" in b.text): b.click(); break
        except Exception as e: self.log(f"[!] {e}")

    def renew_session(self):
        if not self.xsrf_token: return
        self.btn_renew.setEnabled(False); self.btn_renew.setText("⏳...")
        threading.Thread(target=self._renew, daemon=True).start()

    def _renew(self):
        try:
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            ok = loop.run_until_complete(self._arenew()); loop.close()
            if ok: self.update_status("مستعد (تجديد) ✔️","#2ea043")
        except: pass
        finally: self._ui_renew_btn_signal.emit(True)

    async def _arenew(self):
        ck = {"XSRF-TOKEN":self.xsrf_token,"accurate_session":self.accurate_session}
        if self.remember_token_name: ck[self.remember_token_name]=self.remember_token_value
        h = {"User-Agent":self.user_agent or "Mozilla/5.0","Accept":"text/html,*/*;q=0.8"}
        async with AsyncSession(verify=False, proxy=self.get_proxy_url()) as s:
            r = await s.get("https://accurate.mot.gov.sy/",cookies=ck,headers=h,impersonate="chrome110",timeout=20)
            if r.status_code==200:
                nx=s.cookies.get("XSRF-TOKEN"); ns=s.cookies.get("accurate_session")
                if nx: self.xsrf_token=urllib.parse.unquote(nx)
                if ns: self.accurate_session=ns
                self._save_data_internal(False); return True
            return False


    def start_request(self, mode):
        if not self.xsrf_token: return
        dv = self.inp_date.text().strip()
        if not dv: return
        payload = {"province_id":"804e7642-6798-4353-a556-f11d9aad2637","name":self.inp_name.text().strip(),"plate_number":self.inp_plate.text().strip(),"date":dv,"transaction_type_ids":[self.cmb_transaction.currentData()]}
        headers = {"Host":"api.mot.gov.sy","Accept":"application/json, text/plain, */*","Content-Type":"application/json","X-Requested-With":"XMLHttpRequest","Origin":"https://accurate.mot.gov.sy","Referer":"https://accurate.mot.gov.sy/","X-Xsrf-Token":self.xsrf_token,"User-Agent":self.user_agent or "Mozilla/5.0 Chrome/147.0.0.0"}
        cookies = {"XSRF-TOKEN":self.xsrf_token,"accurate_session":self.accurate_session}
        pu = self.get_proxy_url(); tc = self.spn_threads.value()
        self.btn_stop.setEnabled(True); self.inp_payment.clear()
        if mode=="single": self.btn_single.setStyleSheet(self.as_); self.update_status(f"إرسال ({tc})...","#e3b341")
        else: self.btn_snipe.setStyleSheet(self.asnp); self.update_status(f"قنص ({tc})...","#e3b341")
        bid = len(self.workers)
        for i in range(tc):
            w = RequestWorker(self.session_id, payload, headers, cookies, mode, bid+i, pu)
            w.log_signal.connect(self.log); w.success_signal.connect(self.on_success)
            w.error_signal.connect(self.on_error); w.finished_signal.connect(self.on_tfin)
            w.response_signal.connect(self.on_resp)
            self.workers.append(w); w.start()
        self._upd_thr()

    def _upd_thr(self):
        a = sum(1 for w in self.workers if w.isRunning())
        self.lbl_threads.setText(f"خيوط: {a}/{len(self.workers)}")

    def on_resp(self, tid, code, body):
        c = "🟢" if code in [200,201] else "🟡" if code==422 else "🔴"
        self.log(f"{c} [{self.session_id}][T{tid}] {code} | {body[:60]}")

    def on_tfin(self, tid):
        self._upd_thr()
        if not any(w.isRunning() for w in self.workers): self._all_done()

    def _all_done(self):
        self.workers.clear()
        self.btn_single.setEnabled(True); self.btn_snipe.setEnabled(True); self.btn_stop.setEnabled(False)
        self.btn_single.setText("⚡ إرسال"); self.btn_single.setStyleSheet(self.ds)
        self.btn_snipe.setText("🚀 قنص"); self.btn_snipe.setStyleSheet(self.dsnp)
        self._upd_thr()
        if "تم" not in self.lbl_status.text() and "توقف" not in self.lbl_status.text():
            self.update_status("مستعد","#8b949e")

    def stop_request(self):
        for w in self.workers: w.stop()
        self.update_status("تم الإيقاف","#da3633")

    def on_success(self, code, fee, appt_id, tid):
        self.inp_payment.setText(code)
        self.last_appointment_id = appt_id
        self.update_status(f"✅ تم الحجز ({fee})","#238636")
        self.payment_received.emit(code)
        self.log(f"[$$$] [{self.session_id}][T{tid}] الرمز: {code} | {fee} | {appt_id}")
        for w in self.workers: w.stop()
        self._save_data_internal(False)
        # تلجرام
        all_data = load_all_data(); tg = all_data.get("TELEGRAM_CONFIG",{})
        if tg.get("token") and tg.get("chat_id"):
            threading.Thread(target=send_telegram_message, args=(tg["token"],tg["chat_id"],
                f"✅ <b>حجز!</b> {self.session_id}\n💳 <code>{code}</code>\n💰 {fee}"), daemon=True).start()
        # === دفع تلقائي شام كاش ===
        if self.chk_auto_pay.isChecked() and code:
            self.log(f"🏦 [{self.session_id}] بدء الدفع التلقائي عبر شام كاش...")
            self._do_shamcash_pay(code)

    def on_error(self, err): self.update_status("توقف","#da3633")

    def check_payment_status(self):
        if not self.xsrf_token or not self.last_appointment_id: return
        h = {"Host":"api.mot.gov.sy","Accept":"application/json, text/plain, */*","X-Requested-With":"XMLHttpRequest","Origin":"https://accurate.mot.gov.sy","Referer":"https://accurate.mot.gov.sy/","X-Xsrf-Token":self.xsrf_token,"Accept-Language":"ar","User-Agent":self.user_agent or "Mozilla/5.0"}
        ck = {"XSRF-TOKEN":self.xsrf_token,"accurate_session":self.accurate_session}
        if self.remember_token_name: ck[self.remember_token_name]=self.remember_token_value
        self.btn_check.setEnabled(False)
        self._pw = PaymentStatusWorker(self.session_id, self.last_appointment_id, h, ck, self.get_proxy_url())
        self._pw.log_signal.connect(self.log); self._pw.result_signal.connect(self._pmt_res); self._pw.finished.connect(lambda: self.btn_check.setEnabled(True))
        self._pw.start()

    def _pmt_res(self, data):
        if not data: return
        pd = data.get("data",{})
        st = {"pending":"قيد الانتظار ⏳","paid":"مدفوع ✅","expired":"منتهي ❌"}.get(pd.get("payment_status",""), pd.get("payment_status",""))
        QMessageBox.information(self,"دفع", f"الحالة: {st}\nالرمز: {pd.get('payment_code','')}\nالمبلغ: {pd.get('fee_amount','')} ل.س\nمتبقي: {int(pd.get('payment_remaining_seconds',0))}ث")

    def copy_payment(self):
        c = self.inp_payment.text()
        if c: QApplication.clipboard().setText(c)

    def on_rename(self):
        with self.driver_lock:
            if self.driver: QMessageBox.warning(self,"!","أغلق المتصفح."); return
        n, ok = QInputDialog.getText(self,"تسمية","الاسم:",text=self.session_id)
        if ok and n and n != self.session_id: self.rename_callback(self, self.session_id, n.strip())

    def on_delete(self):
        if QMessageBox.question(self,'حذف',f"حذف '{self.session_id}'؟",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.delete_callback(self)



class SarmadaPro(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alghanem - Sarmada V18 (Threads + Proxy + ShamCash)")
        self.resize(1100, 900)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet("""QMainWindow{background:#0d1117;color:#c9d1d9;} QWidget{font-family:'Segoe UI',Tahoma;} QLabel{color:#c9d1d9;} QLineEdit{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:5px;border-radius:4px;} QPushButton{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px;border-radius:4px;} QPushButton:hover{background:#30363d;} QPushButton:disabled{background:#161b22;color:#484f58;}""")
        self.log_window = LogWindow(self)
        self.sessions = []
        self.log_signal.connect(self._slog)
        self.session_counter = 0
        self._build(load_all_data())

    def _build(self, sd):
        cw = QWidget(); self.setCentralWidget(cw); ml = QVBoxLayout(cw)
        # تلجرام
        tg = QGroupBox("إعدادات التلجرام"); tl = QHBoxLayout()
        self.inp_tt = QLineEdit(); self.inp_tt.setPlaceholderText("Bot Token"); self.inp_tt.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.inp_tc = QLineEdit(); self.inp_tc.setPlaceholderText("Chat ID")
        tc = sd.get("TELEGRAM_CONFIG",{}); self.inp_tt.setText(tc.get("token","")); self.inp_tc.setText(tc.get("chat_id",""))
        bt = QPushButton("💾 حفظ"); bt.setStyleSheet("background:#1f6feb;color:white;"); bt.clicked.connect(self._save_tg)
        tl.addWidget(QLabel("توكن:")); tl.addWidget(self.inp_tt); tl.addWidget(QLabel("ID:")); tl.addWidget(self.inp_tc); tl.addWidget(bt)
        tg.setLayout(tl); ml.addWidget(tg)
        # شريط
        top = QHBoxLayout()
        for txt, sty, fn in [("➕ جلسة","background:#238636;color:white;font-weight:bold;",self.add_session),
            ("👥 مجموعات","background:#d29922;color:white;font-weight:bold;",self.open_groups),
            ("♻️ تجديد الكل","background:#2ea043;color:white;font-weight:bold;",self.renew_all),
            ("✨ تعبئة للكل","background:#8e44ad;color:white;font-weight:bold;",self.fill_all),
            ("⚡ إرسال","",lambda: self.trigger_all("single")),
            ("🚀 قنص","border-color:#1f6feb;",lambda: self.trigger_all("snipe")),
            ("🛑 إيقاف","border-color:#da3633;",self.stop_all),
            ("👁️ مطفأة","background:#6e7681;color:white;",self.show_hidden),
            ("📋 سجلات","",self.log_window.show)]:
            b = QPushButton(txt)
            if sty: b.setStyleSheet(sty)
            b.clicked.connect(fn); top.addWidget(b)
        ml.addLayout(top)
        # جلسات
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.sc = QWidget(); self.sl = QVBoxLayout(self.sc); self.sl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.sc); ml.addWidget(self.scroll)
        # تحميل
        pd = os.path.join(os.getcwd(),"Profiles"); ex=[]; mx=0
        if os.path.exists(pd):
            for f in os.listdir(pd):
                if f.startswith("Profile_"):
                    sid=f[8:]; ex.append(sid)
                    if sid.startswith("رقم_"):
                        try: n=int(sid[4:]);
                        except: n=0
                        if n>mx: mx=n
        self.session_counter=mx
        if ex:
            for sid in ex: self._mk(sid)
        else: self.add_session()

    def _save_tg(self):
        t,c = self.inp_tt.text().strip(), self.inp_tc.text().strip()
        d=load_all_data(); d["TELEGRAM_CONFIG"]={"token":t,"chat_id":c}; save_all_data(d)
        if t and c: threading.Thread(target=send_telegram_message, args=(t,c,"🤖 اختبار V18!"), daemon=True).start()

    def print_log(self, m): self.log_signal.emit(m)
    def _slog(self, m): self.log_window.append_log(m); print(m)
    def _mk(self, sid):
        card = SessionCard(sid, self.print_log, self._ren, self._del)
        self.sessions.append(card); self.sl.addWidget(card)
    def add_session(self): self.session_counter+=1; self._mk(f"رقم_{self.session_counter}")
    def open_groups(self): GroupActionDialog(self, self).exec()
    def fill_all(self):
        for c in self.sessions:
            if not c.isHidden() and c.driver: c.fill_browser(True)
    def renew_all(self):
        for c in self.sessions:
            if not c.isHidden() and c.xsrf_token: c.renew_session()
    def trigger_all(self, m):
        for c in self.sessions:
            if not c.isHidden() and c.xsrf_token: c.start_request(m)
    def stop_all(self):
        for c in self.sessions: c.stop_request()
    def show_hidden(self): HiddenSessionsDialog(self, self).exec()
    def _ren(self, card, old, new):
        if any(c.session_id==new for c in self.sessions): return
        pd=os.path.join(os.getcwd(),"Profiles")
        try:
            od=os.path.join(pd,f"Profile_{old}"); nd=os.path.join(pd,f"Profile_{new}")
            if os.path.exists(od): os.rename(od,nd)
        except: return
        d=load_all_data()
        if old in d: d[new]=d.pop(old); save_all_data(d)
        card.session_id=new; card.setTitle(f"جلسة: {new}")
    def _del(self, card):
        card.stop_request(); card.close_browser(); sid=card.session_id
        d=load_all_data()
        if sid in d: del d[sid]; save_all_data(d)
        p=os.path.join(os.getcwd(),"Profiles",f"Profile_{sid}")
        if os.path.exists(p): shutil.rmtree(p, ignore_errors=True)
        self.sessions.remove(card); card.setParent(None); card.deleteLater()
    def closeEvent(self, ev):
        self.stop_all()
        for c in self.sessions:
            if c.driver: c.close_browser()
        ev.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SarmadaPro()
    window.show()
    sys.exit(app.exec())
