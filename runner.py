import os

from routes1846web.routes1846web import app

HOST = os.getenv("IP", "0.0.0.0")
PORT = int(os.getenv("PORT", 8080))

app.run(host=HOST, port=PORT, debug=os.environ.get("DEBUG", "True") == "True")
