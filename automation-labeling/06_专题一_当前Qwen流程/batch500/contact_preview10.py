import argparse
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).parent
parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,choices=[10,500],default=10);parser.add_argument('--folder');args=parser.parse_args()
folder=Path(args.folder) if args.folder else ROOT/f'preview{args.count}'
names=['议题指标','中海_议题指标','保利_议题指标','招商_议题指标','金茂_议题指标','品牌发布者角色指标','产品信息单元','专题一标签体系','测试渠道统计','项目平台文章评论统计','产品标签与做法','产品指标与来源']
canvas=Image.new('RGB',(3000,1800),'#e8edf2');draw=ImageDraw.Draw(canvas)
for i,name in enumerate(names):
    im=Image.open(folder/f'{name}.png').convert('RGB');im.thumbnail((980,410))
    x=(i%3)*1000+10;y=(i//3)*450+30
    canvas.paste(im,(x,y));draw.text((x,y-22),str(i+1)+' '+name,fill='#182638')
canvas.save(folder/'contact.png')
