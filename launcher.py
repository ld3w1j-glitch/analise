from __future__ import annotations

import threading
import time
import webbrowser

from app import app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


def abrir_navegador() -> None:
    """Abre o navegador depois que o servidor Flask começa a subir."""
    time.sleep(1.2)
    webbrowser.open(URL)


if __name__ == "__main__":
    threading.Thread(target=abrir_navegador, daemon=True).start()
    print("=" * 64)
    print("Dashboard de Inventário Rotativo")
    print(f"Abra no navegador: {URL}")
    print("Para encerrar, feche esta janela.")
    print("=" * 64)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
