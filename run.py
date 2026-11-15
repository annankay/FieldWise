"""Start FieldWise:  python run.py   then open http://127.0.0.1:8000"""
import webbrowser
import threading

import uvicorn

from backend import config

if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"\n  FieldWise is starting at {url}  (Ctrl+C to stop)\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("backend.api:app", host=config.HOST, port=config.PORT, reload=False)
