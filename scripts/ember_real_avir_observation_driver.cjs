const fs = require('fs');
const http = require('http');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const pty = require('<local-path>');

const root = process.argv[2];
if (!root) {
  console.error('usage: node real_avir_observation_driver.cjs <output-dir>');
  process.exit(2);
}

const avirExe = '<local-path>';
const repoCwd = '<local-path>';
const outDir = path.resolve(root);
const tempHome = path.join(outDir, 'temp-home');
const avirHome = path.join(tempHome, '.avir');
const transcriptPath = path.join(outDir, 'terminal-transcript.txt');
const cleanTranscriptPath = path.join(outDir, 'terminal-transcript-clean.txt');
const stubLogPath = path.join(outDir, 'stub-server-log.jsonl');
const metaPath = path.join(outDir, 'observation-meta.json');
const adapterTracePath = path.join(outDir, 'adapter-trace.log');

fs.mkdirSync(avirHome, { recursive: true });
fs.mkdirSync(path.join(avirHome, 'debug'), { recursive: true });
fs.writeFileSync(path.join(avirHome, 'models.json'), JSON.stringify({
  default: 'codex-observer',
  models: {
    'codex-observer': {
      endpoint: 'http://127.0.0.1:18173',
      managed: false,
      thinking_format: 'none',
      thinking_budget: 0,
      compact_at: 131072,
      sampling_params: {
        temperature: 0,
        top_p: 1
      }
    }
  }
}, null, 2));

function writeJsonl(file, obj) {
  fs.appendFileSync(file, JSON.stringify(obj) + '\n');
}

function stripAnsi(s) {
  return s
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '')
    .replace(/\r/g, '\n');
}

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (chunk) => chunks.push(chunk));
  req.on('end', () => {
    const body = Buffer.concat(chunks).toString('utf8');
    writeJsonl(stubLogPath, {
      ts: new Date().toISOString(),
      method: req.method,
      url: req.url,
      body: body ? JSON.parse(body) : null
    });

    if (req.method === 'GET' && req.url === '/v1/models') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ object: 'list', data: [{ id: 'codex-observer', object: 'model' }] }));
      return;
    }

    if (req.method === 'GET' && req.url === '/props') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ default_generation_settings: { n_ctx: 131072 }, total_slots: 1 }));
      return;
    }

    if (req.method === 'POST' && req.url === '/tokenize') {
      const parsed = body ? JSON.parse(body) : {};
      const content = String(parsed.content || '');
      const n = Math.max(1, Math.ceil(content.length / 4));
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ tokens: Array.from({ length: n }, (_, i) => i + 1) }));
      return;
    }

    if (req.method === 'POST' && req.url === '/v1/chat/completions') {
      const parsed = body ? JSON.parse(body) : {};
      const content = 'OBSERVATION_OK real-avir-uiux-ax loop reached via compiled avir.exe, isolated unmanaged backend, no llama-server spawn requested.';
      if (parsed.stream) {
        res.writeHead(200, {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache',
          connection: 'keep-alive'
        });
        const id = 'chatcmpl-' + crypto.randomBytes(4).toString('hex');
        res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'codex-observer', choices: [{ index: 0, delta: { role: 'assistant' }, finish_reason: null }] })}\n\n`);
        res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'codex-observer', choices: [{ index: 0, delta: { content }, finish_reason: null }] })}\n\n`);
        res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'codex-observer', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] })}\n\n`);
        res.end('data: [DONE]\n\n');
      } else {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({
          id: 'chatcmpl-' + crypto.randomBytes(4).toString('hex'),
          object: 'chat.completion',
          created: Math.floor(Date.now() / 1000),
          model: 'codex-observer',
          choices: [{ index: 0, message: { role: 'assistant', content }, finish_reason: 'stop' }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }
        }));
      }
      return;
    }

    res.writeHead(404, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'not found' }));
  });
});

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  await new Promise((resolve) => server.listen(18173, '127.0.0.1', resolve));
  const startedAt = new Date().toISOString();
  let transcript = '';
  const child = pty.spawn(avirExe, [
    '--bare',
    '--debug-file', path.join(outDir, 'avir-debug.log'),
    '--permission-mode', 'acceptEdits'
  ], {
    name: 'xterm-256color',
    cols: 120,
    rows: 40,
    cwd: repoCwd,
    env: {
      ...process.env,
      HOME: tempHome,
      USERPROFILE: tempHome,
      AVIR_MODEL_NAME: 'codex-observer',
      AVIR_MODEL_URL: 'http://127.0.0.1:18173',
      AVIR_API_KEY: 'local',
      AVIR_DISABLE_NONESSENTIAL_TRAFFIC: '1',
      AVIR_ADAPTER_TRACE: '1',
      AVIR_ADAPTER_TRACE_PATH: adapterTracePath,
      AVIR_MAX_OUTPUT_TOKENS: '512',
      AVIR_NCTX_PROBE_OVERRIDE: '131072',
      AVIR_NCTX_PROBE_OVERRIDE_REASON: 'bounded-real-avir-observation-stub',
      NO_COLOR: '1'
    }
  });

  child.onData((data) => {
    transcript += data;
    fs.writeFileSync(transcriptPath, transcript);
    fs.writeFileSync(cleanTranscriptPath, stripAnsi(transcript));
  });

  let exit = null;
  child.onExit((event) => {
    exit = event;
  });

  await wait(8000);
  child.write('Reply with exactly OBSERVATION_OK and one sentence naming the current executable path.\r');
  await wait(35000);
  child.write('\x03');
  await wait(3000);
  if (!exit) {
    child.kill();
    await wait(1000);
  }

  await new Promise((resolve) => server.close(resolve));
  const cleanTranscript = fs.existsSync(cleanTranscriptPath) ? fs.readFileSync(cleanTranscriptPath, 'utf8') : '';
  const stubLog = fs.existsSync(stubLogPath) ? fs.readFileSync(stubLogPath, 'utf8') : '';
  const meta = {
    ticket: 'EMBER-REAL-AVIR-UIUX-AX-OBSERVATION',
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    avir_exe: avirExe,
    cwd: repoCwd,
    temp_home: tempHome,
    model_backend: 'isolated local OpenAI-compatible stub',
    command: `${avirExe} --bare --debug-file ${path.join(outDir, 'avir-debug.log')} --permission-mode acceptEdits`,
    process_exit: exit,
    files: {
      terminal_transcript: transcriptPath,
      clean_terminal_transcript: cleanTranscriptPath,
      stub_log: stubLogPath,
      adapter_trace: adapterTracePath
    },
    observed_markers: {
      transcript_has_avir: /Avir|avir|Claude|Tip:|cwd|permission|OBSERVATION_OK/i.test(cleanTranscript),
      transcript_has_user_prompt: cleanTranscript.includes('Reply with exactly OBSERVATION_OK'),
      transcript_has_observation_ok: cleanTranscript.includes('OBSERVATION_OK'),
      stub_saw_chat_completion: stubLog.includes('/v1/chat/completions')
    }
  };
  fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));
  console.log(JSON.stringify(meta, null, 2));
}

main().catch(async (err) => {
  try { await new Promise((resolve) => server.close(resolve)); } catch {}
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
