"""Contact sheets of already rendered workbook views for visual QA."""
from PIL import Image,ImageOps,ImageDraw
from pathlib import Path
root=Path(__file__).parent/'run_r40'
for b in 'ABC':
    files=sorted((root/f'previews_{b}').glob('*.png'))
    groups=[files[:6],files[6:]]
    for n,group in enumerate(groups,1):
        thumbs=[]
        for p in group:
            im=Image.open(p).convert('RGB')
            im.thumbnail((1400,720))
            tile=Image.new('RGB',(1440,im.height+44),'#ffffff')
            tile.paste(im,(20,35));ImageDraw.Draw(tile).text((20,10),p.stem,font_size=18,fill='#202b3c')
            thumbs.append(tile)
        h=sum(im.height for im in thumbs)
        canvas=Image.new('RGB',(1440,h),'#d9dfe7')
        y=0
        for im in thumbs:canvas.paste(im,(0,y));y+=im.height
        canvas.save(root/f'preview_index_{b}_{n}.png')
