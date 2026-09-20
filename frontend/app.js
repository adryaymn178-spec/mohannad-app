'use strict';

/**
 * Mohannad App - Frontend Application Logic
 * Comprehensive messaging client with WebSocket, JWT authentication,
 * contacts management, dark mode, and browser notifications.
 */

(function () {
    // --- Application Configuration & State ---
    const CONFIG = {
        API_BASE: 'http://localhost:3000/api',
        WS_URL: 'ws://localhost:3000/ws',
        RECONNECT_INTERVAL: 3000,
        MAX_RECONNECT_ATTEMPTS: 10,
        STORAGE_KEYS: {
            TOKEN: 'mohannad_jwt_token',
            USER: 'mohannad_user_data',
            THEME: 'mohannad_theme_mode'
        }
    };

    const state = {
        token: localStorage.getItem(CONFIG.STORAGE_KEYS.TOKEN) || null,
        currentUser: null,
        activeContact: null,
        contacts: [],
        messages: {}, // Keyed by contactId: Array of message objects
        socket: null,
        reconnectAttempts: 0,
        reconnectTimer: null,
        currentView: 'chat',
        notificationsAllowed: false
    };

    // Parse stored user if token exists
    try {
        const storedUser = localStorage.getItem(CONFIG.STORAGE_KEYS.USER);
        if (storedUser) {
            state.currentUser = JSON.parse(storedUser);
        }
    } catch (e) {
        state.currentUser = null;
    }

    // --- DOM Elements Cache ---
    const elements = {
        // Screens & Containers
        authContainer: document.getElementById('authScreen'),
        appContainer: document.getElementById('appScreen'),
        viewScreens: {
            chat: document.getElementById('chatView'),
            contacts: document.getElementById('contactsView'),
            settings: document.getElementById('settingsView')
        },

        // Navigation
        navButtons: document.querySelectorAll('[data-nav-target]'),

        // Auth
        loginForm: document.getElementById('loginForm'),
        loginUsername: document.getElementById('loginUsername'),
        loginPassword: document.getElementById('loginPassword'),
        loginError: document.getElementById('loginError'),
        logoutBtn: document.getElementById('logoutBtn'),

        // Contacts
        contactsList: document.getElementById('contactsList'),
        contactsSearch: document.getElementById('contactsSearch'),

        // Chat
        activeChatHeader: document.getElementById('activeChatHeader'),
        activeContactName: document.getElementById('activeContactName'),
        activeContactStatus: document.getElementById('activeContactStatus'),
        messagesContainer: document.getElementById('messagesContainer'),
        messageForm: document.getElementById('messageForm'),
        messageInput: document.getElementById('messageInput'),
        chatEmptyState: document.getElementById('chatEmptyState'),
        chatArea: document.getElementById('chatArea'),

        // Settings
        themeToggle: document.getElementById('themeToggle'),
        notificationsToggle: document.getElementById('notificationsToggle'),
        userProfileName: document.getElementById('userProfileName')
    };

    // --- Core Initialization ---
    function init() {
        initTheme();
        initNotifications();
        bindEvents();

        if (state.token) {
            showApp();
        } else {
            showAuth();
        }
    }

    // --- Authentication & Session Management ---
    function showAuth() {
        if (elements.authContainer) elements.authContainer.style.display = 'block';
        if (elements.appContainer) elements.appContainer.style.display = 'none';
        disconnectWebSocket();
    }

    function showApp() {
        if (elements.authContainer) elements.authContainer.style.display = 'none';
        if (elements.appContainer) elements.appContainer.style.display = 'flex';

        if (elements.userProfileName && state.currentUser) {
            elements.userProfileName.textContent = state.currentUser.username || state.currentUser.name || 'User';
        }

        switchView(state.currentView);
        fetchContacts();
        connectWebSocket();
    }

    async function handleLogin(e) {
        e.preventDefault();
        const username = elements.loginUsername ? elements.loginUsername.value.trim() : '';
        const password = elements.loginPassword ? elements.loginPassword.value.trim() : '';

        if (!username || !password) {
            displayAuthError('يرجى إدخال اسم المستخدم وكلمة المرور');
            return;
        }

        try {
            const response = await fetch(`${CONFIG.API_BASE}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (!response.ok || !data.token) {
                throw new Error(data.message || 'فشل تسجيل الدخول. تحقق من صحة البيانات.');
            }

            state.token = data.token;
            state.currentUser = data.user || { username: username };

            localStorage.setItem(CONFIG.STORAGE_KEYS.TOKEN, state.token);
            localStorage.setItem(CONFIG.STORAGE_KEYS.USER, JSON.stringify(state.currentUser));

            if (elements.loginForm) elements.loginForm.reset();
            displayAuthError('');
            showApp();
        } catch (error) {
            displayAuthError(error.message);
        }
    }

    function handleLogout() {
        state.token = null;
        state.currentUser = null;
        state.activeContact = null;
        state.contacts = [];
        state.messages = {};

        localStorage.removeItem(CONFIG.STORAGE_KEYS.TOKEN);
        localStorage.removeItem(CONFIG.STORAGE_KEYS.USER);

        disconnectWebSocket();
        showAuth();
    }

    function displayAuthError(message) {
        if (elements.loginError) {
            elements.loginError.textContent = message;
            elements.loginError.style.display = message ? 'block' : 'none';
        }
    }

    // --- WebSocket Communication ---
    function connectWebSocket() {
        if (!state.token) return;

        if (state.socket && (state.socket.readyState === WebSocket.OPEN || state.socket.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrlWithToken = `${CONFIG.WS_URL}?token=${encodeURIComponent(state.token)}`;

        try {
            state.socket = new WebSocket(wsUrlWithToken);

            state.socket.onopen = () => {
                state.reconnectAttempts = 0;
                clearTimeout(state.reconnectTimer);
                updateConnectionStatus(true);
            };

            state.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    handleIncomingSocketData(data);
                } catch (err) {
                    console.error('WebSocket payload parsing error:', err);
                }
            };

            state.socket.onclose = (event) => {
                updateConnectionStatus(false);
                if (state.token && state.reconnectAttempts < CONFIG.MAX_RECONNECT_ATTEMPTS) {
                    state.reconnectAttempts++;
                    state.reconnectTimer = setTimeout(connectWebSocket, CONFIG.RECONNECT_INTERVAL);
                }
            };

            state.socket.onerror = (error) => {
                console.error('WebSocket Error:', error);
                state.socket.close();
            };
        } catch (err) {
            console.error('Failed to instantiate WebSocket:', err);
        }
    }

    function disconnectWebSocket() {
        clearTimeout(state.reconnectTimer);
        if (state.socket) {
            state.socket.onclose = null;
            state.socket.close();
            state.socket = null;
        }
        updateConnectionStatus(false);
    }

    function updateConnectionStatus(isConnected) {
        const indicator = document.getElementById('connectionIndicator');
        if (indicator) {
            indicator.className = isConnected ? 'status-online' : 'status-offline';
            indicator.title = isConnected ? 'متصل' : 'جارٍ إعادة الاتصال...';
        }
    }

    function handleIncomingSocketData(payload) {
        switch (payload.type) {
            case 'message':
                onMessageReceived(payload.data);
                break;
            case 'user_status':
                updateUserOnlineStatus(payload.data.userId, payload.data.isOnline);
                break;
            case 'contacts_update':
                state.contacts = payload.data;
                renderContacts();
                break;
            default:
                break;
        }
    }

    // --- Messaging System ---
    function sendMessage(e) {
        if (e) e.preventDefault();

        if (!elements.messageInput || !state.activeContact) return;

        const text = elements.messageInput.value.trim();
        if (!text) return;

        const messagePayload = {
            id: 'msg_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
            senderId: state.currentUser.id || state.currentUser.username,
            recipientId: state.activeContact.id,
            content: text,
            timestamp: new Date().toISOString()
        };

        // Cache locally
        saveMessageLocally(state.activeContact.id, messagePayload);
        renderMessages();

        // Send via WebSocket
        if (state.socket && state.socket.readyState === WebSocket.OPEN) {
            state.socket.send(JSON.stringify({
                type: 'message',
                data: messagePayload
            }));
        } else {
            // Fallback REST API if WS not connected
            fetch(`${CONFIG.API_BASE}/messages`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${state.token}`
                },
                body: JSON.stringify(messagePayload)
            }).catch((err) => console.error('REST message fallback failed:', err));
        }

        elements.messageInput.value = '';
        elements.messageInput.focus();
    }

    function onMessageReceived(msg) {
        const contactId = (msg.senderId === (state.currentUser.id || state.currentUser.username))
            ? msg.recipientId
            : msg.senderId;

        saveMessageLocally(contactId, msg);

        // If message is from current active conversation, render it
        if (state.activeContact && state.activeContact.id === contactId) {
            renderMessages();
        } else {
            // Update unread count indicator for contact
            const contact = state.contacts.find((c) => c.id === contactId);
            if (contact) {
                contact.unread = (contact.unread || 0) + 1;
                renderContacts();
            }
        }

        // Show Notification if conversation is not active or window blurred
        if (!state.activeContact || state.activeContact.id !== contactId || document.hidden) {
            const sender = state.contacts.find((c) => c.id === contactId);
            const senderName = sender ? sender.name : 'رسالة جديدة';
            showNotification(senderName, {
                body: msg.content,
                tag: contactId
            });
        }
    }

    function saveMessageLocally(contactId, message) {
        if (!state.messages[contactId]) {
            state.messages[contactId] = [];
        }
        state.messages[contactId].push(message);
    }

    function renderMessages() {
        if (!elements.messagesContainer) return;

        elements.messagesContainer.innerHTML = '';

        if (!state.activeContact) {
            if (elements.chatEmptyState) elements.chatEmptyState.style.display = 'block';
            if (elements.chatArea) elements.chatArea.style.display = 'none';
            return;
        }

        if (elements.chatEmptyState) elements.chatEmptyState.style.display = 'none';
        if (elements.chatArea) elements.chatArea.style.display = 'flex';

        const conversation = state.messages[state.activeContact.id] || [];
        const currentUserId = state.currentUser.id || state.currentUser.username;

        const fragment = document.createDocumentFragment();

        conversation.forEach((msg) => {
            const isMe = msg.senderId === currentUserId;
            const messageEl = document.createElement('div');
            messageEl.className = `message-item ${isMe ? 'message-outgoing' : 'message-incoming'}`;

            const textEl = document.createElement('div');
            textEl.className = 'message-text';
            textEl.textContent = msg.content;

            const timeEl = document.createElement('div');
            timeEl.className = 'message-time';
            const date = new Date(msg.timestamp);
            timeEl.textContent = !isNaN(date.getTime())
                ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                : '';

            messageEl.appendChild(textEl);
            messageEl.appendChild(timeEl);
            fragment.appendChild(messageEl);
        });

        elements.messagesContainer.appendChild(fragment);
        elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
    }

    // --- Contacts Management ---
    async function fetchContacts() {
        try {
            const res = await fetch(`${CONFIG.API_BASE}/contacts`, {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });

            if (!res.ok) throw new Error('فشل جلب جهات الاتصال');

            state.contacts = await res.json();
            renderContacts();
        } catch (err) {
            console.warn('API Contacts error, initializing fallback list:', err);
            if (!state.contacts || state.contacts.length === 0) {
                state.contacts = [
                    { id: 'usr_1', name: 'مهند', status: 'online', avatar: '' },
                    { id: 'usr_2', name: 'أحمد علي', status: 'offline', avatar: '' },
                    { id: 'usr_3', name: 'سارة خالد', status: 'online', avatar: '' }
                ];
                renderContacts();
            }
        }
    }

    function renderContacts() {
        if (!elements.contactsList) return;

        elements.contactsList.innerHTML = '';
        const query = elements.contactsSearch ? elements.contactsSearch.value.toLowerCase().trim() : '';

        const filtered = state.contacts.filter((c) => c.name.toLowerCase().includes(query));

        if (filtered.length === 0) {
            const emptyEl = document.createElement('div');
            emptyEl.className = 'contacts-empty';
            emptyEl.textContent = 'لا توجد جهات اتصال مطابقة';
            elements.contactsList.appendChild(emptyEl);
            return;
        }

        const fragment = document.createDocumentFragment();

        filtered.forEach((contact) => {
            const item = document.createElement('div');
            item.className = `contact-item ${state.activeContact && state.activeContact.id === contact.id ? 'active' : ''}`;
            item.dataset.contactId = contact.id;

            // Avatar / Icon
            const avatar = document.createElement('div');
            avatar.className = 'contact-avatar';
            avatar.textContent = contact.name.charAt(0).toUpperCase();

            const statusDot = document.createElement('span');
            statusDot.className = `status-dot ${contact.status === 'online' ? 'online' : 'offline'}`;
            avatar.appendChild(statusDot);

            // Info Wrapper
            const info = document.createElement('div');
            info.className = 'contact-info';

            const name = document.createElement('span');
            name.className = 'contact-name';
            name.textContent = contact.name;

            const lastMsg = document.createElement('span');
            lastMsg.className = 'contact-preview';
            const history = state.messages[contact.id];
            lastMsg.textContent = history && history.length > 0
                ? history[history.length - 1].content
                : (contact.status === 'online' ? 'متصل الآن' : 'غير متصل');

            info.appendChild(name);
            info.appendChild(lastMsg);

            item.appendChild(avatar);
            item.appendChild(info);

            if (contact.unread && contact.unread > 0) {
                const badge = document.createElement('span');
                badge.className = 'unread-badge';
                badge.textContent = contact.unread;
                item.appendChild(badge);
            }

            item.addEventListener('click', () => openChat(contact));
            fragment.appendChild(item);
        });

        elements.contactsList.appendChild(fragment);
    }

    function openChat(contact) {
        state.activeContact = contact;
        contact.unread = 0;

        if (elements.activeContactName) {
            elements.activeContactName.textContent = contact.name;
        }

        if (elements.activeContactStatus) {
            elements.activeContactStatus.textContent = contact.status === 'online' ? 'متصل الآن' : 'غير متصل';
            elements.activeContactStatus.className = `user-status ${contact.status === 'online' ? 'online' : 'offline'}`;
        }

        // Fetch history if not loaded
        if (!state.messages[contact.id]) {
            fetchMessageHistory(contact.id);
        } else {
            renderMessages();
        }

        renderContacts();
        switchView('chat');
    }

    async function fetchMessageHistory(contactId) {
        try {
            const res = await fetch(`${CONFIG.API_BASE}/messages/${contactId}`, {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });
            if (res.ok) {
                state.messages[contactId] = await res.json();
            } else {
                state.messages[contactId] = [];
            }
        } catch (err) {
            state.messages[contactId] = [];
        }
        renderMessages();
    }

    function updateUserOnlineStatus(userId, isOnline) {
        const contact = state.contacts.find((c) => c.id === userId);
        if (contact) {
            contact.status = isOnline ? 'online' : 'offline';
            renderContacts();

            if (state.activeContact && state.activeContact.id === userId && elements.activeContactStatus) {
                elements.activeContactStatus.textContent = isOnline ? 'متصل الآن' : 'غير متصل';
                elements.activeContactStatus.className = `user-status ${isOnline ? 'online' : 'offline'}`;
            }
        }
    }

    // --- Navigation System ---
    function switchView(viewName) {
        if (!elements.viewScreens[viewName]) return;

        state.currentView = viewName;

        Object.keys(elements.viewScreens).forEach((key) => {
            const viewElement = elements.viewScreens[key];
            if (viewElement) {
                viewElement.style.display = key === viewName ? 'flex' : 'none';
            }
        });

        elements.navButtons.forEach((btn) => {
            if (btn.dataset.navTarget === viewName) {
                btn.classList.add('nav-active');
            } else {
                btn.classList.remove('nav-active');
            }
        });
    }

    // --- Dark / Light Theme System ---
    function initTheme() {
        const savedTheme = localStorage.getItem(CONFIG.STORAGE_KEYS.THEME) || 'light';
        applyTheme(savedTheme);

        if (elements.themeToggle) {
            elements.themeToggle.checked = savedTheme === 'dark';
        }
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.body.classList.remove('theme-dark', 'theme-light');
        document.body.classList.add(`theme-${theme}`);
        localStorage.setItem(CONFIG.STORAGE_KEYS.THEME, theme);
    }

    function toggleTheme() {
        const currentTheme = localStorage.getItem(CONFIG.STORAGE_KEYS.THEME) || 'light';
        const targetTheme = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(targetTheme);
    }

    // --- Browser Notifications ---
    function initNotifications() {
        if (!('Notification' in window)) {
            if (elements.notificationsToggle) {
                elements.notificationsToggle.disabled = true;
            }
            return;
        }

        state.notificationsAllowed = Notification.permission === 'granted';

        if (elements.notificationsToggle) {
            elements.notificationsToggle.checked = state.notificationsAllowed;
        }
    }

    async function requestNotificationPermission() {
        if (!('Notification' in window)) return false;

        const permission = await Notification.requestPermission();
        state.notificationsAllowed = permission === 'granted';

        if (elements.notificationsToggle) {
            elements.notificationsToggle.checked = state.notificationsAllowed;
        }

        return state.notificationsAllowed;
    }

    function showNotification(title, options) {
        if (!state.notificationsAllowed || Notification.permission !== 'granted') {
            return;
        }

        try {
            const notification = new Notification(title, {
                icon: '/assets/icon.png',
                badge: '/assets/badge.png',
                ...options
            });

            notification.onclick = function () {
                window.focus();
                if (options.tag) {
                    const contact = state.contacts.find((c) => c.id === options.tag);
                    if (contact) openChat(contact);
                }
                notification.close();
            };
        } catch (e) {
            console.error('Notification display error:', e);
        }
    }

    // --- Event Listeners Binding ---
    function bindEvents() {
        // Navigation Buttons
        elements.navButtons.forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const targetView = btn.dataset.navTarget;
                switchView(targetView);
            });
        });

        // Auth Form Events
        if (elements.loginForm) {
            elements.loginForm.addEventListener('submit', handleLogin);
        }
        if (elements.logoutBtn) {
            elements.logoutBtn.addEventListener('click', handleLogout);
        }

        // Message Sending
        if (elements.messageForm) {
            elements.messageForm.addEventListener('submit', sendMessage);
        }

        // Send on Enter (without Shift)
        if (elements.messageInput) {
            elements.messageInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }

        // Contacts Search
        if (elements.contactsSearch) {
            elements.contactsSearch.addEventListener('input', renderContacts);
        }

        // Settings Toggles
        if (elements.themeToggle) {
            elements.themeToggle.addEventListener('change', toggleTheme);
        }

        if (elements.notificationsToggle) {
            elements.notificationsToggle.addEventListener('change', async (e) => {
                if (e.target.checked) {
                    const granted = await requestNotificationPermission();
                    e.target.checked = granted;
                }
            });
        }

        // Reconnect WebSocket on window focus or network recovery
        window.addEventListener('online', connectWebSocket);
        window.addEventListener('focus', () => {
            if (state.token && (!state.socket || state.socket.readyState !== WebSocket.OPEN)) {
                connectWebSocket();
            }
        });
    }

    // Run application on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();