from . import tenant_bp

@tenant_bp.post("/register")
def register_tenant():
    return "TODO: register tenant", 501