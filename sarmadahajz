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
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QTextEdit, QGroupBox,
                             QFormLayout, QDialog, QMessageBox, QScrollArea, QGridLayout,
                             QInputDialog, QCheckBox, QComboBox, QSpinBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from curl_cffi.requests import AsyncSession

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
    """تحليل سلسلة البروكسي ودعم أنواع متعددة بما فيها SmartProxy"""
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    # دعم صيغة SmartProxy: user:pass@host:port
    # أو http://user:pass@host:port
    # أو socks5://user:pass@host:port
    if proxy_str.startswith("http://") or proxy_str.startswith("https://"):
        return {"http": proxy_str, "https": proxy_str}
    elif proxy_str.startswith("socks5://") or proxy_str.startswith("socks4://"):
        return {"http": proxy_str, "https": proxy_str}
    else:
        # صيغة user:pass@host:port أو host:port
        if proxy_type == "socks5":
            return {"http": f"socks5://{proxy_str}", "https": f"socks5://{proxy_str}"}
        else:
            return {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}



def send_telegram_message(token, chat_id, text, retries=3):
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
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

    print("[!] فشل إرسال رسالة التلجرام نهائياً بعد جميع المحاولات.")



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
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                self.clear_layout(item.layout())

        hidden_cards = [card for card in self.main_window.sessions if card.isHidden()]

        if not hidden_cards:
            lbl = QLabel("✅ لا توجد جلسات مطفأة حالياً.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(lbl)
            return

        for card in hidden_cards:
            row = QHBoxLayout()
            lbl = QLabel(f"جلسة: {card.session_id}")
            lbl.setStyleSheet("color: #8b949e;")

            btn_restore = QPushButton("🔄 إعادة للواجهة")
            btn_restore.clicked.connect(lambda checked, c=card: self.restore_session(c))

            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(btn_restore)
            self.layout.addLayout(row)

        self.layout.addStretch()

    def clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
                else:
                    self.clear_layout(item.layout())

    def restore_session(self, card):
        card.show()
        self.main_window.print_log(f"[*] تم استعادة الجلسة {card.session_id} إلى واجهة العمل.")
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
        btn_select_all = QPushButton("☑️ تحديد الكل")
        btn_select_all.setStyleSheet("background-color: #3b3b3b; color: white;")
        btn_select_all.clicked.connect(lambda: self.set_all_checked(True))

        btn_deselect_all = QPushButton("☐ إلغاء التحديد")
        btn_deselect_all.setStyleSheet("background-color: #3b3b3b; color: white;")
        btn_deselect_all.clicked.connect(lambda: self.set_all_checked(False))

        top_bar.addWidget(btn_select_all)
        top_bar.addWidget(btn_deselect_all)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #30363d; background-color: transparent; }")

        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("تحديد/الجلسة"), 2)
        header_layout.addWidget(QLabel("اللوحة"), 1)
        header_layout.addWidget(QLabel("التاريخ"), 1)
        header_layout.addWidget(QLabel("حالة الجلسة"), 2)
        header_layout.addWidget(QLabel("رمز الدفع"), 2)
        header_layout.addWidget(QLabel(""), 1)
        self.list_layout.addLayout(header_layout)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #30363d;")
        self.list_layout.addWidget(line)


        active_cards = [card for card in self.main_window.sessions if not card.isHidden()]

        for card in active_cards:
            row_layout = QHBoxLayout()

            checkbox = QCheckBox(f"{card.session_id}")
            row_layout.addWidget(checkbox, 2)

            lbl_plate = QLabel(card.inp_plate.text())
            row_layout.addWidget(lbl_plate, 1)

            lbl_date = QLabel(card.inp_date.text())
            row_layout.addWidget(lbl_date, 1)

            lbl_status = QLabel(card.lbl_status.text())
            lbl_status.setStyleSheet(card.lbl_status.styleSheet())
            row_layout.addWidget(lbl_status, 2)

            conn1 = card.status_changed.connect(
                lambda text, color, l=lbl_status: self.update_row_status(l, text, color))
            self.signal_connections.append((card.status_changed, conn1))

            inp_code = QLineEdit(card.inp_payment.text())
            inp_code.setReadOnly(True)
            inp_code.setPlaceholderText("بانتظار الرمز...")
            row_layout.addWidget(inp_code, 2)

            conn2 = card.payment_received.connect(lambda code, i=inp_code: i.setText(code))
            self.signal_connections.append((card.payment_received, conn2))

            btn_copy = QPushButton("📋 نسخ")
            btn_copy.setStyleSheet("background-color: #21262d; color: white;")
            btn_copy.clicked.connect(lambda checked, c=card, i=inp_code: self.copy_row_code(c, i.text()))
            row_layout.addWidget(btn_copy, 1)

            self.list_layout.addLayout(row_layout)

            self.rows_data.append({
                'card': card,
                'checkbox': checkbox,
                'status_label': lbl_status,
                'code_input': inp_code
            })

        scroll.setWidget(container)
        main_layout.addWidget(scroll)


        actions_layout = QHBoxLayout()

        btn_send_selected = QPushButton("⚡ إرسال فردي (للمحدد)")
        btn_send_selected.setStyleSheet("background-color: #d29922; color: white;")
        btn_send_selected.clicked.connect(lambda: self.execute_on_selected("single"))

        btn_snipe_selected = QPushButton("🚀 قنص مستمر (للمحدد)")
        btn_snipe_selected.setStyleSheet("background-color: #1f6feb; color: white;")
        btn_snipe_selected.clicked.connect(lambda: self.execute_on_selected("snipe"))

        btn_stop_selected = QPushButton("🛑 إيقاف (للمحدد)")
        btn_stop_selected.setStyleSheet("background-color: #da3633; color: white;")
        btn_stop_selected.clicked.connect(self.stop_selected)

        actions_layout.addWidget(btn_send_selected)
        actions_layout.addWidget(btn_snipe_selected)
        actions_layout.addWidget(btn_stop_selected)
        main_layout.addLayout(actions_layout)

    def set_all_checked(self, state):
        for row in self.rows_data:
            row['checkbox'].setChecked(state)

    def update_row_status(self, label, text, color):
        try:
            label.setText(text)
            label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except RuntimeError:
            pass

    def copy_row_code(self, card, code):
        if code:
            QApplication.clipboard().setText(code)
            self.main_window.print_log(f"[+] [{card.session_id}] تم نسخ الكود من تبويبة المجموعات: {code}")
        else:
            QMessageBox.information(self, "تنبيه", "لا يوجد رمز دفع لنسخه بعد.")

    def execute_on_selected(self, mode):
        selected_count = 0
        for row in self.rows_data:
            if row['checkbox'].isChecked():
                card = row['card']
                if card.xsrf_token:
                    card.start_request(mode)
                    selected_count += 1
                else:
                    self.main_window.print_log(f"[-] تم تخطي {card.session_id}: لا يوجد توكن مسحوب.")

        if selected_count > 0:
            self.main_window.print_log(f"[*] تم إطلاق الأمر ({mode}) لعدد {selected_count} جلسة محددة.")
        else:
            QMessageBox.warning(self, "تنبيه", "لم يتم تحديد أي جلسة صالحة (يجب سحب التوكن أولاً).")

    def stop_selected(self):
        for row in self.rows_data:
            if row['checkbox'].isChecked():
                row['card'].stop_request()

    def closeEvent(self, event):
        for signal, conn in self.signal_connections:
            try:
                signal.disconnect(conn)
            except Exception:
                pass
        super().closeEvent(event)



class RequestWorker(QThread):
    """خيط واحد يرسل طلبات - يمكن إطلاق عدة نسخ منه بالتوازي"""
    log_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str, str, int)  # payment_code, fee, thread_id
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(int)  # thread_id
    response_signal = pyqtSignal(int, int, str)  # thread_id, status_code, body_snippet

    def __init__(self, session_id, payload, headers, cookies, mode="snipe",
                 thread_id=0, proxy_config=None):
        super().__init__()
        self.session_id = session_id
        self.payload = payload
        self.headers = headers
        self.cookies = cookies
        self.mode = mode
        self.thread_id = thread_id
        self.proxy_config = proxy_config  # {"http": "...", "https": "..."}
        self.is_running = True

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.execute_requests())
        except Exception as e:
            self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] خطأ غير متوقع: {e}")
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
            except Exception:
                pass


    async def execute_requests(self):
        try:
            target_ip = socket.gethostbyname("api.mot.gov.sy")
        except Exception:
            target_ip = "api.mot.gov.sy"

        monitor_url = f"https://{target_ip}/api/provinces/804e7642-6798-4353-a556-f11d9aad2637/weeks/active"
        post_url = f"https://{target_ip}/api/appointments/book"

        # إعداد البروكسي إن وجد
        proxy_arg = None
        if self.proxy_config:
            proxy_arg = self.proxy_config.get("http") or self.proxy_config.get("https")
            self.log_signal.emit(f"🔗 [{self.session_id}][T{self.thread_id}] استخدام بروكسي: {proxy_arg}")

        async with AsyncSession(verify=False, proxy=proxy_arg) as session:
            attempts = 0
            while self.is_running:
                attempts += 1

                if self.mode == "snipe":
                    try:
                        avail_resp = await session.get(monitor_url, headers=self.headers,
                                                       cookies=self.cookies, timeout=30)
                        if avail_resp.status_code == 200:
                            avail_data = avail_resp.json()
                            reg_state = avail_data.get("data", {}).get("registration", {}).get("state", "")

                            if reg_state != "open":
                                if attempts % 3 == 1:
                                    self.log_signal.emit(
                                        f"⏳ [{self.session_id}][T{self.thread_id}] البوابة مغلقة. مراقبة...")
                                await asyncio.sleep(1.5)
                                continue
                            else:
                                if attempts % 3 == 1:
                                    self.log_signal.emit(
                                        f"🟢 [{self.session_id}][T{self.thread_id}] البوابة مفتوحة! إطلاق...")
                        else:
                            self.log_signal.emit(
                                f"⚠️ [{self.session_id}][T{self.thread_id}] خطأ مراقبة: {avail_resp.status_code}")
                    except Exception as e:
                        self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] فشل المراقب: {e}")
                        await asyncio.sleep(1)
                        continue


                try:
                    response = await session.post(
                        post_url,
                        json=self.payload,
                        headers=self.headers,
                        cookies=self.cookies,
                        timeout=30
                    )

                    # إرسال الرد لعرضه في السجل
                    body_snippet = response.text[:200] if response.text else ""
                    self.response_signal.emit(self.thread_id, response.status_code, body_snippet)

                    if response.status_code in [200, 201]:
                        data = response.json()
                        payment_code = data.get('data', {}).get('payment_code', 'غير متوفر')
                        fee_amount = str(data.get('data', {}).get('fee_amount', ''))
                        self.log_signal.emit(
                            f"🎉 [{self.session_id}][T{self.thread_id}] تم اصطياد الدور بنجاح!")
                        self.success_signal.emit(payment_code, fee_amount, self.thread_id)

                        threading.Thread(target=self.play_success_sound, daemon=True).start()
                        break

                    elif response.status_code == 422:
                        self.log_signal.emit(
                            f"⚠️ [{self.session_id}][T{self.thread_id}] رد 422: {response.text[:150]}")
                        if self.mode == "single":
                            break

                    elif response.status_code in [401, 419]:
                        self.log_signal.emit(
                            f"❌ [{self.session_id}][T{self.thread_id}] الجلسة منتهية! حدّث التوكن.")
                        self.error_signal.emit("انتهت الجلسة.")
                        break
                    else:
                        self.log_signal.emit(
                            f"⚠️ [{self.session_id}][T{self.thread_id}] حالة: {response.status_code}")

                except Exception as e:
                    self.log_signal.emit(f"❌ [{self.session_id}][T{self.thread_id}] فشل POST: {e}")

                if self.mode == "single":
                    break
                await asyncio.sleep(0.3)

    def stop(self):
        self.is_running = False



class PaymentStatusWorker(QThread):
    """خيط للاستعلام عن حالة رمز الدفع"""
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(dict)  # نتيجة الاستعلام

    def __init__(self, session_id, appointment_id, headers, cookies, proxy_config=None):
        super().__init__()
        self.session_id = session_id
        self.appointment_id = appointment_id
        self.headers = headers
        self.cookies = cookies
        self.proxy_config = proxy_config

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

        proxy_arg = None
        if self.proxy_config:
            proxy_arg = self.proxy_config.get("http") or self.proxy_config.get("https")

        headers = dict(self.headers)
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Accept-Language"] = "ar"
        if "Content-Type" in headers:
            del headers["Content-Type"]

        async with AsyncSession(verify=False, proxy=proxy_arg) as session:
            try:
                response = await session.get(
                    url,
                    headers=headers,
                    cookies=self.cookies,
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    self.result_signal.emit(data)
                    payment_data = data.get("data", {})
                    status = payment_data.get("payment_status", "غير معروف")
                    code = payment_data.get("payment_code", "")
                    remaining = payment_data.get("payment_remaining_seconds", 0)
                    self.log_signal.emit(
                        f"💳 [{self.session_id}] حالة الدفع: {status} | الرمز: {code} | "
                        f"الوقت المتبقي: {int(remaining)} ثانية")
                else:
                    self.log_signal.emit(
                        f"⚠️ [{self.session_id}] فشل استعلام الدفع: {response.status_code} | {response.text[:100]}")
                    self.result_signal.emit({})
            except Exception as e:
                self.log_signal.emit(f"❌ [{self.session_id}] خطأ اتصال استعلام الدفع: {e}")
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
        self.workers = []  # قائمة الخيوط النشطة
        self.last_appointment_id = ""  # آخر معرف حجز للاستعلام

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

        # --- صف المتصفح ---
        browser_layout = QHBoxLayout()
        self.btn_browser = QPushButton("🌐 فتح المتصفح")
        self.btn_browser.clicked.connect(self.launch_browser)

        self.btn_extract = QPushButton("🔄 سحب التوكن والتاريخ")
        self.btn_extract.clicked.connect(self.extract_tokens)

        self.btn_close_browser = QPushButton("❌ إغلاق المتصفح")
        self.btn_close_browser.clicked.connect(self.close_browser)
        self.btn_close_browser.setStyleSheet("color: #ff7b72;")

        browser_layout.addWidget(self.btn_browser)
        browser_layout.addWidget(self.btn_extract)
        browser_layout.addWidget(self.btn_close_browser)
        layout.addLayout(browser_layout)

        # --- صف البيانات ---
        data_layout = QGridLayout()
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

        data_layout.addWidget(QLabel("الاسم:"), 0, 0)
        data_layout.addWidget(self.inp_name, 0, 1)
        data_layout.addWidget(QLabel("اللوحة:"), 0, 2)
        data_layout.addWidget(self.inp_plate, 0, 3)
        data_layout.addWidget(QLabel("التاريخ:"), 1, 0)
        data_layout.addWidget(self.inp_date, 1, 1)
        data_layout.addWidget(QLabel("المعاملة:"), 1, 2)
        data_layout.addWidget(self.cmb_transaction, 1, 3)
        layout.addLayout(data_layout)


        # --- صف البروكسي ---
        proxy_group = QGroupBox("⚙️ إعدادات البروكسي")
        proxy_group.setStyleSheet(
            "QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 5px; padding-top: 10px;}"
            " QGroupBox::title { color: #e3b341; font-size: 11px; }")
        proxy_layout = QGridLayout(proxy_group)

        self.chk_proxy_enabled = QCheckBox("تفعيل البروكسي")
        self.chk_proxy_enabled.setStyleSheet("color: #f0883e; font-weight: bold;")
        proxy_layout.addWidget(self.chk_proxy_enabled, 0, 0, 1, 2)

        proxy_layout.addWidget(QLabel("HTTP Proxy:"), 1, 0)
        self.inp_http_proxy = QLineEdit()
        self.inp_http_proxy.setPlaceholderText("user:pass@host:port أو http://host:port")
        proxy_layout.addWidget(self.inp_http_proxy, 1, 1)

        proxy_layout.addWidget(QLabel("SOCKS5 Proxy:"), 2, 0)
        self.inp_socks_proxy = QLineEdit()
        self.inp_socks_proxy.setPlaceholderText("user:pass@host:port أو socks5://host:port")
        proxy_layout.addWidget(self.inp_socks_proxy, 2, 1)

        layout.addWidget(proxy_group)

        # --- صف عدد الخيوط ---
        threads_layout = QHBoxLayout()
        threads_layout.addWidget(QLabel("عدد الخيوط المتزامنة:"))
        self.spn_threads = QSpinBox()
        self.spn_threads.setMinimum(1)
        self.spn_threads.setMaximum(20)
        self.spn_threads.setValue(1)
        self.spn_threads.setStyleSheet(
            "background-color: #21262d; border: 1px solid #30363d; color: #58a6ff;"
            " font-weight: bold; padding: 3px;")
        threads_layout.addWidget(self.spn_threads)

        self.lbl_threads_info = QLabel("(كل ضغطة ترسل بعدد الخيوط المحدد)")
        self.lbl_threads_info.setStyleSheet("color: #8b949e; font-size: 11px;")
        threads_layout.addWidget(self.lbl_threads_info)
        threads_layout.addStretch()
        layout.addLayout(threads_layout)


        # --- صف الأدوات ---
        tools_layout = QHBoxLayout()
        self.btn_fill = QPushButton("✍️ تعبئة المتصفح")
        self.btn_fill.clicked.connect(lambda: self.fill_browser(auto_submit=False))

        self.btn_renew = QPushButton("♻️ تجديد (API)")
        self.btn_renew.setStyleSheet("background-color: #2ea043; color: white;")
        self.btn_renew.clicked.connect(self.renew_session)

        self.btn_save_data = QPushButton("💾 حفظ البيانات")
        self.btn_save_data.setStyleSheet("background-color: #238636; color: white;")
        self.btn_save_data.clicked.connect(self.save_session_data)

        tools_layout.addWidget(self.btn_fill)
        tools_layout.addWidget(self.btn_renew)
        tools_layout.addWidget(self.btn_save_data)
        layout.addLayout(tools_layout)

        # --- صف الإجراءات ---
        action_layout = QHBoxLayout()
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

        action_layout.addWidget(self.btn_single)
        action_layout.addWidget(self.btn_snipe)
        action_layout.addWidget(self.btn_stop)
        layout.addLayout(action_layout)


        # --- صف النتائج مع زر استعلام الدفع ---
        res_layout = QHBoxLayout()
        self.lbl_status = QLabel("الحالة: جاهز")
        self.lbl_status.setStyleSheet("color: #8b949e;")
        self.inp_payment = QLineEdit()
        self.inp_payment.setPlaceholderText("رمز الدفع سيظهر هنا")
        self.inp_payment.setReadOnly(True)
        self.inp_payment.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 14px;")

        self.btn_copy = QPushButton("📋 نسخ الرمز")
        self.btn_copy.clicked.connect(self.copy_payment)

        self.btn_check_payment = QPushButton("🔍 استعلام الدفع")
        self.btn_check_payment.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_check_payment.clicked.connect(self.check_payment_status)

        res_layout.addWidget(self.lbl_status)
        res_layout.addStretch()
        res_layout.addWidget(QLabel("الرمز:"))
        res_layout.addWidget(self.inp_payment)
        res_layout.addWidget(self.btn_copy)
        res_layout.addWidget(self.btn_check_payment)
        layout.addLayout(res_layout)

        # --- صف معلومات الخيوط النشطة ---
        self.lbl_active_threads = QLabel("الخيوط النشطة: 0")
        self.lbl_active_threads.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.lbl_active_threads)

        # --- صف الإدارة ---
        mgmt_layout = QHBoxLayout()

        self.btn_rename = QPushButton("✏️ إعادة تسمية")
        self.btn_rename.setStyleSheet("background-color: #3b3b3b; color: white;")
        self.btn_rename.clicked.connect(self.on_rename_clicked)

        self.btn_hide = QPushButton("👁️ إطفاء (إخفاء)")
        self.btn_hide.setStyleSheet("background-color: #6e7681; color: white;")
        self.btn_hide.clicked.connect(self.on_hide_clicked)

        self.btn_delete = QPushButton("🗑️ حذف نهائي")
        self.btn_delete.setStyleSheet("background-color: #8b0000; color: white;")
        self.btn_delete.clicked.connect(self.on_delete_clicked)

        mgmt_layout.addWidget(self.btn_rename)
        mgmt_layout.addWidget(self.btn_hide)
        mgmt_layout.addWidget(self.btn_delete)
        layout.addLayout(mgmt_layout)


    def get_proxy_config(self):
        """الحصول على إعدادات البروكسي الحالية"""
        if not self.chk_proxy_enabled.isChecked():
            return None

        # أولوية SOCKS ثم HTTP
        socks_proxy = self.inp_socks_proxy.text().strip()
        http_proxy = self.inp_http_proxy.text().strip()

        if socks_proxy:
            return parse_proxy_string(socks_proxy, "socks5")
        elif http_proxy:
            return parse_proxy_string(http_proxy, "http")
        return None

    def load_session_data(self):
        all_data = load_all_data()
        if self.session_id in all_data:
            s_data = all_data[self.session_id]
            self.inp_name.setText(s_data.get("name", ""))
            self.inp_plate.setText(s_data.get("plate", ""))
            self.inp_date.setText(s_data.get("date", ""))

            trans_id = s_data.get("transaction_id", "")
            if trans_id:
                index = self.cmb_transaction.findData(trans_id)
                if index >= 0:
                    self.cmb_transaction.setCurrentIndex(index)

            self.xsrf_token = s_data.get("xsrf_token", "")
            self.accurate_session = s_data.get("accurate_session", "")
            self.remember_token_name = s_data.get("remember_token_name", "")
            self.remember_token_value = s_data.get("remember_token_value", "")
            self.user_agent = s_data.get("user_agent", "")
            self.last_appointment_id = s_data.get("last_appointment_id", "")

            # استرجاع إعدادات البروكسي
            self.inp_http_proxy.setText(s_data.get("http_proxy", ""))
            self.inp_socks_proxy.setText(s_data.get("socks_proxy", ""))
            self.chk_proxy_enabled.setChecked(s_data.get("proxy_enabled", False))
            self.spn_threads.setValue(s_data.get("thread_count", 1))

            if self.xsrf_token and self.accurate_session:
                self.update_status("مستعد للعمل (توكن محفوظ) ✔️", "#238636")
                self.log(f"[*] [{self.session_id}] تم استرجاع البيانات والتوكن المحفوظ بنجاح.")
            else:
                self.log(f"[*] [{self.session_id}] تم استرجاع البيانات المحفوظة.")


    def save_session_data(self):
        self._save_data_internal(show_msg=True)

    def _save_data_internal(self, show_msg=True):
        all_data = load_all_data()
        all_data[self.session_id] = {
            "name": self.inp_name.text(),
            "plate": self.inp_plate.text(),
            "date": self.inp_date.text(),
            "transaction_id": self.cmb_transaction.currentData(),
            "xsrf_token": self.xsrf_token,
            "accurate_session": self.accurate_session,
            "remember_token_name": self.remember_token_name,
            "remember_token_value": self.remember_token_value,
            "user_agent": self.user_agent,
            "last_appointment_id": self.last_appointment_id,
            "http_proxy": self.inp_http_proxy.text().strip(),
            "socks_proxy": self.inp_socks_proxy.text().strip(),
            "proxy_enabled": self.chk_proxy_enabled.isChecked(),
            "thread_count": self.spn_threads.value()
        }
        save_all_data(all_data)
        self.log(f"[+] [{self.session_id}] تم حفظ بيانات الجلسة والتوكن بنجاح.")
        if show_msg:
            QMessageBox.information(self, "نجاح", "تم حفظ بيانات الإدخال والتوكن لهذه الجلسة.")

    def log(self, msg):
        self._log_signal.emit(msg)

    def _update_browser_btn(self, text, enabled):
        self.btn_browser.setText(text)
        self.btn_browser.setEnabled(enabled)

    def _update_renew_btn(self, enabled):
        self.btn_renew.setEnabled(enabled)
        if enabled:
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
        self.log(f"[*] [{self.session_id}] ننتظر دورنا في طابور المتصفحات...")
        threading.Thread(target=self._browser_thread, daemon=True).start()

    def _browser_thread(self):
        try:
            profile_dir = os.path.join(os.getcwd(), "Profiles", f"Profile_{self.session_id}")
            os.makedirs(profile_dir, exist_ok=True)

            with GLOBAL_BROWSER_LOCK:
                self.log(f"[*] [{self.session_id}] جاري تهيئة المتصفح الآن...")

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if sys.platform == 'win32':
                            try:
                                safe_id = self.session_id.replace("'", "")
                                kill_cmd = (f'wmic process where "name=\'chrome.exe\' and '
                                           f'commandline like \'%Profile_{safe_id}%\'" call terminate')
                                subprocess.run(kill_cmd, shell=True, capture_output=True)
                                time.sleep(0.5)
                            except Exception:
                                pass

                        for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                            lock_path = os.path.join(profile_dir, lock_name)
                            if os.path.exists(lock_path):
                                try:
                                    os.remove(lock_path)
                                except:
                                    pass

                        options = uc.ChromeOptions()
                        options.add_argument('--no-sandbox')
                        options.add_argument('--disable-dev-shm-usage')
                        options.add_argument('--disable-extensions')
                        options.add_argument('--disable-gpu')

                        def get_free_port():
                            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                                s.bind(('127.0.0.1', 0))
                                return s.getsockname()[1]

                        free_port = get_free_port()
                        chrome_main_version = get_chrome_main_version()

                        self.driver = uc.Chrome(
                            user_data_dir=profile_dir,
                            options=options,
                            use_subprocess=True,
                            port=free_port,
                            version_main=chrome_main_version
                        )
                        break
                    except Exception as inner_e:
                        if attempt < max_retries - 1:
                            err_msg = str(inner_e).splitlines()[0] if str(inner_e) else "خطأ غير معروف"
                            self.log(f"[*] [{self.session_id}] فشل (المحاولة {attempt + 1}): {err_msg}")
                            time.sleep(2)
                        else:
                            raise inner_e


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

            self.log(f"[+] [{self.session_id}] تم فتح المتصفح على صفحة المواعيد مباشرة.")
            self._ui_browser_btn_signal.emit("🌐 المتصفح مفتوح حالياً", False)
            self.update_status("المتصفح قيد التشغيل", "#e3b341")

        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ نهائي في المتصفح: {e}")
            self._ui_browser_btn_signal.emit("🌐 فتح المتصفح", True)


    def extract_tokens(self):
        with self.driver_lock:
            if not self.driver:
                QMessageBox.warning(self, "خطأ", "افتح المتصفح أولاً!")
                return
            try:
                self.user_agent = self.driver.execute_script("return navigator.userAgent;")

                page_date = self.driver.execute_script("""
                    if (window.sarmadaSelectedDate) {
                        return window.sarmadaSelectedDate;
                    }
                    let match = document.body.innerText.match(/20\\d{2}-\\d{2}-\\d{2}/);
                    return match ? match[0] : '';
                """)

                if page_date:
                    self.inp_date.setText(page_date)
                    self.log(f"[*] [{self.session_id}] تم التقاط التاريخ: {page_date}")
                else:
                    self.log(f"[-] [{self.session_id}] لم يتم التقاط التاريخ.")

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
                    self.log(f"[+] [{self.session_id}] تم سحب الجلسة بالكامل بنجاح.")
                    self.update_status("مستعد للعمل ✔️", "#238636")
                    self._save_data_internal(show_msg=False)
                else:
                    self.log(f"[-] [{self.session_id}] لم أجد التوكن. هل قمت بتسجيل الدخول؟")
            except Exception as e:
                self.log(f"[!] [{self.session_id}] خطأ استخراج: {e}")

    def close_browser(self):
        with self.driver_lock:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as e:
                    self.log(f"[!] [{self.session_id}] تحذير أثناء الإغلاق: {e}")
                finally:
                    self.driver = None
                    self.log(f"[*] [{self.session_id}] تم إغلاق المتصفح.")
                    self._ui_browser_btn_signal.emit("🌐 فتح المتصفح", True)
                    self.update_status("المتصفح مغلق (التوكن محفوظ)", "#8b949e")


    def fill_browser(self, auto_submit=False):
        with self.driver_lock:
            if not self.driver:
                if not auto_submit:
                    QMessageBox.warning(self, "خطأ", "افتح المتصفح أولاً!")
                return

        name = self.inp_name.text()
        plate = self.inp_plate.text()
        threading.Thread(target=self._selenium_keyboard_fill, args=(auto_submit, name, plate),
                         daemon=True).start()

    def _selenium_keyboard_fill(self, auto_submit, name, plate):
        try:
            self.log(f"[*] [{self.session_id}] جاري محاكاة الكتابة البشرية...")

            with self.driver_lock:
                if not self.driver:
                    return
                inputs = self.driver.find_elements(By.TAG_NAME, 'input')

            visible_text_inputs = []
            for inp in inputs:
                if inp.is_displayed() and inp.is_enabled():
                    input_type = inp.get_attribute('type')
                    if input_type in ['text', 'number', 'tel', '']:
                        visible_text_inputs.append(inp)

            if len(visible_text_inputs) >= 2:
                values_to_fill = [name, plate]
                with self.driver_lock:
                    if not self.driver:
                        return
                    for i in range(2):
                        field = visible_text_inputs[i]
                        field.send_keys(Keys.CONTROL + "a")
                        field.send_keys(Keys.DELETE)
                        time.sleep(0.1)
                        field.send_keys(values_to_fill[i])
                        time.sleep(0.1)

                self.log(f"[+] [{self.session_id}] تم تعبئة البيانات بنجاح.")

                if auto_submit:
                    time.sleep(0.5)
                    with self.driver_lock:
                        if not self.driver:
                            return
                        buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                        for btn in buttons:
                            if btn.is_displayed() and ("حجز" in btn.text or "تأكيد" in btn.text):
                                btn.click()
                                self.log(f"[+] [{self.session_id}] تم الضغط على زر الحجز.")
                                break
            else:
                self.log(f"[-] [{self.session_id}] لم يتم العثور على مربعي نص ظاهرين.")

        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ أثناء محاكاة الكيبورد: {e}")


    def renew_session(self):
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", "لا يوجد توكن لتجديده.")
            return

        self.btn_renew.setEnabled(False)
        self.btn_renew.setText("⏳ جاري التجديد...")
        self.log(f"[*] [{self.session_id}] جاري إرسال طلب تجديد الجلسة...")
        threading.Thread(target=self._renew_thread, daemon=True).start()

    def _renew_thread(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(self._async_renew())
            loop.close()

            if success:
                self.log(f"[+] [{self.session_id}] تم تجديد الجلسة بنجاح ♻️.")
                self.update_status("مستعد (تم التجديد) ✔️", "#2ea043")
            else:
                self.log(f"[-] [{self.session_id}] فشل تجديد الجلسة.")
        except Exception as e:
            self.log(f"[!] [{self.session_id}] خطأ أثناء التجديد: {e}")
        finally:
            self._ui_renew_btn_signal.emit(True)

    async def _async_renew(self):
        cookies = {
            "XSRF-TOKEN": self.xsrf_token,
            "accurate_session": self.accurate_session
        }
        if self.remember_token_name and self.remember_token_value:
            cookies[self.remember_token_name] = self.remember_token_value

        headers = {
            "User-Agent": self.user_agent if self.user_agent else
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Ch-Ua": '"Not-A.Brand";v="24", "Chromium";v="147"',
            "Sec-Ch-Ua-Platform": '"Windows"',
        }

        proxy_config = self.get_proxy_config()
        proxy_arg = None
        if proxy_config:
            proxy_arg = proxy_config.get("http") or proxy_config.get("https")

        async with AsyncSession(verify=False, proxy=proxy_arg) as session:
            response = await session.get(
                "https://accurate.mot.gov.sy/",
                cookies=cookies,
                headers=headers,
                impersonate="chrome110",
                timeout=20
            )

            if response.status_code == 200:
                updated = False
                new_xsrf = session.cookies.get("XSRF-TOKEN")
                new_acc = session.cookies.get("accurate_session")

                if new_xsrf and new_xsrf != self.xsrf_token:
                    self.xsrf_token = urllib.parse.unquote(new_xsrf)
                    updated = True
                if new_acc and new_acc != self.accurate_session:
                    self.accurate_session = new_acc
                    updated = True

                if updated:
                    self.log(f"[*] [{self.session_id}] تم تحديث الكوكيز بنجاح.")
                    self._save_data_internal(show_msg=False)
                return True
            return False


    def start_request(self, mode):
        """إطلاق عدة خيوط بالتوازي - كل ضغطة تضيف خيوطاً جديدة"""
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", f"الرجاء سحب توكن الجلسة {self.session_id} أولاً!")
            return

        date_val = self.inp_date.text().strip()
        plate_val = self.inp_plate.text().strip()

        if not date_val:
            QMessageBox.warning(self, "تنبيه", "يجب تحديد التاريخ أولاً!")
            return

        payload = {
            "province_id": "804e7642-6798-4353-a556-f11d9aad2637",
            "name": self.inp_name.text().strip(),
            "plate_number": plate_val,
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
            "User-Agent": self.user_agent if self.user_agent else
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36"
        }
        cookies = {"XSRF-TOKEN": self.xsrf_token, "accurate_session": self.accurate_session}

        proxy_config = self.get_proxy_config()
        thread_count = self.spn_threads.value()

        self.btn_stop.setEnabled(True)
        self.inp_payment.clear()

        if mode == "single":
            self.btn_single.setText(f"⏳ إرسال ({thread_count} خيط)...")
            self.btn_single.setStyleSheet(self.active_single_style)
            self.update_status(f"إرسال فردي ({thread_count} خيط)...", "#e3b341")
        else:
            self.btn_snipe.setText(f"⏳ قنص ({thread_count} خيط)...")
            self.btn_snipe.setStyleSheet(self.active_snipe_style)
            self.update_status(f"قنص مستمر ({thread_count} خيط)...", "#e3b341")

        # إطلاق عدة خيوط بالتوازي
        base_id = len(self.workers)
        for i in range(thread_count):
            tid = base_id + i
            worker = RequestWorker(
                self.session_id, payload, headers, cookies, mode,
                thread_id=tid, proxy_config=proxy_config
            )
            worker.log_signal.connect(self.log)
            worker.success_signal.connect(self.on_success)
            worker.error_signal.connect(self.on_error)
            worker.finished_signal.connect(self.on_thread_finished)
            worker.response_signal.connect(self.on_response_received)
            self.workers.append(worker)
            worker.start()

        self._update_threads_label()
        self.log(f"[*] [{self.session_id}] تم إطلاق {thread_count} خيط بالتوازي (المجموع: {len(self.workers)})")


    def _update_threads_label(self):
        active = sum(1 for w in self.workers if w.isRunning())
        self.lbl_active_threads.setText(f"الخيوط النشطة: {active} / الإجمالي: {len(self.workers)}")

    def on_response_received(self, thread_id, status_code, body_snippet):
        """عرض ردود الخيوط في السجل"""
        color = "🟢" if status_code in [200, 201] else "🟡" if status_code == 422 else "🔴"
        self.log(f"{color} [{self.session_id}][T{thread_id}] رد: {status_code} | {body_snippet[:80]}")

    def on_thread_finished(self, thread_id):
        """عند انتهاء خيط واحد"""
        self._update_threads_label()

        # تحقق إذا كل الخيوط انتهت
        active = sum(1 for w in self.workers if w.isRunning())
        if active == 0:
            self.on_all_finished()

    def on_all_finished(self):
        """عند انتهاء كل الخيوط"""
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
        self.update_status("تم الإيقاف يدوياً", "#da3633")

    def on_success(self, code, fee, thread_id):
        self.inp_payment.setText(code)
        self.update_status(f"تم الحجز ({fee}) [T{thread_id}]", "#238636")
        self.payment_received.emit(code)
        self.log(f"[$$$] [{self.session_id}][T{thread_id}] الرمز: {code} | الرسوم: {fee}")

        # إيقاف باقي الخيوط عند النجاح
        for w in self.workers:
            w.stop()

        # حفظ معرف الحجز للاستعلام لاحقاً
        # نحاول استخراج appointment_id من الرد
        all_data = load_all_data()
        tg_config = all_data.get("TELEGRAM_CONFIG", {})
        tg_token = tg_config.get("token", "")
        tg_chat_id = tg_config.get("chat_id", "")

        if tg_token and tg_chat_id:
            msg = (f"✅ <b>تم الحجز بنجاح!</b>\n\n"
                   f"🚗 <b>الجلسة:</b> {self.session_id}\n"
                   f"👤 <b>الاسم:</b> {self.inp_name.text()}\n"
                   f"🔢 <b>اللوحة:</b> {self.inp_plate.text()}\n"
                   f"📅 <b>التاريخ:</b> {self.inp_date.text()}\n"
                   f"📑 <b>المعاملة:</b> {self.cmb_transaction.currentText()}\n"
                   f"💰 <b>الرسوم:</b> {fee} ل.س\n\n"
                   f"💳 <b>رمز الدفع:</b>\n<code>{code}</code>\n\n"
                   f"⏳ <i>لديك دقيقتان فقط للتسديد!</i>")
            threading.Thread(target=send_telegram_message, args=(tg_token, tg_chat_id, msg, 3),
                           daemon=True).start()

    def on_error(self, err):
        self.update_status("توقف (راجع السجل)", "#da3633")


    def check_payment_status(self):
        """استعلام عن حالة رمز الدفع"""
        if not self.xsrf_token:
            QMessageBox.warning(self, "تنبيه", "يجب سحب التوكن أولاً!")
            return

        # طلب معرف الحجز إذا لم يكن محفوظاً
        appointment_id = self.last_appointment_id
        if not appointment_id:
            appointment_id, ok = QInputDialog.getText(
                self, "معرف الحجز",
                "أدخل معرف الحجز (appointment_id):\n"
                "مثال: 1d886d32-0960-4e09-a822-0a461011b00b",
                text=""
            )
            if not ok or not appointment_id.strip():
                return
            appointment_id = appointment_id.strip()
            self.last_appointment_id = appointment_id
            self._save_data_internal(show_msg=False)

        headers = {
            "Host": "api.mot.gov.sy",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://accurate.mot.gov.sy",
            "Referer": "https://accurate.mot.gov.sy/",
            "X-Xsrf-Token": self.xsrf_token,
            "Accept-Language": "ar",
            "User-Agent": self.user_agent if self.user_agent else
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36"
        }
        cookies = {"XSRF-TOKEN": self.xsrf_token, "accurate_session": self.accurate_session}

        if self.remember_token_name and self.remember_token_value:
            cookies[self.remember_token_name] = self.remember_token_value

        proxy_config = self.get_proxy_config()

        self.btn_check_payment.setEnabled(False)
        self.btn_check_payment.setText("⏳ جاري الاستعلام...")

        self.payment_worker = PaymentStatusWorker(
            self.session_id, appointment_id, headers, cookies, proxy_config
        )
        self.payment_worker.log_signal.connect(self.log)
        self.payment_worker.result_signal.connect(self.on_payment_status_result)
        self.payment_worker.finished.connect(self._on_payment_check_done)
        self.payment_worker.start()

    def on_payment_status_result(self, data):
        """معالجة نتيجة استعلام الدفع"""
        if not data:
            return

        payment_data = data.get("data", {})
        status = payment_data.get("payment_status", "غير معروف")
        code = payment_data.get("payment_code", "")
        remaining = payment_data.get("payment_remaining_seconds", 0)
        fee = payment_data.get("fee_amount", "")
        slot_no = payment_data.get("slot_no", "")
        target_date = payment_data.get("target_date", "")
        start_at = payment_data.get("start_at", "")

        # تحديث الرمز إذا كان فارغاً
        if code and not self.inp_payment.text():
            self.inp_payment.setText(code)

        # عرض ملخص
        status_map = {"pending": "قيد الانتظار ⏳", "paid": "مدفوع ✅", "expired": "منتهي ❌"}
        status_text = status_map.get(status, status)

        info_msg = (f"📊 حالة الدفع: {status_text}\n"
                   f"💳 الرمز: {code}\n"
                   f"💰 المبلغ: {fee} ل.س\n"
                   f"📅 التاريخ: {target_date}\n"
                   f"🔢 الدور: {slot_no}\n"
                   f"⏰ الموعد: {start_at}\n"
                   f"⏳ الوقت المتبقي: {int(remaining)} ثانية")

        QMessageBox.information(self, "نتيجة استعلام الدفع", info_msg)

    def _on_payment_check_done(self):
        self.btn_check_payment.setEnabled(True)
        self.btn_check_payment.setText("🔍 استعلام الدفع")


    def copy_payment(self):
        code = self.inp_payment.text()
        if code:
            QApplication.clipboard().setText(code)
            self.log(f"[+] [{self.session_id}] تم نسخ الكود: {code}")

    def on_rename_clicked(self):
        with self.driver_lock:
            if self.driver:
                QMessageBox.warning(self, "تنبيه", "الرجاء إغلاق المتصفح أولاً قبل إعادة التسمية.")
                return

        new_name, ok = QInputDialog.getText(self, "إعادة تسمية الجلسة", "أدخل الاسم الجديد للجلسة:",
                                            text=self.session_id)
        if ok and new_name and new_name != self.session_id:
            self.rename_callback(self, self.session_id, new_name.strip())

    def on_hide_clicked(self):
        self.hide()
        self.log(f"[*] [{self.session_id}] تم إطفاء (إخفاء) الجلسة.")

    def on_delete_clicked(self):
        reply = QMessageBox.question(self, 'تأكيد الحذف النهائي',
                                     f"هل أنت متأكد من حذف الجلسة '{self.session_id}' نهائياً؟",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_callback(self)



class SarmadaPro(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alghanem Office - Sarmada Stealth Poller V17 (Multi-Thread + Proxy)")
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

        self.log_signal.connect(self._safe_print_log)

        saved_data = load_all_data()
        self.session_counter = 0

        self.setup_ui(saved_data)


    def setup_ui(self, saved_data):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- إعدادات التلجرام ---
        tg_group = QGroupBox("إعدادات إشعارات التلجرام (اختياري)")
        tg_layout = QHBoxLayout()

        self.inp_tg_token = QLineEdit()
        self.inp_tg_token.setPlaceholderText("Bot Token (e.g. 1234:ABC...)")
        self.inp_tg_token.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)

        self.inp_tg_chat_id = QLineEdit()
        self.inp_tg_chat_id.setPlaceholderText("Chat ID (e.g. 51234567)")

        tg_config = saved_data.get("TELEGRAM_CONFIG", {})
        if tg_config:
            self.inp_tg_token.setText(tg_config.get("token", ""))
            self.inp_tg_chat_id.setText(tg_config.get("chat_id", ""))

        btn_save_tg = QPushButton("💾 حفظ واختبار التلجرام")
        btn_save_tg.setStyleSheet("background-color: #1f6feb; color: white;")
        btn_save_tg.clicked.connect(self.save_and_test_telegram)

        tg_layout.addWidget(QLabel("توكن البوت:"))
        tg_layout.addWidget(self.inp_tg_token)
        tg_layout.addWidget(QLabel("معرف المحادثة:"))
        tg_layout.addWidget(self.inp_tg_chat_id)
        tg_layout.addWidget(btn_save_tg)
        tg_group.setLayout(tg_layout)
        main_layout.addWidget(tg_group)


        # --- شريط الأدوات العلوي ---
        top_bar = QHBoxLayout()
        btn_add = QPushButton("➕ إضافة جلسة")
        btn_add.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        btn_add.clicked.connect(self.add_session)

        btn_groups = QPushButton("👥 إدارة المجموعات")
        btn_groups.setStyleSheet("background-color: #d29922; color: white; font-weight: bold; font-size: 13px;")
        btn_groups.clicked.connect(self.open_group_actions_dialog)

        btn_renew_all = QPushButton("♻️ تجديد الكل")
        btn_renew_all.setStyleSheet("background-color: #2ea043; color: white; font-weight: bold;")
        btn_renew_all.clicked.connect(self.renew_all)

        btn_fill_all = QPushButton("✨ تعبئة وحجز للكل")
        btn_fill_all.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold;")
        btn_fill_all.clicked.connect(self.fill_and_book_all)

        btn_all_single = QPushButton("⚡ إرسال للكل")
        btn_all_single.clicked.connect(lambda: self.trigger_all("single"))

        btn_all_snipe = QPushButton("🚀 قنص للكل")
        btn_all_snipe.setStyleSheet("border-color: #1f6feb;")
        btn_all_snipe.clicked.connect(lambda: self.trigger_all("snipe"))

        btn_all_stop = QPushButton("🛑 إيقاف الكل")
        btn_all_stop.setStyleSheet("border-color: #da3633;")
        btn_all_stop.clicked.connect(self.stop_all)

        btn_hidden_sessions = QPushButton("👁️ الجلسات المطفأة")
        btn_hidden_sessions.setStyleSheet("background-color: #6e7681; color: white;")
        btn_hidden_sessions.clicked.connect(self.show_hidden_sessions)

        btn_logs = QPushButton("📋 السجلات")
        btn_logs.clicked.connect(self.log_window.show)

        top_bar.addWidget(btn_add)
        top_bar.addWidget(btn_groups)
        top_bar.addWidget(btn_renew_all)
        top_bar.addWidget(btn_fill_all)
        top_bar.addWidget(btn_all_single)
        top_bar.addWidget(btn_all_snipe)
        top_bar.addWidget(btn_all_stop)
        top_bar.addWidget(btn_hidden_sessions)
        top_bar.addWidget(btn_logs)
        main_layout.addLayout(top_bar)


        # --- منطقة الجلسات ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.sessions_container = QWidget()
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.sessions_container)
        main_layout.addWidget(self.scroll_area)

        # --- تحميل الجلسات المحفوظة ---
        profiles_dir = os.path.join(os.getcwd(), "Profiles")
        existing_sessions = []
        max_num = 0

        if os.path.exists(profiles_dir):
            for folder_name in os.listdir(profiles_dir):
                if folder_name.startswith("Profile_"):
                    s_id = folder_name.replace("Profile_", "")
                    existing_sessions.append((0, s_id))
                    if s_id.startswith("رقم_"):
                        try:
                            num = int(s_id.replace("رقم_", ""))
                            if num > max_num:
                                max_num = num
                        except ValueError:
                            pass

        self.session_counter = max_num

        if existing_sessions:
            for _, s_id in existing_sessions:
                self.create_session_card(s_id)
        else:
            self.add_session()


    def save_and_test_telegram(self):
        token = self.inp_tg_token.text().strip()
        chat_id = self.inp_tg_chat_id.text().strip()

        all_data = load_all_data()
        all_data["TELEGRAM_CONFIG"] = {"token": token, "chat_id": chat_id}
        save_all_data(all_data)

        if token and chat_id:
            test_msg = ("🤖 <b>رسالة اختبار من نظام سرمدا V17</b>\n\n"
                       "الربط يعمل بنجاح! سيتم إرسال رموز الدفع هنا.")
            threading.Thread(target=send_telegram_message, args=(token, chat_id, test_msg),
                           daemon=True).start()
            QMessageBox.information(self, "نجاح", "تم حفظ الإعدادات. تفقد التلجرام.")
        else:
            QMessageBox.warning(self, "تنبيه", "الرجاء إدخال التوكن ومعرف المحادثة.")

    def print_log(self, msg):
        self.log_signal.emit(msg)

    def _safe_print_log(self, msg):
        self.log_window.append_log(msg)
        print(msg)

    def create_session_card(self, session_id):
        card = SessionCard(session_id, self.print_log, self.handle_rename_session, self.handle_delete_session)
        self.sessions.append(card)
        self.sessions_layout.addWidget(card)
        self.print_log(f"[*] تم تحميل الجلسة: {session_id}")

    def add_session(self):
        self.session_counter += 1
        new_id = f"رقم_{self.session_counter}"
        self.create_session_card(new_id)

    def open_group_actions_dialog(self):
        dialog = GroupActionDialog(self, self)
        dialog.exec()

    def fill_and_book_all(self):
        self.print_log("[*] تعبئة البيانات والضغط على حجز في جميع المتصفحات المفتوحة.")
        for card in self.sessions:
            if not card.isHidden():
                if card.driver:
                    card.fill_browser(auto_submit=True)
                else:
                    self.print_log(f"[-] تم تخطي {card.session_id} لأن المتصفح مغلق.")

    def renew_all(self):
        self.print_log("[*] تجديد الجلسات لجميع البطاقات الفعالة.")
        for card in self.sessions:
            if not card.isHidden():
                if card.xsrf_token:
                    card.renew_session()
                else:
                    self.print_log(f"[-] تم تخطي {card.session_id} لعدم وجود توكن.")

    def trigger_all(self, mode):
        for card in self.sessions:
            if not card.isHidden():
                if card.xsrf_token:
                    card.start_request(mode)
                else:
                    self.print_log(f"[-] تم تخطي {card.session_id} لعدم وجود توكن مسحوب.")

    def stop_all(self):
        for card in self.sessions:
            card.stop_request()

    def show_hidden_sessions(self):
        dialog = HiddenSessionsDialog(self, self)
        dialog.exec()


    def handle_rename_session(self, card, old_id, new_id):
        if any(c.session_id == new_id for c in self.sessions):
            QMessageBox.warning(self, "خطأ", "هذا الاسم مستخدم لجلسة أخرى.")
            return

        profiles_dir = os.path.join(os.getcwd(), "Profiles")
        old_dir = os.path.join(profiles_dir, f"Profile_{old_id}")
        new_dir = os.path.join(profiles_dir, f"Profile_{new_id}")

        try:
            if os.path.exists(old_dir):
                os.rename(old_dir, new_dir)
        except Exception as e:
            QMessageBox.critical(self, "خطأ",
                                 f"فشل في تغيير اسم مجلد البروفايل.\n{e}")
            return

        all_data = load_all_data()
        if old_id in all_data:
            all_data[new_id] = all_data.pop(old_id)
            save_all_data(all_data)

        card.session_id = new_id
        card.setTitle(f"جلسة: {new_id}")
        self.print_log(f"[*] تم إعادة تسمية الجلسة من '{old_id}' إلى '{new_id}'.")

    def handle_delete_session(self, card):
        card.stop_request()
        card.close_browser()

        session_id = card.session_id

        all_data = load_all_data()
        if session_id in all_data:
            del all_data[session_id]
            save_all_data(all_data)

        profile_dir = os.path.join(os.getcwd(), "Profiles", f"Profile_{session_id}")
        if os.path.exists(profile_dir):
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception as e:
                self.print_log(f"[!] فشل حذف مجلد {session_id}: {e}")

        self.sessions.remove(card)
        card.setParent(None)
        card.deleteLater()
        self.print_log(f"[*] تم حذف الجلسة '{session_id}' نهائياً.")

    def closeEvent(self, event):
        self.print_log("[*] جاري إغلاق البرنامج بأمان...")
        self.stop_all()
        for card in self.sessions:
            if card.driver:
                card.close_browser()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SarmadaPro()
    window.show()
    sys.exit(app.exec())
