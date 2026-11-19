#!/bin/bash
# 预clone p4a并用预打补丁的libffi recipe覆盖(官方release tarball自带configure, 跳过autoreconf)
# 根因: 云端libtool 2.5.x宏不兼容 libffi 3.4.2 的autoreconf
set -e
P4A_DIR="apk/.buildozer/android/platform/python-for-android"
BRANCH=$(grep -oP 'p4a\.branch\s*=\s*\K\S+' apk/buildozer.spec 2>/dev/null || echo master)
if [ ! -d "$P4A_DIR" ]; then
  git clone -b "$BRANCH" --single-branch --depth 1 https://github.com/kivy/python-for-android.git "$P4A_DIR"
fi
cp ci/libffi_recipe_patched.py "$P4A_DIR/pythonforandroid/recipes/libffi/__init__.py"
echo "p4a就绪(branch=$BRANCH), libffi recipe已替换为release-tarball版"
