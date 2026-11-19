#!/bin/bash
# 预clone p4a并patch libffi recipe: autoreconf前把ltdl.m4补进源码m4/目录
# 根因: 云端libtool 2.5.x的libtool.m4不再定义LT_SYS_SYMBOL_USCORE, libffi 3.4.2 configure.ac引用它 → autoreconf挂
# 修法: 改用官方release tarball(自带configure,完全跳过autogen/autoreconf)
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
s = s.replace("url = 'https://github.com/libffi/libffi/archive/{version}.tar.gz'",
              "url = 'https://github.com/libffi/libffi/releases/download/v3.4.2/libffi-3.4.2.tar.gz'")
s = s.replace("version = 'v3.4.2'", "version = '3.4.2'")
# release tarball自带configure, 跳过autogen与autoreconf(云端libtool 2.5.x宏不兼容)
s = s.replace("            shprint(sh.Command('autoreconf'), '-vif', _env=env)
", "")
open(p, 'w').write(s)
print('libffi recipe: 改用release tarball + 移除autoreconf')
PYEOF
fi
echo "p4a就绪: $P4A_DIR (branch=$BRANCH)"
