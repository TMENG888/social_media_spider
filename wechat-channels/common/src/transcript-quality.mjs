import {readFileSync} from 'node:fs';
const rules=JSON.parse(readFileSync(new URL('./transcript-quality-rules.json',import.meta.url),'utf8'));
export const TRANSCRIPT_ARTIFACT_POLICY=rules.policy;
// A negative screen only, never a substitute for media identity/audio proof.
export function transcriptArtifact(value){
 const normalized=String(value??'').replace(/[^0-9A-Za-z\u4e00-\u9fff]/gu,'').toLowerCase();
 return rules.contains.find(marker=>normalized.includes(marker))||null;
}
