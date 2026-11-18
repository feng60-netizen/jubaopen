#!/bin/bash
# 预clone p4a并patch libffi recipe: autoreconf前把ltdl.m4补进源码m4/目录
# 根因: libtoolize只复制libtool.m4系列,不复制ltdl.m4; libffi的configure.ac引用LT_SYS_SYMBOL_USCORE(在ltdl.m4) → autoreconf报possibly undefined
set -e
P4A_DIR="apk/.buildozer/android/platform/python-for-android"
BRANCH=$(grep -oP 'p4a\.branch\s*=\s*\K\S+' apk/buildozer.spec 2>/dev/null || echo master)
if [ ! -d "$P4A_DIR" ]; then
  git clone -b "$BRANCH" --single-branch --depth 1 https://github.com/kivy/python-for-android.git "$P4A_DIR"
fi
RECIPE="$P4A_DIR/pythonforandroid/recipes/libffi/__init__.py"
if ! grep -q "ltdl.m4" "$RECIPE"; then
  python3 - "$RECIPE" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
old = """            if not exists('configure'):
                shprint(sh.Command('./autogen.sh'), _env=env)"""
new = """            if not exists('configure'):
                try:
                    import os as _os
                    _os.makedirs('m4', exist_ok=True)
                    shprint(sh.cp, '/usr/share/aclocal/ltdl.m4', 'm4/')
                except Exception:
                    pass  # 非Linux/CI无系统宏时忽略
                shprint(sh.Command('./autogen.sh'), _env=env)"""
assert old in s, 'recipe结构变化'
open(p, 'w').write(s.replace(old, new))
print('libffi recipe已打补丁(ltdl.m4补齐)')
PYEOF
fi
echo "p4a就绪: $P4A_DIR (branch=$BRANCH)"
