// Reactive auth state, shared across components.
//
// localStorage is the source of truth (so the value survives page
// reloads and matches what the axios interceptor reads), but every
// component that needs to react to login/logout reads from these
// refs instead of polling localStorage. We mirror writes back to
// localStorage and listen for `storage` events so multi-tab use
// stays in sync (sign out in one tab → other tabs see it).
//
// Keys:
//   fm_token  : JWT bearer token (string)
//   fm_user   : JSON-encoded {username, role}

import { ref, computed, readonly } from 'vue'

const TOKEN_KEY = 'fm_token'
const USER_KEY  = 'fm_user'

function readToken() {
  return localStorage.getItem(TOKEN_KEY)
}
function readUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// Module-scoped refs — shared by every importer (Vue makes refs
// reactive across components without needing Pinia for this).
const _token = ref(readToken())
const _user  = ref(readUser())

// Listen once for cross-tab changes. Adding the listener at module
// load time is fine because the module is only imported in the
// browser bundle.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === TOKEN_KEY) _token.value = readToken()
    if (e.key === USER_KEY)  _user.value  = readUser()
  })
}

export function useAuth() {
  const isAuthenticated = computed(() => !!_token.value)

  function setSession({ token, username, role }) {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify({ username, role: role || 'user' }))
    _token.value = token
    _user.value  = { username, role: role || 'user' }
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    _token.value = null
    _user.value  = null
  }

  return {
    token: readonly(_token),
    user: readonly(_user),
    isAuthenticated,
    setSession,
    clearSession,
  }
}
