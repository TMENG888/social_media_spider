"""Combine already rendered sheet previews for visual review only."""
import sys
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

root=Path(__file__).parent
version=sys.argv[1]
for batch in 'ABC':
    directory=root/f'run_{version}'/f'previews_{batch}'
    files=[f for f in directory.glob('*.png') if f.stem not in {'产品标签与做法','产品指标与来源'}]
    thumb_width,cell_height=1120,610
    canvas=Image.new('RGB',(thumb_width*2,cell_height*((len(files)+1)//2)),'#e7eaf0')
    draw=ImageDraw.Draw(canvas)
    for i,file in enumerate(files):
        im=Image.open(file).convert('RGB')
        im=ImageOps.contain(im,(thumb_width-12,cell_height-35))
        x=(i%2)*thumb_width+6;y=(i//2)*cell_height
        draw.text((x,y+5),file.stem,fill='black')
        canvas.paste(im,(x,y+30))
    canvas.save(directory/'contact.png')
