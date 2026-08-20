"""
webview_bridge.py
==================
Native Android WebView wrapper (via pyjnius) + JS injection helpers.
Replaces Playwright on Android, since Playwright cannot run on mobile.

Flow used by main.py:
  1. build_login_script()             -> autofill username/password
  2. JS_CHECK_DASHBOARD (polled)      -> detect successful manual login
  3. build_select_task_fields_script  -> fill date, duration, task
  4. JS_CHECK_SUBTASKS_READY (polled) -> wait for dynamic subtask checkboxes
  5. JS_GET_SUBTASK_OPTIONS           -> pull the REAL subtask labels from
                                          the live page (can't know them in
                                          advance - ICAI loads them per task)
  6. build_finish_script()            -> check the chosen subtask, fill
                                          "other task", done
"""

import json

from jnius import autoclass, PythonJavaClass, java_method
from android.runnable import run_on_ui_thread

WebView = autoclass("android.webkit.WebView")
WebViewClient = autoclass("android.webkit.WebViewClient")
LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
PythonActivity = autoclass("org.kivy.android.PythonActivity")


class _JSBridge(PythonJavaClass):
    __javainterfaces__ = ["android/webkit/JavascriptInterface"]
    __javacontext__ = "app"

    def __init__(self, on_message):
        super().__init__()
        self._on_message = on_message

    @java_method("(Ljava/lang/String;)V")
    def postMessage(self, message):
        self._on_message(message)


class ICAIWebView:
    def __init__(self, on_log, on_js_event):
        self.on_log = on_log
        self.on_js_event = on_js_event
        self.webview = None
        self._bridge = _JSBridge(self._handle_bridge_message)
        self._create_webview()

    def _handle_bridge_message(self, raw_message: str):
        try:
            data = json.loads(raw_message)
        except (ValueError, TypeError):
            data = {"type": "log", "text": raw_message}
        self.on_js_event(data)

    @run_on_ui_thread
    def _create_webview(self):
        activity = PythonActivity.mActivity
        self.webview = WebView(activity)

        settings = self.webview.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setJavaScriptCanOpenWindowsAutomatically(True)

        self.webview.addJavascriptInterface(self._bridge, "AndroidBridge")
        self.webview.setWebViewClient(WebViewClient())

        layout_params = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
        self.webview.setLayoutParams(layout_params)
        activity.addContentView(self.webview, layout_params)
        self.on_log("Native Android WebView created and attached.")

    @run_on_ui_thread
    def show(self):
        if self.webview:
            self.webview.setVisibility(0)

    @run_on_ui_thread
    def hide(self):
        if self.webview:
            self.webview.setVisibility(8)

    @run_on_ui_thread
    def load_url(self, url: str):
        if self.webview:
            self.webview.loadUrl(url)

    @run_on_ui_thread
    def eval_js(self, script: str):
        if self.webview:
            self.webview.evaluateJavascript(script, None)

    @run_on_ui_thread
    def remove(self):
        if self.webview:
            activity = PythonActivity.mActivity
            try:
                activity.getWindow().getDecorView().findViewById(16908290).removeView(self.webview)
            except Exception:
                pass
            self.webview = None


# --------------------------------------------------------------------------- #
# JS snippets
# --------------------------------------------------------------------------- #

JS_FILL_LOGIN = """
(function() {
    try {
        var u = document.querySelector('#userId');
        var p = document.querySelector('#password');
        if (!u || !p) {
            AndroidBridge.postMessage(JSON.stringify({type:'error', text:'Login fields not found yet.'}));
            return;
        }
        u.value = %(username)s;
        p.value = %(password)s;
        u.dispatchEvent(new Event('input', {bubbles:true}));
        p.dispatchEvent(new Event('input', {bubbles:true}));
        AndroidBridge.postMessage(JSON.stringify({type:'log', text:'Login fields filled automatically.'}));
    } catch (e) {
        AndroidBridge.postMessage(JSON.stringify({type:'error', text:String(e)}));
    }
})();
"""

JS_CHECK_DASHBOARD = """
(function() {
    var found = !!document.querySelector('.dashboard-welcome-message');
    AndroidBridge.postMessage(JSON.stringify({type:'dashboard_check', found: found}));
})();
"""

JS_SELECT_TASK_FIELDS = """
(function() {
    function setSelectByText(selector, text) {
        var select = document.querySelector(selector);
        if (!select) return false;
        for (var i = 0; i < select.options.length; i++) {
            if (select.options[i].text.trim() === text) {
                select.selectedIndex = i;
                select.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            }
        }
        return false;
    }

    var result = {type: 'select_result'};
    try {
        var dateField = document.querySelector('#taskDate');
        if (dateField) {
            dateField.value = %(date)s;
            dateField.dispatchEvent(new Event('input', {bubbles:true}));
            dateField.dispatchEvent(new Event('change', {bubbles:true}));
            result.date = true;
        } else {
            result.date = false;
        }
        result.duration = setSelectByText('#taskDuration', %(duration)s);
        result.task = setSelectByText('#taskName', %(task)s);
        AndroidBridge.postMessage(JSON.stringify(result));
    } catch (e) {
        AndroidBridge.postMessage(JSON.stringify({type:'error', text:String(e)}));
    }
})();
"""

JS_CHECK_SUBTASKS_READY = """
(function() {
    var wrapper = document.querySelector('#subTaskList');
    var ready = !!(wrapper && wrapper.querySelectorAll('input[type=checkbox]').length > 0);
    AndroidBridge.postMessage(JSON.stringify({type:'subtasks_ready', ready: ready}));
})();
"""

JS_GET_SUBTASK_OPTIONS = """
(function() {
    var wrapper = document.querySelector('#subTaskList');
    var options = [];
    if (wrapper) {
        var labels = wrapper.querySelectorAll('label');
        for (var i = 0; i < labels.length; i++) {
            var t = labels[i].textContent.trim();
            if (t) options.push(t);
        }
    }
    AndroidBridge.postMessage(JSON.stringify({type:'subtask_options', options: options}));
})();
"""

JS_FINISH_FORM = """
(function() {
    function checkSubtaskByLabel(text) {
        var wrapper = document.querySelector('#subTaskList');
        if (!wrapper) return false;
        var labels = wrapper.querySelectorAll('label');
        for (var i = 0; i < labels.length; i++) {
            if (labels[i].textContent.trim() === text || labels[i].textContent.trim().indexOf(text) !== -1) {
                var forId = labels[i].getAttribute('for');
                var checkbox = forId ? document.getElementById(forId) : null;
                if (!checkbox) checkbox = labels[i].querySelector('input[type=checkbox]');
                if (!checkbox && labels[i].parentElement) {
                    checkbox = labels[i].parentElement.querySelector('input[type=checkbox]');
                }
                if (checkbox) {
                    checkbox.checked = true;
                    checkbox.dispatchEvent(new Event('change', {bubbles:true}));
                    return true;
                }
            }
        }
        return false;
    }

    var result = {type: 'finish_result'};
    try {
        var subtaskText = %(subtask)s;
        result.subtask = subtaskText ? checkSubtaskByLabel(subtaskText) : null;

        var otherText = %(other_task)s;
        if (otherText) {
            var otherField = document.querySelector('#other_task');
            if (otherField) {
                otherField.value = otherText;
                otherField.dispatchEvent(new Event('input', {bubbles:true}));
                result.other_task = true;
            } else {
                result.other_task = false;
            }
        } else {
            result.other_task = null;
        }
        AndroidBridge.postMessage(JSON.stringify(result));
    } catch (e) {
        AndroidBridge.postMessage(JSON.stringify({type:'error', text:String(e)}));
    }
})();
"""


def _js_str(value: str) -> str:
    return json.dumps(value or "")


def build_login_script(username: str, password: str) -> str:
    return JS_FILL_LOGIN % {"username": _js_str(username), "password": _js_str(password)}


def build_select_task_fields_script(date: str, duration: str, task: str) -> str:
    return JS_SELECT_TASK_FIELDS % {
        "date": _js_str(date),
        "duration": _js_str(duration),
        "task": _js_str(task),
    }


def build_finish_script(subtask: str, other_task: str) -> str:
    return JS_FINISH_FORM % {"subtask": _js_str(subtask), "other_task": _js_str(other_task)}
