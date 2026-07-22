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
                             QButtonGroup, QTabWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from curl_cffi.requests import AsyncSession

try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    try:
        from Cryptodome.Cipher import AES
        HAS_CRYPTO = True
    except ImportError:
        HAS_CRYPTO = False

# =============================================
# ثوابت شام كاش
# =============================================
SHAMCASH_MASTER_KEY = b"g0Zrgp8XRK/BN2ZAtUfJDQ=="  # مفتاح فك forge
SHAMCASH_PAYMENT_URL = "https://payment.shamcash.sy/v4/api/Billing"

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

GLOBAL_BROWSER_LOCK = threading.Lock()
GLOBAL_SOUND_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
DATA_FILE = "sarmada_data.json"


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
            print(f"[!] خطأ أثناء حفظ البيانات في الملف: {e}")


def get_chrome_main_version():
    try:
        if sys.platform == 'win32':
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Google\Chrome\BLBeacon')
                version, _ = winreg.QueryValueEx(key, 'version')
                return int(version.split('.')[0])
            except Exception:
                pass
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                     r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome')
                version, _ = winreg.QueryValueEx(key, 'version')
                return int(version.split('.')[0])
            except Exception:
                pass
    except Exception:
        pass
    return None


def parse_proxy_string(proxy_str, proxy_type="http"):
    """تحليل سلسلة البروكسي - خانة واحدة تدعم كل الأنواع"""
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None
    # إذا يحتوي على بروتوكول مسبقاً
    if proxy_str.startswith("http://") or proxy_str.startswith("https://"):
        return proxy_str
    elif proxy_str.startswith("socks5://") or proxy_str.startswith("socks4://"):
        return proxy_str
    else:
        # صيغة user:pass@host:port أو host:port
        if proxy_type == "socks5":
            return f"socks5://{proxy_str}"
        else:
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
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    print(f"[+] تم إرسال رسالة التلجرام بنجاح.")
                    return
        except Exception as e:
            print(f"[!] خطأ في إرسال رسالة تلجرام (المحاولة {attempt + 1}/{retries}): {e}")
            time.sleep(3)
    print("[!] فشل إرسال رسالة التلجرام نهائياً.")



# =============================================
# دوال شام كاش - فك التشفير والدفع المباشر
# =============================================

def shamcash_get_session_key(forge_cookie, master_key=SHAMCASH_MASTER_KEY):
    """فك تشفير forge cookie لاستخراج مفتاح الجلسة"""
    if not HAS_CRYPTO:
        raise ImportError("مكتبة pycryptodome غير مثبتة!")
    parts = forge_cookie.split('.')
    encrypted_data = base64.b64decode(parts[0])
    iv = base64.b64decode(parts[1])
    tag = encrypted_data[-16:]
    ciphertext = encrypted_data[:-16]
    cipher = AES.new(master_key, AES.MODE_GCM, nonce=iv)
    cipher.update(b"")
    return cipher.decrypt_and_verify(ciphertext, tag)


def shamcash_encrypt_payload(payload_dict, session_key, access_token, auth_token):
    """تشفير payload للإرسال لشام كاش"""
    if not HAS_CRYPTO:
        raise ImportError("مكتبة pycryptodome غير مثبتة!")
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


def shamcash_check_bill(process_number, auth_token, access_token, forge_cookie, service_id=37):
    """استعلام فاتورة - بدون بروكسي"""
    import requests as req_lib
    session_key = shamcash_get_session_key(forge_cookie)
    payload = {"values": [{"key": "process_number", "value": str(process_number)}]}
    enc_data = shamcash_encrypt_payload(payload, session_key, access_token, auth_token)
    url = f"{SHAMCASH_PAYMENT_URL}/presentment?serviceId={service_id}"
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
    response = req_lib.post(url, json={"encData": enc_data}, headers=headers, timeout=30)
    return response.json()


def shamcash_pay_bill(process_no, due_amount, auth_token, access_token, forge_cookie, service_id=37):
    """دفع فاتورة - بدون بروكسي (مستقل تماماً)"""
    import requests as req_lib
    session_key = shamcash_get_session_key(forge_cookie)
    payload = {
        "values": [
            {"key": "process_no", "value": str(process_no)},
            {"key": "due_amount", "value": str(due_amount)}
        ]
    }
    enc_data = shamcash_encrypt_payload(payload, session_key, access_token, auth_token)
    url = f"{SHAMCASH_PAYMENT_URL}/pay?serviceId={service_id}"
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
    response = req_lib.post(url, json={"encData": enc_data}, headers=headers, timeout=30)
    return response.json()


class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("سجلات النظام المركزية")
        self.resize(800, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
            "background-color: #0d1117; color: #58a6ff; font-family: Consolas; font-size: 13px;")
        layout.addWidget(self.log_area)
        clear_btn = QPushButton("🧹 مسح السجلات")
        clear_btn.setStyleSheet("background-color: #21262d; color: white; padding: 5px;")
        clear_btn.clicked.connect(self.log_area.clear)
        layout.addWidget(clear_btn)

    def append_log(self, text):
        self.log_area.append(text)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())


class HiddenSessionsDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("تبويبة الجلسات المطفأة")
        self.resize(400, 300)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; color: #c9d1d9; }
            QLabel { font-weight: bold; font-size: 14px; }
            QPushButton { background-color: #238636; color: white; border-radius: 4px; padding: 5px; }
            QPushButton:hover { background-color: #2ea043; }
        """)
        self.layout = QVBoxLayout(self)
        self.populate()

    def populate(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear(item.layout())
        hidden = [c for c in self.main_window.sessions if c.isHidden()]
        if not hidden:
            lbl = QLabel("✅ لا توجد جلسات مطفأة حالياً.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(lbl)
            return
        for card in hidden:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"جلسة: {card.session_id}"))
            row.addStretch()
            btn = QPushButton("🔄 إعادة للواجهة")
            btn.clicked.connect(lambda ch, c=card: self._restore(c))
            row.addWidget(btn)
            self.layout.addLayout(row)
        self.layout.addStretch()

    def _clear(self, layout):
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
                elif item.layout():
                    self._clear(item.layout())

    def _restore(self, card):
        card.show()
        self.main_window.print_log(f"[*] تم استعادة الجلسة {card.session_id}.")
        self.populate()



class GroupActionDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("إدارة المجموعات (تحديد وإرسال)")
        self.resize(850, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; color: #c9d1d9; }
            QLabel { font-weight: bold; font-size: 13px; }
            QCheckBox { spacing: 8px; color: #58a6ff; font-weight: bold; font-size: 14px;}
            QCheckBox::indicator { width: 18px; height: 18px; }
            QLineEdit { background-color: #21262d; border: 1px solid #30363d; color: #58a6ff; font-weight: bold; border-radius: 4px; padding: 4px;}
            QPushButton { border-radius: 4px; padding: 6px; font-weight: bold; }
        """)
        self.rows_data = []
        self.signal_connections = []
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        top_bar = QHBoxLayout()
        btn_sel = QPushButton("☑️ تحديد الكل")
        btn_sel.setStyleSheet("background-color: #3b3b3b; color: white;")
        btn_sel.clicked.connect(lambda: self._set_all(True))
        btn_desel = QPushButton("☐ إلغاء التحديد")
        btn_desel.setStyleSheet("background-color: #3b3b3b; color: white;")
        btn_desel.clicked.connect(lambda: self._set_all(False))
        top_bar.addWidget(btn_sel)
        top_bar.addWidget(btn_desel)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #30363d; background-color: transparent; }")
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QHBoxLayout()
        header.addWidget(QLabel("تحديد/الجلسة"), 2)
        header.addWidget(QLabel("اللوحة"), 1)
        header.addWidget(QLabel("التاريخ"), 1)
        header.addWidget(QLabel("حالة"), 2)
        header.addWidget(QLabel("رمز الدفع"), 2)
        header.addWidget(QLabel(""), 1)
        self.list_layout.addLayout(header)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #30363d;")
        self.list_layout.addWidget(line)

        for card in [c for c in self.main_window.sessions if not c.isHidden()]:
            row = QHBoxLayout()
            chk = QCheckBox(f"{card.session_id}")
            row.addWidget(chk, 2)
            row.addWidget(QLabel(card.inp_plate.text()), 1)
            row.addWidget(QLabel(card.inp_date.text()), 1)
            lbl_st = QLabel(card.lbl_status.text())
            lbl_st.setStyleSheet(card.lbl_status.styleSheet())
            row.addWidget(lbl_st, 2)
            c1 = card.status_changed.connect(lambda t, co, l=lbl_st: self._upd_st(l, t, co))
            self.signal_connections.append((card.status_changed, c1))
            inp = QLineEdit(card.inp_payment.text())
            inp.setReadOnly(True)
            inp.setPlaceholderText("بانتظار...")
            row.addWidget(inp, 2)
            c2 = card.payment_received.connect(lambda code, i=inp: i.setText(code))
            self.signal_connections.append((card.payment_received, c2))
            btn_cp = QPushButton("📋")
            btn_cp.setStyleSheet("background-color: #21262d; color: white;")
            btn_cp.clicked.connect(lambda ch, c=card, i=inp: self._copy(c, i.text()))
            row.addWidget(btn_cp, 1)
            self.list_layout.addLayout(row)
            self.rows_data.append({'card': card, 'checkbox': chk})

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        acts = QHBoxLayout()
        b1 = QPushButton("⚡ إرسال فردي (للمحدد)")
        b1.setStyleSheet("background-color: #d29922; color: white;")
        b1.clicked.connect(lambda: self._exec("single"))
        b2 = QPushButton("🚀 قنص مستمر (للمحدد)")
        b2.setStyleSheet("background-color: #1f6feb; color: white;")
        b2.clicked.connect(lambda: self._exec("snipe"))
        b3 = QPushButton("🛑 إيقاف (للمحدد)")
        b3.setStyleSheet("background-color: #da3633; color: white;")
        b3.clicked.connect(self._stop)
        acts.addWidget(b1)
        acts.addWidget(b2)
        acts.addWidget(b3)
        main_layout.addLayout(acts)

    def _set_all(self, state):
        for r in self.rows_data:
            r['checkbox'].setChecked(state)

    def _upd_st(self, label, text, color):
        try:
            label.setText(text)
            label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except RuntimeError:
            pass

    def _copy(self, card, code):
        if code:
            QApplication.clipboard().setText(code)
            self.main_window.print_log(f"[+] [{card.session_id}] تم نسخ الكود: {code}")

    def _exec(self, mode):
        cnt = 0
        for r in self.rows_data:
            if r['checkbox'].isChecked():
                if r['card'].xsrf_token:
                    r['card'].start_request(mode)
                    cnt += 1
        if cnt:
            self.main_window.print_log(f"[*] تم إطلاق ({mode}) لـ {cnt} جلسة.")
        else:
            QMessageBox.warning(self, "تنبيه", "لم يتم تحديد جلسة صالحة.")

    def _stop(self):
        for r in self.rows_data:
            if r['checkbox'].isChecked():
                r['card'].stop_request()

    def closeEvent(self, event):
        for sig, conn in self.signal_connections:
            try:
                sig.disconnect(conn)
            except:
                pass
        super().closeEvent(event)



class ShamCashWorker(QThread):
    """خيط لعمليات شام كاش (استعلام/دفع) - بدون بروكسي"""
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(dict, str)  # data, operation_type

    def __init__(self, operation, session_id, auth_token, access_token, forge_cookie,
                 process_number="", process_no="", due_amount="", service_id=37):
        super().__init__()
        self.operation = operation  # "check" or "pay"
        self.session_id = session_id
        self.auth_token = auth_token
        self.access_token = access_token
        self.forge_cookie = forge_cookie
        self.process_number = process_number
        self.process_no = process_no
        self.due_amount = due_amount
        self.service_id = service_id

    def run(self):
        try:
            if self.operation == "check":
                self.log_signal.emit(f"🔍 [{self.session_id}] جاري الاستعلام عن: {self.process_number}")
                result = shamcash_check_bill(
                    self.process_number, self.auth_token,
                    self.access_token, self.forge_cookie, self.service_id)
                self.result_signal.emit(result, "check")
            elif self.operation == "pay":
                self.log_signal.emit(f"💳 [{self.session_id}] جاري الدفع: {self.process_no} - {self.due_amount}")
                result = shamcash_pay_bill(
                    self.process_no, self.due_amount, self.auth_token,
                    self.access_token, self.forge_cookie, self.service_id)
                self.result_signal.emit(result, "pay")
        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}] خطأ شام كاش: {e}")
            self.result_signal.emit({"succeeded": False, "message": str(e)}, self.operation)


class ShamCashSessionDialog(QDialog):
    """نافذة جلسات شام كاش المرتبطة بكل جلسة حجز"""

    def __init__(self, session_card, log_callback, parent=None):
        super().__init__(parent)
        self.session_card = session_card
        self.log_callback = log_callback
        self.shamcash_driver = None
        self.shamcash_driver_lock = threading.Lock()
        self.setWindowTitle(f"🏦 شام كاش - {session_card.session_id}")
        self.resize(550, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; color: #c9d1d9; }
            QLabel { font-weight: bold; font-size: 13px; }
            QLineEdit { background-color: #21262d; border: 1px solid #30363d; color: #58a6ff;
                        font-weight: bold; border-radius: 4px; padding: 6px; }
            QPushButton { border-radius: 4px; padding: 8px; font-weight: bold; }
            QGroupBox { border: 2px solid #30363d; border-radius: 8px; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #f0883e; }
        """)
        self.current_process_no = None
        self.current_due_amount = None
        self.setup_ui()
        self.load_shamcash_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- قسم تسجيل الدخول ---
        login_grp = QGroupBox("🔐 تسجيل الدخول لشام كاش")
        login_lay = QVBoxLayout()
        btn_row = QHBoxLayout()
        self.btn_open_shamcash = QPushButton("🌐 فتح متصفح شام كاش")
        self.btn_open_shamcash.setStyleSheet("background-color: #1f6feb; color: white;")
        self.btn_open_shamcash.clicked.connect(self.open_shamcash_browser)
        self.btn_extract_tokens = QPushButton("🔑 سحب التوكنات وحفظها")
        self.btn_extract_tokens.setStyleSheet("background-color: #238636; color: white;")
        self.btn_extract_tokens.clicked.connect(self.extract_shamcash_tokens)
        self.btn_close_shamcash = QPushButton("❌ إغلاق")
        self.btn_close_shamcash.setStyleSheet("background-color: #da3633; color: white;")
        self.btn_close_shamcash.clicked.connect(self.close_shamcash_browser)
        btn_row.addWidget(self.btn_open_shamcash)
        btn_row.addWidget(self.btn_extract_tokens)
        btn_row.addWidget(self.btn_close_shamcash)
        login_lay.addLayout(btn_row)
        # حالة التوكنات
        self.lbl_token_status = QLabel("حالة التوكنات: ❌ غير متصل")
        self.lbl_token_status.setStyleSheet("color: #da3633;")
        login_lay.addWidget(self.lbl_token_status)
        login_grp.setLayout(login_lay)
        layout.addWidget(login_grp)

        # --- قسم الاستعلام والدفع ---
        pay_grp = QGroupBox("💳 استعلام ودفع")
        pay_lay = QVBoxLayout()
        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("رقم المعاملة:"))
        self.inp_process_num = QLineEdit()
        self.inp_process_num.setPlaceholderText("أدخل رقم المعاملة (رمز الدفع)")
        inp_row.addWidget(self.inp_process_num)
        pay_lay.addLayout(inp_row)

        action_row = QHBoxLayout()
        self.btn_check = QPushButton("🔍 استعلام")
        self.btn_check.setStyleSheet("background-color: #3b82f6; color: white;")
        self.btn_check.clicked.connect(self.check_bill)
        self.btn_pay = QPushButton("💰 دفع")
        self.btn_pay.setStyleSheet("background-color: #10b981; color: white;")
        self.btn_pay.clicked.connect(self.pay_bill)
        self.btn_pay.setEnabled(False)
        action_row.addWidget(self.btn_check)
        action_row.addWidget(self.btn_pay)
        pay_lay.addLayout(action_row)

        # نتيجة
        self.lbl_result = QLabel("النتيجة: بانتظار...")
        self.lbl_result.setStyleSheet("color: #8b949e; font-size: 12px;")
        self.lbl_result.setWordWrap(True)
        pay_lay.addWidget(self.lbl_result)
        pay_grp.setLayout(pay_lay)
        layout.addWidget(pay_grp)

        # --- سجل العمليات ---
        log_grp = QGroupBox("📋 سجل العمليات")
        log_lay = QVBoxLayout()
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(150)
        self.txt_log.setStyleSheet("background-color: #161b22; color: #58a6ff; font-size: 12px;")
        log_lay.addWidget(self.txt_log)
        log_grp.setLayout(log_lay)
        layout.addWidget(log_grp)

    def log(self, msg):
        self.txt_log.append(msg)
        self.log_callback(msg)

    def load_shamcash_data(self):
        """تحميل بيانات شام كاش المحفوظة لهذه الجلسة"""
        all_data = load_all_data()
        session_data = all_data.get(self.session_card.session_id, {})
        sc = session_data.get("shamcash", {})
        if sc.get("auth_token") and sc.get("access_token") and sc.get("forge_cookie"):
            self.session_card.shamcash_auth_token = sc["auth_token"]
            self.session_card.shamcash_access_token = sc["access_token"]
            self.session_card.shamcash_forge_cookie = sc["forge_cookie"]
            self.lbl_token_status.setText("حالة التوكنات: ✅ متصل (محفوظ)")
            self.lbl_token_status.setStyleSheet("color: #238636;")

    def save_shamcash_data(self):
        """حفظ بيانات شام كاش لهذه الجلسة"""
        all_data = load_all_data()
        if self.session_card.session_id not in all_data:
            all_data[self.session_card.session_id] = {}
        all_data[self.session_card.session_id]["shamcash"] = {
            "auth_token": self.session_card.shamcash_auth_token,
            "access_token": self.session_card.shamcash_access_token,
            "forge_cookie": self.session_card.shamcash_forge_cookie
        }
        save_all_data(all_data)

    def open_shamcash_browser(self):
        """فتح متصفح مستقل لتسجيل الدخول لشام كاش"""
        self.btn_open_shamcash.setEnabled(False)
        self.btn_open_shamcash.setText("⏳ جاري الفتح...")
        threading.Thread(target=self._open_browser_thread, daemon=True).start()

    def _open_browser_thread(self):
        try:
            profile_dir = os.path.join(os.getcwd(), "Profiles",
                                       f"ShamCash_{self.session_card.session_id}")
            os.makedirs(profile_dir, exist_ok=True)
            with GLOBAL_BROWSER_LOCK:
                # تنظيف الأقفال
                for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    p = os.path.join(profile_dir, lk)
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except:
                            pass
                options = uc.ChromeOptions()
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-gpu')
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', 0))
                    free_port = s.getsockname()[1]
                self.shamcash_driver = uc.Chrome(
                    user_data_dir=profile_dir, options=options,
                    use_subprocess=True, port=free_port,
                    version_main=get_chrome_main_version())
            time.sleep(1)
            with self.shamcash_driver_lock:
                if self.shamcash_driver:
                    self.shamcash_driver.set_page_load_timeout(45)
                    self.shamcash_driver.get("https://shamcash.sy/ar/application/home")
            self.log(f"[+] [{self.session_card.session_id}] تم فتح متصفح شام كاش.")
            self.btn_open_shamcash.setText("🌐 المتصفح مفتوح")
        except Exception as e:
            self.log(f"[!] [{self.session_card.session_id}] خطأ فتح شام كاش: {e}")
            self.btn_open_shamcash.setEnabled(True)
            self.btn_open_shamcash.setText("🌐 فتح متصفح شام كاش")

    def extract_shamcash_tokens(self):
        """سحب التوكنات من كوكيز المتصفح وحفظها بشكل دائم"""
        with self.shamcash_driver_lock:
            if not self.shamcash_driver:
                QMessageBox.warning(self, "خطأ", "افتح متصفح شام كاش أولاً!")
                return
            try:
                cookies = self.shamcash_driver.get_cookies()
                auth_token = None
                access_token = None
                forge_cookie = None
                for c in cookies:
                    if c['name'] == 'authToken':
                        auth_token = c['value']
                    elif c['name'] == 'accessToken':
                        access_token = c['value']
                    elif c['name'] == 'forge':
                        forge_cookie = c['value']

                if auth_token and access_token and forge_cookie:
                    self.session_card.shamcash_auth_token = auth_token
                    self.session_card.shamcash_access_token = access_token
                    self.session_card.shamcash_forge_cookie = forge_cookie
                    self.save_shamcash_data()
                    self.lbl_token_status.setText("حالة التوكنات: ✅ متصل ومحفوظ")
                    self.lbl_token_status.setStyleSheet("color: #238636;")
                    self.log(f"[+] [{self.session_card.session_id}] تم سحب وحفظ توكنات شام كاش بنجاح!")
                    # التحقق من صحة المفتاح
                    try:
                        shamcash_get_session_key(forge_cookie)
                        self.log(f"[+] [{self.session_card.session_id}] ✅ مفتاح الجلسة صالح.")
                    except Exception as e:
                        self.log(f"[!] [{self.session_card.session_id}] ⚠️ خطأ في فك forge: {e}")
                else:
                    missing = []
                    if not auth_token:
                        missing.append("authToken")
                    if not access_token:
                        missing.append("accessToken")
                    if not forge_cookie:
                        missing.append("forge")
                    self.log(f"[-] [{self.session_card.session_id}] توكنات ناقصة: {', '.join(missing)}")
                    self.lbl_token_status.setText(f"❌ ناقص: {', '.join(missing)}")
                    self.lbl_token_status.setStyleSheet("color: #da3633;")
                    QMessageBox.warning(self, "تنبيه",
                        "يرجى تسجيل الدخول لشام كاش في المتصفح أولاً!")
            except Exception as e:
                self.log(f"[!] [{self.session_card.session_id}] خطأ سحب: {e}")

    def close_shamcash_browser(self):
        with self.shamcash_driver_lock:
            if self.shamcash_driver:
                try:
                    self.shamcash_driver.quit()
                except:
                    pass
                self.shamcash_driver = None
        self.btn_open_shamcash.setEnabled(True)
        self.btn_open_shamcash.setText("🌐 فتح متصفح شام كاش")
        self.log(f"[*] [{self.session_card.session_id}] تم إغلاق متصفح شام كاش.")

    def check_bill(self):
        """استعلام عن فاتورة"""
        process_num = self.inp_process_num.text().strip()
        if not process_num:
            QMessageBox.warning(self, "تنبيه", "أدخل رقم المعاملة!")
            return
        if not self.session_card.shamcash_auth_token:
            QMessageBox.warning(self, "تنبيه", "سحب توكنات شام كاش أولاً!")
            return
        self.btn_check.setEnabled(False)
        self.btn_check.setText("⏳...")
        self.lbl_result.setText("⏳ جاري الاستعلام...")
        self._worker = ShamCashWorker(
            "check", self.session_card.session_id,
            self.session_card.shamcash_auth_token,
            self.session_card.shamcash_access_token,
            self.session_card.shamcash_forge_cookie,
            process_number=process_num)
        self._worker.log_signal.connect(self.log)
        self._worker.result_signal.connect(self._on_result)
        self._worker.finished.connect(lambda: self._reset_btn(self.btn_check, "🔍 استعلام"))
        self._worker.start()

    def pay_bill(self):
        """دفع الفاتورة"""
        if not self.current_process_no or not self.current_due_amount:
            QMessageBox.warning(self, "تنبيه", "قم بالاستعلام أولاً!")
            return
        self.btn_pay.setEnabled(False)
        self.btn_pay.setText("⏳...")
        self.lbl_result.setText("⏳ جاري الدفع...")
        self._pay_worker = ShamCashWorker(
            "pay", self.session_card.session_id,
            self.session_card.shamcash_auth_token,
            self.session_card.shamcash_access_token,
            self.session_card.shamcash_forge_cookie,
            process_no=self.current_process_no,
            due_amount=self.current_due_amount)
        self._pay_worker.log_signal.connect(self.log)
        self._pay_worker.result_signal.connect(self._on_result)
        self._pay_worker.finished.connect(lambda: self._reset_btn(self.btn_pay, "💰 دفع"))
        self._pay_worker.start()

    def _on_result(self, data, op_type):
        if op_type == "check":
            if data.get("succeeded") and data.get("data") and len(data["data"]) > 0:
                fields = data["data"][0]
                self.current_process_no = next(
                    (item["value"] for item in fields if item["key"] == "process_no"), None)
                self.current_due_amount = next(
                    (item["value"] for item in fields if item["key"] == "due_amount"), None)
                if self.current_process_no and self.current_due_amount:
                    self.lbl_result.setText(
                        f"✅ جاهز للدفع | المبلغ: {self.current_due_amount} ل.س | الرقم: {self.current_process_no}")
                    self.lbl_result.setStyleSheet("color: #238636; font-size: 12px;")
                    self.btn_pay.setEnabled(True)
                    self.log(f"[+] [{self.session_card.session_id}] استعلام ناجح: {self.current_due_amount} ل.س")
                else:
                    self.lbl_result.setText("❌ لم يتم العثور على بيانات الدفع")
                    self.lbl_result.setStyleSheet("color: #da3633; font-size: 12px;")
            else:
                msg = data.get("message", "خطأ غير معروف")
                self.lbl_result.setText(f"❌ فشل: {msg}")
                self.lbl_result.setStyleSheet("color: #da3633; font-size: 12px;")
                self.btn_pay.setEnabled(False)
        elif op_type == "pay":
            if data.get("succeeded"):
                self.lbl_result.setText("🎉 تم الدفع بنجاح!")
                self.lbl_result.setStyleSheet("color: #238636; font-size: 14px;")
                self.btn_pay.setEnabled(False)
                self.log(f"[+] [{self.session_card.session_id}] 🎉 تم دفع شام كاش بنجاح!")
            else:
                msg = data.get("message", "خطأ غير معروف")
                self.lbl_result.setText(f"❌ فشل الدفع: {msg}")
                self.lbl_result.setStyleSheet("color: #da3633; font-size: 12px;")
                self.log(f"[-] [{self.session_card.session_id}] فشل الدفع: {msg}")

    def _reset_btn(self, btn, text):
        btn.setEnabled(True)
        btn.setText(text)

    def closeEvent(self, event):
        self.close_shamcash_browser()
        super().closeEvent(event)


class RequestWorker(QThread):
    """خيط واحد - يمكن إطلاق عدة نسخ بالتوازي"""
    log_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str, str, str, int)  # payment_code, fee, appointment_id, thread_id
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(int)
    response_signal = pyqtSignal(int, int, str)  # thread_id, status_code, body

    def __init__(self, session_id, payload, headers, cookies, mode="snipe",
                 thread_id=0, proxy_url=None):
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
            loop.run_until_complete(self.execute_requests())
        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] خطأ: {e}")
        finally:
            try:
                loop.close()
            except:
                pass
            self.finished_signal.emit(self.thread_id)

    def play_success_sound(self):
        with GLOBAL_SOUND_LOCK:
            try:
                winsound.Beep(1000, 1500)
            except:
                pass

    async def execute_requests(self):
        try:
            target_ip = socket.gethostbyname("api.mot.gov.sy")
        except:
            target_ip = "api.mot.gov.sy"

        monitor_url = f"https://{target_ip}/api/provinces/804e7642-6798-4353-a556-f11d9aad2637/weeks/active"
        post_url = f"https://{target_ip}/api/appointments/book"

        if self.proxy_url:
            self.log_signal.emit(f"🔗 [{self.session_id}][T{self.thread_id}] بروكسي: {self.proxy_url}")

        async with AsyncSession(verify=False, proxy=self.proxy_url) as session:
            attempts = 0
            while self.is_running:
                attempts += 1

                if self.mode == "snipe":
                    try:
                        resp = await session.get(monitor_url, headers=self.headers,
                                                 cookies=self.cookies, timeout=30)
                        if resp.status_code == 200:
                            state = resp.json().get("data", {}).get("registration", {}).get("state", "")
                            if state != "open":
                                if attempts % 3 == 1:
                                    self.log_signal.emit(
                                        f"⏳ [{self.session_id}][T{self.thread_id}] البوابة مغلقة...")
                                await asyncio.sleep(1.5)
                                continue
                            else:
                                if attempts % 3 == 1:
                                    self.log_signal.emit(
                                        f"🟢 [{self.session_id}][T{self.thread_id}] البوابة مفتوحة!")
                    except Exception as e:
                        self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] فشل المراقب: {e}")
                        await asyncio.sleep(1)
                        continue

                try:
                    response = await session.post(post_url, json=self.payload,
                                                  headers=self.headers, cookies=self.cookies, timeout=30)
                    body = response.text[:200] if response.text else ""
                    self.response_signal.emit(self.thread_id, response.status_code, body)

                    if response.status_code in [200, 201]:
                        data = response.json()
                        code = data.get('data', {}).get('payment_code', 'غير متوفر')
                        fee = str(data.get('data', {}).get('fee_amount', ''))
                        appt_id = data.get('data', {}).get('appointment_id', '')
                        self.log_signal.emit(
                            f"🎉 [{self.session_id}][T{self.thread_id}] تم اصطياد الدور!")
                        self.success_signal.emit(code, fee, appt_id, self.thread_id)
                        threading.Thread(target=self.play_success_sound, daemon=True).start()
                        break
                    elif response.status_code == 422:
                        self.log_signal.emit(
                            f"⚠️ [{self.session_id}][T{self.thread_id}] 422: {body[:100]}")
                        if self.mode == "single":
                            break
                    elif response.status_code in [401, 419]:
                        self.log_signal.emit(
                            f"❌ [{self.session_id}][T{self.thread_id}] الجلسة منتهية!")
                        self.error_signal.emit("انتهت الجلسة.")
                        break
                    else:
                        self.log_signal.emit(
                            f"⚠️ [{self.session_id}][T{self.thread_id}] حالة: {response.status_code}")
                except Exception as e:
                    self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] فشل: {e}")

                if self.mode == "single":
                    break
                await asyncio.sleep(0.3)

    def stop(self):
        self.is_running = False



class PaymentStatusWorker(QThread):
    """استعلام حالة رمز الدفع - يأخذ appointment_id مباشرة"""
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(dict)

    def __init__(self, session_id, appointment_id, headers, cookies, proxy_url=None):
        super().__init__()
        self.session_id = session_id
        self.appointment_id = appointment_id
        self.headers = headers
        self.cookies = cookies
        self.proxy_url = proxy_url

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.check_status())
        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}] خطأ استعلام الدفع: {e}")
        finally:
            loop.close()

    async def check_status(self):
        url = f"https://api.mot.gov.sy/api/appointments/{self.appointment_id}/payment-status"
        headers = dict(self.headers)
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Accept-Language"] = "ar"
        if "Content-Type" in headers:
            del headers["Content-Type"]

        async with AsyncSession(verify=False, proxy=self.proxy_url) as session:
            try:
                response = await session.get(url, headers=headers, cookies=self.cookies, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    self.result_signal.emit(data)
                    pd = data.get("data", {})
                    self.log_signal.emit(
                        f"💳 [{self.session_id}] حالة: {pd.get('payment_status','')} | "
                        f"الرمز: {pd.get('payment_code','')} | "
                        f"متبقي: {int(pd.get('payment_remaining_seconds',0))}ث")
                else:
                    self.log_signal.emit(
                        f"⚠️ [{self.session_id}] فشل استعلام: {response.status_code}")
                    self.result_signal.emit({})
            except Exception as e:
                self.log_signal.emit(f"❌ [{self.session_id}] خطأ اتصال: {e}")
                self.result_signal.emit({})



class SessionCard(QGroupBox):
    payment_received = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    _log_signal = pyqtSignal(str)
    _ui_browser_btn_signal = pyqtSignal(str, bool)
    _ui_renew_btn_signal = pyqtSignal(bool)
    _ui_status_signal = pyqtSignal(str, str)

    def __init__(self, session_id, log_callback, rename_callback, delete_callback, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.log_callback = log_callback
        self.rename_callback = rename_callback
        self.delete_callback = delete_callback
        self.driver = None
        self.driver_lock = threading.Lock()
        self.xsrf_token = ""
        self.accurate_session = ""
        self.remember_token_name = ""
        self.remember_token_value = ""
        self.user_agent = ""
        self.workers = []
        self.last_appointment_id = ""  # يُحفظ تلقائياً من رد الحجز الناجح
        # بيانات شام كاش
        self.shamcash_auth_token = ""
        self.shamcash_access_token = ""
        self.shamcash_forge_cookie = ""
        self.auto_pay_enabled = False  # دفع تلقائي فور وصول الرمز

        self._log_signal.connect(self.log_callback)
        self._ui_browser_btn_signal.connect(self._update_browser_btn)
        self._ui_renew_btn_signal.connect(self._update_renew_btn)
        self._ui_status_signal.connect(self._update_status_ui)

        self.setTitle(f"جلسة: {self.session_id}")
        self.setStyleSheet(
            "QGroupBox { border: 2px solid #30363d; border-radius: 8px; margin-top: 10px; font-weight: bold;}"
            " QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff;}")
        self.setup_ui()
        self.load_session_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- المتصفح ---
        br_lay = QHBoxLayout()
        self.btn_browser = QPushButton("🌐 فتح المتصفح")
        self.btn_browser.clicked.connect(self.launch_browser)
        self.btn_extract = QPushButton("🔄 سحب التوكن والتاريخ")
        self.btn_extract.clicked.connect(self.extract_tokens)
        self.btn_close_browser = QPushButton("❌ إغلاق المتصفح")
        self.btn_close_browser.clicked.connect(self.close_browser)
        self.btn_close_browser.setStyleSheet("color: #ff7b72;")
        br_lay.addWidget(self.btn_browser)
        br_lay.addWidget(self.btn_extract)
        br_lay.addWidget(self.btn_close_browser)
        layout.addLayout(br_lay)

        # --- البيانات ---
        data_lay = QGridLayout()
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
        self.cmb_transaction.setStyleSheet(
            "background-color: #21262d; border: 1px solid #30363d; color: #58a6ff;"
            " font-weight: bold; border-radius: 4px; padding: 4px;")
        data_lay.addWidget(QLabel("الاسم:"), 0, 0)
        data_lay.addWidget(self.inp_name, 0, 1)
        data_lay.addWidget(QLabel("اللوحة:"), 0, 2)
        data_lay.addWidget(self.inp_plate, 0, 3)
        data_lay.addWidget(QLabel("التاريخ:"), 1, 0)
        data_lay.addWidget(self.inp_date, 1, 1)
        data_lay.addWidget(QLabel("المعاملة:"), 1, 2)
        data_lay.addWidget(self.cmb_transaction, 1, 3)
        layout.addLayout(data_lay)

        # --- البروكسي: خانة واحدة + مربع تحديد النوع ---
        proxy_lay = QHBoxLayout()
        self.chk_proxy_enabled = QCheckBox("تفعيل")
        self.chk_proxy_enabled.setStyleSheet("color: #f0883e; font-weight: bold;")
        proxy_lay.addWidget(self.chk_proxy_enabled)

        self.radio_http = QRadioButton("HTTP")
        self.radio_http.setChecked(True)
        self.radio_http.setStyleSheet("color: #58a6ff;")
        self.radio_socks = QRadioButton("SOCKS5")
        self.radio_socks.setStyleSheet("color: #58a6ff;")
        self.proxy_type_group = QButtonGroup(self)
        self.proxy_type_group.addButton(self.radio_http)
        self.proxy_type_group.addButton(self.radio_socks)
        proxy_lay.addWidget(self.radio_http)
        proxy_lay.addWidget(self.radio_socks)

        self.inp_proxy = QLineEdit()
        self.inp_proxy.setPlaceholderText("user:pass@host:port  (مثلاً smart-xxx:pass@proxy.smartproxy.net:3120)")
        proxy_lay.addWidget(self.inp_proxy, 1)
        layout.addLayout(proxy_lay)

        # --- عدد الخيوط ---
        thr_lay = QHBoxLayout()
        thr_lay.addWidget(QLabel("عدد الخيوط:"))
        self.spn_threads = QSpinBox()
        self.spn_threads.setMinimum(1)
        self.spn_threads.setMaximum(20)
        self.spn_threads.setValue(1)
        self.spn_threads.setStyleSheet(
            "background-color: #21262d; border: 1px solid #30363d; color: #58a6ff; font-weight: bold; padding: 3px;")
        thr_lay.addWidget(self.spn_threads)
        self.lbl_threads_info = QLabel("(كل ضغطة ترسل بعدد الخيوط)")
        self.lbl_threads_info.setStyleSheet("color: #8b949e; font-size: 11px;")
        thr_lay.addWidget(self.lbl_threads_info)
        thr_lay.addStretch()
        layout.addLayout(thr_lay)


        # --- أدوات ---
        tools_lay = QHBoxLayout()
        self.btn_fill = QPushButton("✍️ تعبئة المتصفح")
        self.btn_fill.clicked.connect(lambda: self.fill_browser(False))
        self.btn_renew = QPushButton("♻️ تجديد (API)")
        self.btn_renew.setStyleSheet("background-color: #2ea043; color: white;")
        self.btn_renew.clicked.connect(self.renew_session)
        self.btn_save_data = QPushButton("💾 حفظ البيانات")
        self.btn_save_data.setStyleSheet("background-color: #238636; color: white;")
        self.btn_save_data.clicked.connect(self.save_session_data)
        tools_lay.addWidget(self.btn_fill)
        tools_lay.addWidget(self.btn_renew)
        tools_lay.addWidget(self.btn_save_data)
        layout.addLayout(tools_lay)

        # --- شام كاش + دفع تلقائي ---
        shamcash_lay = QHBoxLayout()
        self.btn_shamcash = QPushButton("🏦 جلسة شام كاش")
        self.btn_shamcash.setStyleSheet("background-color: #f0883e; color: white; font-weight: bold;")
        self.btn_shamcash.clicked.connect(self.open_shamcash_dialog)
        shamcash_lay.addWidget(self.btn_shamcash)
        self.chk_auto_pay = QCheckBox("💳 دفع تلقائي فور وصول الرمز")
        self.chk_auto_pay.setStyleSheet("color: #10b981; font-weight: bold;")
        self.chk_auto_pay.setToolTip("عند تفعيله: فور حصولك على رمز دفع من الحجز، يتم الدفع تلقائياً عبر شام كاش (بدون بروكسي)")
        shamcash_lay.addWidget(self.chk_auto_pay)
        self.lbl_shamcash_status = QLabel("")
        self.lbl_shamcash_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        shamcash_lay.addWidget(self.lbl_shamcash_status)
        shamcash_lay.addStretch()
        layout.addLayout(shamcash_lay)

        # --- إجراءات ---
        act_lay = QHBoxLayout()
        self.default_single_style = "background-color: #d29922; color: white; font-weight: bold;"
        self.active_single_style = "background-color: #9c7319; color: white; font-weight: bold; border: 1px solid white;"
        self.btn_single = QPushButton("⚡ إرسال مرة واحدة (API)")
        self.btn_single.setStyleSheet(self.default_single_style)
        self.btn_single.clicked.connect(lambda: self.start_request("single"))
        self.default_snipe_style = "background-color: #1f6feb; color: white; font-weight: bold;"
        self.active_snipe_style = "background-color: #11428f; color: white; font-weight: bold; border: 1px solid white;"
        self.btn_snipe = QPushButton("🚀 بدء القنص (API)")
        self.btn_snipe.setStyleSheet(self.default_snipe_style)
        self.btn_snipe.clicked.connect(lambda: self.start_request("snipe"))
        self.btn_stop = QPushButton("🛑 إيقاف")
        self.btn_stop.setStyleSheet("background-color: #da3633; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_request)
        self.btn_stop.setEnabled(False)
        act_lay.addWidget(self.btn_single)
        act_lay.addWidget(self.btn_snipe)
        act_lay.addWidget(self.btn_stop)
        layout.addLayout(act_lay)

        # --- النتائج + نسخ الرمز + استعلام الدفع ---
        res_lay = QHBoxLayout()
        self.lbl_status = QLabel("الحالة: جاهز")
        self.lbl_status.setStyleSheet("color: #8b949e;")
        self.inp_payment = QLineEdit()
        self.inp_payment.setPlaceholderText("رمز الدفع سيظهر هنا")
        self.inp_payment.setReadOnly(True)
        self.inp_payment.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 14px;")
        self.btn_copy = QPushButton("📋 نسخ")
        self.btn_copy.clicked.connect(self.copy_payment)
        self.btn_check_payment = QPushButton("🔍 استعلام")
        self.btn_check_payment.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_check_payment.clicked.connect(self.check_payment_status)
        res_lay.addWidget(self.lbl_status)
        res_lay.addStretch()
        res_lay.addWidget(QLabel("الرمز:"))
        res_lay.addWidget(self.inp_payment)
        res_lay.addWidget(self.btn_copy)
        res_lay.addWidget(self.btn_check_payment)
        layout.addLayout(res_lay)

        # --- الخيوط النشطة ---
        self.lbl_active_threads = QLabel("الخيوط النشطة: 0")
        self.lbl_active_threads.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.lbl_active_threads)

        # --- إدارة ---
        mgmt_lay = QHBoxLayout()
        self.btn_rename = QPushButton("✏️ إعادة تسمية")
        self.btn_rename.setStyleSheet("background-color: #3b3b3b; color: white;")
        self.btn_rename.clicked.connect(self.on_rename_clicked)
        self.btn_hide = QPushButton("👁️ إطفاء")
        self.btn_hide.setStyleSheet("background-color: #6e7681; color: white;")
        self.btn_hide.clicked.connect(self.on_hide_clicked)
        self.btn_delete = QPushButton("🗑️ حذف نهائي")
        self.btn_delete.setStyleSheet("background-color: #8b0000; color: white;")
        self.btn_delete.clicked.connect(self.on_delete_clicked)
        mgmt_lay.addWidget(self.btn_rename)
        mgmt_lay.addWidget(self.btn_hide)
        mgmt_lay.addWidget(self.btn_delete)
        layout.addLayout(mgmt_lay)


    # ===== المنطق =====

    def get_proxy_url(self):
        """خانة واحدة + مربع تحديد النوع"""
        if not self.chk_proxy_enabled.isChecked():
            return None
        proxy_str = self.inp_proxy.text().strip()
        if not proxy_str:
            return None
        ptype = "socks5" if self.radio_socks.isChecked() else "http"
        return parse_proxy_string(proxy_str, ptype)

    def load_session_data(self):
        all_data = load_all_data()
        if self.session_id in all_data:
            d = all_data[self.session_id]
            self.inp_name.setText(d.get("name", ""))
            self.inp_plate.setText(d.get("plate", ""))
            self.inp_date.setText(d.get("date", ""))
            trans_id = d.get("transaction_id", "")
            if trans_id:
                idx = self.cmb_transaction.findData(trans_id)
                if idx >= 0:
                    self.cmb_transaction.setCurrentIndex(idx)
            self.xsrf_token = d.get("xsrf_token", "")
            self.accurate_session = d.get("accurate_session", "")
            self.remember_token_name = d.get("remember_token_name", "")
            self.remember_token_value = d.get("remember_token_value", "")
            self.user_agent = d.get("user_agent", "")
            self.last_appointment_id = d.get("last_appointment_id", "")
            self.inp_proxy.setText(d.get("proxy", ""))
            self.chk_proxy_enabled.setChecked(d.get("proxy_enabled", False))
            if d.get("proxy_type", "http") == "socks5":
                self.radio_socks.setChecked(True)
            else:
                self.radio_http.setChecked(True)
            self.spn_threads.setValue(d.get("thread_count", 1))
            # تحميل شام كاش
            sc = d.get("shamcash", {})
            if sc.get("auth_token"):
                self.shamcash_auth_token = sc["auth_token"]
                self.shamcash_access_token = sc.get("access_token", "")
                self.shamcash_forge_cookie = sc.get("forge_cookie", "")
                self.lbl_shamcash_status.setText("✅ شام كاش متصل")
                self.lbl_shamcash_status.setStyleSheet("color: #238636; font-size: 11px;")
            self.chk_auto_pay.setChecked(d.get("auto_pay_enabled", False))
            if self.xsrf_token and self.accurate_session:
                self.update_status("مستعد (توكن محفوظ) ✔️", "#238636")
                self.log(f"[*] [{self.session_id}] تم استرجاع البيانات والتوكن.")
            else:
                self.log(f"[*] [{self.session_id}] تم استرجاع البيانات المحفوظة.")

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
            "proxy_enabled": self.chk_proxy_enabled.isChecked(),
            "proxy_type": "socks5" if self.radio_socks.isChecked() else "http",
            "thread_count": self.spn_threads.value(),
            "auto_pay_enabled": self.chk_auto_pay.isChecked(),
            "shamcash": {
                "auth_token": self.shamcash_auth_token,
                "access_token": self.shamcash_access_token,
                "forge_cookie": self.shamcash_forge_cookie
            }
        }
        save_all_data(all_data)
        self.log(f"[+] [{self.session_id}] تم الحفظ.")
        if show_msg:
            QMessageBox.information(self, "نجاح", "تم حفظ بيانات الجلسة.")

    def log(self, msg):
        self._log_signal.emit(msg)

    def _update_browser_btn(self, text, en):
        self.btn_browser.setText(text)
        self.btn_browser.setEnabled(en)

    def _update_renew_btn(self, en):
        self.btn_renew.setEnabled(en)
        if en:
            self.btn_renew.setText("♻️ تجديد (API)")

    def _update_status_ui(self, text, color):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color};")
        self.status_changed.emit(text, color)

    def update_status(self, text, color="#8b949e"):
        self._ui_status_signal.emit(text, color)


    def launch_browser(self):
        self.btn_browser.setEnabled(False)
        self.btn_browser.setText("⏳ جاري التحضير...")
        threading.Thread(target=self._browser_thread, daemon=True).start()

    def _browser_thread(self):
        try:
            profile_dir = os.path.join(os.getcwd(), "Profiles", f"Profile_{self.session_id}")
            os.makedirs(profile_dir, exist_ok=True)
            with GLOBAL_BROWSER_LOCK:
                self.log(f"[*] [{self.session_id}] جاري تهيئة المتصفح...")
                for attempt in range(3):
                    try:
                        if sys.platform == 'win32':
                            try:
                                safe_id = self.session_id.replace("'", "")
                                subprocess.run(
                                    f'wmic process where "name=\'chrome.exe\' and commandline like \'%Profile_{safe_id}%\'" call terminate',
                                    shell=True, capture_output=True)
                                time.sleep(0.5)
                            except:
                                pass
                        for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                            p = os.path.join(profile_dir, lk)
                            if os.path.exists(p):
                                try:
                                    os.remove(p)
                                except:
                                    pass
                        options = uc.ChromeOptions()
                        options.add_argument('--no-sandbox')
                        options.add_argument('--disable-dev-shm-usage')
                        options.add_argument('--disable-extensions')
                        options.add_argument('--disable-gpu')
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.bind(('127.0.0.1', 0))
                            free_port = s.getsockname()[1]
                        self.driver = uc.Chrome(user_data_dir=profile_dir, options=options,
                                                use_subprocess=True, port=free_port,
                                                version_main=get_chrome_main_version())
                        break
                    except Exception as e:
                        if attempt < 2:
                            self.log(f"[*] [{self.session_id}] فشل ({attempt+1}): {str(e)[:60]}")
                            time.sleep(2)
                        else:
                            raise e

            time.sleep(1.5)
            inject_js = r"""
            window.sarmadaSelectedDate = '';
            const origOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                if (typeof url === 'string' && url.includes('date=')) {
                    let m = url.match(/date=(20\d{2}-\d{2}-\d{2})/);
                    if (m) window.sarmadaSelectedDate = m[1];
                }
                return origOpen.apply(this, arguments);
            };
            const origFetch = window.fetch;
            window.fetch = async function() {
                let url = arguments[0] instanceof Request ? arguments[0].url : arguments[0];
                if (typeof url === 'string' && url.includes('date=')) {
                    let m = url.match(/date=(20\d{2}-\d{2}-\d{2})/);
                    if (m) window.sarmadaSelectedDate = m[1];
                }
                return origFetch.apply(this, arguments);
            };
            """
            with self.driver_lock:
                if self.driver:
                    self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': inject_js})
                    self.driver.set_page_load_timeout(45)
                    self.driver.get("https://accurate.mot.gov.sy/reviewer/availability")
            self.log(f"[+] [{self.session_id}] تم فتح المتصفح.")
            self._ui_browser_btn_signal.emit("🌐 المتصفح مفتوح", False)
            self.update_status("المتصفح قيد التشغيل", "#e3b341")
        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ المتصفح: {e}")
            self._ui_browser_btn_signal.emit("🌐 فتح المتصفح", True)

    def extract_tokens(self):
        with self.driver_lock:
            if not self.driver:
                QMessageBox.warning(self, "خطأ", "افتح المتصفح أولاً!")
                return
            try:
                self.user_agent = self.driver.execute_script("return navigator.userAgent;")
                page_date = self.driver.execute_script("""
                    if (window.sarmadaSelectedDate) return window.sarmadaSelectedDate;
                    let m = document.body.innerText.match(/20\\d{2}-\\d{2}-\\d{2}/);
                    return m ? m[0] : '';
                """)
                if page_date:
                    self.inp_date.setText(page_date)
                    self.log(f"[*] [{self.session_id}] تاريخ: {page_date}")
                cookies = self.driver.get_cookies()
                for c in cookies:
                    if c['name'] == 'XSRF-TOKEN':
                        self.xsrf_token = urllib.parse.unquote(c['value'])
                    elif c['name'] == 'accurate_session':
                        self.accurate_session = c['value']
                    elif c['name'].startswith('remember_web_'):
                        self.remember_token_name = c['name']
                        self.remember_token_value = c['value']
                if self.xsrf_token and self.accurate_session:
                    self.log(f"[+] [{self.session_id}] تم سحب الجلسة بنجاح.")
                    self.update_status("مستعد ✔️", "#238636")
                    self._save_data_internal(False)
                else:
                    self.log(f"[-] [{self.session_id}] لم أجد التوكن.")
            except Exception as e:
                self.log(f"[!] [{self.session_id}] خطأ: {e}")

    def close_browser(self):
        with self.driver_lock:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                finally:
                    self.driver = None
                    self._ui_browser_btn_signal.emit("🌐 فتح المتصفح", True)
                    self.update_status("المتصفح مغلق", "#8b949e")


    def fill_browser(self, auto_submit=False):
        with self.driver_lock:
            if not self.driver:
                if not auto_submit:
                    QMessageBox.warning(self, "خطأ", "افتح المتصفح أولاً!")
                return
        threading.Thread(target=self._selenium_fill, args=(auto_submit,), daemon=True).start()

    def _selenium_fill(self, auto_submit):
        try:
            name, plate = self.inp_name.text(), self.inp_plate.text()
            with self.driver_lock:
                if not self.driver:
                    return
                inputs = self.driver.find_elements(By.TAG_NAME, 'input')
            vis = [i for i in inputs if i.is_displayed() and i.is_enabled()
                   and i.get_attribute('type') in ['text', 'number', 'tel', '']]
            if len(vis) >= 2:
                with self.driver_lock:
                    if not self.driver:
                        return
                    for i, val in enumerate([name, plate]):
                        vis[i].send_keys(Keys.CONTROL + "a")
                        vis[i].send_keys(Keys.DELETE)
                        time.sleep(0.1)
                        vis[i].send_keys(val)
                        time.sleep(0.1)
                self.log(f"[+] [{self.session_id}] تم تعبئة البيانات.")
                if auto_submit:
                    time.sleep(0.5)
                    with self.driver_lock:
                        if not self.driver:
                            return
                        for btn in self.driver.find_elements(By.TAG_NAME, 'button'):
                            if btn.is_displayed() and ("حجز" in btn.text or "تأكيد" in btn.text):
                                btn.click()
                                self.log(f"[+] [{self.session_id}] ضغط زر الحجز.")
                                break
        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ تعبئة: {e}")

    def renew_session(self):
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", "لا يوجد توكن.")
            return
        self.btn_renew.setEnabled(False)
        self.btn_renew.setText("⏳ تجديد...")
        threading.Thread(target=self._renew_thread, daemon=True).start()

    def _renew_thread(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok = loop.run_until_complete(self._async_renew())
            loop.close()
            if ok:
                self.log(f"[+] [{self.session_id}] تم التجديد ♻️.")
                self.update_status("مستعد (تجديد) ✔️", "#2ea043")
            else:
                self.log(f"[-] [{self.session_id}] فشل التجديد.")
        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ تجديد: {e}")
        finally:
            self._ui_renew_btn_signal.emit(True)

    async def _async_renew(self):
        cookies = {"XSRF-TOKEN": self.xsrf_token, "accurate_session": self.accurate_session}
        if self.remember_token_name:
            cookies[self.remember_token_name] = self.remember_token_value
        headers = {
            "User-Agent": self.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/147.0.0.0",
            "Accept": "text/html,*/*;q=0.8",
        }
        proxy_url = self.get_proxy_url()
        async with AsyncSession(verify=False, proxy=proxy_url) as session:
            resp = await session.get("https://accurate.mot.gov.sy/", cookies=cookies,
                                     headers=headers, impersonate="chrome110", timeout=20)
            if resp.status_code == 200:
                new_x = session.cookies.get("XSRF-TOKEN")
                new_s = session.cookies.get("accurate_session")
                if new_x:
                    self.xsrf_token = urllib.parse.unquote(new_x)
                if new_s:
                    self.accurate_session = new_s
                self._save_data_internal(False)
                return True
            return False


    def start_request(self, mode):
        """إطلاق خيوط متعددة - كل ضغطة تضيف خيوط جديدة"""
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", "سحب التوكن أولاً!")
            return
        date_val = self.inp_date.text().strip()
        if not date_val:
            QMessageBox.warning(self, "تنبيه", "حدد التاريخ!")
            return

        payload = {
            "province_id": "804e7642-6798-4353-a556-f11d9aad2637",
            "name": self.inp_name.text().strip(),
            "plate_number": self.inp_plate.text().strip(),
            "date": date_val,
            "transaction_type_ids": [self.cmb_transaction.currentData()]
        }
        headers = {
            "Host": "api.mot.gov.sy",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://accurate.mot.gov.sy",
            "Referer": "https://accurate.mot.gov.sy/",
            "X-Xsrf-Token": self.xsrf_token,
            "User-Agent": self.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/147.0.0.0 Safari/537.36"
        }
        cookies = {"XSRF-TOKEN": self.xsrf_token, "accurate_session": self.accurate_session}
        proxy_url = self.get_proxy_url()
        thread_count = self.spn_threads.value()

        self.btn_stop.setEnabled(True)
        self.inp_payment.clear()
        if mode == "single":
            self.btn_single.setText(f"⏳ ({thread_count})...")
            self.btn_single.setStyleSheet(self.active_single_style)
            self.update_status(f"إرسال ({thread_count} خيط)...", "#e3b341")
        else:
            self.btn_snipe.setText(f"⏳ ({thread_count})...")
            self.btn_snipe.setStyleSheet(self.active_snipe_style)
            self.update_status(f"قنص ({thread_count} خيط)...", "#e3b341")

        base_id = len(self.workers)
        for i in range(thread_count):
            tid = base_id + i
            w = RequestWorker(self.session_id, payload, headers, cookies, mode,
                              thread_id=tid, proxy_url=proxy_url)
            w.log_signal.connect(self.log)
            w.success_signal.connect(self.on_success)
            w.error_signal.connect(self.on_error)
            w.finished_signal.connect(self.on_thread_finished)
            w.response_signal.connect(self.on_response_received)
            self.workers.append(w)
            w.start()
        self._update_threads_label()
        self.log(f"[*] [{self.session_id}] أُطلق {thread_count} خيط (المجموع: {len(self.workers)})")

    def _update_threads_label(self):
        active = sum(1 for w in self.workers if w.isRunning())
        self.lbl_active_threads.setText(f"الخيوط النشطة: {active} / {len(self.workers)}")

    def on_response_received(self, tid, code, body):
        c = "🟢" if code in [200, 201] else "🟡" if code == 422 else "🔴"
        self.log(f"{c} [{self.session_id}][T{tid}] رد: {code} | {body[:80]}")

    def on_thread_finished(self, tid):
        self._update_threads_label()
        if not any(w.isRunning() for w in self.workers):
            self._on_all_done()

    def _on_all_done(self):
        self.workers.clear()
        self.btn_single.setEnabled(True)
        self.btn_snipe.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_single.setText("⚡ إرسال مرة واحدة (API)")
        self.btn_single.setStyleSheet(self.default_single_style)
        self.btn_snipe.setText("🚀 بدء القنص (API)")
        self.btn_snipe.setStyleSheet(self.default_snipe_style)
        self._update_threads_label()
        if "تم الحجز" not in self.lbl_status.text() and "توقف" not in self.lbl_status.text():
            self.update_status("مستعد", "#8b949e")

    def stop_request(self):
        for w in self.workers:
            w.stop()
        self.update_status("تم الإيقاف", "#da3633")

    def on_success(self, code, fee, appt_id, tid):
        self.inp_payment.setText(code)
        self.last_appointment_id = appt_id  # حفظ تلقائي للاستعلام المباشر
        self.update_status(f"✅ تم الحجز ({fee})", "#238636")
        self.payment_received.emit(code)
        self.log(f"[$$$] [{self.session_id}][T{tid}] الرمز: {code} | الرسوم: {fee} | ID: {appt_id}")
        for w in self.workers:
            w.stop()
        self._save_data_internal(False)
        # تلجرام
        all_data = load_all_data()
        tg = all_data.get("TELEGRAM_CONFIG", {})
        if tg.get("token") and tg.get("chat_id"):
            msg = (f"✅ <b>تم الحجز!</b>\n🚗 {self.session_id}\n👤 {self.inp_name.text()}\n"
                   f"🔢 {self.inp_plate.text()}\n📅 {self.inp_date.text()}\n"
                   f"💰 {fee} ل.س\n💳 <code>{code}</code>\n⏳ دقيقتان للتسديد!")
            threading.Thread(target=send_telegram_message,
                           args=(tg["token"], tg["chat_id"], msg), daemon=True).start()
        # --- الدفع التلقائي عبر شام كاش ---
        self.trigger_auto_pay(code)

    def on_error(self, err):
        self.update_status("توقف (راجع السجل)", "#da3633")


    def check_payment_status(self):
        """استعلام مباشر - يأخذ appointment_id من رد الحجز تلقائياً"""
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", "سحب التوكن أولاً!")
            return
        if not self.last_appointment_id:
            QMessageBox.warning(self, "تنبيه",
                "لا يوجد معرف حجز محفوظ!\nقم بالحجز أولاً أو أدخل المعرف يدوياً.")
            # إتاحة الإدخال اليدوي كخيار أخير
            appt_id, ok = QInputDialog.getText(self, "معرف الحجز",
                "أدخل appointment_id:", text="")
            if not ok or not appt_id.strip():
                return
            self.last_appointment_id = appt_id.strip()
            self._save_data_internal(False)

        headers = {
            "Host": "api.mot.gov.sy",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://accurate.mot.gov.sy",
            "Referer": "https://accurate.mot.gov.sy/",
            "X-Xsrf-Token": self.xsrf_token,
            "Accept-Language": "ar",
            "User-Agent": self.user_agent or "Mozilla/5.0 Chrome/147.0.0.0"
        }
        cookies = {"XSRF-TOKEN": self.xsrf_token, "accurate_session": self.accurate_session}
        if self.remember_token_name:
            cookies[self.remember_token_name] = self.remember_token_value

        self.btn_check_payment.setEnabled(False)
        self.btn_check_payment.setText("⏳...")
        self._pmt_worker = PaymentStatusWorker(
            self.session_id, self.last_appointment_id, headers, cookies, self.get_proxy_url())
        self._pmt_worker.log_signal.connect(self.log)
        self._pmt_worker.result_signal.connect(self._on_pmt_result)
        self._pmt_worker.finished.connect(self._on_pmt_done)
        self._pmt_worker.start()

    def _on_pmt_result(self, data):
        if not data:
            return
        pd = data.get("data", {})
        status = pd.get("payment_status", "")
        code = pd.get("payment_code", "")
        remaining = pd.get("payment_remaining_seconds", 0)
        fee = pd.get("fee_amount", "")
        slot = pd.get("slot_no", "")
        target = pd.get("target_date", "")
        start = pd.get("start_at", "")
        if code and not self.inp_payment.text():
            self.inp_payment.setText(code)
        st_map = {"pending": "قيد الانتظار ⏳", "paid": "مدفوع ✅", "expired": "منتهي ❌"}
        QMessageBox.information(self, "استعلام الدفع",
            f"📊 الحالة: {st_map.get(status, status)}\n"
            f"💳 الرمز: {code}\n💰 المبلغ: {fee} ل.س\n"
            f"📅 التاريخ: {target}\n🔢 الدور: {slot}\n"
            f"⏰ الموعد: {start}\n⏳ متبقي: {int(remaining)}ث")

    def _on_pmt_done(self):
        self.btn_check_payment.setEnabled(True)
        self.btn_check_payment.setText("🔍 استعلام")

    def copy_payment(self):
        code = self.inp_payment.text()
        if code:
            QApplication.clipboard().setText(code)
            self.log(f"[+] [{self.session_id}] نُسخ: {code}")

    def open_shamcash_dialog(self):
        """فتح نافذة جلسات شام كاش المرتبطة بهذه الجلسة"""
        dlg = ShamCashSessionDialog(self, self.log_callback)
        dlg.exec()

    def trigger_auto_pay(self, payment_code):
        """الدفع التلقائي عبر شام كاش فور وصول رمز الدفع - بدون بروكسي"""
        if not self.chk_auto_pay.isChecked():
            return
        if not self.shamcash_auth_token or not self.shamcash_access_token or not self.shamcash_forge_cookie:
            self.log(f"[!] [{self.session_id}] الدفع التلقائي: توكنات شام كاش غير متوفرة!")
            self.lbl_shamcash_status.setText("❌ لا توكنات شام كاش")
            self.lbl_shamcash_status.setStyleSheet("color: #da3633; font-size: 11px;")
            return
        self.log(f"[*] [{self.session_id}] 💳 بدء الدفع التلقائي عبر شام كاش للرمز: {payment_code}")
        self.lbl_shamcash_status.setText("⏳ دفع تلقائي...")
        self.lbl_shamcash_status.setStyleSheet("color: #e3b341; font-size: 11px;")
        # استعلام ثم دفع في خيط مستقل - بدون بروكسي
        threading.Thread(target=self._auto_pay_thread, args=(payment_code,), daemon=True).start()

    def _auto_pay_thread(self, payment_code):
        """خيط الدفع التلقائي - مستقل وبدون بروكسي"""
        try:
            # 1. استعلام
            self.log(f"[*] [{self.session_id}] 🔍 استعلام شام كاش عن: {payment_code}")
            result = shamcash_check_bill(
                payment_code, self.shamcash_auth_token,
                self.shamcash_access_token, self.shamcash_forge_cookie)
            if result.get("succeeded") and result.get("data") and len(result["data"]) > 0:
                fields = result["data"][0]
                process_no = next((item["value"] for item in fields if item["key"] == "process_no"), None)
                due_amount = next((item["value"] for item in fields if item["key"] == "due_amount"), None)
                if process_no and due_amount:
                    self.log(f"[+] [{self.session_id}] ✅ استعلام ناجح: {due_amount} ل.س - جاري الدفع...")
                    # 2. دفع
                    pay_result = shamcash_pay_bill(
                        process_no, due_amount, self.shamcash_auth_token,
                        self.shamcash_access_token, self.shamcash_forge_cookie)
                    if pay_result.get("succeeded"):
                        self.log(f"[+] [{self.session_id}] 🎉🎉 تم الدفع التلقائي بنجاح! المبلغ: {due_amount} ل.س")
                        self._ui_status_signal.emit(f"✅ تم الدفع ({due_amount})", "#238636")
                        # إشعار تلجرام
                        all_data = load_all_data()
                        tg = all_data.get("TELEGRAM_CONFIG", {})
                        if tg.get("token") and tg.get("chat_id"):
                            msg = (f"💳 <b>دفع تلقائي ناجح!</b>\n🚗 {self.session_id}\n"
                                   f"💰 {due_amount} ل.س\n"
                                   f"🔢 الرمز: <code>{payment_code}</code>")
                            threading.Thread(target=send_telegram_message,
                                           args=(tg["token"], tg["chat_id"], msg), daemon=True).start()
                    else:
                        msg = pay_result.get("message", "خطأ")
                        self.log(f"[-] [{self.session_id}] ❌ فشل الدفع التلقائي: {msg}")
                else:
                    self.log(f"[-] [{self.session_id}] ❌ لم يتم العثور على بيانات الدفع في الاستعلام")
            else:
                msg = result.get("message", "خطأ غير معروف")
                self.log(f"[-] [{self.session_id}] ❌ فشل استعلام شام كاش: {msg}")
        except Exception as e:
            self.log(f"[!] [{self.session_id}] ❌ خطأ في الدفع التلقائي: {e}")

    def on_rename_clicked(self):
        with self.driver_lock:
            if self.driver:
                QMessageBox.warning(self, "تنبيه", "أغلق المتصفح أولاً.")
                return
        new_name, ok = QInputDialog.getText(self, "تسمية", "الاسم الجديد:", text=self.session_id)
        if ok and new_name and new_name != self.session_id:
            self.rename_callback(self, self.session_id, new_name.strip())

    def on_hide_clicked(self):
        self.hide()
        self.log(f"[*] [{self.session_id}] تم الإخفاء.")

    def on_delete_clicked(self):
        if QMessageBox.question(self, 'حذف', f"حذف '{self.session_id}' نهائياً؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.delete_callback(self)



class SarmadaPro(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alghanem Office - Sarmada V17 (Multi-Thread + Proxy + Payment Check)")
        self.resize(1100, 850)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; color: #c9d1d9; }
            QWidget { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            QLabel { color: #c9d1d9; }
            QLineEdit { background-color: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 5px; border-radius: 4px; }
            QPushButton { background-color: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px; border-radius: 4px; }
            QPushButton:hover { background-color: #30363d; }
            QPushButton:disabled { background-color: #161b22; color: #484f58; border: 1px solid #21262d; }
        """)
        self.log_window = LogWindow(self)
        self.sessions = []
        self.log_signal.connect(self._safe_log)
        self.session_counter = 0
        self.setup_ui(load_all_data())

    def setup_ui(self, saved_data):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)

        # تلجرام
        tg_grp = QGroupBox("إعدادات التلجرام (اختياري)")
        tg_lay = QHBoxLayout()
        self.inp_tg_token = QLineEdit()
        self.inp_tg_token.setPlaceholderText("Bot Token")
        self.inp_tg_token.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.inp_tg_chat_id = QLineEdit()
        self.inp_tg_chat_id.setPlaceholderText("Chat ID")
        tg_cfg = saved_data.get("TELEGRAM_CONFIG", {})
        self.inp_tg_token.setText(tg_cfg.get("token", ""))
        self.inp_tg_chat_id.setText(tg_cfg.get("chat_id", ""))
        btn_tg = QPushButton("💾 حفظ واختبار")
        btn_tg.setStyleSheet("background-color: #1f6feb; color: white;")
        btn_tg.clicked.connect(self.save_test_tg)
        tg_lay.addWidget(QLabel("توكن:"))
        tg_lay.addWidget(self.inp_tg_token)
        tg_lay.addWidget(QLabel("Chat ID:"))
        tg_lay.addWidget(self.inp_tg_chat_id)
        tg_lay.addWidget(btn_tg)
        tg_grp.setLayout(tg_lay)
        main_lay.addWidget(tg_grp)

        # شريط علوي
        top = QHBoxLayout()
        btn_add = QPushButton("➕ إضافة جلسة")
        btn_add.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        btn_add.clicked.connect(self.add_session)
        btn_grp = QPushButton("👥 المجموعات")
        btn_grp.setStyleSheet("background-color: #d29922; color: white; font-weight: bold;")
        btn_grp.clicked.connect(self.open_groups)
        btn_st = QPushButton("🛑 إيقاف الكل")
        btn_st.setStyleSheet("background-color: #da3633; color: white; font-weight: bold;")
        btn_st.clicked.connect(self.stop_all)
        btn_hid = QPushButton("👁️ المطفأة")
        btn_hid.setStyleSheet("background-color: #6e7681; color: white;")
        btn_hid.clicked.connect(self.show_hidden)
        btn_log = QPushButton("📋 السجلات")
        btn_log.clicked.connect(self.log_window.show)
        for b in [btn_add, btn_grp, btn_st, btn_hid, btn_log]:
            top.addWidget(b)
        main_lay.addLayout(top)

        # جلسات
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        self.sessions_container = QWidget()
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.sessions_container)
        main_lay.addWidget(self.scroll)

        # تحميل
        profiles_dir = os.path.join(os.getcwd(), "Profiles")
        existing = []
        max_num = 0
        if os.path.exists(profiles_dir):
            for f in os.listdir(profiles_dir):
                if f.startswith("Profile_"):
                    sid = f.replace("Profile_", "")
                    existing.append(sid)
                    if sid.startswith("رقم_"):
                        try:
                            n = int(sid.replace("رقم_", ""))
                            if n > max_num:
                                max_num = n
                        except:
                            pass
        self.session_counter = max_num
        if existing:
            for sid in existing:
                self._create_card(sid)
        else:
            self.add_session()


    def save_test_tg(self):
        token = self.inp_tg_token.text().strip()
        chat_id = self.inp_tg_chat_id.text().strip()
        all_data = load_all_data()
        all_data["TELEGRAM_CONFIG"] = {"token": token, "chat_id": chat_id}
        save_all_data(all_data)
        if token and chat_id:
            threading.Thread(target=send_telegram_message,
                args=(token, chat_id, "🤖 <b>اختبار سرمدا V17</b> - يعمل!"), daemon=True).start()
            QMessageBox.information(self, "نجاح", "تفقد التلجرام.")
        else:
            QMessageBox.warning(self, "تنبيه", "أدخل التوكن و Chat ID.")

    def print_log(self, msg):
        self.log_signal.emit(msg)

    def _safe_log(self, msg):
        self.log_window.append_log(msg)
        print(msg)

    def _create_card(self, sid):
        card = SessionCard(sid, self.print_log, self.handle_rename, self.handle_delete)
        self.sessions.append(card)
        self.sessions_layout.addWidget(card)
        self.print_log(f"[*] تم تحميل: {sid}")

    def add_session(self):
        self.session_counter += 1
        self._create_card(f"رقم_{self.session_counter}")

    def open_groups(self):
        GroupActionDialog(self, self).exec()

    def stop_all(self):
        for c in self.sessions:
            c.stop_request()

    def show_hidden(self):
        HiddenSessionsDialog(self, self).exec()

    def handle_rename(self, card, old_id, new_id):
        if any(c.session_id == new_id for c in self.sessions):
            QMessageBox.warning(self, "خطأ", "الاسم مستخدم.")
            return
        profiles_dir = os.path.join(os.getcwd(), "Profiles")
        old_d = os.path.join(profiles_dir, f"Profile_{old_id}")
        new_d = os.path.join(profiles_dir, f"Profile_{new_id}")
        try:
            if os.path.exists(old_d):
                os.rename(old_d, new_d)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))
            return
        all_data = load_all_data()
        if old_id in all_data:
            all_data[new_id] = all_data.pop(old_id)
            save_all_data(all_data)
        card.session_id = new_id
        card.setTitle(f"جلسة: {new_id}")
        self.print_log(f"[*] تسمية: {old_id} → {new_id}")

    def handle_delete(self, card):
        card.stop_request()
        card.close_browser()
        sid = card.session_id
        all_data = load_all_data()
        if sid in all_data:
            del all_data[sid]
            save_all_data(all_data)
        p = os.path.join(os.getcwd(), "Profiles", f"Profile_{sid}")
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
        self.sessions.remove(card)
        card.setParent(None)
        card.deleteLater()
        self.print_log(f"[*] حُذفت: {sid}")

    def closeEvent(self, event):
        self.stop_all()
        for c in self.sessions:
            if c.driver:
                c.close_browser()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SarmadaPro()
    window.show()
    sys.exit(app.exec())
