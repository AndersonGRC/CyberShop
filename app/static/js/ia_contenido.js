/* Asistente IA para Contenido Web (Publicaciones, Slides, Servicios).
 *
 * Cada página tiene VARIOS formularios (crear + un editar por ítem) con IDs
 * repetidos, así que todo se resuelve por-formulario con btn.closest('form')
 * y campos por [name=...]. Un único handler delegado en document cubre los
 * formularios presentes y los que se agreguen luego.
 *
 * Marcado esperado (gated con 'ai_assistant'):
 *   <button class="ia-content-btn" data-ia-accion="generar|mejorar"
 *           data-ia-target="descripcion" data-ia-titulo="titulo"
 *           data-ia-tipo="publicación">…</button>
 *   <span class="ia-content-status"></span>   (dentro del mismo .gem-btn-row)
 */
(function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var CSRF = meta ? meta.getAttribute('content') : '';

    function fieldIn(form, name) {
        return form ? form.querySelector('[name="' + name + '"]') : null;
    }

    function setBusy(btn, busy) {
        if (!btn) return;
        btn.disabled = busy;
        if (busy) {
            btn.dataset.orig = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Procesando...';
        } else {
            btn.innerHTML = btn.dataset.orig || btn.innerHTML;
        }
    }

    function setStatus(el, msg, tipo) {
        if (!el) return;
        el.className = 'ia-content-status' +
            (tipo === 'error' ? ' ia-status-error' : (msg ? ' ia-status-ok' : ''));
        el.innerHTML = msg
            ? ((tipo === 'error'
                ? '<i class="fas fa-exclamation-circle"></i> '
                : '<i class="fas fa-check-circle"></i> ') + msg)
            : '';
        el.style.display = msg ? 'inline-flex' : 'none';
    }

    function flash(el) {
        if (!el) return;
        el.classList.remove('ia-field-flash');
        void el.offsetWidth;
        el.classList.add('ia-field-flash');
        setTimeout(function () { el.classList.remove('ia-field-flash'); }, 1800);
    }

    document.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('.ia-content-btn') : null;
        if (!btn) return;
        ev.preventDefault();

        var form = btn.closest('form');
        var group = btn.closest('.gem-btn-row');
        var statusEl = group ? group.querySelector('.ia-content-status') : null;
        var accion = btn.dataset.iaAccion || 'mejorar';
        var target = fieldIn(form, btn.dataset.iaTarget || 'descripcion');
        if (!target) { return; }

        var body;
        if (accion === 'mejorar') {
            var texto = (target.value || '').trim();
            if (!texto) { setStatus(statusEl, 'Escribe o genera un texto primero.', 'error'); return; }
            body = { accion: 'mejorar', texto: texto };
        } else {
            var tituloEl = fieldIn(form, btn.dataset.iaTitulo || 'titulo');
            var titulo = tituloEl ? (tituloEl.value || '').trim() : '';
            if (!titulo) { setStatus(statusEl, 'Escribe primero el título.', 'error'); return; }
            body = {
                accion: 'generar',
                titulo: titulo,
                tipo: btn.dataset.iaTipo || 'contenido',
                detalle: (target.value || '').trim()
            };
        }

        setBusy(btn, true);
        setStatus(statusEl, accion === 'mejorar' ? 'Mejorando...' : 'Generando...', '');

        fetch('/admin/ia/contenido', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(body)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data && data.ok) {
                target.value = data.texto;
                flash(target);
                setStatus(statusEl, '¡Listo! Revisa el texto y guarda.', '');
            } else {
                setStatus(statusEl, (data && data.error) || 'No se pudo procesar.', 'error');
            }
        })
        .catch(function () { setStatus(statusEl, 'Error de red.', 'error'); })
        .finally(function () { setBusy(btn, false); });
    });
})();
