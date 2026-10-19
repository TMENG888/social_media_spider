import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export const monitorRoot=path.dirname(fileURLToPath(import.meta.url));
export const packageRoot=path.dirname(monitorRoot);
export function platformPath(platform,config={}){
 const defaults={'小红书':'xiaohongshu','抖音':'douyin','视频号':'wechat-channels'};
 const directory=config.platform_directories?.[platform]||(fs.existsSync(path.join(packageRoot,platform))?platform:defaults[platform]);
 const target=path.resolve(packageRoot,directory),relative=path.relative(packageRoot,target);
 if(!relative||relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))throw new Error('PLATFORM_DIRECTORY_OUTSIDE_PACKAGE');
 return target;
}
