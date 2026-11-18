'''聚宝盆 APK 主入口 — Kivy界面 + 后台启动双服务'''
import os, sys, threading, subprocess, time, json, socket

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

def find_cjk_font():
    # Android系统自带CJK字体; p4a打包环境也能读/system/fonts
    for cand in ('/system/fonts/NotoSansCJK-Regular.ttc',
                 '/system/fonts/NotoSerifCJK-Regular.ttc',
                 '/system/fonts/NotoSansSC-Regular.otf',
                 '/system/fonts/NotoSansSC-Regular.ttf'):
        if os.path.exists(cand):
            return cand
    # app自带字体(可选)
    local = os.path.join(APP_DIR, 'font.ttf')
    return local if os.path.exists(local) else None

CJK_FONT = find_cjk_font()

def port_open(p, host='127.0.0.1'):
    try:
        s = socket.socket(); s.settimeout(1)
        s.connect((host, p)); s.close(); return True
    except Exception:
        return False

def start_services():
    py = sys.executable
    try:
        subprocess.Popen([py, os.path.join(APP_DIR, 'jubaopen.py'), 'serve'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_lines.append('聚宝盆服务已启动 (6210)')
    except Exception as e:
        log_lines.append(f'聚宝盆启动失败: {e}')
    time.sleep(2)
    try:
        subprocess.Popen([py, os.path.join(APP_DIR, 'freepool.py')],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_lines.append('FreePool网关已启动 (6120)')
    except Exception as e:
        log_lines.append(f'网关启动失败: {e}')

# ---------- Kivy UI ----------
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window

Window.size = (400, 700)
Window.background_color = (0.04, 0.04, 0.05, 1)

log_lines = []

class JubaoApp(App):
    def build(self):
        self.title = '聚宝盆'
        root = BoxLayout(orientation='vertical', padding=16, spacing=10)

        title = Label(text='聚宝盆 JubaoPen',
                      font_size='22sp', size_hint=(1, None), height=44,
                      color=(0.49, 0.42, 1, 1),
                      font_name=CJK_FONT or 'Roboto')
        root.add_widget(title)

        self.status = Label(text='状态: 未启动', font_size='14sp',
                            size_hint=(1, None), height=30, color=(0.6, 0.6, 0.65, 1),
                            font_name=CJK_FONT or 'Roboto')
        root.add_widget(self.status)

        btn = Button(text='启动服务', size_hint=(1, None), height=52,
                     background_normal='', background_color=(0.49, 0.42, 1, 1),
                     bold=True, font_size='16sp',
                     font_name=CJK_FONT or 'Roboto')
        btn.bind(on_press=self.start)
        root.add_widget(btn)

        btn2 = Button(text='打开驾驶舱 (管理面板)',
                      size_hint=(1, None), height=48,
                      background_normal='', background_color=(0.15, 0.15, 0.18, 1),
                      font_name=CJK_FONT or 'Roboto')
        btn2.bind(on_press=self.open_admin)
        root.add_widget(btn2)

        info = Label(text=(  'BaseURL: http://127.0.0.1:6120/v1\n'
                             'Key: sk-freepool-fixed-2026\n'
                             '本人Key: sk-owner-me-2026\n'
                             '模型: free-pool'),
                     font_size='12sp', size_hint=(1, None), height=90,
                     color=(0.5, 0.85, 0.55, 1), halign='left',
                     font_name=CJK_FONT or 'Roboto')
        info.bind(size=lambda i, s: setattr(i, 'text_size', (s[0], None)))
        root.add_widget(info)

        self.logview = ScrollView(size_hint=(1, 1))
        self.loglabel = Label(text='日志:\n', font_size='11sp',
                              color=(0.7, 0.7, 0.75, 1), halign='left', valign='top',
                              font_name=CJK_FONT or 'Roboto')
        self.loglabel.bind(size=lambda i, s: setattr(i, 'text_size', (s[0], None)))
        self.logview.add_widget(self.loglabel)
        root.add_widget(self.logview)
        return root

    def start(self, *a):
        if port_open(6120):
            self.set_log('服务已在运行')
            self.status.text = '状态: 运行中'
            return
        self.status.text = '状态: 启动中…'
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        start_services()
        for _ in range(30):
            if port_open(6210) and port_open(6120):
                break
            time.sleep(1)
        if port_open(6120):
            self.set_log('全部就绪! 网关 6120 / 聚宝盆 6210')
            self.status.text = '状态: 运行中'
        else:
            self.set_log('启动超时, 请查看日志')
            self.status.text = '状态: 启动失败'

    def open_admin(self, *a):
        if not port_open(6130):
            subprocess.Popen([sys.executable, '-m', 'http.server', '6130',
                              '--bind', '127.0.0.1', '--directory', APP_DIR],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        url = 'http://127.0.0.1:6130/admin.html'
        try:
            from jnius import autoclass
            Uri = autoclass('android.net.Uri')
            Intent = autoclass('android.content.Intent')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            activity.startActivity(intent)
            self.set_log('已调起浏览器打开驾驶舱')
        except Exception:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception as e:
                self.set_log(f'请手动打开: {url} ({e})')

    def set_log(self, msg):
        log_lines.append(msg)
        self.loglabel.text = '日志:\n' + '\n'.join(log_lines[-12:])

if __name__ == '__main__':
    JubaoApp().run()
