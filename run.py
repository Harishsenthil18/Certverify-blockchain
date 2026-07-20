from app import create_app
import webbrowser
from threading import Timer
import os

app = create_app()

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        Timer(1, open_browser).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )