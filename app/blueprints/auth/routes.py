from . import auth_bp

@auth_bp.post("/login")
def login():
    return "TODO: login", 501

@auth_bp.get("/forgot-password")
def forgot_password():
    return "TODO: forgot password", 501