(function () {
    'use strict';

    const WIDGET = document.getElementById('chatbot-widget');
    if (!WIDGET) return;

    const TOGGLE = document.getElementById('chatbot-toggle');
    const PANEL = document.getElementById('chatbot-panel');
    const CLOSE = document.getElementById('chatbot-close');
    const FULLSCREEN = document.getElementById('chatbot-fullscreen');
    const MESSAGES = document.getElementById('chatbot-messages');
    const FORM = document.getElementById('chatbot-form');
    const INPUT = document.getElementById('chatbot-input');
    const TYPING = document.getElementById('chatbot-typing');
    const ERROR = document.getElementById('chatbot-error');

    const API_MESSAGE = '/chatbot/api/message/';
    const API_HISTORY = '/chatbot/api/history/';
    const API_NEW = '/chatbot/api/new/';

    let conversationId = localStorage.getItem('chatbot_conversation_id') || null;
    let isOpen = false;

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    function getCsrfToken() {
        return getCookie('csrftoken');
    }

    function detectPageContext() {
        const path = window.location.pathname;
        const productMatch = path.match(/^\/products\/([^\/]+)\/$/);
        if (productMatch) {
            return { type: 'product_detail', slug: productMatch[1] };
        }
        const categoryMatch = path.match(/^\/danh-muc\/([^\/]+)\/$/);
        if (categoryMatch) {
            return { type: 'category', slug: categoryMatch[1] };
        }
        return null;
    }

    function formatPrice(value) {
        if (value == null) return '';
        const num = Number(value);
        if (Number.isNaN(num)) return value;
        if (num >= 1_000_000) {
            return `${(num / 1_000_000).toFixed(2).replace('.', ',')} triệuđ`.replace('00 triệuđ', ' triệuđ');
        }
        return `${num.toLocaleString('vi-VN')}đ`;
    }

    function renderMarkdown(text) {
        if (!text) return '';
        let html = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/^\s*[-*]\s+(.+)$/gm, '<li>$1</li>')
            .replace(/(<li>.+<\/li>\n?)+/g, '<ul>$&</ul>')
            .replace(/\n/g, '<br>');
        return html;
    }

    function createMessageElement(role, html, extraClass = '') {
        const wrapper = document.createElement('div');
        wrapper.className = `chatbot-message ${role}`;
        const bubble = document.createElement('div');
        bubble.className = `chatbot-bubble ${extraClass}`;
        bubble.innerHTML = html;
        wrapper.appendChild(bubble);
        return wrapper;
    }

    function renderStars(rating) {
        const full = Math.round(Number(rating || 0));
        let html = '';
        for (let i = 1; i <= 5; i++) {
            html += `<i class="bi bi-star${i <= full ? '-fill' : ''} text-warning"></i>`;
        }
        return html;
    }

    function renderProductCard(product) {
        const discount = product.discount_price && product.discount_price < product.price;
        return `
            <a class="chatbot-product-card" href="${product.url}" target="_blank">
                <img src="${product.image || '/static/img/no-image.png'}" alt="${product.name}" loading="lazy">
                <div class="chatbot-product-body">
                    <div class="chatbot-product-name">${product.name}</div>
                    <div class="chatbot-product-price">
                        ${formatPrice(product.final_price)}
                        ${discount ? `<span class="chatbot-product-original">${formatPrice(product.price)}</span>` : ''}
                    </div>
                    <div class="chatbot-product-meta">
                        ${renderStars(product.rating)} ${product.review_count || 0} đánh giá
                        ${product.in_stock ? '' : '<span class="text-danger">Hết hàng</span>'}
                    </div>
                    ${product.in_stock ? `
                        <button class="btn btn-sm btn-primary chatbot-add-to-cart" data-product-id="${product.id}">
                            <i class="bi bi-cart-plus"></i> Thêm
                        </button>
                    ` : ''}
                </div>
            </a>
        `;
    }

    function renderProducts(products) {
        if (!products || !products.length) return '';
        return `<div class="chatbot-products">${products.map(renderProductCard).join('')}</div>`;
    }

    function renderCompareTable(comparison) {
        if (!comparison || !comparison.products || comparison.products.length < 2) return '';

        const products = comparison.products;
        const headers = ['Thông số', ...products.map(p => p.name)];
        const rows = [];

        function addRow(groupName, values, isDiff) {
            rows.push({ name: groupName, values, isDiff });
        }

        if (comparison.price_row) {
            addRow('Giá', comparison.price_row.values.map(formatPrice), comparison.price_row.is_different);
        }
        (comparison.rows_different || []).forEach(row => {
            addRow(row.group_name, row.values, true);
        });

        let sameRows = '';
        if (comparison.rows_same && comparison.rows_same.length) {
            sameRows = comparison.rows_same.map(row => `
                <tr>
                    <td>${row.group_name}</td>
                    ${row.values.map(v => `<td>${v}</td>`).join('')}
                </tr>
            `).join('');
        }

        const diffRows = rows.map(row => `
            <tr>
                <td>${row.name}</td>
                ${row.values.map(v => `<td class="${row.isDiff ? 'diff' : ''}">${v}</td>`).join('')}
            </tr>
        `).join('');

        const tableId = 'chatbot-compare-' + Date.now();
        return `
            <div class="chatbot-compare-table-wrap">
                <table class="chatbot-compare-table">
                    <thead>
                        <tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>
                    </thead>
                    <tbody>
                        ${diffRows}
                        <tr class="same-rows d-none">${sameRows ? '' : '<td colspan="' + (products.length + 1) + '"></td>'}</tr>
                        ${sameRows}
                    </tbody>
                </table>
                ${comparison.rows_same && comparison.rows_same.length ? `
                    <button class="btn btn-sm btn-outline-secondary chatbot-compare-toggle" data-target="${tableId}">
                        Xem tất cả thông số
                    </button>
                ` : ''}
            </div>
        `;
    }

    function scrollToBottom() {
        MESSAGES.scrollTop = MESSAGES.scrollHeight;
    }

    function appendMessage(role, html, products, comparison) {
        const el = createMessageElement(role, html);
        if (products && products.length) {
            const productsWrap = document.createElement('div');
            productsWrap.innerHTML = renderProducts(products);
            el.querySelector('.chatbot-bubble').appendChild(productsWrap.firstElementChild);
        }
        if (comparison && comparison.products && comparison.products.length) {
            const compareWrap = document.createElement('div');
            compareWrap.innerHTML = renderCompareTable(comparison);
            el.querySelector('.chatbot-bubble').appendChild(compareWrap.firstElementChild);
        }
        MESSAGES.appendChild(el);
        scrollToBottom();
    }

    function setTyping(show) {
        TYPING.classList.toggle('d-none', !show);
        if (show) scrollToBottom();
    }

    function setError(message) {
        if (!message) {
            ERROR.classList.add('d-none');
            ERROR.textContent = '';
            return;
        }
        ERROR.textContent = message;
        ERROR.classList.remove('d-none');
    }

    async function postJSON(url, payload) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const err = new Error(data.error || `HTTP ${response.status}`);
            err.status = response.status;
            err.retryAfter = data.retry_after || 0;
            throw err;
        }
        return response.json();
    }

    async function sendMessage(message) {
        appendMessage('user', renderMarkdown(message));
        INPUT.value = '';
        setTyping(true);
        setError('');

        try {
            const payload = {
                message: message,
                conversation_id: conversationId,
                page_context: detectPageContext(),
            };
            const data = await postJSON(API_MESSAGE, payload);
            conversationId = data.conversation_id;
            localStorage.setItem('chatbot_conversation_id', conversationId);
            appendMessage('assistant', renderMarkdown(data.reply), data.products, data.comparison);
        } catch (err) {
            let msg = err.message || 'Có lỗi xảy ra, bạn thử lại sau nhé.';
            if (err.status === 429) {
                msg = `Bạn đã gửi quá nhiều tin nhắn. Thử lại sau ${err.retryAfter || 'một lát'}.`;
            }
            appendMessage('assistant', renderMarkdown(msg));
        } finally {
            setTyping(false);
        }
    }

    async function loadHistory() {
        if (!conversationId) return;
        try {
            const response = await fetch(`${API_HISTORY}?conversation_id=${conversationId}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) return;
            const data = await response.json();
            MESSAGES.innerHTML = '';
            data.messages.forEach(msg => {
                appendMessage(msg.role, renderMarkdown(msg.content), msg.products, msg.comparison);
            });
            scrollToBottom();
        } catch (err) {
            console.warn('Không load được lịch sử chatbot', err);
        }
    }

    async function createConversation() {
        try {
            const data = await postJSON(API_NEW, {});
            conversationId = data.conversation_id;
            localStorage.setItem('chatbot_conversation_id', conversationId);
        } catch (err) {
            console.error('Không tạo được conversation', err);
        }
    }

    function openPanel() {
        PANEL.classList.remove('d-none');
        isOpen = true;
        if (!conversationId) {
            createConversation();
        } else {
            loadHistory();
        }
    }

    function closePanel() {
        PANEL.classList.add('d-none');
        exitFullscreen();
        isOpen = false;
    }

    function toggleFullscreen() {
        const isFullscreen = PANEL.classList.toggle('chatbot-fullscreen');
        const icon = FULLSCREEN.querySelector('i');
        if (isFullscreen) {
            icon.classList.replace('bi-fullscreen', 'bi-fullscreen-exit');
            FULLSCREEN.setAttribute('aria-label', 'Thu nhỏ');
        } else {
            icon.classList.replace('bi-fullscreen-exit', 'bi-fullscreen');
            FULLSCREEN.setAttribute('aria-label', 'Phóng to');
        }
        setTimeout(scrollToBottom, 260);
    }

    function exitFullscreen() {
        PANEL.classList.remove('chatbot-fullscreen');
        const icon = FULLSCREEN.querySelector('i');
        if (icon) {
            icon.classList.remove('bi-fullscreen-exit');
            icon.classList.add('bi-fullscreen');
        }
        FULLSCREEN.setAttribute('aria-label', 'Phóng to');
    }

    TOGGLE.addEventListener('click', () => {
        if (isOpen) closePanel(); else openPanel();
    });
    CLOSE.addEventListener('click', closePanel);
    FULLSCREEN.addEventListener('click', toggleFullscreen);

    FORM.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = INPUT.value.trim();
        if (!text) return;
        sendMessage(text);
    });

    WIDGET.addEventListener('click', (event) => {
        const quick = event.target.closest('.quick-prompt');
        if (quick) {
            const prompt = quick.getAttribute('data-prompt');
            if (prompt) sendMessage(prompt);
            return;
        }

        const toggleCompare = event.target.closest('.chatbot-compare-toggle');
        if (toggleCompare) {
            const wrap = toggleCompare.closest('.chatbot-compare-table-wrap');
            const sameRows = wrap.querySelectorAll('tbody tr:not(:first-child):not(.same-rows)');
            // Simple toggle: show/hide rows after first (price + diffs)
            const diffCount = wrap.querySelectorAll('thead th').length > 0 ? 1 : 0;
            // More robust: toggle a class on tbody
            const tbody = wrap.querySelector('tbody');
            const expanded = tbody.classList.toggle('show-all');
            toggleCompare.textContent = expanded ? 'Thu gọn thông số' : 'Xem tất cả thông số';
            return;
        }

        const addBtn = event.target.closest('.chatbot-add-to-cart');
        if (addBtn) {
            event.preventDefault();
            event.stopPropagation();
            const productId = addBtn.getAttribute('data-product-id');
            fetch('/gio-hang/them/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: `product_id=${encodeURIComponent(productId)}&quantity=1`,
            })
                .then(r => r.json())
                .then(data => {
                    addBtn.innerHTML = '<i class="bi bi-check2"></i> Đã thêm';
                    addBtn.classList.replace('btn-primary', 'btn-success');
                    if (window.updateCartCount && data.cart_count != null) {
                        window.updateCartCount(data.cart_count);
                    }
                })
                .catch(() => {
                    addBtn.innerHTML = '<i class="bi bi-exclamation-circle"></i> Lỗi';
                });
        }
    });

    // CSS class toggle helper for compare table
    const style = document.createElement('style');
    style.textContent = `
        .chatbot-compare-table tbody:not(.show-all) tr:nth-child(n+${1 + 1}) { display: none; }
        .chatbot-compare-table tbody.show-all tr { display: table-row; }
    `;
    document.head.appendChild(style);
})();
