"""Contact sheets of existing PNGs for read-only delivery visual inspection."""
import argparse
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);a=ap.parse_args()
paths=[]
for kind in ['产品信息单元','观点信息单元']:
    paths.extend(p for p in sorted((a.directory/(kind+'_核验')).glob('*.png'))
        if not p.stem.startswith('标签强调方向_') and p.stem not in [kind,'标签字典来源与路径'])
assert len(paths)==28
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',24)
out=a.directory/'visual_review';out.mkdir(exist_ok=True)
for i in range(0,len(paths),4):
    panels=[]
    for path in paths[i:i+4]:
        im=Image.open(path).convert('RGB')
        scale=min(1,1800/im.width)
        if scale<1:im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.LANCZOS)
        panels.append((path,im))
    board=Image.new('RGB',(1840,sum(im.height+64 for _,im in panels)+20),'white')
    draw=ImageDraw.Draw(board);y=10
    for path,im in panels:
        draw.text((20,y),path.parent.name+' / '+path.stem,fill='#17365D',font=font)
        y+=44;board.paste(im,(20,y));y+=im.height+20
    target=out/f'sheets_{i//4+1:02}.png';board.save(target);print(target)
