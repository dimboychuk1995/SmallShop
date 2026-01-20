from flask import render_template
from . import main_bp

@main_bp.get("/")
def index():
    return render_template("public/auth.html")