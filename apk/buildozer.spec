[app]
title = 聚宝盆
package.name = jubaopen
package.domain = com.jubaopen
source.dir = .
source.include_exts = py,html,json
source.exclude_dirs = bin,.buildozer,__pycache__
version = 1.0.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS
android.api = 31
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
android.extra_manifest_xml = manifest_extra.xml
log_level = 2

p4a.branch = v2026.05.09

[buildozer]
log_level = 2
warn_on_root = 0
