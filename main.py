"""
ICAI SSP E-Diary Auto-Filler - Mobile (Android)
================================================
Flow:
  1. Enter SSP username/password once, tap "Save Login" (encrypted local
     storage - no plaintext).
  2. Date is autofilled to today (editable). Pick Duration and Task from
     dropdowns.
  3. Tap "Submit". The app opens the real ICAI site, auto-fills your saved
     login, and waits for you to solve the CAPTCHA and tap Sign-in (no way
     around this part - CAPTCHAs exist specifically to require a human).
  4. Once logged in, it opens the E-Diary form and auto-fills Date,
     Duration, and Task.
  5. ICAI loads the Sub-Task checkboxes dynamically based on the Task you
     picked - there's no way to know those options ahead of time, so the
     app pulls the real list straight off the live page and shows it to
     you as a dropdown right then. Pick one.
  6. The app checks that sub-task box and fills "Other Task" if you gave
     one, then stops. It never taps Save - you review and tap it yourself.
"""

from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.metrics import dp

from secure_storage import SecureStorage

LOGIN_URL = "https://eservices.icai.org/"
EDIARY_URL = (
    "https://eservices.icai.org/EForms/loginAction.do"
    "?subAction=ViewLoginPage&formId=95906&orgId=1666"
)

TASK_OPTIONS = [
    "Assurance Services", "Risk, Tax & Regulatory", "Growth",
    "DigiTech/Information Technology", "Compliance and Outsourcing",
    "Taxation", "Accounting", "Auditing", "Direct Tax Laws",
    "Indirect Tax Laws", "Management consultancy and services",
    "Others", "Holiday", "Leave", "Weekoff", "No Task Allocated",
]
DURATION_OPTIONS = ["Full Day", "Half Day"]

DASHBOARD_POLL_INTERVAL = 2.0
DASHBOARD_TIMEOUT = 120
SUBTASK_POLL_INTERVAL = 1.0
SUBTASK_TIMEOUT = 20
REVIEW_WINDOW_SECONDS = 120


def show_popup(title: str, message: str):
    content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
    content.add_widget(Label(text=message))
    close_btn = Button(text="OK", size_hint=(1, None), height=dp(44))
    content.add_widget(close_btn)
    popup = Popup(title=title, content=content, size_hint=(0.85, 0.4))
    close_btn.bind(on_release=popup.dismiss)
    popup.open()


class EDiaryMobileApp(App):
    def build(self):
        self.title = "ICAI E-Diary Auto-Filler"
        self.storage = SecureStorage(self.user_data_dir)
        self.webview_wrapper = None
        self._dashboard_event = None
        self._subtask_event = None
        self._review_countdown_event = None

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        root.add_widget(self._build_login_section())
        root.add_widget(self._build_entry_section())
        root.add_widget(self._build_action_section())
        root.add_widget(self._build_log_section())

        self._prefill_saved_username()
        return root

    # ---------------------------------------------------------------- UI --
    def _build_login_section(self):
        box = BoxLayout(orientation="vertical", size_hint=(1, None), height=dp(150), spacing=dp(4))
        box.add_widget(Label(text="SSP Login (saved once)", size_hint=(1, None), height=dp(24), bold=True))

        row1 = BoxLayout(size_hint=(1, None), height=dp(40), spacing=dp(6))
        row1.add_widget(Label(text="Username", size_hint=(0.3, 1)))
        self.username_input = TextInput(multiline=False, size_hint=(0.7, 1))
        row1.add_widget(self.username_input)
        box.add_widget(row1)

        row2 = BoxLayout(size_hint=(1, None), height=dp(40), spacing=dp(6))
        row2.add_widget(Label(text="Password", size_hint=(0.3, 1)))
        self.password_input = TextInput(multiline=False, password=True, size_hint=(0.7, 1))
        row2.add_widget(self.password_input)
        box.add_widget(row2)

        save_btn = Button(text="Save Login", size_hint=(1, None), height=dp(40))
        save_btn.bind(on_release=lambda *_: self._save_credentials())
        box.add_widget(save_btn)
        return box

    def _build_entry_section(self):
        grid = GridLayout(cols=2, size_hint=(1, None), height=dp(190), spacing=dp(6), row_default_height=dp(40))

        grid.add_widget(Label(text="Date (auto-filled)"))
        self.date_input = TextInput(text=datetime.now().strftime("%d/%m/%Y"), multiline=False)
        grid.add_widget(self.date_input)

        grid.add_widget(Label(text="Duration"))
        self.duration_spinner = Spinner(text=DURATION_OPTIONS[0], values=DURATION_OPTIONS)
        grid.add_widget(self.duration_spinner)

        grid.add_widget(Label(text="Task"))
        self.task_spinner = Spinner(text=TASK_OPTIONS[0], values=TASK_OPTIONS)
        grid.add_widget(self.task_spinner)

        grid.add_widget(Label(text="Other Task (optional)"))
        self.other_task_input = TextInput(multiline=False)
        grid.add_widget(self.other_task_input)

        return grid

    def _build_action_section(self):
        box = BoxLayout(size_hint=(1, None), height=dp(50), spacing=dp(6))
        self.submit_button = Button(text="Submit (Login & Fill E-Diary)")
        self.submit_button.bind(on_release=lambda *_: self._start_automation())
        box.add_widget(self.submit_button)
        self.status_label = Label(text="Idle", size_hint=(0.4, 1))
        box.add_widget(self.status_label)
        return box

    def _build_log_section(self):
        scroll = ScrollView(size_hint=(1, 1))
        self.log_label = Label(text="", size_hint_y=None, halign="left", valign="top")
        self.log_label.bind(
            width=lambda inst, w: setattr(inst, "text_size", (w, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        scroll.add_widget(self.log_label)
        self._log_scroll = scroll
        return scroll

    # ----------------------------------------------------------- behaviour --
    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_label.text += f"[{timestamp}] {message}\n"
        self._log_scroll.scroll_y = 0

    def _prefill_saved_username(self):
        creds = self.storage.load_credentials()
        if creds:
            self.username_input.text = creds[0]
            self._log(f"Loaded saved username: {creds[0]}")

    def _save_credentials(self):
        username = self.username_input.text.strip()
        password = self.password_input.text
        if not username or not password:
            show_popup("Missing info", "Enter both a username and password first.")
            return
        self.storage.save_credentials(username, password)
        self.password_input.text = ""
        self._log(f"Login for '{username}' saved securely.")
        show_popup("Saved", "Login saved. You won't need to re-enter it.")

    def _validate_and_get_password(self):
        username = self.username_input.text.strip()
        if not username:
            return None, "Enter your username and tap Save Login first."
        creds = self.storage.load_credentials()
        if not creds or creds[0] != username or not creds[1]:
            return None, "No saved password for this username. Tap Save Login first."
        try:
            datetime.strptime(self.date_input.text.strip(), "%d/%m/%Y")
        except ValueError:
            return None, "Date must be in DD/MM/YYYY format."
        return creds[1], None

    # --------------------------------------------------------- automation --
    def _start_automation(self):
        password, error = self._validate_and_get_password()
        if error:
            show_popup("Cannot start", error)
            return

        try:
            from webview_bridge import ICAIWebView
        except ImportError:
            show_popup(
                "Android only",
                "This automation only runs inside the compiled Android APK "
                "(it needs pyjnius/python-for-android). Build it via the "
                "included GitHub Actions workflow and run it on a device.",
            )
            return

        self.submit_button.disabled = True
        self.status_label.text = "Logging in..."
        self._log("=" * 40)
        self._log("Submit tapped - starting automated run.")

        self.form_data = {
            "date": self.date_input.text.strip(),
            "duration": self.duration_spinner.text,
            "task": self.task_spinner.text,
            "other_task": self.other_task_input.text.strip(),
        }
        self._username = self.username_input.text.strip()
        self._password = password

        self.webview_wrapper = ICAIWebView(on_log=self._log, on_js_event=self._handle_js_event)
        self.webview_wrapper.show()
        self._log(f"Opening login page...")
        self.webview_wrapper.load_url(LOGIN_URL)
        Clock.schedule_once(lambda dt: self._inject_login_fill(), 3.0)

    def _inject_login_fill(self):
        from webview_bridge import build_login_script
        self._log("Auto-filling your saved username/password.")
        self._log("Please solve the CAPTCHA and tap Sign-in yourself.")
        self.webview_wrapper.eval_js(build_login_script(self._username, self._password))
        self._begin_dashboard_wait()

    def _begin_dashboard_wait(self):
        self._dashboard_elapsed = 0
        self.status_label.text = "Waiting for login..."
        self._log(f"Waiting up to {DASHBOARD_TIMEOUT}s for you to finish logging in...")

        def poll(dt):
            self._dashboard_elapsed += DASHBOARD_POLL_INTERVAL
            if self._dashboard_elapsed >= DASHBOARD_TIMEOUT:
                self._dashboard_event.cancel()
                self._log("ERROR: Timed out waiting for login. Aborting.")
                self._finish_run(success=False)
                return
            from webview_bridge import JS_CHECK_DASHBOARD
            self.webview_wrapper.eval_js(JS_CHECK_DASHBOARD)

        self._dashboard_event = Clock.schedule_interval(poll, DASHBOARD_POLL_INTERVAL)

    def _begin_subtask_wait(self):
        self._subtask_elapsed = 0

        def poll(dt):
            self._subtask_elapsed += SUBTASK_POLL_INTERVAL
            if self._subtask_elapsed >= SUBTASK_TIMEOUT:
                self._subtask_event.cancel()
                self._log("Sub-task list didn't appear in time - skipping sub-task.")
                self._finish_fields(subtask="")
                return
            from webview_bridge import JS_CHECK_SUBTASKS_READY
            self.webview_wrapper.eval_js(JS_CHECK_SUBTASKS_READY)

        self._subtask_event = Clock.schedule_interval(poll, SUBTASK_POLL_INTERVAL)

    def _request_subtask_options(self):
        from webview_bridge import JS_GET_SUBTASK_OPTIONS
        self.webview_wrapper.eval_js(JS_GET_SUBTASK_OPTIONS)

    def _finish_fields(self, subtask: str):
        from webview_bridge import build_finish_script
        self._log(f"Confirming sub-task: {subtask or '(none)'}")
        self.webview_wrapper.eval_js(build_finish_script(subtask, self.form_data["other_task"]))

    # ---------------------------------------------------------- JS events --
    def _handle_js_event(self, data: dict):
        Clock.schedule_once(lambda dt: self._process_js_event(data), 0)

    def _process_js_event(self, data: dict):
        event_type = data.get("type")

        if event_type == "log":
            self._log(data.get("text", ""))

        elif event_type == "error":
            self._log(f"JS ERROR: {data.get('text', '')}")

        elif event_type == "dashboard_check":
            if data.get("found"):
                self._dashboard_event.cancel()
                self._log("Login successful.")
                self.status_label.text = "Opening form..."
                self._log("Opening E-Diary form...")
                self.webview_wrapper.load_url(EDIARY_URL)
                Clock.schedule_once(lambda dt: self._inject_task_selection(), 3.0)

        elif event_type == "select_result":
            self._log(f"Date/Duration/Task filled: {data}")
            Clock.schedule_once(lambda dt: self._begin_subtask_wait(), 0.5)

        elif event_type == "subtasks_ready":
            if data.get("ready"):
                self._subtask_event.cancel()
                self._log("Sub-task options loaded - fetching them now.")
                self._request_subtask_options()

        elif event_type == "subtask_options":
            options = data.get("options") or []
            self.status_label.text = "Pick a sub-task"
            if not options:
                self._log("No sub-task options found for this Task - continuing without one.")
                self._finish_fields(subtask="")
            else:
                self._log(f"Found {len(options)} sub-task option(s).")
                self._show_subtask_picker(options)

        elif event_type == "finish_result":
            self._log(f"Final fill result: {data}")
            if data.get("subtask") is False:
                self._log("WARNING: Could not check the chosen sub-task - please check it manually.")
            self._begin_review_window()

    def _inject_task_selection(self):
        from webview_bridge import build_select_task_fields_script
        self._log(
            f"Filling date={self.form_data['date']}, duration={self.form_data['duration']}, "
            f"task={self.form_data['task']}"
        )
        self.webview_wrapper.eval_js(
            build_select_task_fields_script(
                self.form_data["date"], self.form_data["duration"], self.form_data["task"]
            )
        )

    def _show_subtask_picker(self, options):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text="Select the sub-task:", size_hint=(1, None), height=dp(30)))
        spinner = Spinner(text=options[0], values=options, size_hint=(1, None), height=dp(44))
        content.add_widget(spinner)
        confirm_btn = Button(text="Confirm", size_hint=(1, None), height=dp(44))
        content.add_widget(confirm_btn)

        popup = Popup(
            title="Sub-Task (from live page)",
            content=content,
            size_hint=(0.9, 0.5),
            auto_dismiss=False,
        )

        def on_confirm(*_):
            popup.dismiss()
            self._finish_fields(subtask=spinner.text)

        confirm_btn.bind(on_release=on_confirm)
        popup.open()

    def _begin_review_window(self):
        self._log(
            "Form filled! You have 2 minutes to review and tap Save "
            "yourself - this app will NOT tap Save automatically."
        )
        self.status_label.text = "Review & Save now"
        self._review_remaining = REVIEW_WINDOW_SECONDS

        def countdown(dt):
            self._review_remaining -= 1
            if self._review_remaining <= 0:
                self._review_countdown_event.cancel()
                self._log("Review window elapsed.")
                self._finish_run(success=True)
            elif self._review_remaining % 30 == 0:
                self._log(f"{self._review_remaining}s left in the review window...")

        self._review_countdown_event = Clock.schedule_interval(countdown, 1.0)

    def _finish_run(self, success: bool):
        if self.webview_wrapper:
            self.webview_wrapper.remove()
            self.webview_wrapper = None
        self.status_label.text = "Idle"
        self.submit_button.disabled = False
        self._log("Done." if success else "Run ended with an error.")


if __name__ == "__main__":
    EDiaryMobileApp().run()
