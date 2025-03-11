STATIC_URL ='/static/'
STATICFILES_DIR = ''
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # Servidor SMTP de Gmail
EMAIL_PORT = 587  # Puerto para TLS
EMAIL_USE_TLS = True
EMAIL_HOST_USER = '@gmail.com'  # Tu dirección de correo
EMAIL_HOST_PASSWORD = 'tucontraseña'  # Tu contraseña de correo