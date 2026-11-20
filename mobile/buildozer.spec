[app]
title = Naruto Netplay
package.name = narutonetplay
package.domain = org.un5
source.dir = build/app
source.include_exts = py,png
version.regex = VERSION = "(.*)"
version.filename = ../release_info.py
android.numeric_version = 1026409
icon.filename = ../appimage/un5-netplay.png
requirements = python3,kivy==2.3.1,openssl,certifi,pyjnius
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,FOREGROUND_SERVICE,FOREGROUND_SERVICE_CONNECTED_DEVICE,CHANGE_NETWORK_STATE,POST_NOTIFICATIONS,SYSTEM_ALERT_WINDOW,REQUEST_INSTALL_PACKAGES
services = host:host_service.py:foreground:foregroundServiceType=connectedDevice
android.extra_manifest_xml = android_queries.xml
android.add_aars = build/update-provider.aar
android.add_gradle_repositories = flatDir { dirs 'libs' }
android.add_src = java
android.api = 35
android.minapi = 26
android.ndk = 28c
android.archs = arm64-v8a
android.allow_backup = False
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
