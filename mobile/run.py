import subprocess
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


PROCESS = None


def start_app():
    global PROCESS
    PROCESS = subprocess.Popen([sys.executable, "main.py"])


class ReloadHandler(FileSystemEventHandler):

    def on_modified(self, event):
        if event.src_path.endswith(".py"):
            print("\nCambio detectado. Reiniciando Kivy...")

            global PROCESS

            if PROCESS:
                PROCESS.terminate()
                PROCESS.wait()

            start_app()


if __name__ == '__main__':

    observer = Observer()
    observer.schedule(
        ReloadHandler(),
        path='.',
        recursive=True
    )

    observer.start()

    start_app()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if PROCESS:
            PROCESS.terminate()

        observer.stop()

    observer.join()