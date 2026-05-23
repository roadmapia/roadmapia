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
    } catch (e) {
      console.error('Error guardando checklist:', e);
    }
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
      const item = cb.closest('.check-item');
      item.classList.toggle('checked', cb.checked);
    });
  }

  items.forEach(cb => {
    cb.addEventListener('change', saveChecklist);
  });

  // Inicializar estado
  const initialChecklist = Array.from(items).map(cb => cb.checked);
  updateCompleteBtn(initialChecklist);
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
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');
  if (!form || !messagesEl) return;

  // Cargar historial
  async function loadHistory() {
    try {
      const res = await fetch(`/tutor/${roadmapId}/${leccionId}/historial`);
      const data = await res.json();
      data.mensajes.forEach(m => addMessage(m.rol, m.contenido));
      scrollToBottom();
    } catch (e) {
      console.error('Error cargando historial:', e);
    }
  }

  function addMessage(rol, contenido) {
    const div = document.createElement('div');
    div.className = `msg ${rol}`;
    if (rol === 'assistant' && typeof marked !== 'undefined') {
      div.innerHTML = marked.parse(contenido);
    } else {
      div.textContent = contenido;
    }
    messagesEl.appendChild(div);
    return div;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

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
      const res = await fetch(`/tutor/${roadmapId}/${leccionId}/mensaje`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensaje: msg })
      });
      const data = await res.json();
      messagesEl.removeChild(typingEl);

      if (data.error) {
        const errEl = addMessage('assistant', `⚠️ ${data.error}`);
        errEl.style.color = 'var(--red)';
      } else {
        addMessage('assistant', data.respuesta);
      }
    } catch (e) {
      messagesEl.removeChild(typingEl);
      addMessage('assistant', '❌ Error de conexión. Intenta de nuevo.');
    }

    sendBtn.disabled = false;
    scrollToBottom();
  });

  // Ctrl+Enter para enviar
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event('submit'));
    }
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
  const btn = document.getElementById(`btn-${plan}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Redirigiendo...'; }
  try {
    const res = await fetch('/payments/checkout', {
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
    const res = await fetch(`/roadmaps/${roadmapId}`, { method: 'DELETE' });
    if (res.ok) window.location.reload();
  } catch (e) {
    alert('Error al eliminar el roadmap.');
  }
}

// ===== MODAL RESEÑA =====
function mostrarModalResena(roadmapId) {
  const modal = document.getElementById('modal-resena');
  if (modal) {
    modal.style.display = 'flex';
    // Guardar roadmapId para redirigir al cerrar
    modal.dataset.roadmapId = roadmapId;
  }
}

function cerrarModalResena(irARoadmap) {
  const modal = document.getElementById('modal-resena');
  if (!modal) return;
  modal.style.display = 'none';
  if (irARoadmap) {
    window.location.href = `/roadmaps/${modal.dataset.roadmapId}`;
  }
}

async function abrirTrustpilotYMarcar() {
  // Marcar reseña en el servidor → +5 mensajes
  try {
    await fetch('/api/resena-completada', { method: 'POST' });
  } catch(e) {}
  // Abrir Trustpilot en nueva pestaña
  window.open('https://www.trustpilot.com/review/roadmapia.com', '_blank');
  // Actualizar el botón
  const btn = document.getElementById('btn-resena-trustpilot');
  if (btn) {
    btn.textContent = '✅ ¡Gracias! Ya tienes +5 mensajes';
    btn.disabled = true;
  }
  // Cerrar modal después de 3 segundos
  setTimeout(() => cerrarModalResena(true), 3000);
}

// ===== SOPORTE FLOTANTE =====
function toggleSupport() {
  const panel = document.getElementById('support-panel');
  const badge = document.getElementById('support-badge');
  if (!panel) return;
  panel.classList.toggle('open');
  if (badge) badge.classList.add('hidden');
}

function showView(viewId) {
  const views = ['support-view-faqs', 'support-view-answer', 'support-view-form', 'support-view-sent'];
  views.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = id === viewId ? 'flex' : 'none';
  });
  // Ocultar footer principal en vistas secundarias
  const footer = document.getElementById('support-main-footer');
  if (footer) footer.style.display = viewId === 'support-view-faqs' ? 'block' : 'none';
}

function showFaqs() { showView('support-view-faqs'); }
function showContactForm() { showView('support-view-form'); }

function selectFaq(btn) {
  const answerEl = document.getElementById('support-answer-text');
  if (answerEl) answerEl.textContent = btn.dataset.answer;
  showView('support-view-answer');
}

async function submitSupportForm(e) {
  e.preventDefault();
  const nombre  = document.getElementById('sf-nombre')?.value.trim();
  const email   = document.getElementById('sf-email')?.value.trim();
  const mensaje = document.getElementById('sf-mensaje')?.value.trim();
  const btn     = document.querySelector('.support-submit-btn');

  if (!nombre || !email || !mensaje) return;

  btn.disabled = true;
  btn.textContent = 'Enviando…';

  try {
    const res = await fetch('/api/soporte', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre, email, mensaje })
    });
    const data = await res.json();
    if (data.ok && data.auto_respuesta) {
      // ¡Tenemos respuesta automática en la BD!
      showView('support-view-answer');
      const answerEl = document.getElementById('support-answer-text');
      if (answerEl) answerEl.textContent = data.auto_respuesta;
      // Cambiar el subtítulo para indicar que es respuesta automática
      const footer = document.querySelector('#support-view-answer .support-answer-footer');
      if (footer) footer.innerHTML = '<p class="support-sub">✅ Respondido automáticamente · <button class="support-faq-btn" onclick="showContactForm()" style="margin-top:0.4rem">¿No es lo que buscabas?</button></p>';
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

// ===== FAQ LANDING (acordeón) =====
function toggleFaqItem(item) {
  const isOpen = item.classList.contains('open');
  document.querySelectorAll('.faq-land-item.open').forEach(el => el.classList.remove('open'));
  if (!isOpen) item.classList.add('open');
}

// ===== MOBILE MENU =====
function toggleMobileMenu() {
  const links = document.getElementById('navbar-links');
  const right = document.getElementById('navbar-right');
  const btn = document.getElementById('hamburger');
  if (!links) return;
  const isOpen = links.classList.toggle('open');
  btn.classList.toggle('open');
  // En móvil mostrar/ocultar también los botones de auth
  if (right) {
    if (isOpen) {
      right.style.cssText = 'display:flex!important;flex-direction:column;gap:0.5rem;padding:0 1rem 0.5rem;';
      // Mover navbar-right dentro del menú desplegable
      links.appendChild(right);
    } else {
      right.style.cssText = '';
      // Restaurar posición original
      links.parentElement.appendChild(right);
    }
  }
}

// ===== SCROLL REVEAL =====
function initScrollReveal() {
  const els = document.querySelectorAll('.reveal');
  if (!els.length) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        observer.unobserve(e.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach(el => observer.observe(el));
}

// ===== STATS COUNTER =====
async function loadStats() {
  const elUsers = document.getElementById('stat-usuarios');
  const elRoadmaps = document.getElementById('stat-roadmaps');
  if (!elUsers && !elRoadmaps) return;
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (elUsers) elUsers.textContent = data.usuarios > 0 ? data.usuarios.toLocaleString('es') : 'Lanzamiento';
    if (elRoadmaps) elRoadmaps.textContent = data.roadmaps > 0 ? data.roadmaps.toLocaleString('es') : 'Beta';
  } catch (e) { /* silencioso */ }
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  initNewRoadmapForm();
  initScrollReveal();
  loadStats();
});
