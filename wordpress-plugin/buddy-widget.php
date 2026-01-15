<?php
/**
 * Plugin Name: AI Sales Agent Chatbot Widget
 * Description: Embeds the AI Sales Agent conversational shopping assistant for WooCommerce.
 * Version: 1.0.0
 * Author: Sameer Qadri (Sinc Solution Team)
 */

if (!defined('ABSPATH')) {
    exit;
}

define('BUDDY_WIDGET_PLUGIN_VERSION', '1.0.0');
define(
    'BUDDY_WIDGET_DEFAULT_API_URL',
    'http://127.0.0.1:8000/chat'
);

/**
 * Resolve the API URL used by the widget.
 *
 * Allows overriding via the BUDDY_WIDGET_CUSTOM_API_URL constant or
 * the buddy_widget_api_url filter.
 */
function buddy_widget_get_api_url(): string
{
    $api_url = defined('BUDDY_WIDGET_CUSTOM_API_URL')
        ? BUDDY_WIDGET_CUSTOM_API_URL
        : BUDDY_WIDGET_DEFAULT_API_URL;

    /**
     * Filter the API URL used by the Buddy widget.
     *
     * @param string $api_url Default API URL.
     */
    return apply_filters('buddy_widget_api_url', $api_url);
}

/**
 * Enqueue widget assets and inject configuration.
 */
function buddy_widget_enqueue_assets(): void
{
    $base_url = plugin_dir_url(__FILE__) . 'assets/';

    wp_enqueue_style(
        'buddy-widget-style',
        $base_url . 'widget.css',
        [],
        BUDDY_WIDGET_PLUGIN_VERSION
    );

    wp_enqueue_script(
        'buddy-widget-script',
        $base_url . 'widget.js',
        [],
        BUDDY_WIDGET_PLUGIN_VERSION,
        true
    );

    $config = [
        'apiUrl' => esc_url_raw(buddy_widget_get_api_url()),
    ];

    wp_add_inline_script(
        'buddy-widget-script',
        'window.BUDDY_WIDGET_CONFIG = ' . wp_json_encode($config) . ';',
        'before'
    );
}
add_action('wp_enqueue_scripts', 'buddy_widget_enqueue_assets');

/**
 * Output the widget markup in the footer.
 */
function buddy_widget_render_markup(): void
{
    ?>
    <div id="buddy-widget" class="buddy-widget" aria-live="polite">
        <button
            id="buddy-launcher"
            class="buddy-launcher"
            aria-controls="buddy-panel"
            aria-expanded="false"
            aria-label="Open Buddy the Bear chat"
            type="button"
        >
            <span class="launcher-icon" aria-hidden="true">
                <img
                    src="<?php echo esc_url(plugin_dir_url(__FILE__) . 'assets/buddy-bear-icon.png'); ?>"
                    alt=""
                    width="28"
                    height="28"
                />
            </span>
            <span class="launcher-text">Buddy</span>
            <span class="launcher-pulse" aria-hidden="true"></span>
        </button>

        <div
            id="buddy-teaser"
            class="buddy-teaser"
            role="status"
            aria-live="polite"
            aria-hidden="true"
        ></div>

        <section
            id="buddy-panel"
            class="buddy-panel"
            aria-hidden="true"
            aria-label="Buddy the Bear conversational assistant"
        >
            <header class="buddy-panel__header">
                <div class="buddy-identity">
                    <span class="buddy-avatar" aria-hidden="true">
                        <img
                            src="<?php echo esc_url(plugin_dir_url(__FILE__) . 'assets/buddy-bear-icon.png'); ?>"
                            alt=""
                            width="42"
                            height="42"
                        />
                    </span>
                    <div>
                        <p class="buddy-name">Buddy the Bear</p>
                        <p class="buddy-tagline">Toy &amp; gift expert</p>
                    </div>
                </div>
                <div class="buddy-controls">
                    <button
                        type="button"
                        id="buddy-minimize"
                        class="control-btn"
                        aria-label="Minimize chat"
                    >
                        &minus;
                    </button>
                    <button
                        type="button"
                        id="buddy-close"
                        class="control-btn"
                        aria-label="Close chat"
                    >
                        &times;
                    </button>
                </div>
            </header>

            <div
                id="chat-window"
                class="buddy-panel__body"
                role="log"
                aria-live="polite"
                aria-relevant="additions"
            ></div>

            <form id="chat-form" class="buddy-panel__form">
                <label class="visually-hidden" for="chat-input">
                    Ask Buddy for the perfect gift
                </label>
                <input
                    type="text"
                    id="chat-input"
                    placeholder="Ask Buddy for the perfect gift..."
                    autocomplete="off"
                    aria-label="Message Buddy the Bear"
                />
                <button type="submit" class="send-btn">Send</button>
            </form>
        </section>
    </div>
    <?php
}
add_action('wp_footer', 'buddy_widget_render_markup');

