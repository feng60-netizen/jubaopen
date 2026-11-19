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

# ---------- Kivy UI v5: 现代移动风格 (底部导航+圆角卡片+数据大字) ----------
from kivy.config import Config
Config.set('graphics', 'width', '0')
Config.set('graphics', 'height', '0')
Config.set('graphics', 'resizable', '1')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line
from kivy.utils import platform

if platform == 'android':
    try:
        from jnius import autoclass
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        activity.getWindow().getDecorView().setSystemUiVisibility(0x4 | 0x2 | 0x1000)
    except Exception:
        pass

# 深色主题
C_BG      = (0.055, 0.06, 0.085, 1)
C_CARD    = (0.115, 0.125, 0.165, 1)
C_CARD_HI = (0.16, 0.175, 0.23, 1)
C_PRIMARY = (0.40, 0.40, 0.95, 1)
C_GOOD    = (0.28, 0.72, 0.50, 1)
C_BAD     = (0.85, 0.32, 0.32, 1)
C_WARN    = (0.92, 0.65, 0.22, 1)
C_TXT     = (0.94, 0.95, 0.97, 1)
C_SUB     = (0.55, 0.59, 0.67, 1)
C_LOG     = (0.60, 0.70, 0.62, 1)
R = [dp(14)]

Window.background_color = C_BG
log_lines = []

def L(text, size=13, color=C_TXT, bold=False, halign='left'):
    l = Label(text=text, font_size=f'{size}sp', color=color, bold=bold,
              halign=halign, valign='middle', font_name=CJK_FONT or 'Roboto')
    l.bind(size=lambda i, s: setattr(i, 'text_size', (s[0], None)))
    return l

def rounded(w, color=C_CARD, radius=None, border=True):
    """圆角卡片底 + 1px高光描边(健壮版)"""
    rad = radius or R
    with w.canvas.before:
        Color(*color)
        RoundedRectangle(pos=w.pos, size=w.size, radius=rad)
    if border:
        line_obj = [None]
        def upd(i=None, s=None):
            geo = (w.x, w.y, w.width, w.height, *rad)
            if line_obj[0] is None:
                with w.canvas.before:
                    Color(1, 1, 1, 0.07)
                    line_obj[0] = Line(rounded_rectangle=geo, width=1)
            else:
                line_obj[0].rounded_rectangle = geo
        upd()
        w.bind(pos=upd, size=upd)
    return w

def card(children, pad=dp(14), color=C_CARD, radius=None):
    """圆角卡片容器"""
    box = BoxLayout(orientation='vertical', padding=pad)
    rounded(box, color, radius)
    for c in children:
        box.add_widget(c)
    return box

def pill_button(text, bg, size=14, height=48, color=(1,1,1,1)):
    b = Button(text=text, background_normal='', background_color=bg,
               bold=True, font_size=f'{size}sp', size_hint=(1, None), height=dp(height),
               font_name=CJK_FONT or 'Roboto', color=color)
    with b.canvas.before:
        Color(*bg)
        b.rr = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(height/2)])
    b.bind(pos=lambda i, p: setattr(b.rr, 'pos', p),
           size=lambda i, s: setattr(b.rr, 'size', s))
    b.background_color = (0, 0, 0, 0)
    return b

def stat_card(title, refs, accent=C_PRIMARY):
    """监控小卡: 标题小字 + 数值大字"""
    box = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(4))
    rounded(box, C_CARD)
    box.add_widget(L(title, 10, C_SUB))
    v = L('—', 20, accent, bold=True)
    box.add_widget(v)
    refs.append(v)
    return box

class JubaoApp(App):
    title = '聚宝盆'
    TABS = ['服务', '监控', '配置', '日志']

    def build(self):
        self.tab_idx = 0
        root = BoxLayout(orientation='vertical', padding=dp(16))

        # ═══ 内容区 (FloatLayout叠页) ═══
        self.holder = FloatLayout(size_hint=(1, 1))
        self.pages = [self._page_service(), self._page_monitor(),
                      self._page_config(), self._page_logs()]
        for p in self.pages:
            self.holder.add_widget(p)
        root.add_widget(self.holder)

        # ═══ 底部导航 ═══
        nav = BoxLayout(spacing=dp(6), size_hint=(1, None), height=dp(58),
                        padding=[dp(6), dp(6)])
        rounded(nav, C_CARD, [dp(16)])
        self.navbtns = []
        icons = ['⌂', '◔', '⚙', '☰']
        for i, t in enumerate(self.TABS):
            b = Button(text=f'{icons[i]}\n{t}', background_normal='',
                       background_color=(0, 0, 0, 0), bold=False,
                       font_size='10sp', font_name=CJK_FONT or 'Roboto',
                       color=C_SUB, size_hint=(1, 1), halign='center')
            b.bind(on_press=lambda *a, idx=i: self.switch_tab(idx))
            self.navbtns.append(b)
            nav.add_widget(b)
        root.add_widget(nav)

        self.switch_tab(0)
        threading.Thread(target=self._auto_probe, daemon=True).start()
        return root

    # ---------- 页面 ----------
    def _page_service(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(14))

        # 问候+状态
        head = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(16),
                         size_hint=(1, None), height=dp(120))
        rounded(head, C_CARD)
        # 标题行: 大字 + 右侧状态点
        tl = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(34))
        tl.add_widget(L('聚宝盆', 24, C_TXT, bold=True))
        self.status_dot = Widget(size_hint=(None, 1), width=dp(12))
        with self.status_dot.canvas:
            Color(*C_SUB)
            self.status_dot.circ = RoundedRectangle(pos=self.status_dot.pos,
                size=(dp(12), dp(12)), radius=[dp(6)])
        self.status_dot.bind(pos=lambda i,p: setattr(self.status_dot.circ,'pos',p),
                             size=lambda i,s: setattr(self.status_dot.circ,'size',s))
        tr = BoxLayout(size_hint=(None, 1), width=dp(24))
        tr.add_widget(self.status_dot)
        tl.add_widget(Widget()); tl.add_widget(tr)
        head.add_widget(tl)
        self.status = L('服务未启动', 12, C_SUB)
        head.add_widget(self.status)
        self.status_detail = L('网关 6120 · 管理 6210', 10, C_SUB)
        head.add_widget(self.status_detail)
        pg.add_widget(head)

        # 主按钮
        self.btn_start = pill_button('启动服务', C_PRIMARY, 16, 56)
        self.btn_start.bind(on_press=self.start)
        pg.add_widget(self.btn_start)
        row = BoxLayout(spacing=dp(10), size_hint=(1, None), height=dp(46))
        self.btn_stop = pill_button('停止', C_BAD, 13, 46)
        self.btn_refresh = pill_button('刷新', C_CARD_HI, 13, 46)
        self.btn_stop.bind(on_press=self.stop_services)
        self.btn_refresh.bind(on_press=self.refresh_status)
        row.add_widget(self.btn_stop); row.add_widget(self.btn_refresh)
        pg.add_widget(row)

        # 接入信息行式卡
        icard = BoxLayout(orientation='vertical', spacing=dp(2), padding=dp(14),
                          size_hint=(1, None), height=dp(132))
        rounded(icard, C_CARD)
        for name, val in [('BaseURL', '127.0.0.1:6120/v1'),
                          ('API Key', 'sk-freepool-fixed-2026'),
                          ('管理 Key', 'sk-owner-me-2026'),
                          ('模型', 'free-pool')]:
            row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(28))
            row.add_widget(L(name, 12, C_SUB))
            row.add_widget(L(val, 12, C_GOOD, halign='right'))
            icard.add_widget(row)
        pg.add_widget(icard)
        pg.add_widget(Widget())
        return pg

    def _page_monitor(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(10))
        pg.add_widget(L('实时监控', 18, C_TXT, bold=True))

        # 资源行式面板: 图标+标签 ......... 数值
        res_card = BoxLayout(orientation='vertical', spacing=dp(2), padding=dp(14))
        rounded(res_card, C_CARD)
        self.res_rows = {}
        for icon, name, key in [('◍', 'CPU 负载', 'cpuLoad'), ('▤', '内存占用', 'memPct'),
                                ('♨', '设备温度', 'thermal'), ('⇅', '路由压力', 'load')]:
            row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(34))
            lb = L(f'{icon}  {name}', 13, C_SUB)
            vl = L('—', 15, C_TXT, bold=True, halign='right')
            row.add_widget(lb); row.add_widget(vl)
            res_card.add_widget(row)
            self.res_rows[key] = vl
        pg.add_widget(res_card)

        # 上游模型行式
        pg.add_widget(L('上游模型', 14, C_TXT, bold=True))
        self.mon_models = L('刷新获取', 11, C_LOG)
        sc = ScrollView(size_hint=(1, 1))
        mcard = BoxLayout(orientation='vertical', spacing=dp(2), padding=dp(14))
        rounded(mcard, C_CARD)
        mcard.add_widget(self.mon_models)
        sc.add_widget(mcard)
        pg.add_widget(sc)

        btn = pill_button('刷新监控', C_PRIMARY, 14, 48)
        btn.bind(on_press=self.show_scores)
        pg.add_widget(btn)
        return pg

    def _page_config(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(12))
        pg.add_widget(L('配置中心', 18, C_TXT, bold=True))
        self.cfg_view = L('选择查看内容', 11, C_LOG)
        sc = ScrollView(size_hint=(1, 1))
        sc.add_widget(card([self.cfg_view]))
        pg.add_widget(sc)
        row = BoxLayout(spacing=dp(10), size_hint=(1, None), height=dp(46))
        b1 = pill_button('配置 JSON', C_CARD_HI, 13, 46)
        b2 = pill_button('接入说明', C_CARD_HI, 13, 46)
        b1.bind(on_press=self.show_config)
        b2.bind(on_press=self.show_help)
        row.add_widget(b1); row.add_widget(b2)
        pg.add_widget(row)
        b_admin = pill_button('打开管理面板', C_PRIMARY, 13, 48)
        b_admin.bind(on_press=self.open_admin)
        pg.add_widget(b_admin)
        return pg

    def _page_logs(self):
        pg = BoxLayout(orientation='vertical', spacing=dp(12))
        pg.add_widget(L('运行日志', 18, C_TXT, bold=True))
        self.logview = ScrollView(size_hint=(1, 1))
        self.loglabel = L('等待操作…', 10, C_LOG)
        self.logview.add_widget(card([self.loglabel]))
        pg.add_widget(self.logview)
        clr = pill_button('清空日志', C_CARD_HI, 12, 42)
        clr.bind(on_press=self.clear_log)
        pg.add_widget(clr)
        return pg

    # ---------- 行为 ----------
    def switch_tab(self, idx):
        self.tab_idx = idx
        for i, page in enumerate(self.pages):
            active = (i == idx)
            page.size_hint_y = 1 if active else None
            if active:
                page.height = dp(0)  # size_hint接管
            else:
                page.height = dp(0)
            page.opacity = 1 if active else 0
        for i, b in enumerate(self.navbtns):
            b.color = C_TXT if i == idx else C_SUB
            b.bold = (i == idx)

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
        self.status.text = '启动中…'
        self.status_dot.canvas.before.clear()
        with self.status_dot.canvas:
            Color(*C_WARN)
            self.status_dot.circ = RoundedRectangle(pos=self.status_dot.pos,
                size=(dp(12), dp(12)), radius=[dp(6)])
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
            self.set_log('❌ 启动超时')
            self.status.text = '启动失败'

    def _set_running(self, *a):
        self._mark_running()

    def _mark_running(self):
        self.status.text = '运行中'
        self.status.color = C_GOOD
        self.status_dot.canvas.before.clear()
        with self.status_dot.canvas:
            Color(*C_GOOD)
            self.status_dot.circ = RoundedRectangle(pos=self.status_dot.pos,
                size=(dp(12), dp(12)), radius=[dp(6)])
        self.status_detail.text = '网关 6120 ✅ · 管理 6210 ✅ · 资源监控激活'
        self.btn_start.text = '✓ 服务运行中'
        self.set_log('资源监控已激活')

    def stop_services(self, *a):
        try:
            subprocess.run(['pkill', '-f', 'freepool.py'], capture_output=True)
            subprocess.run(['pkill', '-f', 'jubaopen.py'], capture_output=True)
        except Exception as e:
            self.set_log(f'停止失败: {e}')
        self.status.text = '已停止'
        self.status.color = C_SUB
        self.status_dot.canvas.before.clear()
        with self.status_dot.canvas:
            Color(*C_SUB)
            self.status_dot.circ = RoundedRectangle(pos=self.status_dot.pos,
                size=(dp(12), dp(12)), radius=[dp(6)])
        self.status_detail.text = '网关 6120 · 管理 6210'
        self.btn_start.text = '启动服务'
        self.set_log('服务已停止')

    def refresh_status(self, *a):
        self.show_scores(silent=True)

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

    def show_scores(self, *a, silent=False):
        s = http_get('/scores')
        if not s:
            if not silent:
                self.set_log('监控: 服务未运行')
            return
        r = s.get('resource', {})
        self.res_rows['cpuLoad'].text = str(r.get('cpuLoad', '—'))
        self.res_rows['memPct'].text = f"{r.get('memPct','—')}%"
        self.res_rows['thermal'].text = str(r.get('thermal', '—'))
        self.res_rows['load'].text = str(r.get('load', '—'))
        lines = ['上游模型']
        models = s.get('models') or s.get('upstreams') or {}
        if isinstance(models, dict):
            for k, v in list(models.items())[:14]:
                lines.append(f'{k}:  {v}')
        self.mon_models.text = '\n'.join(lines) or '无数据'
        if not silent:
            self.switch_tab(1)
            self.set_log('监控已刷新')

    def show_config(self, *a):
        try:
            cfg = json.load(open(os.path.join(APP_DIR, 'config.json')))
            self.cfg_view.text = json.dumps(cfg, ensure_ascii=False, indent=1)[:900]
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
            '安全: 限速120/分 · 10次失败拉黑600s')
        self.switch_tab(2)

    def clear_log(self, *a):
        log_lines.clear()
        self.loglabel.text = '日志已清空'

    def set_log(self, msg):
        log_lines.append(msg)
        self.loglabel.text = '\n'.join(log_lines[-20:])

def Clock_schedule(fn):
    try:
        from kivy.clock import Clock
        Clock.schedule_once(fn, 0)
    except Exception:
        pass

if __name__ == '__main__':
    JubaoApp().run()
