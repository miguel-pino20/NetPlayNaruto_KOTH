"""Stage only mobile sources and their existing shared dependencies."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARED = ('pine.py', 'appdata.py', 'discord_auth.py', 'koth_client.py', 'hill.py',
          'core_link.py', 'node.py', 'wire.py', 'netplay.py', 'netlink.py', 'statesync.py', 'rooms.py')


def prepare():
    target = HERE / 'build' / 'app'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in SHARED:
        shutil.copy2(ROOT / name, target / name)
    for name in ('main.py', 'backend.py', 'host.py', 'host_service.py', 'floating.py', 'downloads.py'):
        shutil.copy2(HERE / name, target / name)
    shutil.copy2(ROOT / "appimage" / "un5-netplay.png", target / "un5-netplay.png")
    return target


if __name__ == '__main__':
    print(prepare())
