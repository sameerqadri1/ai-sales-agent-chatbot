const API_URL =
  window.BUDDY_WIDGET_CONFIG?.apiUrl || "http://localhost:8000/chat";

const widget = document.getElementById("buddy-widget");
const launcher = document.getElementById("buddy-launcher");
const panel = document.getElementById("buddy-panel");
const teaser = document.getElementById("buddy-teaser");
const minimizeBtn = document.getElementById("buddy-minimize");
const closeBtn = document.getElementById("buddy-close");
const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

const conversation = [];
let greetingShown = false;
let teaserIntervalId = null;
let teaserIndex = 0;
const teaserMessages = [
  "Need a toy suggestion?",
  "Buddy can help—tap to chat!",
];
const greetingMessage =
  "👋 Hi! I'm Buddy the Bear. I'm here to help you grab the perfect toy at the best price. Who are you shopping for today?";

launcher.addEventListener("click", () => {
  if (panel.classList.contains("is-open")) {
    collapsePanel();
  } else {
    openPanel();
  }
});

minimizeBtn.addEventListener("click", () => {
  collapsePanel();
});

closeBtn.addEventListener("click", () => {
  collapsePanel();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && panel.classList.contains("is-open")) {
    collapsePanel();
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  conversation.push({ role: "user", content: message });
  saveConversation();  // Persist conversation
  chatInput.value = "";
  setInputState(true);

  // Show animated thinking indicator
  const thinkingId = showThinkingIndicator("Buddy is finding the perfect toys...");
  
  // Update thinking text if it takes time
  const thinkingTexts = [
    "Buddy is finding the perfect toys...",
    "Searching through our collection...",
    "Almost there..."
  ];
  let textIndex = 0;
  const textInterval = setInterval(() => {
    textIndex = (textIndex + 1) % thinkingTexts.length;
    updateThinkingText(thinkingId, thinkingTexts[textIndex]);
  }, 2000);

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: conversation, session_id: getSessionId() }),
    });
    
    // Clear the interval and hide thinking indicator
    clearInterval(textInterval);
    hideThinkingIndicator(thinkingId);
    
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Server error");
    }
    const reply = data.reply || "I'm still learning!";
    const replyId = appendMessage("assistant", reply);
    // Add fade-in animation
    const replyElement = document.getElementById(replyId);
    if (replyElement) {
      replyElement.classList.add("message-fade-in");
    }
    conversation.push({ role: "assistant", content: reply });
    saveConversation();  // Persist conversation
    renderProducts(data.products || []);
  } catch (error) {
    clearInterval(textInterval);
    hideThinkingIndicator(thinkingId);
    appendMessage("assistant", "Oops, something went wrong. Can you try again?");
    console.error(error);
  } finally {
    setInputState(false);
  }
});

function openPanel() {
  panel.classList.add("is-open");
  panel.setAttribute("aria-hidden", "false");
  launcher.setAttribute("aria-expanded", "true");
  hideTeaser();
  focusInputSoon();

  if (!greetingShown) {
    appendGreeting();
  }
}

function collapsePanel() {
  panel.classList.remove("is-open");
  panel.setAttribute("aria-hidden", "true");
  launcher.setAttribute("aria-expanded", "false");
  showTeaser();
  launcher.focus();
}

function appendGreeting() {
  appendMessage("assistant", greetingMessage);
  conversation.push({ role: "assistant", content: greetingMessage });
  greetingShown = true;
}

function focusInputSoon() {
  setTimeout(() => {
    chatInput.focus();
  }, 250);
}

function showTeaser() {
  teaser.classList.add("is-visible");
  teaser.setAttribute("aria-hidden", "false");
  teaser.textContent = teaserMessages[teaserIndex];
  if (teaserIntervalId) {
    clearInterval(teaserIntervalId);
  }
  teaserIntervalId = setInterval(() => {
    teaserIndex = (teaserIndex + 1) % teaserMessages.length;
    teaser.textContent = teaserMessages[teaserIndex];
  }, 5000);
}

function hideTeaser() {
  teaser.classList.remove("is-visible");
  teaser.setAttribute("aria-hidden", "true");
  if (teaserIntervalId) {
    clearInterval(teaserIntervalId);
    teaserIntervalId = null;
  }
}

function appendMessage(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.dataset.id = generateId();
  
  // Apply formatting: line breaks, bold text, coupon codes in green, and numbered lists
  const formattedText = formatMessageText(text);
  bubble.innerHTML = formattedText;
  
  chatWindow.appendChild(bubble);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return bubble.dataset.id;
}

function updateMessage(id, text) {
  const bubble = chatWindow.querySelector(`[data-id="${id}"]`);
  if (bubble) {
    const formattedText = formatMessageText(text);
    bubble.innerHTML = formattedText;
  }
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function formatMessageText(text) {
  // Step 1: Convert line breaks to <br>
  let formatted = text.replace(/\n/g, "<br>");
  
  // Step 2: Convert **bold** to <strong>bold</strong>
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  
  // Step 3: Convert [COUPON:code] to green colored span
  formatted = formatted.replace(/\[COUPON:(.*?)\]/g, '<span style="color: #22c55e; font-weight: bold; background: rgba(34, 197, 94, 0.1); padding: 2px 6px; border-radius: 4px;">$1</span>');
  
  // Step 4: Ensure numbered lists have proper spacing (line break before "1.", "2.", etc.)
  // This handles cases where AI didn't add double line breaks
  formatted = formatted.replace(/(<br>)?(\d+\.)/g, "<br><br>$2");
  
  return formatted;
}

function showThinkingIndicator(text) {
  const thinkingId = generateId();
  const indicator = document.createElement("div");
  indicator.className = "buddy-thinking";
  indicator.dataset.id = thinkingId;
  indicator.innerHTML = `
    <span class="thinking-avatar">🐻</span>
    <span class="thinking-content">
      <span class="thinking-dots">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <span class="thinking-text">${text}</span>
    </span>
  `;
  chatWindow.appendChild(indicator);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return thinkingId;
}

function updateThinkingText(id, text) {
  const indicator = chatWindow.querySelector(`.buddy-thinking[data-id="${id}"]`);
  if (indicator) {
    const textElement = indicator.querySelector(".thinking-text");
    if (textElement) {
      textElement.textContent = text;
    }
  }
}

function hideThinkingIndicator(id) {
  const indicator = chatWindow.querySelector(`.buddy-thinking[data-id="${id}"]`);
  if (indicator) {
    indicator.remove();
  }
}

function renderProducts(products) {
  // DO NOT remove previous cards - preserve visual history
  // const previousCards = chatWindow.querySelectorAll(".product-card");
  // previousCards.forEach((card) => card.remove());

  products.forEach((product) => {
    const card = document.createElement("div");
    card.className = "product-card";

    if (product.image) {
      const img = document.createElement("img");
      img.src = product.image;
      img.alt = product.name;
      card.appendChild(img);
    }

    const title = document.createElement("h4");
    title.textContent = product.name;
    card.appendChild(title);

    if (product.price) {
      const price = document.createElement("p");
      price.className = "product-price";
      price.textContent = `AED ${product.price}`;
      card.appendChild(price);
    }

    const link = document.createElement("a");
    // Append session ID to product link for cross-tab tracking
    const productUrl = new URL(product.permalink);
    productUrl.searchParams.set('buddy_session', getSessionId());
    link.href = productUrl.toString();
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "View Product";
    card.appendChild(link);

    chatWindow.appendChild(card);
  });

  // Removed: chatWindow.scrollTop = chatWindow.scrollHeight; - products should not force scroll
}

function setInputState(isDisabled) {
  chatInput.disabled = isDisabled;
  chatForm.querySelector("button").disabled = isDisabled;
}

function generateId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Get session ID from URL parameter (for cross-tab continuity).
 */
function getSessionIdFromUrl() {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get('buddy_session');
}

/**
 * Get or create persistent session ID using localStorage.
 * Session persists across page loads and new tabs for continuity.
 * 
 * Benefits:
 * - Rate limiting works correctly across pages
 * - Coupon tracking is preserved
 * - Conversation history is maintained
 * - Shown products are tracked across the site
 */
function getSessionId() {
  const STORAGE_KEY = 'buddy_session_id';
  const SESSION_DURATION = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
  
  try {
    // PRIORITY 1: Check URL parameter (from product link)
    const urlSessionId = getSessionIdFromUrl();
    if (urlSessionId) {
      const sessionData = {
        id: urlSessionId,
        created: Date.now()
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessionData));
      console.log('[Buddy] Session from URL:', urlSessionId);
      return urlSessionId;
    }
    
    // PRIORITY 2: Try to retrieve existing session from localStorage
    const stored = localStorage.getItem(STORAGE_KEY);
    
    if (stored) {
      try {
        const session = JSON.parse(stored);
        const now = Date.now();
        
        // Check if session is still valid (within 24 hours)
        if (session.id && session.created && (now - session.created < SESSION_DURATION)) {
          return session.id;
        }
        
        // Session expired, will create new one below
        console.log('[Buddy] Session expired, creating new session');
      } catch (parseError) {
        // Invalid JSON, will create new session below
        console.warn('[Buddy] Invalid session data, creating new session');
      }
    }
    
    // Create new session
    const newSessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    const sessionData = {
      id: newSessionId,
      created: Date.now()
    };
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessionData));
    console.log('[Buddy] New session created:', newSessionId);
    
    return newSessionId;
    
  } catch (storageError) {
    // localStorage not available (private browsing, disabled, etc.)
    // Fall back to in-memory session (will not persist across page loads)
    console.warn('[Buddy] localStorage not available, using in-memory session');
    if (!window._buddySessionId) {
      window._buddySessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    }
    return window._buddySessionId;
  }
}

/**
 * Save conversation to localStorage for cross-tab persistence.
 */
function saveConversation() {
  try {
    const sessionId = getSessionId();
    const key = `buddy_conversation_${sessionId}`;
    localStorage.setItem(key, JSON.stringify(conversation));
  } catch (e) {
    console.warn('[Buddy] Failed to save conversation:', e);
  }
}

/**
 * Restore conversation from localStorage (for new tabs/page loads).
 */
function restoreConversation() {
  try {
    const sessionId = getSessionId();
    const key = `buddy_conversation_${sessionId}`;
    const stored = localStorage.getItem(key);
    
    if (stored) {
      const restoredConversation = JSON.parse(stored);
      
      if (restoredConversation.length > 0) {
        // Restore conversation array
        conversation.length = 0;
        conversation.push(...restoredConversation);
        
        // Render messages in chat window
        restoredConversation.forEach(msg => {
          if (msg.role === 'assistant') {
            appendMessage('assistant', msg.content);
          } else if (msg.role === 'user') {
            appendMessage('user', msg.content);
          }
        });
        
        greetingShown = true;  // Skip greeting if conversation exists
        console.log('[Buddy] Conversation restored:', restoredConversation.length, 'messages');
      }
    }
  } catch (e) {
    console.warn('[Buddy] Failed to restore conversation:', e);
  }
}

/**
 * Clean up old conversations from localStorage (prevent bloat).
 */
function cleanupOldConversations() {
  try {
    const keys = Object.keys(localStorage);
    const now = Date.now();
    const MAX_AGE = 24 * 60 * 60 * 1000; // 24 hours
    
    keys.forEach(key => {
      if (key.startsWith('buddy_conversation_')) {
        try {
          // Check if session is expired
          const sessionId = key.replace('buddy_conversation_', '');
          const sessionKey = 'buddy_session_id';
          const sessionData = localStorage.getItem(sessionKey);
          
          if (sessionData) {
            const session = JSON.parse(sessionData);
            if (now - session.created > MAX_AGE) {
              localStorage.removeItem(key);
              console.log('[Buddy] Cleaned up old conversation:', sessionId);
            }
          }
        } catch (e) {
          // If we can't parse, remove it
          localStorage.removeItem(key);
        }
      }
    });
  } catch (e) {
    console.warn('[Buddy] Cleanup failed:', e);
  }
}

// Initialize: Restore conversation if exists (cross-tab support)
restoreConversation();
cleanupOldConversations();

// Initialize teaser state on load
showTeaser();


