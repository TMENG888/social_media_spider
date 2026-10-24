import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl


CSV_PATH = Path(r"C:\Users\YS-Insight\Desktop\陈晓锋\参考数据\ods_social_media_post_100_wx.csv")
TEMPLATE_PATH = Path(r"C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\专题一 房地产社媒监测_V6_产品力分析数据模板.xlsx")
TOPIC_1 = "全国地产设计产品力监测"
RULE_VERSION = "topic1-rule-v0.3-test"

# The confirmation workbook is reference data for entity/project disambiguation.
# Rows marked as pending are used as candidate aliases only; they do not become
# automatically confirmed product-line evidence.
CONFIRMATION_PATH = Path(
    r"C:\Users\YS-Insight\Desktop\爬虫任务\爬虫需求文档\专题一 四品牌住宅产品采集确认表\专题一_四品牌住宅产品采集确认表_v8_kimi补充-2.xlsx"
)


def rule(primary, secondary, tertiary, pattern, exclude=None):
    return {
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
        "pattern": re.compile(pattern, re.I),
        "exclude": re.compile(exclude, re.I) if exclude else None,
    }


RULES = [
    rule("总图规划", "楼栋布局与朝向间距", "围合与组团布局", r"(?:楼栋|建筑).{0,16}(?:布局|排布|围合|组团|点式|板式)|(?:围合|组团).{0,10}(?:布局|庭院|楼栋)"),
    rule("总图规划", "楼栋布局与朝向间距", "朝向与楼间距设计", r"(?:楼间距|栋距|日照间距|南北朝向|楼栋朝向)|(?:楼栋|建筑).{0,12}(?:朝向|间距)"),
    rule("总图规划", "社区交通与归家组织", "社区人车与归家流线", r"人车分流|车行.{0,8}(?:入口|流线)|人行.{0,8}(?:入口|流线)|归家流线|社区.{0,8}(?:动线|交通组织)"),
    rule("总图规划", "场地与高差组织", "场地高差处理", r"全域抬板|抬板.{0,10}(?:设计|社区|场地)|(?:场地|社区|园区).{0,8}(?:高差|抬高)|(?:高差|台地).{0,8}(?:组织|设计|打造)"),

    rule("社区主入口及大门", "主入口/门庭", "主入口面宽与高度", r"(?:社区|小区|项目)?(?:主入口|大门|门庭|门楼).{0,28}(?:米|m|面宽|高|宽|尺度)|(?:米|m).{0,12}(?:主入口|大门|门庭|门楼)", r"入户门|室内门"),
    rule("社区主入口及大门", "主入口/门庭", "门楼与门廊构成", r"主入口|社区大门|门庭|门楼|入口门廊|风雨门廊", r"住宅入户门|室内门|地铁入口"),
    rule("社区主入口及大门", "主入口/门庭", "落客与风雨连廊", r"落客区|落客空间|落客厅|风雨连廊|风雨门廊"),
    rule("社区主入口及大门", "主入口/门庭", "无障碍通行设施", r"(?:入口|门庭|大门).{0,16}(?:无障碍|坡道|轮椅)"),
    rule("社区主入口及大门", "主入口/门庭", "入口照明与夜景", r"(?:入口|门庭|大门|门楼).{0,14}(?:照明|灯光|夜景)"),

    rule("园林景观", "园林空间结构", "园林轴线与庭院", r"园林.{0,18}(?:轴线|庭院|花园|空间|组团|序列)|(?:一轴|两轴|三轴|轴线).{0,16}(?:园林|景观|庭院)|下沉庭院|中心花园|宅间花园|归家花园"),
    rule("园林景观", "园林空间结构", "文化景观与艺术装置", r"(?:园林|景观|庭院).{0,18}(?:艺术装置|雕塑|地雕|文化图腾|艺术品)|(?:艺术装置|雕塑|地雕).{0,12}(?:园林|景观|庭院)"),
    rule("园林景观", "儿童活动空间", "儿童分龄活动空间", r"儿童.{0,16}(?:活动|乐园|游乐|分龄|场地|空间)|分龄.{0,10}(?:儿童|活动)"),
    rule("园林景观", "适老空间", "适老步行与休憩", r"适老.{0,16}(?:步道|步行|休憩|座椅|空间|设施)|长者.{0,12}(?:花园|休憩|活动|空间)"),
    rule("园林景观", "户外运动及复合空间", "户外运动与会客场地", r"(?:户外|室外|园林).{0,14}(?:运动|跑道|球场|会客|健身)|(?:跑道|球场|运动场).{0,10}(?:园区|社区|户外)"),
    rule("园林景观", "植物与生态景观", "植物配置与季相", r"植物.{0,18}(?:配置|层次|品种|季相|组团)|乔灌草|乔木|灌木|花境|绿化率|四季.{0,8}(?:花|景)|成龄树|古树"),
    rule("园林景观", "植物与生态景观", "水景雨洪与生态设施", r"雨水花园|下凹绿地|海绵城市|透水铺装|生态水景|镜面水景|跌水|叠水|景观水系"),
    rule("园林景观", "景观材料与设施", "铺装与户外家具", r"(?:园林|景观|庭院|室外).{0,18}(?:铺装|座椅|家具|廊架)|(?:铺装|户外家具|景观座椅).{0,12}(?:园林|景观|庭院|室外)"),
    rule("园林景观", "户外停留与遮阳设施", "遮阳避雨与户外停留", r"(?:廊架|遮阳棚|雨棚|遮阳伞|风雨廊).{0,16}(?:户外|园林|景观|社区|休憩)|(?:户外|园林).{0,12}(?:遮阳|避雨|停留)"),
    rule("园林景观", "人群分区及功能设施", "宠物活动与清洁设施", r"宠物.{0,16}(?:活动|乐园|清洁|冲洗|设施|分区)|人宠分流"),

    rule("建筑立面", "立面设计", "立面构图与比例", r"(?:建筑|外).{0,3}立面.{0,20}(?:构图|比例|线条|曲线|风格|造型|设计)|(?:公建化|现代|东方|海派|古典).{0,10}(?:立面|建筑表情)"),
    rule("建筑立面", "立面设计", "石材铝板玻璃表皮", r"(?:立面|外墙|建筑表皮).{0,18}(?:石材|铝板|玻璃|幕墙|陶板|金属)|(?:石材|铝板|玻璃幕墙|陶板).{0,14}(?:立面|外墙|表皮)"),
    rule("建筑立面", "立面设计", "遮阳与幕墙节点", r"(?:立面|幕墙).{0,16}(?:遮阳|挑檐|节点|格栅)|(?:遮阳|挑檐).{0,12}(?:立面|幕墙|外墙)"),
    rule("建筑立面", "门窗系统", "落地转角与环窗", r"落地窗|转角窗|环幕|环窗|270[°度].{0,6}(?:窗|采光|景观)|大面宽玻璃窗"),
    rule("建筑立面", "门窗系统", "门窗玻璃与型材", r"系统窗|中空玻璃|夹胶玻璃|LOW-?E|断桥铝|铝合金.{0,6}(?:窗|型材)|门窗.{0,14}(?:玻璃|型材|气密|水密)"),
    rule("建筑立面", "阳台栏杆与设备平台", "阳台栏杆与设备平台处理", r"阳台.{0,12}(?:栏杆|玻璃栏板|设备平台)|设备平台.{0,12}(?:遮蔽|百叶|整合)|空调机位.{0,8}(?:隐藏|遮挡)"),

    rule("首层大堂、架空层及地下车库", "首层大堂", "单元大堂尺度与配置", r"(?:首层|入户|单元|归家).{0,8}大堂|大堂.{0,18}(?:挑高|米|面积|配置|材质|尺度)"),
    rule("首层大堂、架空层及地下车库", "首层大堂", "大堂动线与灯光陈设", r"大堂.{0,16}(?:动线|灯光|照明|艺术品|陈设|前台|休息区)"),
    rule("首层大堂、架空层及地下车库", "架空层", "架空层复合空间", r"架空层.{0,24}(?:空间|功能|会客|书吧|亲子|运动|咖啡|花厅)|全架空层|泛会所.{0,6}架空层"),
    rule("首层大堂、架空层及地下车库", "架空层", "架空层会客茶叙与咖啡", r"架空层.{0,20}(?:会客|茶叙|咖啡|花厅|客厅)"),
    rule("首层大堂、架空层及地下车库", "架空层", "架空层运动亲子与文化活动", r"架空层.{0,20}(?:运动|健身|亲子|儿童|阅读|书吧|文化)"),
    rule("首层大堂、架空层及地下车库", "地下车库", "地库采光导视与地坪", r"(?:地库|地下车库).{0,18}(?:采光|导视|灯光|地坪|吊顶|色彩)"),
    rule("首层大堂、架空层及地下车库", "地下车库", "车位与充电配套", r"(?:车位|地库|地下车库).{0,18}(?:充电|配比|尺寸|宽度|预埋)|充电桩|充电管线"),
    rule("首层大堂、架空层及地下车库", "地下车库", "行车动线、净高与通道", r"(?:地库|地下车库).{0,18}(?:动线|净高|通道|转弯|坡道)|车行通道"),
    rule("首层大堂、架空层及地下车库", "地下车库", "地库通风与空气品质", r"(?:地库|地下车库).{0,18}(?:通风|空气|异味|新风)"),
    rule("首层大堂、架空层及地下车库", "地下归家空间", "地下归家与电梯厅", r"(?:地下|地库).{0,10}(?:归家|电梯厅|入户大堂)|地库大堂"),

    rule("户型与空间", "户型整体组织", "动静与居住分区", r"动静分区|动静分离|公私分区|居住分区|卧室区.{0,10}(?:独立|分开)|户型.{0,10}(?:分区|布局)"),
    rule("户型与空间", "户型整体组织", "室内洄游与双通道", r"洄游动线|洄游空间|双通道|双动线|环形动线"),
    rule("户型与空间", "户型整体组织", "玄关与私梯入户组织", r"独立梯厅|私梯入户|电梯入户|双玄关|入户玄关|玄关.{0,10}(?:空间|尺度|收纳)"),
    rule("户型与空间", "户型整体组织", "卫浴分区与洗漱外置", r"三分离|四分离|五分离|洗漱外置|干湿分离|卫浴.{0,8}分区"),
    rule("户型与空间", "户型整体组织", "明卫与卫浴空间关系", r"明卫|暗卫|卫生间.{0,10}(?:采光|窗|套房|相连)"),
    rule("户型与空间", "户型整体组织", "家政洗烘熨空间", r"家政间|家政房|家政空间|洗烘熨|洗衣房|家政阳台"),
    rule("户型与空间", "户型整体组织", "家庭复合功能空间", r"家庭厅|家庭室|家庭起居室|多功能厅|复合空间.{0,10}(?:家庭|居住|生活)"),
    rule("户型与空间", "户型整体组织", "玄关尺度与展示陈列", r"玄关.{0,14}(?:尺度|展示|端景|陈列|仪式)"),
    rule("户型与空间", "户型整体组织", "生活阳台洗晒与家政动线", r"生活阳台.{0,14}(?:洗晒|洗衣|家政|晾晒)|洗晒阳台|家政动线"),
    rule("户型与空间", "户型整体组织", "卧室睡眠健康与私密", r"卧室.{0,14}(?:隔音|遮光|私密|睡眠)|主卧.{0,14}(?:私密|睡眠)"),
    rule("户型与空间", "客餐厨关系", "客餐厨一体化", r"LDK[B|G]?|客餐厨一体|客餐厅一体|餐客一体|横厅.{0,8}(?:餐厅|厨房)"),
    rule("户型与空间", "客餐厨关系", "厨房开放与分合", r"开放式厨房|中西厨.{0,6}(?:分离|分开)|厨房.{0,12}(?:开合|移门|推拉门|玻璃门|可开可合)"),
    rule("户型与空间", "客餐厨关系", "中西厨分工", r"中西双厨|中西厨|西厨.{0,10}(?:中厨|岛台|餐厅)"),
    rule("户型与空间", "客餐厨关系", "岛台与餐厨联动", r"(?:厨房|餐厅|西厨).{0,10}岛台|岛台.{0,14}(?:餐厅|厨房|西厨|水槽|吧台)"),
    rule("户型与空间", "客餐厨关系", "厨房台面布局", r"U型厨房|L型厨房|双排厨房|厨房.{0,10}(?:台面|操作台|操作面)"),
    rule("户型与空间", "客餐厨关系", "冰箱外移与家政衔接", r"冰箱外移|冰箱.{0,12}(?:家政|餐厅|西厨|外置)"),
    rule("户型与空间", "客餐厨关系", "餐厅尺度与聚餐能力", r"餐厅.{0,16}(?:面宽|尺度|米|人餐桌|聚餐)|(?:六人|八人|十人).{0,6}餐桌"),
    rule("户型与空间", "客餐厨关系", "储酒与品饮展示", r"酒柜|储酒|品酒区|品饮区|恒温酒柜"),
    rule("户型与空间", "套房及弹性空间", "双套房与多套房", r"双套房|多套房|三套房|四套房|套房式设计"),
    rule("户型与空间", "套房及弹性空间", "双主卧配置", r"双主卧|双主套"),
    rule("户型与空间", "套房及弹性空间", "可变房间与成长空间", r"可变空间|可变房间|弹性空间|可拆墙|可移动隔墙|成长型空间|N\+1"),
    rule("户型与空间", "空间尺度及室内外关系", "房间面宽进深与高度", r"(?:客厅|卧室|主卧|餐厅|厨房|房间).{0,18}(?:面宽|进深|层高|净高|挑高|米)|(?:面宽|进深|层高|净高|挑高).{0,14}(?:客厅|卧室|主卧|餐厅|厨房)"),
    rule("户型与空间", "空间尺度及室内外关系", "朝南开间与通风采光", r"(?:三|四|五|六|[2-6])开间朝南|全南向|南北通透|双面采光|三面采光|采光面"),
    rule("户型与空间", "空间尺度及室内外关系", "双阳台与功能分工", r"双阳台|生活阳台.{0,12}(?:景观阳台|观景阳台)|南北双阳台"),
    rule("户型与空间", "空间尺度及室内外关系", "客厅卧室与阳台露台联系", r"(?:客厅|卧室|主卧).{0,12}(?:连接|连通|直通|打开).{0,8}(?:阳台|露台)|(?:阳台|露台).{0,10}(?:连接|连通).{0,8}(?:客厅|卧室|主卧)"),
    rule("户型与空间", "空间尺度及室内外关系", "空中花园与错层露台", r"空中花园|错层露台|第四代住宅|立体庭院|空中庭院"),
    rule("户型与空间", "空间尺度及室内外关系", "飘窗与观景空间", r"飘窗|转角飘窗|观景窗|观景空间|IMAX.{0,8}(?:窗|景观)"),
    rule("户型与空间", "空间尺度及室内外关系", "阳台种植休闲与多功能使用", r"阳台.{0,16}(?:种植|花园|休闲|亲子|健身|多功能)|庭院阳台"),
    rule("户型与空间", "灵活独立功能空间", "书房与独立工作间", r"独立书房|书房.{0,12}(?:采光|安静|办公|独立)|工作间|家庭办公"),
    rule("户型与空间", "灵活独立功能空间", "兴趣、儿童与居家运动空间", r"(?:兴趣|儿童|琴房|健身|瑜伽).{0,10}(?:房|空间|室)|居家健身"),
    rule("户型与空间", "家庭复合空间", "客厅展示与收藏陈列", r"客厅.{0,14}(?:展示|收藏|陈列)|展示柜|收藏柜|艺术长廊"),

    rule("收纳", "玄关收纳", "玄关柜体与容量", r"玄关柜|鞋柜|玄关.{0,10}(?:收纳|储物|柜体|容量)"),
    rule("收纳", "玄关收纳", "换鞋雨伞与鞋类分区", r"换鞋凳|雨伞柜|鞋类分区|鞋柜.{0,10}(?:分区|烘鞋|换鞋)"),
    rule("收纳", "玄关收纳", "玄关展示与灵活收纳", r"玄关.{0,10}(?:展示柜|开放格|灵活收纳|端景柜)"),
    rule("收纳", "厨房收纳", "调味碗碟与抽屉分区", r"(?:厨房|橱柜).{0,12}(?:拉篮|抽屉|碗碟|调味|分区收纳)"),
    rule("收纳", "厨房收纳", "转角与升降取物", r"(?:厨房|橱柜).{0,10}(?:转角拉篮|升降拉篮|转角柜|高拉篮)"),
    rule("收纳", "厨房收纳", "餐厨高柜与层架", r"(?:厨房|餐厅|西厨).{0,10}(?:高柜|层架|餐边柜)|餐边柜"),
    rule("收纳", "卧室及卫浴收纳", "衣帽间类型与动线", r"衣帽间|步入式衣柜|主卧.{0,10}衣柜"),
    rule("收纳", "卧室及卫浴收纳", "衣帽间分区与配件", r"衣帽间.{0,14}(?:分区|挂衣|首饰|抽屉|梳妆)|衣柜.{0,12}(?:分区|挂衣|抽屉)"),
    rule("收纳", "卧室及卫浴收纳", "卧室嵌入与通顶储物", r"(?:卧室|主卧|次卧).{0,10}(?:通顶柜|嵌入式柜|衣柜|储物)"),
    rule("收纳", "卧室及卫浴收纳", "镜柜与美妆收纳", r"镜柜|美妆收纳|化妆品收纳"),
    rule("收纳", "卧室及卫浴收纳", "壁龛与卫浴取物", r"(?:卫生间|淋浴|卫浴).{0,10}(?:壁龛|收纳)|淋浴壁龛"),
    rule("收纳", "家政及全屋收纳", "家政清洁工具收纳", r"家政柜|清洁柜|扫把柜|清洁工具.{0,8}收纳"),
    rule("收纳", "家政及全屋收纳", "全屋储藏与容量", r"全屋收纳|收纳率|储物率|储藏室|全屋.{0,8}(?:储物|柜体)"),
    rule("收纳", "家政及全屋收纳", "书房儿童与复合收纳", r"(?:书房|儿童房).{0,10}(?:书柜|收纳|储物|层架)"),

    rule("精装修及材料设备", "室内材料与装修表达", "墙地面石材与板材", r"(?:室内|客厅|餐厅|卧室|玄关|卫生间).{0,16}(?:石材|岩板|木饰面|板材|瓷砖|木地板)|(?:石材|岩板|木饰面|木地板).{0,12}(?:墙面|地面|室内|客厅|餐厅)"),
    rule("精装修及材料设备", "室内材料与装修表达", "色彩与表面处理", r"(?:室内|客厅|卧室|厨房|卫浴).{0,12}(?:配色|色调|色系|哑光|亮光|肌理|表面处理)"),
    rule("精装修及材料设备", "室内材料与装修表达", "地面拼铺与吊顶形式", r"(?:室内|客厅|餐厅|卧室|玄关).{0,12}(?:拼花|拼铺|吊顶|无主灯)|(?:吊顶|拼花地面).{0,10}(?:客厅|餐厅|室内)"),
    rule("精装修及材料设备", "室内材料与装修表达", "分区地面墙面与背景墙选材", r"背景墙|电视墙|沙发墙|床头背景|分区.{0,10}(?:墙面|地面|选材)"),
    rule("精装修及材料设备", "厨卫配置", "嵌入式与集成厨电", r"嵌入式.{0,8}(?:冰箱|烤箱|蒸箱|洗碗机|厨电)|集成厨电|嵌入式厨电"),
    rule("精装修及材料设备", "厨卫配置", "烟灶与厨房小电器", r"油烟机|燃气灶|烟灶|蒸烤箱|洗碗机|厨电.{0,8}(?:品牌|配置)"),
    rule("精装修及材料设备", "厨卫配置", "水槽与厨房龙头", r"厨房.{0,10}(?:水槽|龙头)|大单槽|抽拉龙头"),
    rule("精装修及材料设备", "厨卫配置", "卫浴台盆与龙头", r"(?:卫生间|卫浴).{0,10}(?:台盆|龙头|双台盆)|双台盆"),
    rule("精装修及材料设备", "厨卫配置", "马桶淋浴与浴缸", r"智能马桶|壁挂马桶|浴缸|花洒|淋浴房|马桶.{0,8}(?:品牌|配置)"),
    rule("精装修及材料设备", "厨卫配置", "卫浴舒适设备", r"电热毛巾架|卫浴暖风|镜面除雾|恒温花洒|浴霸"),
    rule("精装修及材料设备", "环境舒适设备", "空气与温度设备", r"新风系统|中央空调|地暖|辐射空调|五恒|六恒|恒温恒湿|除湿系统|空气净化"),
    rule("精装修及材料设备", "环境舒适设备", "净水直饮与软水", r"全屋净水|直饮水|软水机|净水器|前置过滤"),
    rule("精装修及材料设备", "环境舒适设备", "洗烘与晾晒设备", r"洗衣机|烘干机|洗烘套装|电动晾衣架"),
    rule("精装修及材料设备", "门、照明及室内部件", "设备预留点位", r"预留.{0,12}(?:插座|电源|给水|排水|点位|管线|接口)|(?:插座|点位).{0,8}预留"),
    rule("精装修及材料设备", "门、照明及室内部件", "住宅入户门与室内门", r"(?:住宅|家庭|户内)?入户门|室内门|隐形门|通顶门"),
    rule("精装修及材料设备", "门、照明及室内部件", "照明灯带与轨道", r"灯带|轨道灯|磁吸灯|无主灯|筒灯|射灯.{0,8}(?:布局|照明)"),
    rule("精装修及材料设备", "门、照明及室内部件", "固定梳妆与室内部件", r"固定梳妆台|梳妆台|一体化书桌|固定书桌"),
    rule("精装修及材料设备", "门、照明及室内部件", "弱电网络与信息接口", r"弱电箱|网络接口|网口|AP点位|全屋网络|无线AP"),

    rule("会所及配套", "会所空间", "会所位置与空间组织", r"(?:社区|项目|地下|地上)?会所.{0,24}(?:平方米|㎡|平|空间|楼层|面积|设置|配置)|(?:平方米|㎡|平).{0,8}会所"),
    rule("会所及配套", "会所空间", "私宴与商务会谈空间", r"私宴厅|私宴空间|商务会谈|会客包间|宴会厅"),
    rule("会所及配套", "运动配套", "泳池健身与球馆", r"恒温泳池|游泳池|健身房|健身空间|篮球馆|羽毛球馆|球馆"),
    rule("会所及配套", "共享复合空间", "共享阅读餐厨与多功能室", r"共享书吧|共享厨房|共享餐厅|共享客厅|图书馆|阅读室|多功能室|共享空间"),
    rule("会所及配套", "便民配套", "快递与便民设施", r"快递柜|快递驿站|便民设施|社区食堂|共享工具间"),
    rule("会所及配套", "儿童与适老配套", "室内亲子与适老空间", r"(?:会所|室内|公共区域).{0,16}(?:儿童|亲子|适老|长者).{0,8}(?:空间|活动|设施)"),

    rule("智慧社区及智能家居", "社区智慧化", "社区门禁与停车智能", r"(?:社区|小区|地库).{0,14}(?:人脸识别|无感通行|智能门禁|车牌识别|智能停车)|可视门禁"),
    rule("智慧社区及智能家居", "家庭智能控制", "家庭场景与控制入口", r"全屋智能|智能家居|智能中控|场景模式|一键控制|语音控制"),
    rule("智慧社区及智能家居", "家庭智能控制", "灯光窗帘与传感联动", r"智能窗帘|电动窗帘|灯光联动|窗帘联动|人体感应灯|感应照明"),
    rule("智慧社区及智能家居", "家庭智能控制", "离家断电与重要回路", r"一键断电|离家模式.{0,8}断电|重要回路|保留冰箱回路"),
    rule("智慧社区及智能家居", "家庭安全监测", "水气安全与紧急报警", r"燃气报警|漏水报警|水浸传感|紧急按钮|一键报警|烟雾报警"),
    rule("智慧社区及智能家居", "家庭安全监测", "户内安防与可视对讲", r"可视对讲|门磁|入侵报警|户内摄像|智能猫眼"),
    rule("智慧社区及智能家居", "健康及能源管理", "空气感知与能源控制", r"空气质量监测|PM2\.5.{0,8}(?:监测|传感)|能耗管理|能源管理|温湿度传感"),

    rule("材料与工艺工法", "防水、排水及维护", "防水挡水与密封节点", r"防水.{0,18}(?:层|涂料|卷材|节点|挡水|闭水|密封)|挡水坎|止水带|六面防水"),
    rule("材料与工艺工法", "防水、排水及维护", "淋浴排水与地面高差", r"(?:淋浴|卫生间).{0,16}(?:排水|地漏|高差|坡度)|同层排水"),
    rule("材料与工艺工法", "防水、排水及维护", "室外排水与可维护节点", r"(?:室外|园区|园林|景观).{0,16}(?:排水沟|线性排水|防堵网|可拆排水)|(?:排水沟|截水沟).{0,10}(?:可拆|防堵|清理|室外)"),
    rule("材料与工艺工法", "隔声降噪", "墙地面隔声构造", r"浮筑楼板|隔音垫|隔声垫|隔声墙|减震垫|楼板隔声|墙体隔声"),
    rule("材料与工艺工法", "隔声降噪", "门窗隔声构造与测试", r"(?:门窗|玻璃).{0,14}(?:隔声|隔音|分贝|dB)|隔声窗"),
    rule("材料与工艺工法", "环保及耐久", "环保防霉与耐久", r"防霉|耐候|耐久|抗菌材料|低甲醛|零甲醛|环保材料"),
    rule("材料与工艺工法", "建造及安装工法", "石材板材拼接与收边", r"(?:石材|板材|瓷砖|岩板).{0,18}(?:拼接|留缝|缝宽|收边|收口|干挂|铺贴)|海棠角"),
    rule("材料与工艺工法", "建造及安装工法", "台盆台面与设备安装", r"(?:台盆|台面|马桶|龙头|设备).{0,16}(?:安装|固定|检修|连接|收口)"),
    rule("材料与工艺工法", "建造及安装工法", "装配结构与吊顶工法", r"装配式|装配结构|模块化吊顶|吊顶.{0,12}(?:工法|节点|龙骨)|干法施工"),
    rule("材料与工艺工法", "保温隔热及气密", "保温隔热与气密节点", r"保温层|外墙保温|隔热材料|气密性|气密节点|热桥|节能门窗"),
    rule("材料与工艺工法", "防滑及通行安全", "地面防滑与安全节点", r"防滑.{0,16}(?:地砖|地面|拉槽|系数|处理)|地面拉槽"),
    rule("材料与工艺工法", "给排水与管线检修", "给排水管线与检修节点", r"同层排水|检修口|检修空间|给排水管|管线布置|分水器|阀门.{0,8}检修"),
    rule("材料与工艺工法", "防开裂与饰面耐久", "墙地面抗裂与空鼓控制", r"抗裂|防开裂|防空鼓|伸缩缝|基层处理|挂网.{0,8}(?:墙面|抹灰)"),
    rule("材料与工艺工法", "低碳与资源效率", "节能节水与低碳材料", r"节能.{0,12}(?:材料|设备|系统)|节水器具|再生材料|低碳材料|绿色建材|光伏"),

    rule("产品体系与创新", "产品系及定位", "产品系命名与适用定位", r"产品系|产品体系|产品矩阵|[萬方安和天悦人甲誉赋印玺序揽阅天青林屿府璞满棠玖]{1,4}系|玖序|金玉满堂|致美生活图谱"),
    rule("产品体系与创新", "产品标准与研发", "企业标准模块", r"企业标准|产品标准|标准化模块|好房子标准|技术标准|建造标准"),
    rule("产品体系与创新", "产品迭代及研发", "产品迭代与研发验证", r"产品迭代|研发验证|实验室|试验验证|(?:升级|迭代).{0,12}(?:产品|标准|体系|户型|工艺)"),
    rule("产品体系与创新", "体系应用及验证", "体系试点与应用边界", r"(?:体系|标准|产品系).{0,16}(?:落地|应用|试点|首个项目|首发项目)"),
]


NOISE = re.compile(
    r"(?:售楼处|销售中心).{0,18}(?:电话|热线)|400[-—\s]?\d{3}[-—\s]?\d{4}|"
    r"扫码.{0,12}(?:微信|关注|咨询)|添加.{0,8}(?:微信|好友)|联系电话|预约看房|"
    r"免责声明|郑重声明|版权声明|转载.{0,8}(?:联系|授权)|本文仅供参考|"
    r"报名.{0,8}(?:咨询|方式|费用)|课程.{0,8}(?:报名|安排)|研学.{0,8}(?:报名|费用)|"
    r"关注公众号|点击蓝字|点个在看|欢迎转发|商务合作|"
    r"(?:单价|总价|均价|折扣|优惠|首付|佣金|返现).{0,18}(?:万|元|折|起)|"
    r"地铁.{0,12}(?:分钟|公里|站)|学区|学校.{0,12}(?:公里|分钟)"
)
SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])|[\n\r]+")
SPACE = re.compile(r"[\t\u3000 ]+")
PROMO = re.compile(r"封神|顶流|王炸|天花板|重磅|震撼|极致|奢华|豪宅标杆|稀缺|唯一|顶级|惊艳|热销|销冠|抢购|臻藏")
CONCRETE = re.compile(r"\d+(?:\.\d+)?\s*(?:㎡|平米|平方米|米|m|mm|毫米|层|个|处|套|开间|%|度|°)|采用|设置|配置|预留|使用|铺设|安装|连接|分为|形成|打造")
UPGRADE = re.compile(r"相比|较上一代|上一版|从.+到|新增|升级|迭代|提升|优化|首次应用|更新为")
CLAIM = re.compile(r"首创|首次|首个|唯一|领先|创新|革新|突破|全新|颠覆")
COMPARE = re.compile(r"同类|同行|行业|市场|竞品|上一代|旧版|传统做法|相比")


PROJECT_OVERRIDES = {
    "3790131375994823936": "多项目案例（需拆分复核）",
    "541374268997432322": "待判断（东三环项目）",
    "3556247964061951234": "广州保利云城",
    "1532338858809290240": "中环金茂府",
    "2061278883446128128": "保利西子湾",
    "6323616597475683842": "中海·丰和叁號院",
    "5043551634285116672": "待判断（泰州项目）",
    "7369814335544717825": "中海朝阳ONE",
    "420636344140369410": "保利世博天悦",
    "574250575062509056": "中海甲叁號院",
    "4555092255904038658": "保利置业·翡丽甲第",
    "730969642714894849": "南京江宁金茂府",
    "1212036324538486017": "保利天汇",
    "4840379413678011394": "保利香山瑧悦府",
    "6102750557377274624": "保利誉静安",
    "1866189927672964353": "保利都汇和煦",
    "7743051004350693120": "西部乐巢·金茂府",
    "1681786932550637059": "建发金茂观宸",
    "4180452105551262976": "招商·上中隐翠",
    "600371093538534145": "中海·万潮玖序",
    "3510653747630281217": "中海大境",
    "3614363355042456832": "长风金茂悦",
    "1372356641395890176": "保利熙瑞",
    "4698596032515157251": "招商序",
    "1639565779429953282": "招商·林屿间",
    "6437473350341469698": "保利云瑞",
    "4088349571766458112": "华玺",
    "1030350891603880705": "成都中海·翡悦天華",
    "3333919817158478592": "中海·广府萬宸",
    "5609086804991950082": "保利盛棠印",
    "1215076073832192514": "北京丰和叁號院",
    "575391510211191040": "招商徐汇长桥项目",
    "4018694690110234880": "中海海潮玖序",
    "3350059250209447168": "北京臻澐",
    "5387237075065227265": "保利江上印",
    "4968964599246542849": "招商·湖映天青",
    "6179058680929339649": "青羊金茂锦棠",
    "347649758252864256": "晋阳金茂府",
    "5998850165281121024": "中海万潮玖序",
    "2636171174191554050": "保利华创都荟天珺",
    "683580974469269249": "招商海晏府",
    "3802426117774822144": "金茂棠前",
    "148668290381744898": "中海保利朗阅",
    "732707491177680128": "保利海韵",
    "2204988350235841794": "中海甲叁號院",
    "5886432952923525120": "中海·云邸玖章",
    "839013707841936897": "鲸山觐海",
    "4444863715806706689": "金茂璞逸高新",
    "752326435041881857": "保利琅誉",
    "7399017342238828544": "中海峯汇里",
    "695004088915206144": "招商揽阅",
    "4836202378958970368": "保利玥玺湾",
    "650598277925262337": "保利明玥江山",
    "3430899991205860354": "苏州道壹号（叠景星园）",
    "992499867806855170": "新元序",
    "1339826551120725506": "金茂·姑苏满元",
    "2159945060459738369": "招商海晏府",
    "2584272496318961666": "金茂璞印云湾",
    "7289131392705692929": "保利熙瑞",
    "667089159594364930": "保利·世博天悦",
    "5521632270120298496": "中海天誉",
    "2484069652266593025": "杭州招商蛇口爱达1872",
    "2714898326424994049": "招商·湾区1872",
    "7427086035941814529": "中海·云启源境",
    "7194564758111326464": "林溪書院（央序府）",
    "2865387271240872194": "金茂·满昱",
    "116774729723521280": "招商徐汇长桥项目",
    "3938325155689469187": "保利天瓒",
    "7893661930254135040": "多项目案例（需拆分复核）",
    "554164660969864706": "多项目案例（需拆分复核）",
    "6005276953954239745": "多项目案例（需拆分复核）",
    "1207892949509347075": "中海瑞文熙和",
}

BRAND_OVERRIDES = {
    # Confirmation workbook: 北京臻澐 is branded by China Resources Land;
    # China Merchants Shekou is a joint-development participant and must not be
    # counted as an 招商 product-line case.
    "3350059250209447168": "华润置地（招商参与）",
}

ENTITY_OVERRIDES = {
    "3350059250209447168": "北京华润招铁海泽置业（联合开发）",
}

CITY_OVERRIDES = {
    "3556247964061951234": "广州", "1532338858809290240": "上海", "2061278883446128128": "广州",
    "6323616597475683842": "北京", "7369814335544717825": "北京", "420636344140369410": "上海",
    "574250575062509056": "银川", "4555092255904038658": "广州", "730969642714894849": "南京",
    "6102750557377274624": "上海", "1866189927672964353": "上海", "4180452105551262976": "上海",
    "600371093538534145": "杭州", "3510653747630281217": "广州", "3614363355042456832": "上海",
    "1030350891603880705": "成都", "3333919817158478592": "广州", "1215076073832192514": "北京",
    "575391510211191040": "上海", "4018694690110234880": "待判断", "3350059250209447168": "北京",
    "5387237075065227265": "上海", "4968964599246542849": "北京", "6179058680929339649": "成都",
    "347649758252864256": "太原", "5998850165281121024": "杭州", "2636171174191554050": "广州",
    "683580974469269249": "深圳", "3802426117774822144": "待判断", "148668290381744898": "广州",
    "2204988350235841794": "天津", "5886432952923525120": "上海", "4444863715806706689": "西安",
    "752326435041881857": "余姚", "7399017342238828544": "厦门", "4836202378958970368": "广州",
    "3430899991205860354": "天津", "992499867806855170": "淮海区域", "1339826551120725506": "苏州",
    "2159945060459738369": "深圳", "2584272496318961666": "西安", "7289131392705692929": "北京",
    "667089159594364930": "上海",
}


def norm(text):
    return SPACE.sub(" ", str(text or "")).strip()


def clip(text, limit):
    text = norm(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def num(value):
    text = norm(value).replace(",", "")
    if not text:
        return 0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else 0


def infer_brand(row):
    rid = row.get("id", "")
    if rid in BRAND_OVERRIDES:
        return BRAND_OVERRIDES[rid]
    text = " ".join([row.get("关键词", ""), row.get("文章标题", ""), row.get("作者名字", "")])
    hits = [b for b in ["中海", "保利", "招商", "金茂"] if b in text]
    if len(hits) == 1:
        return hits[0]
    keyword = row.get("关键词", "")
    for b in ["中海", "保利", "招商", "金茂"]:
        if b in keyword:
            return b
    return "无法判断"


def infer_entity(row, brand):
    rid = row.get("id", "")
    if rid in ENTITY_OVERRIDES:
        return ENTITY_OVERRIDES[rid]
    text = " ".join([row.get("关键词", ""), row.get("文章标题", ""), row.get("作者名字", ""), row.get("文章内容", "")[:600]])
    if brand == "中海":
        return "中海宏洋" if "宏洋" in text else "中海地产"
    if brand == "保利":
        return "保利置业" if ("保利置业" in text or any(x in text for x in ["翡丽甲第", "誉静安", "盛棠印"])) else "保利发展"
    if brand == "招商":
        return "招商建管" if "招商建管" in text else "招商蛇口"
    if brand == "金茂":
        return "中国金茂"
    return "无法判断"


def infer_source_type(row, brand):
    author = norm(row.get("作者名字"))
    official_keys = ["集团", "公司", "发展", "置业", "招商蛇口", "中国金茂", "中海地产", "保利"]
    if brand in author and any(k in author for k in official_keys):
        return "官方"
    if re.search(r"设计|楼市|房产|新房|财经|研究|观察|资讯|测评|地产|建筑|景观|网", author):
        return "媒体及专业机构"
    return "普通账号" if author else "不明"


def infer_project(row):
    rid = row.get("id", "")
    if rid in PROJECT_OVERRIDES:
        return PROJECT_OVERRIDES[rid]
    title = norm(row.get("文章标题"))
    if any(k in title for k in ["各大地产", "案例合集", "合集", "盘点"]):
        return "多项目案例（需拆分复核）"
    if any(k in title for k in ["产品系", "业绩公布", "行业排名", "战略核心", "代建综合能力", "好房子专题"]):
        return "品牌级内容"
    patterns = [
        r"((?:中海|保利|招商|金茂|华润)[·・\-]?[A-Za-z0-9\u4e00-\u9fa5]{2,14}(?:府|院|湾|城|里|序|章|玺|誉|印|棠|悦|汇|境|天青|ONE))",
        r"([A-Za-z0-9\u4e00-\u9fa5·・]{2,16}金茂府)",
        r"([A-Za-z0-9\u4e00-\u9fa5·・]{2,16}(?:叁號院|号院|天悦|玖序|甲第|海晏府|云启源境))",
    ]
    for pat in patterns:
        match = re.search(pat, title, re.I)
        if match:
            candidate = re.sub(r"^(官方公告|全网首发|原创|首发)", "", match.group(1)).strip(" ：:｜|")
            if 3 <= len(candidate) <= 24:
                return candidate
    return "待判断"


def project_mapping_basis(row, project):
    rid = row.get("id", "")
    if rid == "3350059250209447168":
        return "专题一确认表：项目挂华润置地品牌，招商蛇口为联合开发参与方，不计入招商产品线案例"
    if rid in PROJECT_OVERRIDES:
        return "样本原文/标题明确案名；按确认表的主体与项目角色分离口径规范化"
    if project == "品牌级内容":
        return "品牌或产品体系层内容，未绑定单一项目"
    if project == "多项目案例（需拆分复核）":
        return "同文出现多个项目，未将整篇内容强行归入单一项目"
    if project.startswith("待判断"):
        return "现有标题、关键词及确认表候选不能唯一确定项目"
    return "标题/关键词规则匹配，需在正式生产中以项目字典复核"


def project_role_note(row, brand, entity, project):
    rid = row.get("id", "")
    if rid == "3350059250209447168":
        return "项目品牌：华润置地；联合开发：华润置地×招商蛇口×中铁置业；招商为参与方"
    if project == "多项目案例（需拆分复核）":
        return "多项目文章：须按具体项目与证据段落继续拆分"
    title = norm(row.get("文章标题"))
    mentioned = [name for name in ["中海", "保利", "招商", "金茂", "建发", "华润", "越秀", "中建"] if name in title]
    if len(set(mentioned)) > 1:
        return f"合作/共现项目：当前保留{brand}专题命中，具体投资、操盘或设计角色待核"
    if project == "品牌级内容":
        return f"品牌/体系层：{entity}"
    return f"专题归属：{brand}；经营主体：{entity}"


def infer_city(row):
    rid = row.get("id", "")
    if rid in CITY_OVERRIDES:
        return CITY_OVERRIDES[rid]
    text = " ".join([row.get("文章标题", ""), row.get("关键词", ""), row.get("文章内容", "")[:300]])
    cities = ["北京", "上海", "广州", "深圳", "武汉", "杭州", "南京", "苏州", "成都", "西安", "天津", "厦门", "佛山", "中山", "泰州", "太原", "银川", "余姚", "大连", "宁波", "重庆", "青岛", "济南", "福州", "合肥", "郑州", "长沙", "南昌", "无锡", "昆明"]
    for city in cities:
        if city in text:
            return city
    return "待判断"


def product_series(text, brand, entity, brand_dict):
    matches = []
    for item in brand_dict:
        if item["品牌组"] != brand or item["经营主体"] != entity:
            continue
        labels = [item.get("产品系"), item.get("别名/子系列")]
        for label in labels:
            if not label:
                continue
            for token in re.split(r"[、,，/；;\s]+", str(label)):
                if token and token != "待核" and token in text:
                    matches.append(item)
                    break
    if not matches:
        return None, None, "无法判断"
    item = matches[0]
    status = "已匹配" if len(matches) == 1 else "待核"
    return item.get("体系/矩阵"), item.get("产品系"), status


def infer_grade(text):
    if re.search(r"顶豪|顶级豪宅|千万级|亿元|豪宅", text):
        return "顶豪"
    if re.search(r"高端|改善|大平层|平墅|洋房|四代住宅", text):
        return "改善" if "改善" in text and not re.search(r"高端|豪宅|大平层|平墅", text) else "高端"
    if re.search(r"刚需|上车|小户型", text):
        return "刚需"
    return "无法判断"


def perspective_tags(text):
    found = []
    checks = [
        ("网红盘", r"网红盘|热销|销冠|红盘|封神"),
        ("豪宅标杆", r"豪宅|顶豪|标杆|高端"),
        ("产品创新", r"创新|升级|迭代|新规|革新|突破"),
        ("审美/颜值", r"美学|颜值|审美|设计感|艺术"),
        ("科技住宅", r"科技住宅|智能家居|五恒|六恒|新风|智慧"),
        ("精工品质", r"精工|工艺|匠心|品质|材料|交付"),
        ("生活方式", r"生活方式|场景|社交|圈层|度假"),
    ]
    for name, pat in checks:
        if re.search(pat, text, re.I):
            found.append(name)
    return "；".join(found[:3]) if found else "无法判断"


def split_segments(body):
    segments = []
    noise_count = 0
    seen = set()
    for idx, raw in enumerate(SENT_SPLIT.split(body or ""), 1):
        text = norm(raw).strip("，,、:：-—|/（）()[]【】")
        if len(text) < 10:
            continue
        if NOISE.search(text):
            noise_count += 1
            continue
        key = re.sub(r"[\W_]+", "", text.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        segments.append((idx, text))
    return segments, noise_count


def clean_practice(text):
    text = PROMO.sub("", text)
    text = re.sub(r"[！!]{2,}", "。", text)
    text = re.sub(r"^[一二三四五六七八九十\d]+[、.．]\s*", "", text)
    return clip(text.strip(" ，,。；;：:"), 360)


def build_units(row, brand, entity, project, city, brand_dict):
    body = norm(row.get("文章内容"))
    segments, noise_count = split_segments(body)
    groups = defaultdict(lambda: {"evidence": [], "tertiary": [], "score": 0.0, "positions": []})
    for pos, text in segments:
        for item in RULES:
            if item["exclude"] and item["exclude"].search(text):
                continue
            if not item["pattern"].search(text):
                continue
            key = (item["primary"], item["secondary"])
            score = 0.56
            if CONCRETE.search(text):
                score += 0.14
            if item["tertiary"] in text:
                score += 0.05
            if len(text) >= 35:
                score += 0.04
            if PROMO.search(text):
                score -= 0.05
            g = groups[key]
            g["score"] = max(g["score"], score)
            if item["tertiary"] not in g["tertiary"]:
                g["tertiary"].append(item["tertiary"])
            if len(g["evidence"]) < 4 and text not in g["evidence"]:
                g["evidence"].append(text)
                g["positions"].append(pos)

    # Prefer more concrete groups and cap very broad articles to keep the unit grain usable.
    ordered = sorted(
        groups.items(),
        key=lambda kv: (kv[1]["score"], sum(bool(CONCRETE.search(x)) for x in kv[1]["evidence"]), len(kv[1]["evidence"])),
        reverse=True,
    )[:16]

    series_text = " ".join([row.get("文章标题", ""), row.get("关键词", ""), body[:2000]])
    system, series, match_status = product_series(series_text, brand, entity, brand_dict)
    grade = infer_grade(series_text)
    result = []
    for seq, ((primary, secondary), g) in enumerate(ordered, 1):
        evidence = g["evidence"][:3]
        evidence_text = "；".join(clip(x, 240) for x in evidence)
        tertiary = "；".join(g["tertiary"][:4])
        joined = " ".join(evidence)
        if UPGRADE.search(joined) and COMPARE.search(joined):
            innovation_level = "I2 有升级迭代证据"
            basis = "原文同时出现升级/变化与比较基线；仍需人工核对比较对象、版本和适用范围。"
        elif CLAIM.search(joined):
            innovation_level = "I1 来源宣称创新"
            basis = "来源使用首次、创新或全新等表述，但未形成可独立核验的同类比较证据。"
        else:
            innovation_level = "I0 无创新判断"
            basis = "原文可支持具体产品做法，但未提供升级基线或同类差异证据。"
        if primary == "材料与工艺工法":
            innovation_type = "工艺创新"
        elif primary == "智慧社区及智能家居":
            innovation_type = "技术集成创新"
        elif primary == "产品体系与创新":
            innovation_type = "产品创新"
        else:
            innovation_type = "设计创新" if innovation_level != "I0 无创新判断" else "无明确创新类型"

        confidence = round(max(0.35, min(0.92, g["score"])), 2)
        review_reasons = []
        if project in ["待判断", "多项目案例（需拆分复核）"] or project.startswith("待判断"):
            review_reasons.append("项目归属待核")
            confidence = min(confidence, 0.66)
        if brand not in {"中海", "保利", "招商", "金茂"}:
            review_reasons.append("合作开发参与角色需核；不得计入单一品牌产品线")
            confidence = min(confidence, 0.66)
        if innovation_level == "I2 有升级迭代证据":
            review_reasons.append("I2需核对比较基线")
        if confidence < 0.72:
            review_reasons.append("规则匹配置信度不足")
        review_status = "需人工复核" if review_reasons else "自动通过（测试）"
        note = "；".join(review_reasons) if review_reasons else "规则自动切片；建议抽样复核原文上下文。"
        mapping_basis = project_mapping_basis(row, project)
        role_note = project_role_note(row, brand, entity, project)
        result.append({
            "unit_id": f"T1-{row['id']}-M{seq:02d}",
            "content_id": f"T1-{row['id']}",
            "证据序号": seq,
            "原文摘录": evidence_text,
            "证据定位": "正文句段" + "、".join(str(x) for x in g["positions"][:3]),
            "品牌组": brand,
            "经营主体": entity,
            "项目": project,
            "项目映射依据": mapping_basis,
            "项目角色/归属说明": role_note,
            "城市": city,
            "产品体系": system,
            "产品系标签": series,
            "产品系匹配状态": match_status,
            "产品档": grade,
            "一级维度": primary,
            "二级维度": secondary,
            "三级强调方向": tertiary,
            "具体产品做法": "原文提及：" + clean_practice(evidence_text),
            "创新类型": innovation_type,
            "创新等级": innovation_level,
            "创新依据": basis,
            "备注": note,
            "_confidence": confidence,
            "_review_status": review_status,
            "_review_reason": "；".join(review_reasons),
            "_rule_version": RULE_VERSION,
            "_title": row.get("文章标题", ""),
            "_link": row.get("文章链接", ""),
        })
    return result, len(segments), noise_count


def load_template_data():
    wb = openpyxl.load_workbook(TEMPLATE_PATH, read_only=True, data_only=True)
    label_rows = []
    for row in wb["02_标签字典"].iter_rows(min_row=2, values_only=True):
        if row[0] and row[1] and row[2]:
            label_rows.append({"一级维度": row[0], "二级维度": row[1], "三级强调方向": row[2], "打标说明": row[3]})
    brand_rows = []
    headers = [x for x in next(wb["03_品牌产品系字典"].iter_rows(min_row=1, max_row=1, values_only=True))]
    for row in wb["03_品牌产品系字典"].iter_rows(min_row=2, values_only=True):
        if row[0]:
            brand_rows.append(dict(zip(headers, row)))
    wb.close()
    return label_rows, brand_rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    label_rows, brand_dict = load_template_data()
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    article_rows = []
    units = []
    review_rows = []
    for row in source_rows:
        is_topic_1 = row.get("项目") == TOPIC_1
        brand = infer_brand(row)
        entity = infer_entity(row, brand)
        project = infer_project(row)
        city = infer_city(row)
        source_type = infer_source_type(row, brand)
        body = norm(row.get("文章内容"))
        row_units = []
        segment_count = 0
        noise_count = 0
        if is_topic_1 and len(body) >= 50:
            row_units, segment_count, noise_count = build_units(row, brand, entity, project, city, brand_dict)
            units.extend(row_units)
        elif is_topic_1:
            _, noise_count = split_segments(body)

        if not is_topic_1:
            process_status = "不纳入-专题二"
            relevance = "待判断"
            review_reason = "当前工作按专题一模板处理"
        elif len(body) < 50:
            process_status = "待OCR"
            relevance = "待判断"
            review_reason = "正文不足50字且图片OCR结果为空"
        elif not row_units:
            process_status = "需人工复核"
            relevance = "仅线索"
            review_reason = "未识别出模板内可交付的物理产品单元"
        else:
            pending = sum(u["_review_status"] == "需人工复核" for u in row_units)
            process_status = "需人工复核" if pending else "已完成-测试"
            relevance = "混合内容-住宅段有效" if noise_count >= 2 else "有效住宅产品内容"
            review_reason = f"{pending}条产品单元需复核" if pending else ""

        interaction = sum(num(row.get(field)) for field in ["文章点赞数", "文章收藏数", "文章评论数", "文章分享数"])
        article = {
            "content_id": f"T1-{row['id']}" if is_topic_1 else f"T2-{row['id']}",
            "源表id": row.get("id"),
            "专题": row.get("项目"),
            "平台": row.get("平台"),
            "原始链接": row.get("文章链接"),
            "标题": row.get("文章标题"),
            "正文/摘要": clip(body, 1200),
            "发布日期": row.get("文章时间地点"),
            "发布账号": row.get("作者名字"),
            "点赞": num(row.get("文章点赞数")),
            "收藏": num(row.get("文章收藏数")),
            "评论": num(row.get("文章评论数")),
            "转发": num(row.get("文章分享数")),
            "抓取时间": row.get("文章获取时间"),
            "来源类型": source_type,
            "品牌归属初判": brand,
            "经营主体初判": entity,
            "住宅相关性": relevance,
            "城市": city,
            "项目初判": project,
            "传播视角标签": perspective_tags(" ".join([row.get("文章标题", ""), body[:2000]])),
            "互动量": interaction,
            "原文字符数": len(body),
            "有效句段数": segment_count,
            "噪声句段数": noise_count,
            "产品单元数": len(row_units),
            "处理状态": process_status,
            "复核原因": review_reason,
            "规则版本": RULE_VERSION,
        }
        article_rows.append(article)
        if is_topic_1 and process_status in ["待OCR", "需人工复核"]:
            review_rows.append({
                "对象类型": "文章",
                "对象ID": article["content_id"],
                "标题/维度": article["标题"],
                "项目": project,
                "复核原因": review_reason,
                "建议动作": "补充图片OCR后重新切片" if process_status == "待OCR" else "核对项目归属并抽查上下文",
                "原始链接": article["原始链接"],
                "自动置信度": None,
                "当前状态": process_status,
            })

    for unit in units:
        if unit["_review_status"] == "需人工复核":
            review_rows.append({
                "对象类型": "产品单元",
                "对象ID": unit["unit_id"],
                "标题/维度": f"{unit['一级维度']} / {unit['二级维度']}",
                "项目": unit["项目"],
                "复核原因": unit["_review_reason"],
                "建议动作": "对照原文确认项目、对象边界和创新基线",
                "原始链接": unit["_link"],
                "自动置信度": unit["_confidence"],
                "当前状态": unit["_review_status"],
            })

    dimension_stats = []
    grouped = defaultdict(list)
    for unit in units:
        grouped[(unit["品牌组"], unit["一级维度"], unit["二级维度"])].append(unit)
    for (brand, primary, secondary), items in sorted(grouped.items()):
        dimension_stats.append({
            "品牌组": brand,
            "一级维度": primary,
            "二级维度": secondary,
            "产品单元数": len(items),
            "涉及文章数": len({x["content_id"] for x in items}),
            "I0单元数": sum(x["创新等级"].startswith("I0") for x in items),
            "I1单元数": sum(x["创新等级"].startswith("I1") for x in items),
            "I2单元数": sum(x["创新等级"].startswith("I2") for x in items),
            "需复核单元数": sum(x["_review_status"] == "需人工复核" for x in items),
        })

    summary = {
        "source_rows": len(source_rows),
        "topic1_rows": sum(r.get("项目") == TOPIC_1 for r in source_rows),
        "excluded_topic2_rows": sum(r.get("项目") != TOPIC_1 for r in source_rows),
        "ocr_rows": sum(r["处理状态"] == "待OCR" for r in article_rows),
        "unit_rows": len(units),
        "auto_units": sum(u["_review_status"] == "自动通过（测试）" for u in units),
        "review_units": sum(u["_review_status"] == "需人工复核" for u in units),
        "i0_units": sum(u["创新等级"].startswith("I0") for u in units),
        "i1_units": sum(u["创新等级"].startswith("I1") for u in units),
        "i2_units": sum(u["创新等级"].startswith("I2") for u in units),
        "brands": dict(Counter(u["品牌组"] for u in units)),
        "rule_version": RULE_VERSION,
    }
    print(json.dumps({
        "summary": summary,
        "articles": article_rows,
        "units": units,
        "dimension_stats": dimension_stats,
        "reviews": review_rows,
        "label_dictionary": label_rows,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
