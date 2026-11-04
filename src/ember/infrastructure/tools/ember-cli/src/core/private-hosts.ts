// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// core/private-hosts.ts — one definition of "a private, loopback or link-local address", used by
// WebFetch (refuses to fetch it) and by Bash/PowerShell (asks before a shell command reaches it).
// Blind test W28: headless Bash ran `curl http://127.0.0.1:...` with no approval, which sidestepped
// the WebFetch block; the two tools must not disagree about what is private.

/** True for a host WebFetch must refuse: loopback, private, link-local (cloud metadata) and unspecified addresses. */
export function isBlockedHost(hostname: string): boolean {
  let h = hostname.trim().toLowerCase();
  // URL.hostname keeps the brackets of an IPv6 literal: "[::1]".
  if (h.startsWith("[") && h.endsWith("]")) h = h.slice(1, -1);
  h = h.replace(/\.$/, "");
  if (h === "") return false;
  if (h === "localhost" || h.endsWith(".localhost")) return true;

  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (v4) {
    const a = Number(v4[1]);
    const b = Number(v4[2]);
    return a === 0                              // 0.0.0.0/8, "this host"
      || a === 10                               // 10/8 private
      || a === 127                              // loopback
      || (a === 169 && b === 254)               // link-local, cloud metadata
      || (a === 172 && b >= 16 && b <= 31)      // 172.16/12 private
      || (a === 192 && b === 168);              // 192.168/16 private
  }

  if (h.includes(":")) {
    if (h === "::1" || h === "::") return true;
    // IPv4-mapped (::ffff:127.0.0.1, or ::ffff:7f00:1 as URL.hostname normalises it)
    const dotted = /^::ffff:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/.exec(h);
    if (dotted) return isBlockedHost(dotted[1]!);
    const hex = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(h);
    if (hex) {
      const hi = parseInt(hex[1]!, 16);
      const lo = parseInt(hex[2]!, 16);
      return isBlockedHost(`${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`);
    }
    if (/^f[cd][0-9a-f]{2}:/.test(h)) return true;       // fc00::/7 unique local
    if (/^fe[89ab][0-9a-f]:/.test(h)) return true;       // fe80::/10 link-local
  }
  return false;
}

/** Resolves a host name to every address it points at (A and AAAA). */
export type HostResolver = (hostname: string) => Promise<string[]>;

export const defaultHostResolver: HostResolver = async (hostname) => {
  const dns = await import("node:dns");
  const found = await dns.promises.lookup(hostname, { all: true, verbatim: true });
  return found.map((a) => a.address);
};

function isIpLiteral(host: string): boolean {
  const h = host.replace(/^\[|\]$/g, "");
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(h) || h.includes(":");
}

/**
 * The first address `hostname` resolves to that WebFetch must refuse (loopback, private,
 * link-local, unspecified; IPv4 and IPv6, IPv4-mapped included), or null. Blind test W20: the
 * literal-text check let localtest.me and 127.0.0.1.nip.io through to a local listener, because
 * those names are public DNS records that point at 127.0.0.1. One private answer among several is
 * enough to refuse. A name that does not resolve is not blocked here: the fetch fails by itself.
 */
export async function blockedResolvedAddress(
  hostname: string,
  resolve: HostResolver = defaultHostResolver,
): Promise<string | null> {
  if (isBlockedHost(hostname)) return hostname;
  if (isIpLiteral(hostname)) return null;
  let addrs: string[];
  try {
    addrs = await resolve(hostname.replace(/\.$/, ""));
  } catch {
    return null;
  }
  for (const a of addrs) {
    if (isBlockedHost(a.replace(/%.*$/, ""))) return a;
  }
  return null;
}

/** Commands that open a network connection. */
const NETWORK_CLIENT =
  /(?<![\w-])(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|nc|ncat|netcat|telnet|ssh|scp|sftp|ftp|test-netconnection|tnc|httpie|urllib|requests|http\.client|net\.webclient|httpclient|socket)(?![\w-])/i;

/** `scheme://user@host:port/` hosts. */
const URL_HOST = /\b[a-z][a-z0-9+.-]*:\/\/(?:[^\s/@'"]*@)?(\[[0-9a-f:.]+\]|[^\s/:'"?#]+)/gi;

/** Bare private hosts and addresses, as written after `curl`, `nc`, `ssh`, `Test-NetConnection`. */
const BARE_HOST =
  /(?<![\w.-])(localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|169\.254(?:\.\d{1,3}){2}|\[?::1\]?)(?![\w.-])/gi;

/**
 * The private/loopback host a shell command appears to connect to, or null. Best effort and meant
 * as a tripwire for the plain `curl http://127.0.0.1:8080/` case: a host built with variables or
 * command substitution is not seen. The real boundary is the permission mode.
 */
export function privateHostInCommand(command: string): string | null {
  if (!NETWORK_CLIENT.test(command)) return null;
  for (const m of command.matchAll(URL_HOST)) {
    if (isBlockedHost(m[1]!)) return m[1]!;
  }
  for (const m of command.matchAll(BARE_HOST)) {
    if (isBlockedHost(m[1]!)) return m[1]!;
  }
  return null;
}

export function privateHostAskMessage(host: string): string {
  return `The command connects to ${host}, a private or loopback address (WebFetch refuses these), so it needs approval.`;
}
