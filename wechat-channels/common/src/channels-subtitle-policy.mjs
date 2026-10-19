// Quantity acceptance counts distinct source records, not distinct ASR text.
// Keep legacy similarity filtering outside the explicitly enabled mode.
export function subtitleDedupeEnabled(env=process.env){
 return env.SOCIAL_VOLUME_ENABLED!=='1';
}
