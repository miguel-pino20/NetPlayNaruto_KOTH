"""Stage only mobile sources and their existing shared dependencies."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARED = ('pine.py', 'appdata.py', 'discord_auth.py', 'koth_client.py', 'hill.py', 'spectator.py',
          'updater.py', 'release_info.py', 'core_link.py', 'node.py', 'wire.py', 'netplay.py', 'scoreboard.py', 'chars_un6.json', 'netlink.py', 'statesync.py', 'rooms.py')


def prepare():
    import importlib.util
    spec = importlib.util.spec_from_file_location('shared_release', ROOT / 'release_info.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    import re
    config = HERE / 'buildozer.spec'
    config.write_text(re.sub(r'^android.numeric_version = .*$',
                            'android.numeric_version = ' + str(release.ANDROID_VERSION_CODE),
                            config.read_text(), flags=re.MULTILINE))
    target = HERE / 'build' / 'app'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in SHARED:
        shutil.copy2(ROOT / name, target / name)
    for name in ('main.py', 'mobile_locale.py', 'backend.py', 'koth.py', 'host.py', 'host_service.py', 'floating.py', 'downloads.py', 'updates.py'):
        shutil.copy2(HERE / name, target / name)
    shutil.copy2(ROOT / "appimage" / "un5-netplay.png", target / "un5-netplay.png")
    # Manifest-only Android library merged by Gradle; Java comes from android.add_src.
    import io
    import zipfile
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, 'w'):
        pass
    with zipfile.ZipFile(HERE / 'build' / 'update-provider.aar', 'w') as library:
        library.write(HERE / 'android_update_provider.xml', 'AndroidManifest.xml')
        library.writestr('classes.jar', jar.getvalue())
        library.writestr('R.txt', '')
    return target


if __name__ == '__main__':
    print(prepare())
