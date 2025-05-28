# security.py
from functools import wraps
from flask import request, jsonify
import time

# Diccionario para almacenar temporalmente las solicitudes
request_log = {}

def validar_token(token):
    """Valida el token de autorización (implementación básica)"""
    # Implementa tu lógica real de validación de tokens
    return token == "Bearer token_valido"  # Esto es solo un ejemplo

def controlar_tasa_solicitudes(ip, max_requests=10, interval=60):
    """Controla la tasa de solicitudes por IP"""
    current_time = time.time()
    
    if ip not in request_log:
        request_log[ip] = []
    
    # Eliminar registros antiguos
    request_log[ip] = [t for t in request_log[ip] if current_time - t < interval]
    
    if len(request_log[ip]) >= max_requests:
        return False
    
    request_log[ip].append(current_time)
    return True

def requiere_autenticacion(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if not validar_token(request.headers.get('Authorization')):
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return decorador