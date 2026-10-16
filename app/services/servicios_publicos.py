# -*- coding: utf-8 -*-
"""Tarjetas de la página pública de Servicios (1.9.11.0).

Cada servicio se muestra como una tarjeta (foto o inicial, número, descripción y los
dos primeros beneficios) y al tocarla se abre su detalle con todo lo que incluye y
el botón para pedirlo. Aquí solo se preparan los datos; el diseño sale del color de
cada tienda (templates/servicios.html + static/css/servicios.css)."""
import re

# Viñetas con que la tienda escribe sus beneficios: «- », «• », «* », «1. », «2) »…
_VINETA = re.compile(r'^\s*(?:[-–—•*·]+|\d{1,2}[.)])\s*')
RESUMEN = 2                     # beneficios que se ven en la tarjeta


def lista_beneficios(texto):
    """Los beneficios como los escribió la tienda (uno por línea, con o sin viñeta)."""
    salida = []
    for linea in str(texto or '').splitlines():
        limpio = _VINETA.sub('', linea).strip()
        if limpio:
            salida.append(limpio)
    return salida


def _inicial(titulo):
    return next((ch.upper() for ch in str(titulo or '') if ch.isalnum()), '•')


def tarjetas(items, demo=False):
    """Los servicios listos para la plantilla: número, inicial (si no hay foto),
    beneficios en lista y el resumen que va en la tarjeta. Sin título no hay tarjeta."""
    salida = []
    for item in items or []:
        titulo = str(item.get('titulo') or '').strip()
        if not titulo:
            continue
        beneficios = item.get('beneficios')
        if not isinstance(beneficios, (list, tuple)):
            beneficios = lista_beneficios(beneficios)
        salida.append({
            'numero': f'{len(salida) + 1:02d}',
            'titulo': titulo,
            'descripcion': str(item.get('descripcion') or '').strip(),
            'imagen': (item.get('imagen') or '').strip() if not demo else '',
            'imagen_static': item.get('imagen_static') or '',
            'inicial': _inicial(titulo),
            'beneficios': list(beneficios),
            'resumen': list(beneficios)[:RESUMEN],
            'demo': demo,
        })
    return salida


# Tienda nueva que aún no carga los suyos: servicios de muestra (no los de CyberShop).
SERVICIOS_MUESTRA = (
    {'titulo': 'Tu servicio principal', 'descripcion': 'Describe aquí lo que más vendes o lo que te hace diferente.'},
    {'titulo': 'Tu segundo servicio', 'descripcion': 'Cuenta en una o dos frases qué incluye y para quién es.'},
    {'titulo': 'Tu tercer servicio', 'descripcion': 'Agrega precios, horarios o condiciones si quieres.'},
)

# Los servicios de siempre de CyberShop: solo en la página del operador.
SERVICIOS_OPERADOR = (
    {'titulo': 'Mantenimiento de software y hardware', 'imagen_static': 'img/Servicio1.webp',
     'descripcion': 'Mantén tus equipos funcionando como nuevos con nuestro servicio de mantenimiento profesional.',
     'beneficios': ['Prolonga la vida útil de tus equipos.',
                    'Reduce tiempos de inactividad por fallos técnicos.',
                    'Mejora el rendimiento general de tus sistemas.',
                    'Diagnóstico rápido y soluciones efectivas.',
                    'Soporte técnico confiable y profesional.']},
    {'titulo': 'Actualización de sistemas operativos', 'imagen_static': 'img/Servicio2.webp',
     'descripcion': 'No te quedes atrás en el mundo digital. Te ayudamos a actualizar tus sistemas operativos.',
     'beneficios': ['Aumenta la seguridad de tus dispositivos frente a amenazas.',
                    'Acceso a las últimas funciones y tecnologías.',
                    'Mejora el rendimiento y velocidad de tus equipos.',
                    'Compatibilidad con nuevos programas y aplicaciones.',
                    'Proceso ágil y sin interrupciones para tu negocio.']},
    {'titulo': 'Automatización de procesos de negocios', 'imagen_static': 'img/Servicio3.webp',
     'descripcion': 'Haz que tu empresa sea más productiva con la automatización de tareas clave.',
     'beneficios': ['Ahorro significativo de tiempo y recursos.',
                    'Eliminación de errores humanos en tareas repetitivas.',
                    'Incremento en la productividad de tu equipo.',
                    'Mejora en la toma de decisiones con datos en tiempo real.',
                    'Mayor competitividad en el mercado.']},
    {'titulo': 'Instalación de cableado estructurado', 'imagen_static': 'img/Servicio4.webp',
     'descripcion': 'Garantiza una conexión eficiente y estable con nuestra instalación de cableado estructurado.',
     'beneficios': ['Garantiza una conexión estable y de alta velocidad.',
                    'Facilita la gestión y el mantenimiento de redes.',
                    'Adaptable a las necesidades actuales y futuras de tu negocio.',
                    'Cumple con estándares internacionales de calidad.',
                    'Reduce el riesgo de fallas en la red.']},
    {'titulo': 'Sistemas de vigilancia', 'imagen_static': 'img/Servicio5.webp',
     'descripcion': 'Protege lo que más importa con nuestras soluciones de vigilancia de última generación.',
     'beneficios': ['Monitoreo continuo para mayor seguridad.',
                    'Detección oportuna de incidentes.',
                    'Control remoto desde cualquier lugar.',
                    'Grabaciones en alta resolución para mayor claridad.',
                    'Tranquilidad y confianza para proteger tus activos.']},
    {'titulo': 'Desarrollo web empresarial', 'imagen_static': 'img/Servicio6.webp',
     'descripcion': 'Destaca en el mundo digital con páginas web empresariales diseñadas para impresionar.',
     'beneficios': ['Refleja la identidad profesional de tu marca.',
                    'Mejora tu presencia en línea y posicionamiento en buscadores.',
                    'Facilita la interacción con clientes potenciales.',
                    'Compatible con dispositivos móviles y fácil de usar.',
                    'Incrementa la captación de clientes y las ventas.']},
)
