"""Run the Presentation API and Streamlit UI in one container.

The API must remain a separate child process: replacing this process with
Streamlit would terminate the API and make the UI's localhost:8000 calls fail.
"""
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


API_HEALTH_URL = "http://127.0.0.1:8000/health"


def wait_for_api(process: subprocess.Popen, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Presentation API exited during startup (exit code {process.returncode})."
            )
        try:
            with urlopen(API_HEALTH_URL, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Presentation API did not become healthy: {last_error}")


def main() -> None:
    api_process = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "app.api:app",
        "--host", "0.0.0.0", "--port", "8000",
    ])
    try:
        wait_for_api(api_process)
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "app/ui.py",
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.headless=true",
        ], check=True)
    finally:
        if api_process.poll() is None:
            api_process.terminate()
            try:
                api_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                api_process.kill()
                api_process.wait(timeout=5)


if __name__ == "__main__":
    main()
