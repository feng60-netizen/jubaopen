#!/bin/bash
# 预clone p4a并用预打补丁的libffi recipe覆盖(官方release tarball自带configure, 跳过autoreconf)
# 根因: 云端libtool 2.5.x宏不兼容 libffi 3.4.2 的autoreconf
set -e
P4A_DIR="apk/.buildozer/android/platform/python-for-android"
BRANCH=$(grep -oP 'p4a\.branch\s*=\s*\K\S+' apk/buildozer.spec 2>/dev/null || echo master)
if [ ! -d "$P4A_DIR" ]; then
  git clone -b "$BRANCH" --depth 1 https://github.com/kivy/python-for-android.git "$P4A_DIR" && cd "$P4A_DIR" && git checkout -B "$BRANCH" && cd -
fi
cp ci/libffi_recipe_patched.py "$P4A_DIR/pythonforandroid/recipes/libffi/__init__.py"
echo "p4a就绪(branch=$BRANCH), libffi recipe已替换为release-tarball版"

# 限制编译并行度(-j2), 防止runner 7GB内存OOM静默死亡; 顺带打印磁盘
df -h / | tail -1

# CPython 3.14的compileall -j0在7GB runner上OOM(-j0=每核worker×3优化级别) → 硬杀无日志
# 用patch文件修COMPILEALL_OPTS=-j1
cp ci/compileall_j1.patch "$P4A_DIR/pythonforandroid/recipes/python3/patches/compileall_j1.patch"
cp ci/compileall_j1.patch "$P4A_DIR/pythonforandroid/recipes/hostpython3/compileall_j1.patch"
cp ci/python3_recipe_patched.py "$P4A_DIR/pythonforandroid/recipes/python3/__init__.py"
cp ci/hostpython3_recipe_patched.py "$P4A_DIR/pythonforandroid/recipes/hostpython3/__init__.py"
echo "compileall -j1补丁已就位(修OOM硬杀)"

# 全局限编译并行=2(配合-j1, 双保险防OOM)
P4A_PY="$P4A_DIR/pythonforandroid/recipe.py"
sed -i 's/from multiprocessing import cpu_count/import multiprocessing as _mp\ncpu_count = lambda: 2  # CI内存限制/' "$P4A_PY"
sed -i 's/from multiprocessing import cpu_count/import multiprocessing as _mp\ncpu_count = lambda: 2  # CI内存限制/' "$P4A_DIR/pythonforandroid/recipes/hostpython3/__init__.py"
grep -c "cpu_count = lambda: 2" "$P4A_PY" "$P4A_DIR/pythonforandroid/recipes/hostpython3/__init__.py"
