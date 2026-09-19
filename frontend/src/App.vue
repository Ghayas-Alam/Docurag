<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'

const API_URL = 'http://127.0.0.1:8000'

/* =========================================================
   AUTH
========================================================= */

const isLoggedIn = ref(!!localStorage.getItem('access_token'))
const authMode = ref('login')

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')

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

    localStorage.setItem('access_token', data.access_token)
    isLoggedIn.value = true

    email.value = ''
    password.value = ''

    await loadDocuments()
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
}

function logout() {
  localStorage.removeItem('access_token')
  isLoggedIn.value = false
  documents.value = []
  selectedDocumentId.value = null
  messages.value = []
  question.value = ''
  loginError.value = ''
  signupError.value = ''
  signupSuccess.value = ''
  authMode.value = 'login'
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
    }

    const selectedStillExists = documents.value.some(
      document => document.id === selectedDocumentId.value
    )

    if (documents.value.length > 0 && !selectedStillExists) {
      selectedDocumentId.value = documents.value[0].id
    }

    if (documents.value.length === 0) {
      selectedDocumentId.value = null
    }
  } catch (error) {
    console.error('Load documents error:', error)
  }
}

function selectDocument(documentId) {
  selectedDocumentId.value = documentId
  messages.value = []
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
    } else if (data.document_id) {
      selectedDocumentId.value = data.document_id
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
const conversationId = ref(crypto.randomUUID())
const messagesEnd = ref(null)

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

  try {
    const response = await fetch(`${API_URL}/api/new_chat`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    })

    const data = await response.json()

    if (response.ok) {
      conversationId.value = data.conversation_id || crypto.randomUUID()
    } else {
      conversationId.value = crypto.randomUUID()
    }
  } catch (error) {
    console.error('New chat error:', error)
    conversationId.value = crypto.randomUUID()
  }

  messages.value = []
  question.value = ''
  chatError.value = ''
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

onMounted(() => {
  if (localStorage.getItem('access_token')) {
    loadDocuments()
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

      <div class="auth-tabs" role="tablist">
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
        <input
          id="login-password"
          v-model="password"
          type="password"
          class="field-input"
          placeholder="Enter your password"
          autocomplete="current-password"
        />

        <button type="submit" class="btn btn-ink w-100" :disabled="loginLoading">
          <span v-if="loginLoading">Signing in…</span>
          <span v-else>Sign in</span>
        </button>

      </form>

      <!-- SIGN UP -->
      <form v-else class="auth-form" @submit.prevent="signup">

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
        <input
          id="signup-password"
          v-model="password"
          type="password"
          class="field-input"
          placeholder="8+ chars, A-Z, a-z, 0-9 & special character"
          autocomplete="new-password"
        />

        <label class="field-label" for="signup-confirm">Confirm password</label>
        <input
          id="signup-confirm"
          v-model="confirmPassword"
          type="password"
          class="field-input"
          placeholder="Re-enter your password"
          autocomplete="new-password"
        />

        <button type="submit" class="btn btn-ink w-100" :disabled="signupLoading">
          <span v-if="signupLoading">Creating account…</span>
          <span v-else>Create account</span>
        </button>

      </form>

    </div>

  </div>

  <!-- =====================================================
       MAIN APP
  ====================================================== -->

  <div v-else class="app">

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
            class="dropzone"
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
            <span v-if="uploading">Uploading…</span>
            <span v-else>
              <strong>Add a document</strong>
              <small>Drop a file here, or click to browse</small>
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
              <span class="document-kind">{{ getFileKind(document) }}</span>
              <span class="document-name" :title="getDocumentName(document)">
                {{ getDocumentName(document) }}
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

          <div v-else class="empty-note">
            <p>No documents yet.</p>
            <p class="empty-note-sub">Add a PDF or image to start asking questions.</p>
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

          <div v-if="messages.length === 0" class="welcome">
            <span class="brand-mark brand-mark--lg">DR</span>
            <h1>Ask your documents anything.</h1>
            <p>Upload a document, then ask a question about what's inside.</p>
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
              @keyup.enter="askQuestion"
            />
            <button
              class="btn btn-ink"
              :disabled="asking || !question.trim()"
              @click="askQuestion"
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

</template>