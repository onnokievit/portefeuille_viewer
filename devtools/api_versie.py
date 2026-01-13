from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import threading
import time
import ibapi


class IBApi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

    def nextValidId(self, orderId: int):
        print("✔ Verbonden met IBKR")
        print("Server API version :", self.serverVersion())
        print("Client ibapi version:", ibapi.__version__)
        self.disconnect()


def run_loop(app):
    app.run()


if __name__ == "__main__":
    print("Client ibapi version:", ibapi.__version__)

    app = IBApi()

    # 🔧 Pas dit aan indien nodig
    HOST = "127.0.0.1"
    PORT = 7496   # 7497 = TWS paper, 7496 = TWS live, 4002 = Gateway paper
    CLIENT_ID = 123

    app.connect(HOST, PORT, CLIENT_ID)

    api_thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
    api_thread.start()

    time.sleep(5)
