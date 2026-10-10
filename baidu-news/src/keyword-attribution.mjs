export function normalizeSingleKeyword(value) {
  return String(value || "")
    .normalize("NFKC")
    .split(/[;；\r\n]+/)
    .map((item) => item.replace(/[\u00A0\u2007\u202F]/g, " ").replace(/\s+/g, " ").trim())
    .find(Boolean) || null;
}

export function preferExistingKeyword(existingKeyword, incomingKeyword) {
  return normalizeSingleKeyword(existingKeyword) || normalizeSingleKeyword(incomingKeyword);
}
