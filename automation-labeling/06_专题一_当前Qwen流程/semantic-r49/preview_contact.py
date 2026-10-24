"""Arrange artifact-tool renders for visual review, not workbook authoring."""
from pathlib import Path
import sys
from PIL import Image,ImageOps,ImageDraw
R=Path(__file__).parent/f'run_{sys.argv[2]}'/f'preview_{sys.argv[1]}'
if not R.exists():R=R.parent/f'previews_{sys.argv[1]}'
files=[p for p in R.glob('*.png') if p.name not in {'contact.png','产品标签与做法.png','产品指标与来源.png'}]
assert len(files)==10
w=800;h=420
canvas=Image.new('RGB',(w*2,h*5),'#E8ECF0')
for i,p in enumerate(files):
    img=Image.open(p).convert('RGB');img.thumbnail((w-12,h-28))
    x=(i%2)*w+6;y=(i//2)*h+24
    canvas.paste(img,(x,y))
canvas.save(R/'contact.png')
print(str(R/'contact.png'))
