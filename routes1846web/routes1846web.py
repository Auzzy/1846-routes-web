from flask import Flask
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config.from_object("routes1846web.settings")

csrf = CSRFProtect(app)
