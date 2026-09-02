// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-in-chrome.ts — Chrome extension bridge: native host, model relay, and bridge detection.

import net from 'net';

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const MAX_MESSAGE_SIZE = 1024 * 1024; // 1 MB
export const CHROME_EXTENSION_ID = 'fcoeoabgfenejglbffodgkkbkcdhcgfn';
export const CHROME_TOOL_PREFIX = 'mcp__ember-in-chrome__';

// ---------------------------------------------------------------------------
// Chrome tool label map (AC2: 18+ known tools with descriptive labels)
// ---------------------------------------------------------------------------

const CHROME_TOOL_LABELS: Record<string, string> = {
  browser_batch:        'Batch browser actions',
  computer:             'Control browser cursor/keyboard',
  navigate:             'Navigate to URL',
  find:                 'Find elements on page',
  tabs_create_mcp:      'Create new tab',
  tabs_context_mcp:     'Get tab context',
  tabs_close_mcp:       'Close tab',
  read_page:            'Read page accessibility tree',
  form_input:           'Fill form field',
  file_upload:          'Upload file',
  upload_image:         'Upload image',
  screenshot:           'Take screenshot',
  wait_for:             'Wait for element/text',
  gif_creator:          'Create GIF recording',
  select_option:        'Select dropdown option',
  javascript_tool:      'Execute JavaScript',
  get_page_text:        'Extract page text',
  read_console_messages:   'Read console messages',
  read_network_requests:   'Read network requests',
};

// ---------------------------------------------------------------------------
// renderChromeToolUseMessage
// ---------------------------------------------------------------------------

export function renderChromeToolUseMessage(toolName: string): string {
  if (!toolName.startsWith(CHROME_TOOL_PREFIX)) {
    return toolName;
  }
  const suffix = toolName.slice(CHROME_TOOL_PREFIX.length);
  const label = CHROME_TOOL_LABELS[suffix];
  return label ?? toolName;
}

// ---------------------------------------------------------------------------
// ChromeNativeHost — native messaging host (reads/writes from Chrome extension)
// ---------------------------------------------------------------------------

export class ChromeNativeHost {
  private _server: net.Server | null = null;

  async start(socketPath: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this._server = net.createServer((socket) => {
        let buffer = Buffer.alloc(0);

        socket.on('data', (chunk: Buffer) => {
          buffer = Buffer.concat([buffer, chunk]);

          // Read 4-byte LE length prefix
          while (buffer.length >= 4) {
            const msgLen = buffer.readUInt32LE(0);

            // AC1: reject oversized messages
            if (msgLen > MAX_MESSAGE_SIZE) {
              socket.destroy();
              return;
            }

            if (buffer.length < 4 + msgLen) break;

            const msgBuf = buffer.subarray(4, 4 + msgLen);
            buffer = buffer.subarray(4 + msgLen);

            try {
              const msg = JSON.parse(msgBuf.toString('utf8')) as unknown;
              socket.emit('message', msg);
            } catch {
              socket.destroy();
              return;
            }
          }
        });
      });

      this._server.listen(socketPath, () => resolve());
      this._server.on('error', reject);
    });
  }

  async stop(): Promise<void> {
    return new Promise((resolve) => {
      if (this._server) {
        this._server.close(() => resolve());
        this._server = null;
      } else {
        resolve();
      }
    });
  }
}

// ---------------------------------------------------------------------------
// callModelMessages — Lightning mode cloud API relay
// ---------------------------------------------------------------------------

interface ModelMessagesParams {
  model: string;
  max_tokens: number;
  messages: unknown[];
  [key: string]: unknown;
}

interface ModelMessagesDeps {
  apiKey: string;
  fetchFn?: typeof fetch;
}

export async function callModelMessages(
  params: ModelMessagesParams,
  deps: ModelMessagesDeps,
): Promise<unknown> {
  const fetchFn = deps.fetchFn ?? fetch;
  const url = 'https://api.ember.ai/v1/messages';

  const resp = await fetchFn(url, {
    method: 'POST',
    headers: {
      'x-api-key': deps.apiKey,
      'Content-Type': 'application/json',
      'api-version': '2025-01-01',
    },
    body: JSON.stringify(params),
  });

  if (!resp.ok) {
    throw new Error(`Model API error: ${resp.status}`);
  }

  return resp.json();
}

// ---------------------------------------------------------------------------
// isBridgeActive — AC6: returns true when bridge is enabled
// ---------------------------------------------------------------------------

export function isBridgeActive(featureFlag: boolean): boolean {
  if (featureFlag) return true;
  const userType = process.env['USER_TYPE'];
  return userType === 'ant';
}

// ---------------------------------------------------------------------------
// buildChromeFocusLink
// ---------------------------------------------------------------------------

export function buildChromeFocusLink(tabId: number): string {
  return `https://clau.de/chrome/tab/${tabId}`;
}
