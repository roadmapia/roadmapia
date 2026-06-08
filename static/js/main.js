// ===== CHECKLIST AJAX =====
function initChecklist(roadmapId, leccionId) {
  const items = document.querySelectorAll('.check-item input[type="checkbox"]');
  const completeBtn = document.getElementById('btn-completar');

  async function saveChecklist() {
    const checklist = Array.from(items).map(cb => cb.checked);
    try {
      await fetch(`/progress/${roadmapId}/${leccionId}/checklist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checklist })
      });
    } catch (e) { console.error('Error guardando checklist:', e); }
    updateCompleteBtn(checklist);
    updateChecklistUI();
  }

  function updateCompleteBtn(checklist) {
    if (!completeBtn) return;
    const allDone = checklist.length > 0 && checklist.every(Boolean);
    completeBtn.disabled = !allDone;
  }

  function updateChecklistUI() {
    items.forEach(cb => {
      cb.closest('.check-item').classList.toggle('checked', cb.checked);
    });
  }

  items.forEach(cb => cb.addEventListener('change', saveChecklist));
  updateCompleteBtn(Array.from(items).map(cb => cb.checked));
  updateChecklistUI();
}

// ===== COMPLETAR LECCIÓN =====
async function completarLeccion(roadmapId, leccionId) {
  const btn = document.getElementById('btn-completar');
  btn.disabled = true;
  btn.textContent = 'Completando...';
  try {
    const res = await fetch(`/progress/${roadmapId}/${leccionId}/completar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (res.ok) {
      btn.textContent = '✓ ¡Lección completada!';
      btn.className = 'btn btn-success btn-lg';
      const data = await res.json();
      if (data.pedir_resena) {
        setTimeout(() => mostrarModalResena(roadmapId), 800);
      } else {
        setTimeout(() => { window.location.href = `/roadmaps/${roadmapId}`; }, 1200);
      }
    }
  } catch (e) {
    btn.textContent = 'Error, intenta de nuevo';
    btn.disabled = false;
  }
}

// ===== CHAT TUTOR =====
function initChat(roadmapId, leccionId) {
  const messagesEl = document.getElementById('chat-messages');
  const form       = document.getElementById('chat-form');
  const input      = document.getElementById('chat-input');
  const sendBtn    = document.getElementById('chat-send');
  if (!form || !messagesEl) return;

  async function loadHistory() {
    try {
      const res  = await fetch(`/tutor/${roadmapId}/${leccionId}/historial`);
      const data = await res.json();
      data.mensajes.forEach(m => addMessage(m.rol, m.contenido));
      scrollToBottom();
    } catch (e) { console.error('Error cargando historial:', e); }
  }

  function addMessage(rol, contenido) {
    const div = document.createElement('div');
    div.className = `msg ${rol}`;
    if (rol === 'assistant' && typeof marked !== 'undefined') {
      // marked.parse devuelve HTML del asistente IA (contenido controlado del servidor)
      div.innerHTML = marked.parse(contenido);
    } else {
      div.textContent = contenido;
    }
    messagesEl.appendChild(div);
    return div;
  }

  function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    addMessage('user', msg);
    input.value = '';
    sendBtn.disabled = true;
    scrollToBottom();
    const typingEl = addMessage('assistant', '...');
    typingEl.className = 'msg typing';
    scrollToBottom();
    try {
      const res  = await fetch(`/tutor/${roadmapId}/${leccionId}/mensaje`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensaje: msg })
      });
      const data = await res.json();
      messagesEl.removeChild(typingEl);
      if (data.error) {
        const errEl = addMessage('assistant', '⚠️ ' + data.error);
        errEl.style.color = 'var(--red)';
      } else {
        addMessage('assistant', data.respuesta);
        if (data.mensajes_restantes !== undefined && data.mensajes_restantes !== -1) {
          const el = document.getElementById('msgs-restantes');
          if (el) el.textContent = data.mensajes_restantes;
          if (data.mensajes_restantes === 0) {
            const chatForm = document.getElementById('chat-form');
            if (chatForm) {
              chatForm.outerHTML = '<div class="chat-limit">⚠️ Límite mensual alcanzado. <a href="/pricing">Actualiza →</a></div>';
            }
          }
        }
      }
    } catch (e) {
      messagesEl.removeChild(typingEl);
      addMessage('assistant', '❌ Error de conexión. Intenta de nuevo.');
    }
    sendBtn.disabled = false;
    scrollToBottom();
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.dispatchEvent(new Event('submit')); }
  });

  loadHistory();
}

// ===== NEW ROADMAP — SPINNER =====
function initNewRoadmapForm() {
  const form = document.getElementById('form-nuevo-roadmap');
  if (!form) return;
  form.addEventListener('submit', () => {
    document.getElementById('form-container').style.display = 'none';
    document.getElementById('spinner-container').style.display = 'block';
  });
}

// ===== STRIPE CHECKOUT =====
async function iniciarPago(plan) {
  const btn = document.getElementById('btn-' + plan);
  if (btn) { btn.disabled = true; btn.textContent = 'Redirigiendo...'; }
  try {
    const res  = await fetch('/payments/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan })
    });
    const data = await res.json();
    if (data.url) {
      window.location.href = data.url;
    } else {
      alert('Error al iniciar el pago. Verifica la configuración de Stripe.');
      if (btn) { btn.disabled = false; btn.textContent = 'Suscribirse'; }
    }
  } catch (e) {
    alert('Error de conexión.');
    if (btn) { btn.disabled = false; btn.textContent = 'Suscribirse'; }
  }
}

// ===== ELIMINAR ROADMAP =====
async function eliminarRoadmap(roadmapId) {
  if (!confirm('¿Seguro que quieres eliminar este roadmap? Esta acción no se puede deshacer.')) return;
  try {
    const res = await fetch('/roadmaps/' + roadmapId, { method: 'DELETE' });
    if (res.ok) window.location.reload();
  } catch (e) { alert('Error al eliminar el roadmap.'); }
}

// ===== MODAL RESEÑA — con gestión de focus =====
function mostrarModalResena(roadmapId) {
  const modal = document.getElementById('modal-resena');
  if (!modal) return;
  modal.style.display = 'flex';
  modal.dataset.roadmapId = roadmapId;
  modal._previousFocus = document.activeElement;
  const firstBtn = modal.querySelector('button');
  if (firstBtn) firstBtn.focus();
}

function cerrarModalResena(irARoadmap) {
  const modal = document.getElementById('modal-resena');
  if (!modal) return;
  modal.style.display = 'none';
  if (modal._previousFocus) modal._previousFocus.focus();
  if (irARoadmap) window.location.href = '/roadmaps/' + modal.dataset.roadmapId;
}

async function abrirTrustpilotYMarcar() {
  try { await fetch('/api/resena-completada', { method: 'POST' }); } catch(e) {}
  window.open('https://www.trustpilot.com/review/roadmapia.com', '_blank');
  const btn = document.getElementById('btn-resena-trustpilot');
  if (btn) { btn.textContent = '✅ ¡Gracias! Ya tienes +5 mensajes'; btn.disabled = true; }
  setTimeout(() => cerrarModalResena(true), 3000);
}

// ===== SOPORTE FLOTANTE =====
function toggleSupport() {
  const panel = document.getElementById('support-panel');
  const badge = document.getElementById('support-badge');
  if (!panel) return;
  const isOpen = panel.classList.toggle('open');
  if (badge) badge.classList.add('hidden');
  if (isOpen) {
    const firstFocusable = panel.querySelector('button, input, textarea');
    if (firstFocusable) firstFocusable.focus();
  }
}

function showView(viewId) {
  ['support-view-faqs','support-view-answer','support-view-form','support-view-sent'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = id === viewId ? 'flex' : 'none';
  });
  const footer = document.getElementById('support-main-footer');
  if (footer) footer.style.display = viewId === 'support-view-faqs' ? 'block' : 'none';
}

function showFaqs()        { showView('support-view-faqs'); }
function showContactForm() { showView('support-view-form'); }

function selectFaq(btn) {
  const answerEl = document.getElementById('support-answer-text');
  if (answerEl) answerEl.textContent = btn.dataset.answer;
  showView('support-view-answer');
}

// submitSupportForm — lee datos del propio formulario via FormData (sin ID duplicados)
async function submitSupportForm(e, form) {
  e.preventDefault();
  const fd      = new FormData(form || e.target);
  const nombre  = (fd.get('nombre')  || '').trim();
  const email   = (fd.get('email')   || '').trim();
  const mensaje = (fd.get('mensaje') || '').trim();
  const btn     = (form || e.target).querySelector('.support-submit-btn');
  if (!nombre || !email || !mensaje) return;
  btn.disabled = true;
  btn.textContent = 'Enviando…';
  try {
    const res  = await fetch('/api/soporte', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre, email, mensaje })
    });
    const data = await res.json();
    if (data.ok && data.auto_respuesta) {
      showView('support-view-answer');
      const answerEl = document.getElementById('support-answer-text');
      if (answerEl) answerEl.textContent = data.auto_respuesta;
      const answerFooter = document.querySelector('#support-view-answer .support-answer-footer');
      if (answerFooter) {
        answerFooter.textContent = '';
        const p = document.createElement('p');
        p.className = 'support-sub';
        p.textContent = '✅ Respondido automáticamente';
        const btnVolver = document.createElement('button');
        btnVolver.className = 'support-faq-btn';
        btnVolver.style.marginTop = '0.4rem';
        btnVolver.textContent = '¿No es lo que buscabas?';
        btnVolver.onclick = showContactForm;
        answerFooter.appendChild(p);
        answerFooter.appendChild(btnVolver);
      }
    } else if (data.ok) {
      showView('support-view-sent');
    } else {
      btn.disabled = false;
      btn.textContent = 'Enviar consulta →';
      alert('Error al enviar. Por favor escríbenos a soporte@roadmapia.com');
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Enviar consulta →';
    alert('Error de conexión. Por favor inténtalo de nuevo.');
  }
}

// ===== FAQ LANDING — accesible por teclado =====
function toggleFaqItem(item) {
  const isOpen = item.classList.contains('open');
  document.querySelectorAll('.faq-land-item.open').forEach(el => {
    el.classList.remove('open');
    el.setAttribute('aria-expanded', 'false');
  });
  if (!isOpen) {
    item.classList.add('open');
    item.setAttribute('aria-expanded', 'true');
  }
}

// ===== MOBILE MENU =====
function toggleMobileMenu() {
  const links = document.getElementById('navbar-links');
  const right = document.getElementById('navbar-right');
  const btn   = document.getElementById('hamburger');
  if (!links) return;
  const isOpen = links.classList.toggle('open');
  btn.classList.toggle('open');
  btn.setAttribute('aria-expanded', String(isOpen));
  if (right) right.classList.toggle('menu-open', isOpen);
}

// ===== SCROLL REVEAL =====
function initScrollReveal() {
  const els = document.querySelectorAll('.reveal');
  if (!els.length) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
    });
  }, { threshold: 0.05, rootMargin: '0px 0px -40px 0px' });
  els.forEach(el => observer.observe(el));
}

// ===== STATS COUNTER — con caché sessionStorage (5 min) =====
async function loadStats() {
  const elUsers    = document.getElementById('stat-usuarios');
  const elRoadmaps = document.getElementById('stat-roadmaps');
  if (!elUsers && !elRoadmaps) return;

  function applyStats(data) {
    if (elUsers)    elUsers.textContent    = data.usuarios > 0 ? data.usuarios.toLocaleString('es')  : 'Lanzamiento';
    if (elRoadmaps) elRoadmaps.textContent = data.roadmaps > 0 ? data.roadmaps.toLocaleString('es')  : 'Beta';
  }

  try {
    const cached = sessionStorage.getItem('rm_stats');
    if (cached) {
      const { data, ts } = JSON.parse(cached);
      if (Date.now() - ts < 5 * 60 * 1000) { applyStats(data); return; }
    }
  } catch (_) {}

  try {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    try { sessionStorage.setItem('rm_stats', JSON.stringify({ data, ts: Date.now() })); } catch (_) {}
    applyStats(data);
  } catch (e) { /* silencioso */ }
}

// ===== ADSENSE — carga diferida (solo Free) =====
// El script de AdSense es el recurso de terceros más pesado (≈278 KiB, ~190 KiB sin usar
// en la carga inicial). Se difiere hasta la primera interacción del usuario o, si no
// interactúa, tras unos segundos de inactividad — así no compite con el render inicial.
function initLazyAdsense() {
  const clientId = document.body.dataset.adsClient;
  if (!clientId) return;

  let loaded = false;
  const events = ['scroll', 'mousemove', 'touchstart', 'keydown', 'click'];

  function load() {
    if (loaded) return;
    loaded = true;
    events.forEach(ev => window.removeEventListener(ev, load));
    clearTimeout(timer);
    const s = document.createElement('script');
    s.async = true;
    s.crossOrigin = 'anonymous';
    s.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${clientId}`;
    document.head.appendChild(s);
  }

  events.forEach(ev => window.addEventListener(ev, load, { passive: true, once: true }));
  const timer = setTimeout(load, 4000);
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  initNewRoadmapForm();
  initScrollReveal();
  loadStats();
  initLazyAdsense();
});
