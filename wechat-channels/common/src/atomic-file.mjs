import fs from 'node:fs';
import path from 'node:path';

export function atomicWriteFileSync(target, content, encoding = 'utf8') {
  const resolved = path.resolve(target);
  fs.mkdirSync(path.dirname(resolved), {recursive: true});
  const temporary = `${resolved}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  try {
    fs.writeFileSync(temporary, content, encoding);
    fs.renameSync(temporary, resolved);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}
