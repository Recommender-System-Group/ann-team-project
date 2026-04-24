// ══════════════════════════════════════════
//  auth.js — Utilitaire JWT partagé FolioDB
//  Inclure dans chaque page HTML avant le <script> principal
// ══════════════════════════════════════════

const API = 'http://localhost:8000';

// Récupérer le token JWT stocké
function getToken() {
  return localStorage.getItem('folio_token');
}

// Headers avec JWT pour chaque fetch
function authHeaders() {
  const token = getToken();
  return {
    'Content-Type': 'application/json',
    ...(token && { 'Authorization': 'Bearer ' + token })
  };
}

// Vérifier session — redirige vers login si absent
function requireAuth() {
  const token = getToken();

  if (!token) {
    window.location.href = 'login.html';
    return null;
  }

  try {
    const session = JSON.parse(localStorage.getItem('folio_session'));
    
    return {
      token: token,
      ...session
    };
  } catch {
    logout();
    return null;
  }
}

// Déconnexion complète
function logout() {
  localStorage.removeItem('folio_token');
  localStorage.removeItem('folio_session');
  localStorage.removeItem('folio_prefs');
  window.location.href = 'login.html';
}

// Fetch avec JWT automatique — remplace fetch() standard
// Redirige vers login si 401 (token expiré)
async function apiFetch(endpoint, options) {
  options = options || {};

  const res = await fetch(API + endpoint, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {})
    }
  });

  if (res.status === 401) {
    logout();
    return null;
  }

  try {
    return await res.json();
  } catch {
    return { error: "Réponse invalide du serveur" };
  }
}