"use client";

import { setNonce } from "get-nonce";

/**
 * Radix's scroll lock (react-remove-scroll → react-style-singleton) injects a <style> tag
 * at runtime and takes its nonce from `get-nonce`. Without this, the strict CSP in
 * src/proxy.ts blocks it whenever a dialog opens.
 */
export function StyleNonce({ nonce }: { nonce: string | null }) {
  if (nonce) setNonce(nonce);
  return null;
}
