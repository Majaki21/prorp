import os
import subprocess
import sys
import threading
import uvicorn


def run_api():
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8000,
    )


def main():
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app/ui.py",
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.headless=true",
        ],
    )


if __name__ == "__main__":
    main()
