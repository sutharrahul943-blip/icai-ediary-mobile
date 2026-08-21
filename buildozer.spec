[app]
title = ICAI E-Diary Filler
package.name = icaiediary
package.domain = org.icaica.ediary

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 0.1

requirements = python3==3.11,kivy==master,pyjnius,android

orientation = portrait
fullscreen = 0

# Android permissions - INTERNET is required for the embedded WebView to
# reach the ICAI portal.
android.permissions = INTERNET

android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
