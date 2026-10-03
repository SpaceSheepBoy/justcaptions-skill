// Open-source MCP adapter. The host supplies the existing API handler and catalog.
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js';
import { z } from 'zod';

const read = { readOnlyHint: true, destructiveHint: false, idempotentHint: true };
const paid = { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true };
export async function handleMcpRequest(request, { handleAPI, catalog }) {
  const origin = request.headers.get('Origin');
  if (origin && origin !== 'https://justcaptions.com') {
    return Response.json({ error: 'Origin not allowed.' }, { status: 403 });
  }
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: {
      'Access-Control-Allow-Origin': 'https://justcaptions.com',
      'Access-Control-Allow-Methods': 'POST, GET, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type, Mcp-Protocol-Version, Mcp-Session-Id',
    } });
  }
  const server = new McpServer({ name: 'justcaptions', version: '1.3.1' }, {
    instructions: 'This remote MCP transcribes audio and edits caption text. It does not read local files or render MP4. For local video captioning, style previews and rendering, install the open-source Just Captions local MCP at https://justcaptions.com/agents/. Paid tools require Authorization: Bearer with your Just Captions API key. Use pricing and get_usage before paid calls. Preserve segments and word timestamps separately from corrected text.',
    maxToolInputElements: 10000,
  });
  const call = async (method, path, input) => {
    const headers = new Headers({ 'Content-Type': 'application/json' });
    const auth = request.headers.get('Authorization');
    if (auth) headers.set('Authorization', auth);
    const retryId = input?.request_id;
    if (retryId) headers.set('Idempotency-Key', retryId);
    const body = input ? { ...input } : undefined;
    if (body) delete body.request_id;
    const reply = await handleAPI(new Request(`https://api.justcaptions.com/v1${path}`, {
      method, headers, ...(body ? { body: JSON.stringify(body) } : {}),
    }), path);
    const data = await reply.json();
    return { content: [{ type: 'text', text: JSON.stringify(data) }], structuredContent: data, ...(reply.ok ? {} : { isError: true }) };
  };
  server.registerTool('list_styles', { description: 'List 15 local rendering presets, aliases, style overrides and platform safe areas. This remote server returns the catalog; render via the local MCP.', annotations: read }, async () => ({ content: [{ type: 'text', text: JSON.stringify(catalog) }], structuredContent: catalog }));
  server.registerTool('get_pricing', { description: 'Current API prices and monthly free allowances, no key needed.', annotations: read }, () => call('GET', '/pricing'));
  server.registerTool('get_usage', { description: 'Current usage, estimated bill and monthly spend cap for your configured API key.', annotations: read }, () => call('GET', '/usage'));
  server.registerTool('estimate_cost', {description:'Estimate additional cloud charges and available allowance before a batch. Includes active budget holds; does not reserve credit.',annotations:read,inputSchema:{audio_seconds:z.number().min(0).max(864000).optional(),text_chars:z.number().int().min(0).max(100000000).optional()}},input=>call('POST','/estimate',input));
  const retry = z.string().min(1).max(100).regex(/^[A-Za-z0-9_-]+$/).optional().describe('Unique request ID; reuse only when retrying identical work to avoid repeating paid calls.');
  const captions = z.array(z.string().min(1)).min(1).max(400);
  const language = z.string().max(32).optional();
  const glossary = z.array(z.string().max(200)).max(100).optional();
  server.registerTool('transcribe_audio', {
    description: 'Transcribe extracted audio into segments and word timestamps. Max 12 MB decoded. Never send video. Charged by audio duration past the free allowance.',
    annotations: paid, inputSchema: { audio_base64: z.string().min(1).max(16000004), mime_type: z.string().max(100), language, glossary, request_id: retry },
  }, input => call('POST', '/transcribe', input));
  server.registerTool('correct_captions', { description: 'Correct caption text, preserving caption count and order. Does not realign word timing. Billed by input characters.', annotations: paid, inputSchema: { captions, language, glossary, request_id: retry } }, input => call('POST', '/correct', input));
  server.registerTool('translate_captions', { description: 'Translate caption lines, preserving count and order. Target-language word timing is estimated by the local renderer. Billed by input characters.', annotations: paid, inputSchema: { captions, target_language: z.string().min(1).max(32), glossary, request_id: retry } }, input => call('POST', '/translate', input));
  server.registerTool('pick_emojis', { description: 'Pick one emoji for each caption. Billed by input characters.', annotations: paid, inputSchema: { captions: z.array(z.string().min(1).max(200)).min(1).max(1000), language, request_id: retry } }, input => call('POST', '/emoji', input));
  const transport = new WebStandardStreamableHTTPServerTransport({ enableJsonResponse: true, maxRequestBodySize: 17000000 });
  await server.connect(transport);
  try {
    const response = await transport.handleRequest(request);
    response.headers.set('Access-Control-Allow-Origin', 'https://justcaptions.com');
    response.headers.set('Cache-Control', 'no-store');
    return response;
  } finally {
    await server.close();
  }
}
