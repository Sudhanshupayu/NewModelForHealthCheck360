/**
 * HealthCheck360 Bot - Frontend Application
 */

class HealthCheckBot {
    constructor() {
        this.sessionId = this.generateSessionId();
        this.ws = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        
        this.initElements();
        this.initEventListeners();
        this.connectWebSocket();
    }
    
    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
    
    initElements() {
        this.messagesContainer = document.getElementById('messages');
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.clearBtn = document.getElementById('clearBtn');
        this.connectionStatus = document.getElementById('connectionStatus');
    }
    
    initEventListeners() {
        // Send button click
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        
        // Clear button click
        this.clearBtn.addEventListener('click', () => this.clearChat());
        
        // Input handling
        this.messageInput.addEventListener('input', () => {
            this.autoResizeTextarea();
            this.updateSendButton();
        });
        
        // Keyboard shortcuts
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Event delegation for Copy buttons inside code blocks
        this.messagesContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.copy-btn');
            if (!btn) return;
            const targetId = btn.dataset.target;
            const codeEl = document.getElementById(targetId);
            if (!codeEl) return;
            this.copyToClipboard(codeEl.innerText, btn);
        });
    }

    copyToClipboard(text, buttonEl) {
        const setCopied = () => {
            const label = buttonEl.querySelector('.copy-label');
            if (!label) return;
            const original = label.textContent;
            label.textContent = 'Copied!';
            buttonEl.classList.add('copied');
            setTimeout(() => {
                label.textContent = original;
                buttonEl.classList.remove('copied');
            }, 1500);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(setCopied).catch(() => {
                this._legacyCopy(text);
                setCopied();
            });
        } else {
            this._legacyCopy(text);
            setCopied();
        }
    }

    _legacyCopy(text) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (_) {}
        document.body.removeChild(ta);
    }
    
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ws/${this.sessionId}`;
        
        console.log('Connecting to WebSocket:', wsUrl);
        this.updateConnectionStatus('connecting');
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.updateConnectionStatus('connected');
            this.updateSendButton();
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.isConnected = false;
            this.updateConnectionStatus('disconnected');
            this.updateSendButton();
            this.attemptReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus('disconnected');
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleServerMessage(data);
        };
    }
    
    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
            
            setTimeout(() => this.connectWebSocket(), delay);
        }
    }
    
    updateConnectionStatus(status) {
        const statusText = this.connectionStatus.querySelector('.status-text');
        
        this.connectionStatus.className = 'connection-status ' + status;
        
        switch (status) {
            case 'connected':
                statusText.textContent = 'Connected';
                break;
            case 'connecting':
                statusText.textContent = 'Connecting...';
                break;
            case 'disconnected':
                statusText.textContent = 'Disconnected';
                break;
        }
    }
    
    updateSendButton() {
        const hasText = this.messageInput.value.trim().length > 0;
        this.sendBtn.disabled = !hasText || !this.isConnected;
    }
    
    autoResizeTextarea() {
        const textarea = this.messageInput;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
    }
    
    sendMessage() {
        const message = this.messageInput.value.trim();
        
        if (!message || !this.isConnected) return;
        
        // Add user message to UI
        this.addMessage('user', message);
        
        // Clear input
        this.messageInput.value = '';
        this.autoResizeTextarea();
        this.updateSendButton();
        
        // Send to server
        this.ws.send(message);
    }
    
    handleServerMessage(data) {
        switch (data.type) {
            case 'thinking':
                this.showThinkingIndicator();
                break;
            case 'response':
                this.hideThinkingIndicator();
                this.addMessage('assistant', data.content);
                break;
            case 'error':
                this.hideThinkingIndicator();
                this.addMessage('assistant', `Error: ${data.content}`, true);
                break;
        }
    }
    
    addMessage(role, content, isError = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const avatar = role === 'user' ? 
            `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
            </svg>` :
            `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 6v6l4 2"/>
            </svg>`;
        
        const header = role === 'user' ? 'You' : 'HealthCheck360 Assistant';
        const formattedContent = this.formatMessage(content);
        
        messageDiv.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-header">${header}</div>
                <div class="message-text ${isError ? 'error' : ''}">${formattedContent}</div>
            </div>
        `;
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
    }
    
    escapeHtml(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    formatMessage(content) {
        // Extract fenced code blocks first so we don't HTML-escape their content
        // or apply inline-markdown rules inside code.
        const codeBlocks = [];
        const placeholder = (i) => `__CODEBLOCK_${i}__`;
        const fenceRegex = /```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g;

        let preProcessed = content.replace(fenceRegex, (match, lang, code) => {
            const idx = codeBlocks.length;
            codeBlocks.push({ lang: (lang || 'plaintext').toLowerCase(), code: code.replace(/\n$/, '') });
            return placeholder(idx);
        });

        // Escape HTML on the non-code portion, then apply simple markdown.
        preProcessed = this.escapeHtml(preProcessed)
            // Bold
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            // Italic (avoid matching inside ** by requiring non-space start)
            .replace(/(^|[^*])\*([^*\n]+?)\*/g, '$1<em>$2</em>')
            // Inline code
            .replace(/`([^`\n]+?)`/g, '<code class="inline-code">$1</code>')
            // Line breaks
            .replace(/\n/g, '<br>');

        // Re-insert code blocks as rendered HTML
        preProcessed = preProcessed.replace(/__CODEBLOCK_(\d+)__/g, (m, iStr) => {
            const i = parseInt(iStr, 10);
            return this.renderCodeBlock(codeBlocks[i].lang, codeBlocks[i].code);
        });

        return preProcessed;
    }

    renderCodeBlock(lang, code) {
        const escaped = this.escapeHtml(code);
        const langLabel = lang && lang !== 'plaintext' ? lang : 'code';
        const blockId = 'cb_' + Math.random().toString(36).slice(2, 10);
        return `
<div class="code-block" data-lang="${this.escapeHtml(lang)}">
  <div class="code-block-header">
    <span class="code-lang">${this.escapeHtml(langLabel)}</span>
    <button class="copy-btn" type="button" data-target="${blockId}" aria-label="Copy code">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
      </svg>
      <span class="copy-label">Copy</span>
    </button>
  </div>
  <pre class="code-block-body"><code id="${blockId}">${escaped}</code></pre>
</div>`;
    }
    
    showThinkingIndicator() {
        // Remove existing thinking indicator
        this.hideThinkingIndicator();
        
        const thinkingDiv = document.createElement('div');
        thinkingDiv.className = 'message assistant thinking';
        thinkingDiv.id = 'thinkingIndicator';
        
        thinkingDiv.innerHTML = `
            <div class="message-avatar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M12 6v6l4 2"/>
                </svg>
            </div>
            <div class="message-content">
                <div class="message-header">HealthCheck360 Assistant</div>
                <div class="message-text">
                    <div class="thinking-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                    <span>Thinking...</span>
                </div>
            </div>
        `;
        
        this.messagesContainer.appendChild(thinkingDiv);
        this.scrollToBottom();
    }
    
    hideThinkingIndicator() {
        const indicator = document.getElementById('thinkingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }
    
    async clearChat() {
        // Clear UI messages (except welcome)
        const messages = this.messagesContainer.querySelectorAll('.message:not(:first-child)');
        messages.forEach(msg => msg.remove());
        
        // Clear server-side history
        try {
            await fetch(`/api/clear/${this.sessionId}`, { method: 'POST' });
            console.log('Chat history cleared');
        } catch (error) {
            console.error('Failed to clear server history:', error);
        }
    }
    
    scrollToBottom() {
        const container = document.querySelector('.chat-container');
        container.scrollTop = container.scrollHeight;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.healthCheckBot = new HealthCheckBot();
});
