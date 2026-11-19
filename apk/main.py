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
from kivy.uix.stacklayout import StackLayout
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

    def _tab_btn(self, text, idx):
        b = Button(text=text, background_normal='', background_color=C_CARD2,
                   bold=True, font_size='13sp', font_name=CJK_FONT or 'Roboto',
                   color=C_SUB, size_hint=(1, None), height=dp(40))
        b.bind(on_press=lambda *a: self.switch_tab(idx))
        return b

    def switch_tab(self, idx):
        self.tab_idx = idx
        for i, page in enumerate(self.pages):
            page.height = dp(0) if i != idx else None
            page.size_hint_y = 1 if i == idx else None
            page.opacity = 1 if i == idx else 0
        # tab高亮
        for i, btn in enumerate(self.tabbtns):
            btn.background_color = C_PRIMARY if i == idx else C_CARD2
            btn.color = (1, 1, 1, 1) if i == idx else C_SUB

    def build(self):
        self.tab_idx = 0
        root = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(8))

        # ── 顶部标题栏 ──
        top = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(46))
        t1 = card_label('聚宝盆控制台', 17, C_TXT, bold=True)
        self.status = card_label('● 未启动', 12, C_SUB, halign='right')
        top.add_widget(t1); top.add_widget(self.status)
        root.add_widget(top)

        # ── Tab栏 ──
        tabbar = BoxLayout(spacing=dp(4), size_hint=(1, None), height=dp(40))
        self.tabbtns = [self._tab_btn(t, i) for i, t in enumerate(
            ['服务', '监控', '配置', '日志'])]
        for b in self.tabbtns:
            tabbar.add_widget(b)
        root.add_widget(tabbar)

        # ── 页面容器 ──
        from kivy.uix.floatlayout import FloatLayout
        holder = FloatLayout(size_hint=(1, 1))
        self.pages = [self._page_service(), self._page_monitor(),
                      self._page_config(), self._page_logs()]
        for p in self.pages:
            holder.add_widget(p)
        root.add_widget(holder)

        self.switch_tab(0)
        threading.Thread(target=self._auto_probe, daemon=True).start()
        return root

    def _card_bg(self, w, color=C_CARD):
        with w.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*color)
            w.bg_rect = Rectangle(pos=w.pos, size=w.size)
        w.bind(pos=lambda i, p: setattr(w.bg_rect, 'pos', p),
               size=lambda i, s: setattr(w.bg_rect, 'size', s))
        return w

    # ---- 页1: 服务 ----
    def _page_service(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(10), pos_hint={'x': 0, 'y': 0})
        head = BoxLayout(orientation='vertical', spacing=dp(4),
                         padding=dp(10), size_hint=(1, None), height=dp(70))
        self._card_bg(head)
        head.add_widget(card_label('服务状态', 13, C_TXT, bold=True))
        self.status_detail = card_label('网关(6120) 未运行 · 聚宝盆(6210) 未运行', 11, C_SUB)
        head.add_widget(self.status_detail)
        pg.add_widget(head)

        self.btn_start = card_button('启动全部服务', C_PRIMARY, 15, 54)
        self.btn_start.bind(on_press=self.start)
        pg.add_widget(self.btn_start)
        row = BoxLayout(spacing=dp(8), size_hint=(1, None), height=dp(44))
        self.btn_stop = card_button('停止服务', C_BAD, 13, 44)
        self.btn_refresh = card_button('刷新状态', C_CARD2, 13, 44)
        self.btn_stop.bind(on_press=self.stop_services)
        self.btn_refresh.bind(on_press=self.refresh_status)
        row.add_widget(self.btn_stop); row.add_widget(self.btn_refresh)
        pg.add_widget(row)

        # 接入信息卡
        pg.add_widget(section_title('接入信息'))
        self.info = card_label(
            'BaseURL   http://127.0.0.1:6120/v1\n'
            'API Key    sk-freepool-fixed-2026\n'
            '管理 Key   sk-owner-me-2026\n'
            '模型名称  free-pool',
            11, C_GOOD)
        icard = BoxLayout(orientation='vertical', padding=dp(10))
        self._card_bg(icard)
        icard.add_widget(self.info)
        pg.add_widget(icard)
        pg.add_widget(Widget())
        return pg

    # ---- 页2: 监控 ----
    def _page_monitor(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(10))
        bar = card_label('资源与上游 (实时)', 13, C_TXT, bold=True)
        bar.size_hint = (1, None); bar.height = dp(22)
        pg.add_widget(bar)
        self.mon_res = card_label('点「刷新监控」获取最新数据', 11, C_SUB)
        mcard = BoxLayout(orientation='vertical', padding=dp(10), size_hint=(1, None), height=dp(64))
        self._card_bg(mcard)
        mcard.add_widget(self.mon_res)
        pg.add_widget(mcard)

        self.mon_models = card_label('上游模型: —', 11, C_LOG)
        sc = ScrollView(size_hint=(1, 1))
        mcard2 = BoxLayout(orientation='vertical', padding=dp(10))
        self._card_bg(mcard2)
        mcard2.add_widget(self.mon_models)
        sc.add_widget(mcard2)
        pg.add_widget(sc)

        btn = card_button('刷新监控', C_PRIMARY, 14, 46)
        btn.bind(on_press=self.show_scores)
        pg.add_widget(btn)
        return pg

    # ---- 页3: 配置 ----
    def _page_config(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(10))
        bar = card_label('配置与说明', 13, C_TXT, bold=True)
        bar.size_hint = (1, None); bar.height = dp(22)
        pg.add_widget(bar)
        self.cfg_view = card_label('点下方按钮查看', 11, C_SUB)
        sc = ScrollView(size_hint=(1, 1))
        ccard = BoxLayout(orientation='vertical', padding=dp(10))
        self._card_bg(ccard)
        ccard.add_widget(self.cfg_view)
        sc.add_widget(ccard)
        pg.add_widget(sc)
        row = BoxLayout(spacing=dp(8), size_hint=(1, None), height=dp(46))
        b1 = card_button('查看配置', C_PRIMARY, 13, 46)
        b2 = card_button('接入说明', C_CARD2, 13, 46)
        b1.bind(on_press=self.show_config)
        b2.bind(on_press=self.show_help)
        row.add_widget(b1); row.add_widget(b2)
        pg.add_widget(row)

        b_admin = card_button('打开管理面板 (浏览器)', C_CARD2, 13, 46)
        b_admin.bind(on_press=self.open_admin)
        pg.add_widget(b_admin)
        return pg

    # ---- 页4: 日志 ----
    def _page_logs(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(8))
        self.logview = ScrollView(size_hint=(1, 1))
        lcard = BoxLayout(orientation='vertical', padding=dp(10))
        self._card_bg(lcard)
        self.loglabel = card_label('等待操作…', 10, C_LOG)
        lcard.add_widget(self.loglabel)
        self.logview.add_widget(lcard)
        pg.add_widget(self.logview)
        clr = card_button('清空日志', C_CARD2, 12, 40)
        clr.bind(on_press=self.clear_log)
        pg.add_widget(clr)
        return pg

    def clear_log(self, *a):
        log_lines.clear()
        self.loglabel.text = '日志已清空'

    # ---------- 行为 ----------
    def _auto_probe(self):
        time.sleep(1)
        if port_open(6120):
            Clock_schedule(self._set_running)
            Clock_schedule(lambda *a: self.show_scores())

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
        self.status.text = '● 运行中'
        if hasattr(self, 'status_detail'):
            self.status_detail.text = '网关(6120) ✅ · 聚宝盆(6210) ✅ · 资源监控激活'
        self.btn_start.background_color = C_GOOD
        self.btn_start.text = '✓ 服务运行中'
        self.set_log('资源监控已激活 (mem/cpu/thermal)')

    def stop_services(self, *a):
        try:
            subprocess.run(['pkill', '-f', 'freepool.py'], capture_output=True)
            subprocess.run(['pkill', '-f', 'jubaopen.py'], capture_output=True)
        except Exception as e:
            self.set_log(f'停止失败: {e}')
        self.status.text = '● 已停止'
        if hasattr(self, 'status_detail'):
            self.status_detail.text = '网关(6120) 未运行 · 聚宝盆(6210) 未运行'
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
            self.set_log('模型监控: 服务未运行')
            self.mon_res.text = '⛔ 服务未运行'
            return
        r = s.get('resource', {})
        self.mon_res.text = (f"负载 {r.get('cpuLoad','?')} · 内存 {r.get('memPct','?')}% · "
                             f"温度 {r.get('thermal','?')} · 压力 {r.get('load','?')}")
        lines = ['── 上游模型 ──']
        models = s.get('models') or s.get('upstreams') or {}
        if isinstance(models, dict):
            for k, v in list(models.items())[:14]:
                lines.append(f'  {k}: {v}')
        self.mon_models.text = '\n'.join(lines) or '无数据'
        self.switch_tab(1)
        self.set_log('监控已刷新')

    def show_config(self, *a):
        try:
            cfg = json.load(open(os.path.join(APP_DIR, 'config.json')))
            self.cfg_view.text = json.dumps(cfg, ensure_ascii=False, indent=1)[:800]
            self.switch_tab(2)
            self.set_log('配置已加载')
        except Exception as e:
            self.set_log(f'配置读取失败: {e}')

    def show_help(self, *a):
        self.cfg_view.text = ('第三方客户端接入:\n\n'
            'BaseURL:  http://127.0.0.1:6120/v1\n'
            'API Key:   sk-freepool-fixed-2026\n'
            '模型名称: free-pool\n\n'
            '本机管理Key: sk-owner-me-2026\n\n'
            '安全: 限速120次/分, 10次鉴权失败自动拉黑600秒')
        self.switch_tab(2)

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
