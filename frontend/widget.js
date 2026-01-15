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
let sessionId = null; // Store session ID for continuity
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
  chatInput.value = "";
  setInputState(true);

  // Dynamic loading messages: "Thinking..." then "Writing..." if it takes time
  const loaderId = appendMessage("assistant", "Thinking...");
  
  // Set a timeout to update to "Writing..." if response takes longer than 1.5 seconds
  const writingTimeout = setTimeout(() => {
    updateMessage(loaderId, "Writing...");
  }, 1500);

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: conversation, session_id: generateSessionId() }),
    });
    
    // Clear the timeout since we got a response
    clearTimeout(writingTimeout);
    
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Server error");
    }
    const reply = data.reply || "I'm still learning!";
    updateMessage(loaderId, reply);
    conversation.push({ role: "assistant", content: reply });
    renderProducts(data.products || []);
  } catch (error) {
    clearTimeout(writingTimeout);
    updateMessage(loaderId, "Oops, something went wrong. Can you try again?");
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
    link.href = product.permalink;
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

function generateSessionId() {
  // Generate or retrieve session ID for continuity
  if (!sessionId) {
    sessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  }
  return sessionId;
}

// Initialize teaser state on load
showTeaser();


