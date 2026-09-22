<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'

const API_URL = 'http://127.0.0.1:8000'

/* =========================================================
   AUTH
========================================================= */

const isLoggedIn = ref(!!localStorage.getItem('access_token'))
const appView = ref('user')
const authPortal = ref('user')
const authMode = ref('login')

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')

// Show / Hide Password
const showLoginPassword = ref(false)
const showSignupPassword = ref(false)
const showConfirmPassword = ref(false)

const loginLoading = ref(false)
const signupLoading = ref(false)

const loginError = ref('')
const signupError = ref('')
const signupSuccess = ref('')

async function login() {
  loginError.value = ''
  signupSuccess.value = ''

  if (!email.value || !password.value) {
    loginError.value = 'Please enter email and password.'
    return
  }

  loginLoading.value = true

  try {
    const response = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
        password: password.value
      })
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Login failed.')
    }

    const role = data.user?.role || 'user'

    if (authPortal.value === 'admin' && role !== 'admin') {
      loginError.value = 'Invalid email or password.'
      return
    }

    if (authPortal.value === 'user' && role === 'admin') {
      loginError.value = 'Invalid email or password.'
      return
    }

    localStorage.setItem('access_token', data.access_token)
    isLoggedIn.value = true
    appView.value = role === 'admin' ? 'admin' : 'user'

    email.value = ''
    password.value = ''

    if (appView.value === 'admin') {
      await loadAdminData()
    } else {
      await loadDocuments()
    }
  } catch (error) {
    console.error('Login error:', error)
    loginError.value = error.message || 'Unable to login.'
  } finally {
    loginLoading.value = false
  }
}

async function signup() {
  signupError.value = ''
  signupSuccess.value = ''

  const cleanUsername = username.value.trim()
  const cleanEmail = email.value.trim()

  if (!cleanUsername || !cleanEmail || !password.value || !confirmPassword.value) {
    signupError.value = 'Please fill in all fields.'
    return
  }

  // Password validation
  if (password.value.length < 8) {
    signupError.value = 'Password must be at least 8 characters.'
    return
  }

  if (!/[A-Z]/.test(password.value)) {
    signupError.value = 'Password must contain at least one uppercase letter.'
    return
  }

  if (!/[a-z]/.test(password.value)) {
    signupError.value = 'Password must contain at least one lowercase letter.'
    return
  }

  if (!/[0-9]/.test(password.value)) {
    signupError.value = 'Password must contain at least one number.'
    return
  }

  if (!/[!@#$%^&*(),.?":{}|<>_\-\[\]'/+=;`~]/.test(password.value)) {
    signupError.value = 'Password must contain at least one special character.'
    return
  }

  if (password.value !== confirmPassword.value) {
    signupError.value = 'Passwords do not match.'
    return
  }

  signupLoading.value = true

  try {
    const response = await fetch(`${API_URL}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: cleanUsername,
        email: cleanEmail,
        password: password.value
      })
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Registration failed.')
    }

    signupSuccess.value = 'Account created. Sign in to continue.'

    username.value = ''
    email.value = ''
    password.value = ''
    confirmPassword.value = ''

    authMode.value = 'login'
  } catch (error) {
    console.error('Signup error:', error)
    signupError.value = error.message || 'Unable to create account.'
  } finally {
    signupLoading.value = false
  }
}

function switchAuthMode(mode) {
  authMode.value = mode
  loginError.value = ''
  signupError.value = ''
  signupSuccess.value = ''
  username.value = ''
  email.value = ''
  password.value = ''
  confirmPassword.value = ''
  showLoginPassword.value = false
  showSignupPassword.value = false
  showConfirmPassword.value = false
}

function logout() {
  saveCurrentDocumentChat()
  localStorage.removeItem('access_token')
  isLoggedIn.value = false
  appView.value = 'user'
  authPortal.value = 'user'
  documents.value = []
  selectedDocumentId.value = null
  conversationIds.value = {}
  documentChats.value = {}
  conversationId.value = crypto.randomUUID()
  messages.value = []
  question.value = ''
  loginError.value = ''
  signupError.value = ''
  signupSuccess.value = ''
  authMode.value = 'login'
  showLoginPassword.value = false
  showSignupPassword.value = false
  showConfirmPassword.value = false
}

function openAdminLogin() {
  authPortal.value = 'admin'
  authMode.value = 'login'
  loginError.value = ''
  signupError.value = ''
  signupSuccess.value = ''
  username.value = ''
  email.value = ''
  password.value = ''
  confirmPassword.value = ''
}

function openUserLogin() {
  authPortal.value = 'user'
  authMode.value = 'login'
  loginError.value = ''
  signupError.value = ''
  signupSuccess.value = ''
  username.value = ''
  email.value = ''
  password.value = ''
  confirmPassword.value = ''
}

// ============================================================
// ADMIN DASHBOARD
// ============================================================

const adminLoading = ref(false)
const adminError = ref('')
const adminStats = ref({
  users: { total: 0, active: 0, inactive: 0, admins: 0 },
  documents: { total: 0, processed: 0, failed: 0, processing: 0 },
  queries: { total: 0, cache_hits: 0 }
})
const adminUsers = ref([])
const adminDocuments = ref([])
const adminFailures = ref([])
const adminQueries = ref([])
const adminActionLoading = ref(null)
const adminLastUpdated = ref(null)

const userSearch = ref('')
const userStatusFilter = ref('all')
const userRoleFilter = ref('all')
const documentSearch = ref('')
const documentStatusFilter = ref('all')
const documentTypeFilter = ref('all')
const querySearch = ref('')

const filteredAdminUsers = computed(() => {
  const search = userSearch.value.trim().toLowerCase()
  return adminUsers.value.filter(user => {
    const matchesSearch = !search ||
      String(user.username || '').toLowerCase().includes(search) ||
      String(user.email || '').toLowerCase().includes(search)
    const matchesStatus = userStatusFilter.value === 'all' ||
      (user.is_active ? 'active' : 'inactive') === userStatusFilter.value
    const matchesRole = userRoleFilter.value === 'all' ||
      String(user.role || 'user').toLowerCase() === userRoleFilter.value
    return matchesSearch && matchesStatus && matchesRole
  })
})

const filteredAdminDocuments = computed(() => {
  const search = documentSearch.value.trim().toLowerCase()
  return adminDocuments.value.filter(document => {
    const name = String(document.original_filename || document.filename || '').toLowerCase()
    const uploader = String(document.uploader_username || '').toLowerCase()
    const type = String(document.file_type || '').toLowerCase()
    const status = String(document.processing_status || '').toLowerCase()
    const matchesSearch = !search || name.includes(search) || uploader.includes(search)
    const matchesStatus = documentStatusFilter.value === 'all' || status === documentStatusFilter.value
    const matchesType = documentTypeFilter.value === 'all' || type === documentTypeFilter.value
    return matchesSearch && matchesStatus && matchesType
  })
})

const filteredAdminQueries = computed(() => {
  const search = querySearch.value.trim().toLowerCase()
  return adminQueries.value.filter(query => {
    if (!search) return true
    return String(query.question || '').toLowerCase().includes(search) ||
      String(query.username || '').toLowerCase().includes(search) ||
      String(query.email || '').toLowerCase().includes(search)
  })
})

const adminDocumentTypes = computed(() => {
  return [...new Set(adminDocuments.value.map(document => String(document.file_type || '').toLowerCase()).filter(Boolean))].sort()
})

function clearAdminFilters() {
  userSearch.value = ''
  userStatusFilter.value = 'all'
  userRoleFilter.value = 'all'
  documentSearch.value = ''
  documentStatusFilter.value = 'all'
  documentTypeFilter.value = 'all'
  querySearch.value = ''
}

async function adminFetch(path, options = {}) {
  const token = localStorage.getItem('access_token')
  if (!token) {
    throw new Error('Admin session expired. Please sign in again.')
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`
    }
  })

  const data = await response.json().catch(() => ({}))

  if (response.status === 401) {
    logout()
    throw new Error('Admin session expired. Please sign in again.')
  }

  if (response.status === 403) {
    throw new Error(data.detail || 'Admin access required.')
  }

  if (!response.ok) {
    throw new Error(data.detail || data.message || 'Admin request failed.')
  }

  return data
}

async function loadAdminData() {
  adminLoading.value = true
  adminError.value = ''

  try {
    const [stats, users, documents, failures, queries] = await Promise.all([
      adminFetch('/api/admin/statistics'),
      adminFetch('/api/admin/users'),
      adminFetch('/api/admin/documents'),
      adminFetch('/api/admin/processing-failures'),
      adminFetch('/api/admin/queries')
    ])

    adminStats.value = stats.statistics || adminStats.value
    adminUsers.value = users.users || []
    adminDocuments.value = documents.documents || []
    adminFailures.value = failures.failures || []
    adminQueries.value = queries.queries || []
    adminLastUpdated.value = new Date()
  } catch (error) {
    console.error('Admin dashboard error:', error)
    adminError.value = error.message || 'Failed to load admin dashboard.'
  } finally {
    adminLoading.value = false
  }
}

async function changeUserStatus(user, active) {
  adminActionLoading.value = `status-${user.id}`
  adminError.value = ''

  try {
    await adminFetch(`/api/admin/users/${user.id}/${active ? 'activate' : 'deactivate'}`, {
      method: 'PUT'
    })
    await loadAdminData()
  } catch (error) {
    adminError.value = error.message || 'Failed to update user status.'
  } finally {
    adminActionLoading.value = null
  }
}

async function deleteAdminUser(user) {
  if (user.role === 'admin') {
    adminError.value = 'Admin accounts cannot be deleted from the user management panel.'
    return
  }

  const confirmed = window.confirm(
    `Delete user "${user.username}" permanently?\n\n` +
    `This will remove the user account and associated database records.\n` +
    `This action cannot be undone.\n\n` +
    `Click OK to permanently delete this user.`
  )

  if (!confirmed) return

  adminActionLoading.value = `delete-${user.id}`
  adminError.value = ''

  try {
    await adminFetch(`/api/admin/users/${user.id}`, { method: 'DELETE' })
    await loadAdminData()
  } catch (error) {
    adminError.value = error.message || 'Failed to delete user.'
  } finally {
    adminActionLoading.value = null
  }
}

function enterAdminDashboard() {
  appView.value = 'admin'
  loadAdminData()
}

function formatAdminDate(value) {
  if (!value) return '—'
  const date = new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z'))
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

/* =========================================================
   DOCUMENTS
========================================================= */

const documents = ref([])
const selectedDocumentId = ref(null)
const uploading = ref(false)
const uploadMessage = ref('')
const uploadError = ref('')
const deletingDocument = ref(null)
const fileInput = ref(null)
const isDragging = ref(false)

function openFilePicker() {
  if (fileInput.value) {
    fileInput.value.click()
  }
}

async function loadDocuments() {
  const token = localStorage.getItem('access_token')
  if (!token) return

  try {
    const response = await fetch(`${API_URL}/api/documents`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` }
    })

    if (response.status === 401) {
      logout()
      return
    }

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Failed to load documents.')
    }

    documents.value = data.documents || []

    if (documents.value.length > 0 && selectedDocumentId.value === null) {
      selectedDocumentId.value = documents.value[0].id
      prepareDocumentChat(selectedDocumentId.value)
    }

    const selectedStillExists = documents.value.some(
      document => document.id === selectedDocumentId.value
    )

    if (documents.value.length > 0 && !selectedStillExists) {
      selectedDocumentId.value = documents.value[0].id
      prepareDocumentChat(selectedDocumentId.value)
    }

    if (documents.value.length === 0) {
      selectedDocumentId.value = null
      conversationId.value = crypto.randomUUID()
      messages.value = []
    } else if (selectedDocumentId.value) {
      prepareDocumentChat(selectedDocumentId.value)
    }

    persistChatState()
  } catch (error) {
    console.error('Load documents error:', error)
  }
}

function selectDocument(documentId) {
  // Save the current PDF's chat before switching to another PDF.
  saveCurrentDocumentChat()

  selectedDocumentId.value = documentId
  prepareDocumentChat(documentId)

  chatError.value = ''
  question.value = ''
}

/* =========================================================
   UPLOAD
========================================================= */

async function uploadFile(file) {
  uploadMessage.value = ''
  uploadError.value = ''

  if (!file) return

  const allowedTypes = ['application/pdf', 'image/png', 'image/jpeg']
  const extension = file.name.split('.').pop().toLowerCase()
  const allowedExtensions = ['pdf', 'png', 'jpg', 'jpeg']

  if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(extension)) {
    uploadError.value = 'Only PDF, PNG, JPG and JPEG files are allowed.'
    return
  }

  const maxSize = 100 * 1024 * 1024

  if (file.size > maxSize) {
    uploadError.value = 'File size must not exceed 100 MB.'
    return
  }

  const token = localStorage.getItem('access_token')

  if (!token) {
    logout()
    return
  }

  uploading.value = true

  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_URL}/api/documents/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    })

    const data = await response.json()

    if (response.status === 401) {
      logout()
      return
    }

    if (response.status === 409) {
      uploadError.value = 'This document has already been uploaded.'
      return
    }

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Upload failed.')
    }

    uploadMessage.value = 'Document uploaded.'

    await loadDocuments()

    if (data.document && data.document.id) {
      selectedDocumentId.value = data.document.id
      prepareDocumentChat(selectedDocumentId.value)
    } else if (data.document_id) {
      selectedDocumentId.value = data.document_id
      prepareDocumentChat(selectedDocumentId.value)
    }
  } catch (error) {
    console.error('Upload error:', error)
    uploadError.value = error.message || 'Failed to upload document.'
  } finally {
    uploading.value = false
  }
}

async function handleFileSelect(event) {
  const file = event.target.files[0]
  await uploadFile(file)
  event.target.value = ''
}

function handleDragOver(event) {
  event.preventDefault()
  isDragging.value = true
}

function handleDragLeave() {
  isDragging.value = false
}

async function handleDrop(event) {
  event.preventDefault()
  isDragging.value = false
  const file = event.dataTransfer.files && event.dataTransfer.files[0]
  if (file) {
    await uploadFile(file)
  }
}

/* =========================================================
   DELETE DOCUMENT
========================================================= */

async function deleteDocument(document) {
  const confirmed = window.confirm(
    `Delete "${document.original_filename || document.filename}"?`
  )

  if (!confirmed) {
    return
  }

  const token = localStorage.getItem('access_token')

  if (!token) {
    logout()
    return
  }

  deletingDocument.value = document.id

  try {
    const response = await fetch(`${API_URL}/api/documents/${document.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` }
    })

    const data = await response.json()

    if (response.status === 401) {
      logout()
      return
    }

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Failed to delete document.')
    }

    if (selectedDocumentId.value === document.id) {
      selectedDocumentId.value = null
    }

    await loadDocuments()
  } catch (error) {
    console.error('Delete error:', error)
    uploadError.value = error.message || 'Failed to delete document.'
  } finally {
    deletingDocument.value = null
  }
}

/* =========================================================
   CHAT
========================================================= */

const question = ref('')
const messages = ref([])
const asking = ref(false)
const chatError = ref('')

// Keep a separate conversation and chat state for each document.
// This prevents switching between PDFs from replacing the other PDF's chat.
const conversationId = ref(crypto.randomUUID())
const conversationIds = ref({})
const documentChats = ref({})
const messagesEnd = ref(null)

const CHAT_STATE_KEY = 'docurag_chat_state_v4'

function persistChatState() {
  try {
    localStorage.setItem(CHAT_STATE_KEY, JSON.stringify({
      selectedDocumentId: selectedDocumentId.value,
      conversationIds: conversationIds.value,
      documentChats: documentChats.value
    }))
  } catch (error) {
    console.error('Save chat state error:', error)
  }
}

function restoreChatState() {
  try {
    const saved = localStorage.getItem(CHAT_STATE_KEY)
    if (!saved) return

    const state = JSON.parse(saved)
    conversationIds.value = state.conversationIds || {}
    documentChats.value = state.documentChats || {}

    if (state.selectedDocumentId !== null && state.selectedDocumentId !== undefined) {
      selectedDocumentId.value = state.selectedDocumentId
    }
  } catch (error) {
    console.error('Restore chat state error:', error)
  }
}

function saveCurrentDocumentChat() {
  if (!selectedDocumentId.value) return

  documentChats.value[selectedDocumentId.value] = messages.value.map(message => ({
    ...message,
    sources: message.sources ? [...message.sources] : [],
    imageSources: message.imageSources ? [...message.imageSources] : []
  }))

  persistChatState()
}

function prepareDocumentChat(documentId) {
  if (!conversationIds.value[documentId]) {
    conversationIds.value[documentId] = crypto.randomUUID()
  }

  conversationId.value = conversationIds.value[documentId]
  messages.value = documentChats.value[documentId]
    ? [...documentChats.value[documentId]]
    : []

  persistChatState()
}

watch(
  messages,
  async () => {
    await nextTick()
    if (messagesEnd.value) {
      messagesEnd.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  },
  { deep: true }
)

async function askQuestion() {
  const trimmedQuestion = question.value.trim()

  if (!trimmedQuestion) {
    return
  }

  const token = localStorage.getItem('access_token')

  if (!token) {
    logout()
    return
  }

  if (!selectedDocumentId.value) {
    chatError.value = 'Please select a document first.'
    return
  }

  chatError.value = ''

  messages.value.push({
    role: 'user',
    content: trimmedQuestion
  })

  question.value = ''
  asking.value = true

  try {
    const response = await fetch(`${API_URL}/api/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({
        question: trimmedQuestion,
        conversation_id: conversationId.value,
        document_id: selectedDocumentId.value
      })
    })

    const data = await response.json()

    if (response.status === 401) {
      logout()
      return
    }

    if (!response.ok) {
      throw new Error(data.detail || data.message || 'Failed to get answer.')
    }

    messages.value.push({
      role: 'assistant',
      content: data.answer || 'No answer was generated.',
      confidence: data.confidence ?? 0,
      sources: data.sources || [],
      imageSources: data.image_sources || [],
      cacheHit: data.cache_hit || false
    })

    // Keep the current document's chat state in memory.
    saveCurrentDocumentChat()
  } catch (error) {
    console.error('Ask error:', error)
    chatError.value = error.message || 'Failed to process your question.'
  } finally {
    asking.value = false
  }
}

async function newChat() {
  const token = localStorage.getItem('access_token')
  if (!token) return

  // New chat applies only to the currently selected document.
  // Other PDFs keep their existing conversations.
  if (selectedDocumentId.value) {
    saveCurrentDocumentChat()
    documentChats.value[selectedDocumentId.value] = []
  }

  try {
    const response = await fetch(`${API_URL}/api/new_chat`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    })

    const data = await response.json()

    conversationId.value = response.ok
      ? (data.conversation_id || crypto.randomUUID())
      : crypto.randomUUID()
  } catch (error) {
    console.error('New chat error:', error)
    conversationId.value = crypto.randomUUID()
  }

  if (selectedDocumentId.value) {
    conversationIds.value[selectedDocumentId.value] = conversationId.value
  }

  messages.value = []
  question.value = ''
  chatError.value = ''
  persistChatState()
}




async function normalChat() {
  const trimmedQuestion = question.value.trim()

  if (!trimmedQuestion) {
    return
  }

  const token = localStorage.getItem('access_token')

  if (!token) {
    logout()
    return
  }

  chatError.value = ''

  // Show user's message immediately
  messages.value.push({
    role: 'user',
    content: trimmedQuestion
  })

  question.value = ''
  asking.value = true

  try {
    const response = await fetch(`${API_URL}/chat/normal`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({
        message: trimmedQuestion
      })
    })

    const data = await response.json()

    if (response.status === 401) {
      logout()
      return
    }

    if (!response.ok) {
      throw new Error(
        data.detail ||
        data.message ||
        'Failed to get Gemini response.'
      )
    }

    // Add Gemini response to the same chatbox
    messages.value.push({
      role: 'assistant',
      content: data.answer || 'No answer was generated.',
      confidence: null,
      sources: [],
      imageSources: [],
      cacheHit: false,
      normalChat: true
    })

  } catch (error) {
    console.error('Normal chat error:', error)

    chatError.value =
      error.message ||
      'Failed to process your message.'
  } finally {
    asking.value = false
  }
}

function handleChatSubmit() {
  if (selectedDocumentId.value) {
    askQuestion()
  } else {
    normalChat()
  }
}




/* =========================================================
   DISPLAY HELPERS
========================================================= */

function formatConfidence(confidence) {
  const value = Number(confidence || 0)
  return `${(value * 100).toFixed(1)}%`
}

function confidenceValue(confidence) {
  const value = Number(confidence || 0) * 100
  return Math.max(0, Math.min(100, value))
}

function getDocumentName(document) {
  return document.original_filename || document.filename || 'Unnamed document'
}

function getFileKind(document) {
  const name = getDocumentName(document)
  const extension = name.split('.').pop().toLowerCase()
  if (extension === 'pdf') return 'PDF'
  if (['png', 'jpg', 'jpeg'].includes(extension)) return 'IMG'
  return 'DOC'
}

function formatFileSize(bytes) {
  const size = Number(bytes)
  if (!Number.isFinite(size) || size <= 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatStatus(status) {
  const value = String(status || 'uploaded').toLowerCase()
  return value.charAt(0).toUpperCase() + value.slice(1)
}

onMounted(async () => {
  restoreChatState()

  const token = localStorage.getItem('access_token')
  if (!token) return

  try {
    const response = await fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` }
    })

    if (!response.ok) {
      localStorage.removeItem('access_token')
      isLoggedIn.value = false
      return
    }

    const data = await response.json()
    const role = data.user?.role || 'user'

    isLoggedIn.value = true
    appView.value = role === 'admin' ? 'admin' : 'user'
    authPortal.value = role === 'admin' ? 'admin' : 'user'

    if (role === 'admin') {
      await loadAdminData()
    } else {
      await loadDocuments()
    }
  } catch (error) {
    console.error('Session restore error:', error)
    localStorage.removeItem('access_token')
    isLoggedIn.value = false
  }
})
</script>

<template>

  <!-- =====================================================
       AUTHENTICATION
  ====================================================== -->

  <div v-if="!isLoggedIn" class="auth-page">

    <div class="auth-ambient" aria-hidden="true"></div>

    <div class="auth-card">

      <div class="auth-brand">
        <span class="brand-mark brand-mark--lg">DR</span>
        <div>
          <h1 class="auth-title">DocuRAG</h1>
          <p class="auth-subtitle">Ask questions, get answers with sources.</p>
        </div>
      </div>

      <div class="auth-portal-badge" :class="{ 'auth-portal-badge--admin': authPortal === 'admin' }">
        {{ authPortal === 'admin' ? 'Administrator Access' : 'User Access' }}
      </div>

      <div v-if="authPortal === 'user'" class="auth-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          class="auth-tab"
          :class="{ 'auth-tab--active': authMode === 'login' }"
          :aria-selected="authMode === 'login'"
          @click="switchAuthMode('login')"
        >
          Sign in
        </button>
        <button
          type="button"
          role="tab"
          class="auth-tab"
          :class="{ 'auth-tab--active': authMode === 'signup' }"
          :aria-selected="authMode === 'signup'"
          @click="switchAuthMode('signup')"
        >
          Create account
        </button>
      </div>

      <div v-if="authPortal === 'admin'" class="admin-login-note">
        <strong>Admin Login</strong>
        <span>Sign in with your administrator account to access the control panel.</span>
      </div>

      <!-- LOGIN -->
      <form v-if="authMode === 'login'" class="auth-form" @submit.prevent="login">

        <div v-if="loginError" class="auth-alert auth-alert--danger">{{ loginError }}</div>
        <div v-if="signupSuccess" class="auth-alert auth-alert--success">{{ signupSuccess }}</div>

        <label class="field-label" for="login-email">Email</label>
        <input
          id="login-email"
          v-model="email"
          type="email"
          class="field-input"
          placeholder="you@example.com"
          autocomplete="email"
        />

        <label class="field-label" for="login-password">Password</label>

        <div class="password-wrapper">
          <input
            id="login-password"
            v-model="password"
            :type="showLoginPassword ? 'text' : 'password'"
            class="field-input password-input"
            placeholder="Enter your password"
            autocomplete="current-password"
          />

          <button
            type="button"
            class="password-toggle"
            :aria-label="showLoginPassword ? 'Hide password' : 'Show password'"
            :title="showLoginPassword ? 'Hide password' : 'Show password'"
            @click="showLoginPassword = !showLoginPassword"
          >
            <svg
              v-if="showLoginPassword"
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M3 3l18 18" />
              <path d="M10.58 10.58a2 2 0 0 0 2.83 2.83" />
              <path d="M9.88 4.24A9.84 9.84 0 0 1 12 4c5 0 9.27 3.11 11 8a18.5 18.5 0 0 1-2.06 3.66" />
              <path d="M6.61 6.61A18.5 18.5 0 0 0 1 12c1.73 4.89 6 8 11 8a9.84 9.84 0 0 0 4.24-.93" />
            </svg>

            <svg
              v-else
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M2.06 12.35a1 1 0 0 1 0-.7C3.76 7.6 7.54 5 12 5s8.24 2.6 9.94 6.65a1 1 0 0 1 0 .7C20.24 16.4 16.46 19 12 19s-8.24-2.6-9.94-6.65Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>

        <button type="submit" class="btn btn-ink w-100" :disabled="loginLoading">
          <span v-if="loginLoading">Signing in…</span>
          <span v-else>{{ authPortal === 'admin' ? 'Admin Sign in' : 'Sign in' }}</span>
        </button>

      </form>

      <!-- SIGN UP -->
      <form v-else-if="authPortal === 'user'" class="auth-form" @submit.prevent="signup">

        <div v-if="signupError" class="auth-alert auth-alert--danger">{{ signupError }}</div>

        <label class="field-label" for="signup-username">Username</label>
        <input
          id="signup-username"
          v-model="username"
          type="text"
          class="field-input"
          placeholder="Choose a username"
          autocomplete="username"
        />

        <label class="field-label" for="signup-email">Email</label>
        <input
          id="signup-email"
          v-model="email"
          type="email"
          class="field-input"
          placeholder="you@example.com"
          autocomplete="email"
        />

        <label class="field-label" for="signup-password">Password</label>

        <div class="password-wrapper">
          <input
            id="signup-password"
            v-model="password"
            :type="showSignupPassword ? 'text' : 'password'"
            class="field-input password-input"
            placeholder="8+ chars, A-Z, a-z, 0-9 & special character"
            autocomplete="new-password"
          />

          <button
            type="button"
            class="password-toggle"
            :aria-label="showSignupPassword ? 'Hide password' : 'Show password'"
            :title="showSignupPassword ? 'Hide password' : 'Show password'"
            @click="showSignupPassword = !showSignupPassword"
          >
            <svg
              v-if="showSignupPassword"
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M3 3l18 18" />
              <path d="M10.58 10.58a2 2 0 0 0 2.83 2.83" />
              <path d="M9.88 4.24A9.84 9.84 0 0 1 12 4c5 0 9.27 3.11 11 8a18.5 18.5 0 0 1-2.06 3.66" />
              <path d="M6.61 6.61A18.5 18.5 0 0 0 1 12c1.73 4.89 6 8 11 8a9.84 9.84 0 0 0 4.24-.93" />
            </svg>

            <svg
              v-else
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M2.06 12.35a1 1 0 0 1 0-.7C3.76 7.6 7.54 5 12 5s8.24 2.6 9.94 6.65a1 1 0 0 1 0 .7C20.24 16.4 16.46 19 12 19s-8.24-2.6-9.94-6.65Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>

        <label class="field-label" for="signup-confirm">Confirm password</label>

        <div class="password-wrapper">
          <input
            id="signup-confirm"
            v-model="confirmPassword"
            :type="showConfirmPassword ? 'text' : 'password'"
            class="field-input password-input"
            placeholder="Re-enter your password"
            autocomplete="new-password"
          />

          <button
            type="button"
            class="password-toggle"
            :aria-label="showConfirmPassword ? 'Hide password' : 'Show password'"
            :title="showConfirmPassword ? 'Hide password' : 'Show password'"
            @click="showConfirmPassword = !showConfirmPassword"
          >
            <svg
              v-if="showConfirmPassword"
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M3 3l18 18" />
              <path d="M10.58 10.58a2 2 0 0 0 2.83 2.83" />
              <path d="M9.88 4.24A9.84 9.84 0 0 1 12 4c5 0 9.27 3.11 11 8a18.5 18.5 0 0 1-2.06 3.66" />
              <path d="M6.61 6.61A18.5 18.5 0 0 0 1 12c1.73 4.89 6 8 11 8a9.84 9.84 0 0 0 4.24-.93" />
            </svg>

            <svg
              v-else
              class="password-eye-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M2.06 12.35a1 1 0 0 1 0-.7C3.76 7.6 7.54 5 12 5s8.24 2.6 9.94 6.65a1 1 0 0 1 0 .7C20.24 16.4 16.46 19 12 19s-8.24-2.6-9.94-6.65Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>

        <button type="submit" class="btn btn-ink w-100" :disabled="signupLoading">
          <span v-if="signupLoading">Creating account…</span>
          <span v-else>Create account</span>
        </button>

      </form>

      <button
        v-if="authPortal === 'user'"
        type="button"
        class="auth-admin-link"
        @click="openAdminLogin"
      >
        Administrator? Open Admin Login →
      </button>

      <button
        v-else
        type="button"
        class="auth-admin-link"
        @click="openUserLogin"
      >
        ← Back to User Login
      </button>

    </div>

  </div>

  <!-- =====================================================
       MAIN APP
  ====================================================== -->

  <div v-else-if="appView === 'user'" class="app">

    <nav class="topbar">

      <div class="topbar-brand">
        <span class="brand-mark">DR</span>
        <span class="topbar-title">DocuRAG</span>
      </div>

      <div class="topbar-actions">
        <button class="btn btn-outline-brass btn-sm" @click="newChat">New chat</button>
        <button class="btn btn-ghost btn-sm" @click="logout">Sign out</button>
      </div>

    </nav>

    <div class="workspace">

      <!-- ================================================
           SIDEBAR
      ================================================= -->

      <aside class="sidebar">

        <div class="sidebar-section">

          <div class="sidebar-heading">
            <h2>Your documents</h2>
            <span v-if="documents.length" class="sidebar-count">{{ documents.length }}</span>
          </div>

          <input
            ref="fileInput"
            type="file"
            class="hidden-input"
            accept=".pdf,.png,.jpg,.jpeg"
            @change="handleFileSelect"
          />

          <div
            class="dropzone dropzone--polished"
            role="button"
            tabindex="0"
            aria-label="Add a document"
            :class="{ 'dropzone--active': isDragging, 'dropzone--busy': uploading }"
            @click="openFilePicker"
            @keydown.enter.prevent="openFilePicker"
            @keydown.space.prevent="openFilePicker"
            @dragover="handleDragOver"
            @dragleave="handleDragLeave"
            @drop="handleDrop"
          >
            <span v-if="uploading" class="dropzone-content">
              <span class="upload-icon upload-icon--spin">↻</span>
              <strong>Uploading document…</strong>
              <small>Please wait while DocuRAG processes your file.</small>
            </span>
            <span v-else class="dropzone-content">
              <span class="upload-icon">↑</span>
              <strong>Add a document</strong>
              <small>Drop PDF or image here, or click to browse</small>
              <em>PDF · PNG · JPG · JPEG</em>
            </span>
          </div>

          <div v-if="uploadMessage" class="inline-note inline-note--success">{{ uploadMessage }}</div>
          <div v-if="uploadError" class="inline-note inline-note--danger">{{ uploadError }}</div>

          <ul v-if="documents.length > 0" class="document-list">
            <li
              v-for="document in documents"
              :key="document.id"
              class="document-item"
              :class="{ 'document-item--active': selectedDocumentId === document.id }"
              @click="selectDocument(document.id)"
            >
              <span
                class="document-kind"
                :class="`document-kind--${getFileKind(document).toLowerCase()}`"
                aria-hidden="true"
              >
                {{ getFileKind(document) }}
              </span>

              <span class="document-info">
                <span class="document-name" :title="getDocumentName(document)">
                  {{ getDocumentName(document) }}
                </span>

                <span class="document-meta">
                  <span class="document-type-label">
                    {{ getFileKind(document) }}<span v-if="document.file_size"> · {{ formatFileSize(document.file_size) }}</span>
                  </span>
                </span>

                <span
                  class="document-status"
                  :class="`document-status--${String(document.processing_status || 'uploaded').toLowerCase()}`"
                >
                  <span class="status-dot"></span>
                  {{ formatStatus(document.processing_status) }}
                </span>
              </span>
              <button
                type="button"
                class="document-remove"
                title="Delete document"
                :disabled="deletingDocument === document.id"
                @click.stop="deleteDocument(document)"
              >
                <span v-if="deletingDocument === document.id">…</span>
                <span v-else>&times;</span>
              </button>
            </li>
          </ul>

          <div v-else class="empty-note empty-note--documents">
            <div class="empty-state-icon">◇</div>
            <p>No documents yet</p>
            <p class="empty-note-sub">Upload a PDF or image above to start asking questions.</p>
          </div>

        </div>

        <div class="sidebar-section sidebar-section--muted">

          <h2>Recent questions</h2>

          <div v-if="messages.length === 0" class="empty-note">
            <p class="empty-note-sub">Questions you ask will show up here.</p>
          </div>

          <ul v-else class="recent-list">
            <li v-for="(message, index) in messages.filter(m => m.role === 'user')" :key="index">
              {{ message.content }}
            </li>
          </ul>

        </div>

      </aside>

      <!-- ================================================
           CHAT AREA
      ================================================= -->

      <main class="chat-area">

        <div class="chat-container">

          <div v-if="messages.length === 0" class="welcome welcome--polished">
            <div class="welcome-badge">AI DOCUMENT ASSISTANT</div>
            <span class="brand-mark brand-mark--lg welcome-logo">DR</span>
            <h1>Ask your documents anything.</h1>
            <p>Upload a document and let DocuRAG find the relevant information, answer your question, and show you where it came from.</p>
            <div class="welcome-features">
              <span>⌕ Natural-language search</span>
              <span>◈ PDF &amp; image support</span>
              <span>✓ Source-backed answers</span>
            </div>
          </div>

          <div v-else class="messages" aria-live="polite">

            <div
              v-for="(message, index) in messages"
              :key="index"
              class="message-row"
              :class="message.role === 'user' ? 'message-row--user' : 'message-row--assistant'"
            >

              <template v-if="message.role === 'user'">
                <div class="bubble bubble--user">
                  <span class="visually-hidden">You said:</span>
                  {{ message.content }}
                </div>
              </template>

              <template v-else>
                <span class="brand-mark brand-mark--sm" aria-hidden="true">DR</span>
                <div class="bubble bubble--assistant">
                  <span class="visually-hidden">DocuRAG answered:</span>
                  <p class="bubble-text">{{ message.content }}</p>

                  <div class="confidence-row">
                    <div class="confidence-meter">
                      <div
                        class="confidence-fill"
                        :style="{ width: confidenceValue(message.confidence) + '%' }"
                      ></div>
                    </div>
                    <span class="confidence-label">{{ formatConfidence(message.confidence) }} confidence</span>
                    <span v-if="message.cacheHit" class="cache-tag">from cache</span>
                  </div>

                  <div v-if="message.sources && message.sources.length" class="citation-group">
                    <span class="citation-heading">Sources</span>
                    <div class="citation-list">
                      <span
                        v-for="(source, sourceIndex) in message.sources"
                        :key="'s' + sourceIndex"
                        class="citation-chip"
                      >
                        <span class="citation-index">{{ sourceIndex + 1 }}</span>
                        {{ source.document_name || 'Document' }}, page {{ source.page_number || '?' }}
                      </span>
                    </div>
                  </div>

                  <div v-if="message.imageSources && message.imageSources.length" class="citation-group">
                    <span class="citation-heading">Image sources</span>
                    <div class="citation-list">
                      <span
                        v-for="(image, imageIndex) in message.imageSources"
                        :key="'i' + imageIndex"
                        class="citation-chip citation-chip--image"
                      >
                        <span class="citation-index">{{ imageIndex + 1 }}</span>
                        {{ image.document_name || 'Document' }}, page {{ image.page_number || '?' }}
                      </span>
                    </div>
                  </div>
                </div>
              </template>

            </div>

            <div v-if="asking" class="message-row message-row--assistant">
              <span class="brand-mark brand-mark--sm" aria-hidden="true">DR</span>
              <div class="bubble bubble--assistant bubble--typing">
                <span class="typing-dots"><span></span><span></span><span></span></span>
                Reading through the document…
              </div>
            </div>

            <div ref="messagesEnd"></div>

          </div>

          <div v-if="chatError" class="inline-note inline-note--danger chat-error">{{ chatError }}</div>

          <div class="composer">
            <input
              v-model="question"
              type="text"
              class="composer-input"
              placeholder="Ask a question about the selected document…"
              :disabled="asking"
              @keyup.enter="handleChatSubmit"
            />
            <button
              class="btn btn-ink"
              :disabled="asking || !question.trim()"
              :aria-label="asking ? 'Searching documents' : 'Ask DocuRAG'"
              @click="handleChatSubmit"
            >
              <span v-if="asking">…</span>
              <span v-else>Ask</span>
            </button>
          </div>

          <p v-if="selectedDocumentId" class="composer-hint">
            Asking about
            <strong>{{ getDocumentName(documents.find(document => document.id === selectedDocumentId) || {}) }}</strong>
          </p>
          <p v-else class="composer-hint composer-hint--warn">
            Select a document from the archive before asking a question.
          </p>

        </div>

      </main>

    </div>

  </div>

  <!-- =====================================================
       ADMIN DASHBOARD
  ====================================================== -->

  <div v-else-if="appView === 'admin'" class="admin-app">
    <nav class="admin-topbar">
      <div class="topbar-brand">
        <span class="brand-mark">DR</span>
        <div>
          <span class="topbar-title">DocuRAG</span>
          <span class="admin-topbar-label">Admin Panel</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="btn btn-outline-brass btn-sm" @click="loadAdminData" :disabled="adminLoading">
          {{ adminLoading ? 'Refreshing…' : 'Refresh' }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="logout">Sign out</button>
      </div>
    </nav>

    <main class="admin-content">
      <div class="admin-heading-row">
        <div>
          <p class="admin-eyebrow">CONTROL PANEL</p>
          <h1>Admin Dashboard</h1>
          <p>Manage users, documents, processing status and query activity.</p>
          <small v-if="adminLastUpdated" class="admin-last-updated">Updated {{ adminLastUpdated.toLocaleTimeString() }}</small>
        </div>
        <span class="admin-secure-badge">Administrator</span>
      </div>

      <div v-if="adminError" class="admin-alert">{{ adminError }}</div>

      <section class="admin-stat-grid">
        <article class="admin-stat-card">
          <span>Users</span>
          <strong>{{ adminStats.users.total }}</strong>
          <small>{{ adminStats.users.active }} active · {{ adminStats.users.inactive }} inactive</small>
        </article>
        <article class="admin-stat-card">
          <span>Documents</span>
          <strong>{{ adminStats.documents.total }}</strong>
          <small>{{ adminStats.documents.processed }} processed · {{ adminStats.documents.failed }} failed</small>
        </article>
        <article class="admin-stat-card">
          <span>Queries</span>
          <strong>{{ adminStats.queries.total }}</strong>
          <small>{{ adminStats.queries.cache_hits }} cache hits</small>
        </article>
        <article class="admin-stat-card">
          <span>Admins</span>
          <strong>{{ adminStats.users.admins }}</strong>
          <small>{{ adminStats.documents.processing }} documents processing</small>
        </article>
      </section>

      <section class="admin-panel-card">
        <div class="admin-panel-heading">
          <div>
            <h2>Users</h2>
            <p>Account status and access management.</p>
          </div>
          <span>{{ filteredAdminUsers.length }} of {{ adminUsers.length }} users</span>
        </div>

        <div class="admin-filter-bar">
          <input
            v-model="userSearch"
            class="admin-filter-input"
            type="search"
            placeholder="Search username or email…"
          />
          <select v-model="userStatusFilter" class="admin-filter-select">
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <select v-model="userRoleFilter" class="admin-filter-select">
            <option value="all">All roles</option>
            <option value="user">Users</option>
            <option value="admin">Admins</option>
          </select>
          <button type="button" class="admin-filter-clear" @click="clearAdminFilters">Clear</button>
        </div>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!filteredAdminUsers.length">
                <td colspan="6" class="admin-empty">No users found.</td>
              </tr>
              <tr v-for="user in filteredAdminUsers" :key="user.id">
                <td><strong>{{ user.username }}</strong></td>
                <td>{{ user.email }}</td>
                <td><span class="admin-role">{{ user.role }}</span></td>
                <td>
                  <span class="admin-status" :class="user.is_active ? 'admin-status--active' : 'admin-status--inactive'">
                    {{ user.is_active ? 'Active' : 'Inactive' }}
                  </span>
                </td>
                <td>{{ formatAdminDate(user.last_login) }}</td>
                <td>
                  <div class="admin-actions">
                    <button
                      v-if="user.is_active"
                      class="admin-action-btn admin-action-btn--warn"
                      :disabled="adminActionLoading === `status-${user.id}` || user.role === 'admin'"
                      @click="changeUserStatus(user, false)"
                    >
                      Deactivate
                    </button>
                    <button
                      v-else
                      class="admin-action-btn admin-action-btn--ok"
                      :disabled="adminActionLoading === `status-${user.id}`"
                      @click="changeUserStatus(user, true)"
                    >
                      Activate
                    </button>
                    <button
                      class="admin-action-btn admin-action-btn--danger"
                      :disabled="adminActionLoading === `delete-${user.id}` || user.role === 'admin'"
                      @click="deleteAdminUser(user)"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="admin-panel-card">
        <div class="admin-panel-heading">
          <div>
            <h2>Documents</h2>
            <p>All uploaded documents and their processing state.</p>
          </div>
          <span>{{ filteredAdminDocuments.length }} of {{ adminDocuments.length }} documents</span>
        </div>

        <div class="admin-filter-bar">
          <input
            v-model="documentSearch"
            class="admin-filter-input"
            type="search"
            placeholder="Search filename or uploader…"
          />
          <select v-model="documentStatusFilter" class="admin-filter-select">
            <option value="all">All statuses</option>
            <option value="processed">Processed</option>
            <option value="processing">Processing</option>
            <option value="uploaded">Uploaded</option>
            <option value="failed">Failed</option>
          </select>
          <select v-model="documentTypeFilter" class="admin-filter-select">
            <option value="all">All types</option>
            <option v-for="type in adminDocumentTypes" :key="type" :value="type">{{ type.toUpperCase() }}</option>
          </select>
          <button type="button" class="admin-filter-clear" @click="clearAdminFilters">Clear</button>
        </div>

        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Uploaded By</th>
                <th>Type</th>
                <th>Status</th>
                <th>Pages</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!filteredAdminDocuments.length">
                <td colspan="6" class="admin-empty">No documents found.</td>
              </tr>
              <tr v-for="document in filteredAdminDocuments" :key="document.id">
                <td :title="document.original_filename">{{ document.original_filename || document.filename }}</td>
                <td>{{ document.uploader_username || 'Unknown' }}</td>
                <td>{{ document.file_type || '—' }}</td>
                <td><span class="admin-status">{{ document.processing_status }}</span></td>
                <td>{{ document.page_count ?? '—' }}</td>
                <td>{{ formatAdminDate(document.upload_date) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="admin-two-column">
        <div class="admin-panel-card">
          <div class="admin-panel-heading">
            <div>
              <h2>Processing Failures</h2>
              <p>Documents that could not be processed.</p>
            </div>
            <span>{{ adminFailures.length }}</span>
          </div>
          <div v-if="!adminFailures.length" class="admin-empty-box">No processing failures.</div>
          <div v-else class="admin-failure-list">
            <article v-for="failure in adminFailures" :key="failure.id" class="admin-failure-item">
              <strong>{{ failure.original_filename }}</strong>
              <span>{{ failure.error_message || 'Unknown processing error' }}</span>
              <small>{{ failure.uploader_username || 'Unknown user' }} · {{ formatAdminDate(failure.updated_at) }}</small>
            </article>
          </div>
        </div>

        <div class="admin-panel-card">
          <div class="admin-panel-heading">
            <div>
              <h2>Recent Queries</h2>
              <p>Latest questions submitted to DocuRAG.</p>
            </div>
            <span>{{ adminQueries.length }}</span>
          </div>
          <div class="admin-filter-bar admin-filter-bar--compact">
            <input
              v-model="querySearch"
              class="admin-filter-input"
              type="search"
              placeholder="Search questions or users…"
            />
            <button type="button" class="admin-filter-clear" @click="querySearch = ''">Clear</button>
          </div>
          <div v-if="!filteredAdminQueries.length" class="admin-empty-box">No matching queries found.</div>
          <div v-else class="admin-query-list">
            <article v-for="query in filteredAdminQueries.slice(0, 20)" :key="query.id" class="admin-query-item">
              <strong>{{ query.question }}</strong>
              <span>{{ query.username || 'Unknown user' }} · {{ query.confidence != null ? (Number(query.confidence) * 100).toFixed(1) + '% confidence' : 'No confidence' }}</span>
              <small>{{ formatAdminDate(query.created_at) }}</small>
            </article>
          </div>
        </div>
      </section>
    </main>
  </div>

</template>

<style scoped>
.password-wrapper {
  position: relative;
  width: 100%;
}

.password-wrapper .password-input {
  width: 100%;
  box-sizing: border-box;
  padding-right: 52px;
}

.password-toggle {
  position: absolute;
  top: 50%;
  right: 12px;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  padding: 0;
  margin: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  appearance: none;
  -webkit-appearance: none;
}

.password-toggle:hover {
  color: #111827;
  background: rgba(15, 23, 42, 0.06);
}

.password-toggle:focus-visible {
  box-shadow: 0 0 0 2px rgba(180, 120, 20, 0.25);
}

.password-eye-icon {
  width: 20px;
  height: 20px;
  display: block;
  flex: 0 0 20px;
  pointer-events: none;
}


/* ============================================================
   SEPARATE ADMIN LOGIN
   ============================================================ */
.auth-portal-badge {
  display: inline-flex;
  margin: 0 auto 18px;
  padding: 6px 12px;
  border: 1px solid rgba(180, 120, 20, 0.45);
  border-radius: 999px;
  color: #8b5e00;
  background: rgba(180, 120, 20, 0.08);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.auth-portal-badge--admin {
  color: #111827;
  background: rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.18);
}

.admin-login-note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 20px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f7f4ed;
  color: #475569;
}

.admin-login-note strong {
  color: #111827;
  font-size: 15px;
}

.admin-login-note span {
  font-size: 13px;
  line-height: 1.5;
}

.auth-admin-link {
  display: block;
  width: 100%;
  margin-top: 18px;
  border: 0;
  background: transparent;
  color: #8b5e00;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
}

.auth-admin-link:hover {
  text-decoration: underline;
}

/* ============================================================
   ADMIN DASHBOARD
   ============================================================ */
.admin-app {
  min-height: 100vh;
  background: #eef3f8;
  color: #182234;
}

.admin-topbar {
  min-height: 68px;
  padding: 0 34px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #111827;
  color: #fff;
  border-bottom: 1px solid rgba(180, 120, 20, 0.45);
}

.admin-topbar .topbar-brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.admin-topbar-label {
  display: block;
  margin-top: 2px;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.admin-content {
  width: min(1500px, calc(100% - 48px));
  margin: 0 auto;
  padding: 38px 0 60px;
}

.admin-heading-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
}

.admin-eyebrow {
  margin: 0 0 6px;
  color: #946700;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.admin-heading-row h1 {
  margin: 0;
  font-size: clamp(30px, 4vw, 46px);
}

.admin-heading-row p {
  margin: 8px 0 0;
  color: #64748b;
}

.admin-secure-badge {
  flex: 0 0 auto;
  padding: 9px 14px;
  border: 1px solid rgba(180, 120, 20, 0.4);
  border-radius: 999px;
  background: #fff;
  color: #8b5e00;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.admin-alert {
  margin-bottom: 20px;
  padding: 13px 16px;
  border-radius: 10px;
  background: #fee2e2;
  color: #991b1b;
}

.admin-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.admin-stat-card,
.admin-panel-card {
  background: #fff;
  border: 1px solid #dbe3ec;
  border-radius: 16px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.admin-stat-card {
  padding: 22px;
}

.admin-stat-card span {
  display: block;
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.admin-stat-card strong {
  display: block;
  margin-top: 7px;
  font-size: 34px;
  line-height: 1.1;
}

.admin-stat-card small {
  display: block;
  margin-top: 8px;
  color: #64748b;
}

.admin-panel-card {
  margin-bottom: 20px;
  overflow: hidden;
}

.admin-panel-heading {
  padding: 20px 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border-bottom: 1px solid #e5eaf0;
}

.admin-panel-heading h2 {
  margin: 0;
  font-size: 20px;
}

.admin-panel-heading p {
  margin: 5px 0 0;
  color: #64748b;
  font-size: 13px;
}

.admin-panel-heading > span {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.admin-filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  padding: 14px 18px;
  border-bottom: 1px solid #edf1f5;
  background: #fbfcfe;
}

.admin-filter-bar--compact {
  border-bottom: 0;
  padding: 12px 18px;
}

.admin-filter-input,
.admin-filter-select {
  min-height: 38px;
  border: 1px solid #d7dee8;
  border-radius: 8px;
  background: #fff;
  color: #1e293b;
  padding: 8px 11px;
  font: inherit;
  font-size: 13px;
  outline: none;
}

.admin-filter-input {
  flex: 1 1 240px;
  min-width: 200px;
}

.admin-filter-select {
  min-width: 130px;
}

.admin-filter-input:focus,
.admin-filter-select:focus {
  border-color: #b47a20;
  box-shadow: 0 0 0 3px rgba(180, 122, 32, 0.10);
}

.admin-filter-clear {
  min-height: 38px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  color: #475569;
  padding: 8px 13px;
  font-weight: 700;
  cursor: pointer;
}

.admin-filter-clear:hover {
  background: #f8fafc;
  color: #111827;
}

.admin-last-updated {
  display: block;
  margin-top: 7px;
  color: #94a3b8;
  font-size: 11px;
}

.admin-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.admin-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
}

.admin-table th,
.admin-table td {
  padding: 14px 18px;
  text-align: left;
  border-bottom: 1px solid #edf1f5;
  vertical-align: middle;
  font-size: 13px;
}

.admin-table th {
  color: #64748b;
  background: #f8fafc;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

.admin-table tbody tr:last-child td {
  border-bottom: 0;
}

.admin-role,
.admin-status {
  display: inline-flex;
  align-items: center;
  padding: 5px 9px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  text-transform: capitalize;
}

.admin-status--active {
  background: #dcfce7;
  color: #166534;
}

.admin-status--inactive {
  background: #fee2e2;
  color: #991b1b;
}

.admin-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.admin-action-btn {
  padding: 6px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #fff;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}

.admin-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.admin-action-btn--warn { color: #92400e; border-color: #f0c98a; }
.admin-action-btn--ok { color: #166534; border-color: #a7d9b5; }
.admin-action-btn--danger { color: #991b1b; border-color: #f1b3b3; }

.admin-empty,
.admin-empty-box {
  color: #64748b;
  text-align: center;
}

.admin-empty-box {
  padding: 30px 20px;
}

.admin-two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.admin-two-column .admin-panel-card {
  margin-bottom: 0;
}

.admin-failure-list,
.admin-query-list {
  max-height: 430px;
  overflow-y: auto;
}

.admin-failure-item,
.admin-query-item {
  padding: 15px 20px;
  border-bottom: 1px solid #edf1f5;
}

.admin-failure-item:last-child,
.admin-query-item:last-child {
  border-bottom: 0;
}

.admin-failure-item strong,
.admin-query-item strong {
  display: block;
  color: #182234;
  line-height: 1.45;
}

.admin-failure-item span,
.admin-query-item span,
.admin-failure-item small,
.admin-query-item small {
  display: block;
  margin-top: 5px;
  color: #64748b;
  line-height: 1.45;
}

@media (max-width: 1000px) {
  .admin-stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .admin-two-column { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .admin-topbar { padding: 0 16px; }
  .admin-content { width: min(100% - 24px, 1500px); padding-top: 24px; }
  .admin-heading-row { flex-direction: column; }
  .admin-stat-grid { grid-template-columns: 1fr; }
  .admin-panel-heading { align-items: flex-start; }
}


/* ============================================================
   USER DASHBOARD POLISH
   Visual-only improvements; existing functionality is unchanged.
   ============================================================ */
.workspace {
  height: calc(100dvh - 68px);
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(300px, 25%) minmax(0, 1fr);
  overflow: hidden;
}

.sidebar {
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}

.sidebar::-webkit-scrollbar {
  width: 7px;
}

.sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 999px;
}

.sidebar-section--muted {
  border-top: 1px solid #edf1f5;
  padding-bottom: 28px;
  background: #fbfcfe;
}

.sidebar-section--muted h2 {
  margin: 0 0 12px;
  color: #172033;
  font-size: 15px;
  font-weight: 800;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.recent-list li {
  padding: 10px 11px;
  border: 1px solid #e7ebf0;
  border-radius: 10px;
  background: #fff;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.recent-list li:hover {
  border-color: #d7dee8;
  background: #f8fafc;
}

.workspace {
  background: #f7f8fa;
}

.sidebar {
  background: #ffffff;
  border-right: 1px solid #e7ebf0;
}

.sidebar-section {
  padding: 18px 16px;
}

.sidebar-heading {
  margin-bottom: 14px;
}

.sidebar-heading h2 {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.sidebar-count {
  min-width: 24px;
  height: 24px;
  padding: 0 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
}

.dropzone--polished {
  min-height: 132px;
  padding: 20px 14px;
  border: 1.5px dashed #cbd5e1;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfcfe 0%, #f7f9fc 100%);
  transition: border-color .18s ease, background .18s ease, transform .18s ease, box-shadow .18s ease;
}

.dropzone--polished:hover,
.dropzone--polished.dropzone--active {
  border-color: #b47a14;
  background: #fffcf5;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .06);
  transform: translateY(-1px);
}

.dropzone--polished.dropzone--busy {
  cursor: wait;
  opacity: .82;
}

.dropzone-content {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 6px;
}

.dropzone-content strong {
  color: #172033;
  font-size: 14px;
}

.dropzone-content small {
  max-width: 220px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.dropzone-content em {
  margin-top: 2px;
  color: #94a3b8;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
}

.upload-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: #111827;
  color: #fff;
  font-size: 20px;
  font-weight: 700;
}

.upload-icon--spin {
  animation: docurag-spin 1s linear infinite;
}

@keyframes docurag-spin {
  to { transform: rotate(360deg); }
}

.document-list {
  margin-top: 16px;
  gap: 7px;
}

.document-item {
  min-height: 68px;
  padding: 10px 9px;
  border: 1px solid #e8edf3;
  border-radius: 12px;
  background: #fff;
  transition: background .15s ease, border-color .15s ease, box-shadow .15s ease, transform .15s ease;
}

.document-item:hover {
  background: #fbfcfe;
  border-color: #dbe3ec;
  box-shadow: 0 4px 12px rgba(15, 23, 42, .05);
}

.document-item--active {
  background: #fffbf2;
  border-color: rgba(180, 120, 20, .38);
  box-shadow: inset 3px 0 0 #b47a14, 0 4px 12px rgba(180, 120, 20, .07);
}

.document-kind {
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #eef2f7;
  color: #334155;
  font-size: 9px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.document-kind--pdf {
  background: #fff1f2;
  color: #b42318;
}

.document-kind--img {
  background: #eff6ff;
  color: #1d4ed8;
}

.document-info {
  gap: 3px;
}

.document-name {
  font-size: 12px;
  line-height: 1.35;
}

.document-meta {
  min-width: 0;
  display: flex;
  align-items: center;
}

.document-type-label {
  color: #94a3b8;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.document-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 750;
  line-height: 1.2;
}

.status-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
}

.document-status--processed { color: #15803d; }
.document-status--processed .status-dot { background: #22c55e; }
.document-status--processing { color: #a16207; }
.document-status--processing .status-dot { background: #eab308; }
.document-status--failed { color: #b91c1c; }
.document-status--failed .status-dot { background: #ef4444; }
.document-status--uploaded { color: #64748b; }

.document-remove {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  color: #94a3b8;
  transition: color .15s ease, background .15s ease;
}

.document-remove:hover:not(:disabled) {
  color: #b91c1c;
  background: #fef2f2;
}

.empty-note--documents {
  margin-top: 14px;
  padding: 18px 12px;
  border: 1px dashed #d7dee8;
  border-radius: 12px;
  text-align: center;
}

.empty-state-icon {
  width: 38px;
  height: 38px;
  margin: 0 auto 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 20px;
}

.welcome--polished {
  width: min(100%, 720px);
  max-width: 720px;
  margin: 28px auto;
  padding: 36px 28px;
  align-self: start;
  min-height: 0;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  border: 1px solid #e5eaf0;
  border-radius: 24px;
  background: rgba(255,255,255,.9);
  box-shadow: 0 18px 50px rgba(15, 23, 42, .06);
}

.welcome-badge {
  display: inline-flex;
  margin-bottom: 18px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #f7f4ed;
  color: #8b5e00;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .1em;
}

.welcome-logo {
  margin: 0 auto 18px;
}

.welcome--polished h1 {
  margin: 0 auto 14px;
  max-width: 620px;
  color: #111827;
  font-size: clamp(34px, 4vw, 48px);
  line-height: 1.08;
  font-weight: 800;
  letter-spacing: -.035em;
  text-wrap: balance;
}

.welcome--polished > p {
  max-width: 570px;
  margin: 0 auto;
  color: #64748b;
  line-height: 1.7;
}

.welcome-features {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 24px;
}

.welcome-features span {
  padding: 8px 11px;
  border: 1px solid #e5eaf0;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
}

.chat-area {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  background: #f7f8fa;
}

.chat-container {
  max-width: 900px;
}

/* =====================================================
   CHAT / AI RESPONSE POLISH
===================================================== */

.messages {
  width: min(100%, 900px);
  margin: 0 auto;
  padding: 28px 8px 110px;
}

.message-row {
  display: flex;
  width: 100%;
  margin-bottom: 18px;
}

.message-row--user {
  justify-content: flex-end;
  padding-left: 12%;
}

.message-row--assistant {
  justify-content: flex-start;
  gap: 10px;
  padding-right: 8%;
}

.bubble {
  max-width: min(760px, 82%);
  border-radius: 16px;
  padding: 13px 16px;
  line-height: 1.65;
  font-size: 14px;
  word-break: break-word;
}

.bubble--user {
  background: #111827;
  color: #fff;
  border: 1px solid #111827;
  border-bottom-right-radius: 5px;
}

.bubble--assistant {
  flex: 1;
  background: #fff;
  color: #334155;
  border: 1px solid #e3e8ef;
  border-bottom-left-radius: 5px;
  box-shadow: 0 5px 18px rgba(15, 23, 42, .04);
}

.bubble-text {
  margin: 0;
  white-space: pre-wrap;
}

.brand-mark--sm {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  margin-top: 2px;
  border-radius: 9px;
  font-size: 13px;
}

.confidence-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 13px;
  padding-top: 10px;
  border-top: 1px solid #eef2f6;
}

.confidence-meter {
  width: 74px;
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: #e8edf3;
}

.confidence-fill {
  height: 100%;
  border-radius: inherit;
  background: #b47a14;
  transition: width .3s ease;
}

.confidence-label {
  color: #64748b;
  font-size: 10px;
  font-weight: 700;
}

.cache-tag {
  padding: 3px 7px;
  border-radius: 999px;
  background: #ecfdf3;
  color: #15803d;
  font-size: 9px;
  font-weight: 800;
}

.citation-group {
  margin-top: 13px;
  padding-top: 11px;
  border-top: 1px solid #eef2f6;
}

.citation-heading {
  display: block;
  margin-bottom: 7px;
  color: #334155;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .05em;
  text-transform: uppercase;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.citation-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 6px 8px;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 10px;
  line-height: 1.35;
}

.citation-chip--image {
  background: #f5f8ff;
  border-color: #dfe8fa;
}

.citation-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  flex: 0 0 17px;
  border-radius: 50%;
  background: #111827;
  color: #fff;
  font-size: 9px;
  font-weight: 800;
}

.bubble--typing {
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 9px;
}

.typing-dots {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.typing-dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #94a3b8;
  animation: docurag-bounce 1.1s infinite ease-in-out;
}

.typing-dots span:nth-child(2) {
  animation-delay: .15s;
}

.typing-dots span:nth-child(3) {
  animation-delay: .3s;
}

@keyframes docurag-bounce {
  0%, 70%, 100% { transform: translateY(0); opacity: .45; }
  35% { transform: translateY(-4px); opacity: 1; }
}

.chat-error {
  max-width: 900px;
  margin: 0 auto 10px;
}

.composer {
  position: sticky;
  bottom: 12px;
  z-index: 5;
  width: min(100%, 900px);
  margin: 0 auto;
  border: 1px solid #dce3eb;
  border-radius: 15px;
  background: rgba(255,255,255,.96);
  padding: 6px;
  box-shadow: 0 8px 28px rgba(15, 23, 42, .07);
  backdrop-filter: blur(8px);
}

.composer-input {
  flex: 1;
  min-width: 0;
  min-height: 46px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #172033;
}

.composer-input::placeholder {
  color: #94a3b8;
}

.composer:focus-within {
  border-color: rgba(180, 120, 20, .65);
  box-shadow: 0 0 0 3px rgba(180, 120, 20, .08), 0 8px 28px rgba(15, 23, 42, .07);
}

.composer .btn {
  min-width: 78px;
  min-height: 44px;
  border-radius: 10px;
}

.composer-hint {
  width: min(100%, 900px);
  margin: 7px auto 0;
  color: #64748b;
  font-size: 10px;
}

.composer-hint--warn {
  color: #b45309;
}

@media (max-width: 800px) {
  .messages {
    padding: 20px 4px 100px;
  }

  .message-row--user {
    padding-left: 6%;
  }

  .message-row--assistant {
    padding-right: 2%;
  }

  .bubble {
    max-width: 90%;
  }

  .composer {
    bottom: 6px;
  }

  .citation-chip {
    width: 100%;
  }
}

.bubble--assistant {
  border: 1px solid #e3e8ef;
  box-shadow: 0 5px 18px rgba(15, 23, 42, .04);
}

.bubble--user {
  box-shadow: 0 4px 14px rgba(15, 23, 42, .08);
}

.composer {
  border: 1px solid #dce3eb;
  border-radius: 15px;
  background: #fff;
  padding: 6px;
  box-shadow: 0 8px 28px rgba(15, 23, 42, .07);
}

.composer:focus-within {
  border-color: rgba(180, 120, 20, .65);
  box-shadow: 0 0 0 3px rgba(180, 120, 20, .08), 0 8px 28px rgba(15, 23, 42, .07);
}

.composer-input {
  min-height: 46px;
}

.composer .btn {
  min-width: 78px;
  min-height: 44px;
  border-radius: 10px;
}

.composer-hint {
  color: #64748b;
  font-size: 11px;
}

@media (max-width: 800px) {
  .workspace {
    height: auto;
    min-height: calc(100dvh - 68px);
    display: block;
    overflow: visible;
  }

  .sidebar {
    height: auto;
    max-height: 52vh;
    overflow-y: auto;
    border-right: 0;
    border-bottom: 1px solid #e7ebf0;
  }

  .welcome--polished {
    width: 100%;
    margin: 20px 0;
    padding: 30px 20px;
    border-radius: 18px;
  }

  .welcome-features {
    flex-direction: column;
    align-items: stretch;
  }

  .welcome-features span {
    text-align: center;
  }
}


/* =====================================================
   FINAL POLISH: AUTH
===================================================== */
.auth-page,
.auth-shell,
.auth-card {
  transition: all .2s ease;
}

.auth-card {
  border: 1px solid #e5eaf0;
  border-radius: 20px;
  box-shadow: 0 18px 55px rgba(15, 23, 42, .08);
}

.auth-card input,
.auth-card .form-control {
  min-height: 46px;
  border-radius: 10px;
  border-color: #dbe2ea;
  transition: border-color .15s ease, box-shadow .15s ease;
}

.auth-card input:focus,
.auth-card .form-control:focus {
  border-color: #b47a14;
  box-shadow: 0 0 0 3px rgba(180, 120, 20, .09);
}

.auth-admin-link {
  transition: color .15s ease, background .15s ease;
}

.auth-admin-link:hover {
  color: #8b5e00;
  background: #fffbf2;
}

.password-toggle {
  transition: color .15s ease, background .15s ease;
}

.inline-note--danger,
.alert-danger {
  border-radius: 10px;
}

.inline-note--success,
.alert-success {
  border-radius: 10px;
}

/* =====================================================
   FINAL POLISH: PROCESSING / STATES / NAVBAR / RESPONSIVE
===================================================== */

.document-item--disabled {
  opacity: .72;
  cursor: wait;
}

.document-item--disabled .document-remove {
  pointer-events: none;
}

.document-status--processed {
  color: #15803d;
}

.document-status--processing {
  color: #b45309;
}

.document-status--failed {
  color: #b91c1c;
}

.document-status--uploaded {
  color: #475569;
}

.document-status--processed .status-dot {
  background: #16a34a;
}

.document-status--processing .status-dot {
  background: #f59e0b;
  animation: status-pulse 1.2s infinite ease-in-out;
}

.document-status--failed .status-dot {
  background: #dc2626;
}

.document-status--uploaded .status-dot {
  background: #64748b;
}

@keyframes status-pulse {
  50% { opacity: .35; transform: scale(.7); }
}

.empty-note {
  color: #64748b;
}

.empty-note-sub {
  line-height: 1.55;
}

.inline-note {
  line-height: 1.45;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  backdrop-filter: blur(10px);
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid #e8edf3;
}

.topbar-actions {
  gap: 8px;
}

.topbar .btn {
  min-height: 34px;
  border-radius: 9px;
  transition: transform .15s ease, box-shadow .15s ease, background .15s ease;
}

.topbar .btn:hover {
  transform: translateY(-1px);
}

.chat-area {
  min-width: 0;
}

.sidebar {
  min-width: 0;
}

.document-list,
.recent-list {
  padding-right: 2px;
}

.recent-list li {
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.45;
}

.btn:disabled {
  cursor: not-allowed;
  opacity: .58;
}

button:focus-visible,
input:focus-visible,
.dropzone:focus-visible {
  outline: 3px solid rgba(180, 120, 20, .18);
  outline-offset: 2px;
}

@media (max-width: 900px) {
  .workspace {
    min-height: calc(100dvh - 57px);
  }

  .topbar-title {
    font-size: 15px;
  }

  .topbar-actions .btn {
    padding-inline: 9px;
  }

  .sidebar {
    max-height: none;
  }
}

@media (max-width: 640px) {
  .topbar {
    padding: 10px 12px;
  }

  .topbar-actions .btn-outline-brass {
    display: none;
  }

  .workspace {
    display: block;
  }

  .sidebar {
    width: 100%;
    max-height: none;
    border-right: 0;
    border-bottom: 1px solid #e8edf3;
  }

  .chat-area {
    min-height: calc(100dvh - 57px);
  }

  .welcome--polished {
    margin: 18px 0;
    padding: 30px 18px;
    border-radius: 18px;
  }

  .welcome--polished h1 {
    font-size: clamp(28px, 8vw, 40px);
  }

  .messages {
    padding-bottom: 95px;
  }

  .message-row--user,
  .message-row--assistant {
    padding-left: 0;
    padding-right: 0;
  }

  .bubble {
    max-width: 92%;
  }

  .composer {
    border-radius: 13px;
  }
}

</style>

<style>
/* Final brand visibility override */
.topbar .topbar-title,
.admin-topbar .topbar-title {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  opacity: 1 !important;
  visibility: visible !important;
  font-weight: 800 !important;
}
</style>
