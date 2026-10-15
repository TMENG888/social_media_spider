// Loading stops at an old-year window only after already-discovered candidates
// have dispositions. A date window is not evidence for an unknown candidate.
export function incompleteCandidates(notes){
 return notes.filter(n=>!['completed','skipped_old','skipped_irrelevant','dead_letter'].includes(n.status));
}
