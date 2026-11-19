'''聚宝盆 APK 主入口 — 分区式管理界面 (v2)
顶部状态栏 / 服务控制区 / 功能导航区 / 快捷信息区 / 日志区
'''
import os, sys, threading, subprocess, time, json, socket

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

def find_cjk_font():
    for cand in ('/system/fonts/NotoSansCJK-Regular.ttc',
                 '/system/fonts/NotoSansSC-Regular.otf',
                 '/system/fonts/NotoSerifCJK-Regular.ttc',
                 '/system/fonts/NotoSansSC-Regular.ttf'):
        if os.path.exists(cand):
            return cand
    local = os.path.join(APP_DIR, 'font.ttf')
    return local if os.path.exists(local) else None

CJK_FONT = find_cjk_font()

def port_open(p, host='127.0.0.1'):
    try:
        s = socket.socket(); s.settimeout(1)
        s.connect((host, p)); s.close(); return True
    except Exception:
        return False

def http_get(path, port=6120, timeout=3):
    try:
        import urllib.request
        r = urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=timeout)
        return json.loads(r.read().decode())
    except Exception:
        return None

def start_services():
    py = sys.executable
    try:
        subprocess.Popen([py, os.path.join(APP_DIR, 'jubaopen.py'), 'serve'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_lines.append('[服务] 聚宝盆启动 (6210)')
    except Exception as e:
        log_lines.append(f'[服务] 启动失败: {e}')
    time.sleep(2)
    try:
        subprocess.Popen([py, os.path.join(APP_DIR, 'freepool.py')],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_lines.append('[网关] FreePool启动 (6120)')
    except Exception as e:
        log_lines.append(f'[网关] 启动失败: {e}')

# ---------- Kivy UI ----------
from kivy.config import Config
Config.set('graphics', 'width', '0')
Config.set('graphics', 'height', '0')
Config.set('graphics', 'resizable', '1')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import platform

if platform == 'android':
    from jnius import autoclass
    try:
        # 沉浸式全屏: 隐藏状态栏
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Windowfullscreen = autoclass('android.view.WindowManager$LayoutParams')
        activity = PythonActivity.mActivity
        activity.getWindow().getDecorView().setSystemUiVisibility(
            0x4 | 0x2 | 0x1000)  # IMMERSIVE_STICKY
    except Exception:
        pass

# 配色
C_BG      = (0.06, 0.07, 0.10, 1)
C_CARD    = (0.11, 0.12, 0.17, 1)
C_CARD2   = (0.14, 0.15, 0.21, 1)
C_PRIMARY = (0.42, 0.40, 0.95, 1)
C_GOOD    = (0.30, 0.75, 0.50, 1)
C_WARN    = (0.90, 0.62, 0.20, 1)
C_BAD     = (0.85, 0.30, 0.30, 1)
C_TXT     = (0.92, 0.93, 0.96, 1)
C_SUB     = (0.58, 0.62, 0.70, 1)
C_LOG     = (0.65, 0.72, 0.66, 1)

Window.background_color = C_BG
log_lines = []

def card_label(text, size=13, color=C_TXT, bold=False, halign='left'):
    l = Label(text=text, font_size=f'{size}sp', color=color, bold=bold,
              halign=halign, valign='middle', font_name=CJK_FONT or 'Roboto')
    l.bind(size=lambda i, s: setattr(i, 'text_size', (s[0], None)))
    return l

def card_button(text, bg, size=14, height=46):
    b = Button(text=text, background_normal='', background_color=bg,
               bold=True, font_size=f'{size}sp', size_hint=(1, None), height=dp(height),
               font_name=CJK_FONT or 'Roboto',
               color=(1, 1, 1, 1))
    return b

def section_title(text):
    """分区标题: 竖色条 + 文字, 简洁清晰"""
    row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(18), spacing=dp(6))
    bar = Widget(size_hint=(None, 1), width=dp(3))
    with bar.canvas:
        from kivy.graphics import Color, Rectangle
        Color(*C_PRIMARY)
        bar.rect = Rectangle(pos=bar.pos, size=bar.size)
    bar.bind(pos=lambda i, p: setattr(bar.rect, 'pos', p),
             size=lambda i, s: setattr(bar.rect, 'size', s))
    t = card_label(text, 12, C_SUB, bold=True)
    row.add_widget(bar); row.add_widget(t)
    return row

def bg_box(child, color=C_CARD, pad=8):
    """带底色的卡片容器"""
    box = BoxLayout(orientation='vertical', padding=dp(pad))
    with box.canvas.before:
        from kivy.graphics import Color, Rectangle
        Color(*color)
        box.bg_rect = Rectangle(pos=box.pos, size=box.size)
    box.bind(pos=lambda i, p: setattr(box.bg_rect, 'pos', p),
             size=lambda i, s: setattr(box.bg_rect, 'size', s))
    box.add_widget(child)
    return box

class JubaoApp(App):
    title = '聚宝盆'

    def build(self):
        root = BoxLayout(orientation='vertical', padding=dp(14), spacing=dp(10))

        # ── ① 顶部状态栏 (卡片) ──
        top = BoxLayout(orientation='vertical', spacing=dp(4))
        t1 = card_label('聚宝盆 JubaoPen', 20, C_TXT, bold=True)
        self.status = card_label('●  未启动 · 点击下方按钮开始', 12, C_SUB)
        top.add_widget(t1); top.add_widget(self.status)
        root.add_widget(bg_box(top, C_CARD, pad=10))

        # ── ② 服务控制 ──
        root.add_widget(section_title('服务控制'))
        self.btn_start = card_button('启动服务', C_PRIMARY, 15, 52)
        self.btn_start.bind(on_press=self.start)
        root.add_widget(self.btn_start)
        row = BoxLayout(spacing=dp(8), size_hint=(1, None), height=dp(40))
        self.btn_stop = card_button('停止', C_BAD, 13, 40)
        self.btn_refresh = card_button('刷新状态', C_CARD2, 13, 40)
        self.btn_stop.bind(on_press=self.stop_services)
        self.btn_refresh.bind(on_press=self.refresh_status)
        row.add_widget(self.btn_stop); row.add_widget(self.btn_refresh)
        root.add_widget(row)

        # ── ③ 功能入口 (2×2) ──
        root.add_widget(section_title('功能入口'))
        grid = GridLayout(cols=2, spacing=dp(8), size_hint=(1, None), height=dp(104))
        b_admin  = card_button('管理面板', C_CARD2, 14, 104)
        b_models = card_button('模型监控', C_CARD2, 14, 104)
        b_cfg    = card_button('配置查看', C_CARD2, 14, 104)
        b_help   = card_button('接入说明', C_CARD2, 14, 104)
        b_admin.bind(on_press=self.open_admin)
        b_models.bind(on_press=self.show_scores)
        b_cfg.bind(on_press=self.show_config)
        b_help.bind(on_press=self.show_help)
        for b in (b_admin, b_models, b_cfg, b_help):
            grid.add_widget(b)
        root.add_widget(grid)

        # ── ④ 接入信息 (卡片) ──
        root.add_widget(section_title('接入信息'))
        self.info = card_label(
            'BaseURL   http://127.0.0.1:6120/v1\n'
            'API Key    sk-freepool-fixed-2026\n'
            '管理 Key   sk-owner-me-2026\n'
            '模型名称  free-pool',
            11, C_GOOD)
        root.add_widget(bg_box(self.info, C_CARD, pad=10))

        # ── ⑤ 日志 (自适应剩余空间) ──
        root.add_widget(section_title('日志'))
        self.logview = ScrollView(size_hint=(1, 1))
        self.loglabel = card_label('等待操作…', 10, C_LOG)
        self.logview.add_widget(self.loglabel)
        root.add_widget(bg_box(self.logview, C_CARD, pad=8))

        # 启动时自动探测服务
        threading.Thread(target=self._auto_probe, daemon=True).start()
        return root

    # ---------- 行为 ----------
    def _auto_probe(self):
        time.sleep(1)
        if port_open(6120):
            Clock_schedule(self._set_running)

    def start(self, *a):
        if port_open(6120):
            self.set_log('服务已在运行')
            self._mark_running()
            return
        self.status.text = '状态: 启动中…'
        self.btn_start.background_color = C_WARN
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        start_services()
        for _ in range(30):
            if port_open(6210) and port_open(6120):
                break
            time.sleep(1)
        if port_open(6120):
            self.set_log('✅ 全部就绪! 网关 6120 / 聚宝盆 6210')
            Clock_schedule(self._set_running)
        else:
            self.set_log('❌ 启动超时, 请看日志')
            self.status.text = '状态: 启动失败'

    def _set_running(self, *a):
        self._mark_running()

    def _mark_running(self):
        self.status.text = '状态: ✅ 运行中 · 6120/6210'
        self.btn_start.background_color = C_GOOD
        self.btn_start.text = '✓ 服务运行中'
        self.set_log('资源监控已激活 (mem/cpu/thermal)')

    def stop_services(self, *a):
        try:
            subprocess.run(['pkill', '-f', 'freepool.py'], capture_output=True)
            subprocess.run(['pkill', '-f', 'jubaopen.py'], capture_output=True)
        except Exception as e:
            self.set_log(f'停止失败: {e}')
        self.status.text = '状态: 已停止'
        self.btn_start.text = '▶ 启动服务'
        self.btn_start.background_color = C_PRIMARY
        self.set_log('服务已停止')

    def refresh_status(self, *a):
        s = http_get('/scores')
        if s:
            r = s.get('resource', {})
            self.status.text = (f"状态: ✅ 运行中 · load={r.get('cpuLoad','?')} "
                                f"mem={r.get('memPct','?')}% therm={r.get('thermal','?')}")
            self.set_log(f"刷新: 上游{n}存活" if (n := len(s.get('upstreams', s.get('models', [])) or [])) else '刷新完成')
        else:
            self.status.text = '状态: ⛔ 未运行 (6120无响应)'
            self.set_log('刷新: 6120无响应, 服务未启动')

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

    def show_scores(self, *a):
        s = http_get('/scores')
        if not s:
            self.set_log('模型监控: 服务未运行'); return
        lines = ['── 模型监控 ──']
        r = s.get('resource', {})
        lines.append(f"资源: load={r.get('cpuLoad','?')} mem={r.get('memPct','?')}% "
                     f"therm={r.get('thermal','?')} 压力={r.get('load','?')}")
        models = s.get('models') or s.get('upstreams') or {}
        if isinstance(models, dict):
            for k, v in list(models.items())[:10]:
                lines.append(f'  {k}: {v}')
        self.set_log('\n'.join(lines[:12]))

    def show_config(self, *a):
        try:
            cfg = json.load(open(os.path.join(APP_DIR, 'config.json')))
            self.set_log('── 配置摘要 ──\n' + json.dumps(cfg, ensure_ascii=False, indent=1)[:400])
        except Exception as e:
            self.set_log(f'配置读取失败: {e}')

    def show_help(self, *a):
        self.set_log(
            '── 接入说明 ──\n'
            '第三方客户端添加自定义模型:\n'
            '  BaseURL: http://127.0.0.1:6120/v1\n'
            '  Key: sk-freepool-fixed-2026\n'
            '  模型名: free-pool\n'
            '本机管理Key: sk-owner-me-2026')

    def set_log(self, msg):
        log_lines.append(msg)
        self.loglabel.text = '日志:\n' + '\n'.join(log_lines[-20:])

def Clock_schedule(fn):
    try:
        from kivy.clock import Clock
        Clock.schedule_once(fn, 0)
    except Exception:
        pass

if __name__ == '__main__':
    JubaoApp().run()
