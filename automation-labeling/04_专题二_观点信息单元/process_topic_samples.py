import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl

import process_topic1_samples as topic1


CSV_PATH = Path(r"C:\Users\YS-Insight\Desktop\陈晓锋\参考数据\ods_social_media_post_100_wx.csv")
TOPIC2_TEMPLATE_PATH = Path(
    r"C:\Users\YS-Insight\Documents\WXWork\1688854558869662\Cache\File\2026-09\专题二_北京臻澐网络及竞品口碑分析数据模板_V3.xlsx"
)
TOPIC1_CONFIRMATION_PATH = topic1.CONFIRMATION_PATH
TOPIC2_CONFIRMATION_PATH = Path(
    r"C:\Users\YS-Insight\Desktop\爬虫任务\爬虫需求文档\专题二项目口碑采集确认表\专题二_北京臻澐项目口碑采集确认表_v4_kimi补充-2.xlsx"
)
TOPIC_1 = "全国地产设计产品力监测"
TOPIC_2 = "北京臻澐项目口碑"
RULE_VERSION = "topic1-topic2-rule-v1.1-confirmation-map-test"


DEFAULT_PROJECTS = [
    {
        "project_id": "P01",
        "name": "北京臻澐",
        "role": "本品",
        "aliases": ["华润臻澐", "北京臻澐", "臻澐", "北京臻云", "华润臻云", "臻云雅苑"],
    },
    {
        "project_id": "C01",
        "name": "建发海晏",
        "role": "核心竞品",
        "aliases": ["建发海晏", "建发·海晏", "建发海宴", "北京海晏", "海晏雅苑"],
    },
    {
        "project_id": "C03",
        "name": "和樾玉鳴",
        "role": "核心竞品",
        "aliases": ["和樾玉鳴", "和樾玉鸣", "北京玉鸣", "玉鸣苑"],
    },
    {
        "project_id": "C04",
        "name": "和樾望雲",
        "role": "核心竞品",
        "aliases": ["和樾望雲", "和樾望云", "北京望云", "和樾苑"],
    },
    {
        "project_id": "C02",
        "name": "中海·安澜北京",
        "role": "次核心竞品",
        "aliases": ["中海·安澜北京", "中海安澜北京", "安澜北京", "安和雅苑", "圆明玖序"],
    },
    {
        "project_id": "C05",
        "name": "保利熙瑞",
        "role": "次核心竞品",
        "aliases": ["保利熙瑞", "保利·熙瑞", "北京熙瑞", "瑞璟佳苑"],
    },
    {
        "project_id": "C06",
        "name": "香山樾",
        "role": "次核心竞品",
        "aliases": ["香山樾", "越秀香山樾", "北京香山樾", "香宜嘉园"],
    },
    {
        "project_id": "C07",
        "name": "紫京宸园",
        "role": "次核心竞品",
        "aliases": ["紫京宸园", "北京紫京宸园", "东晏和园", "中建宸园"],
    },
]
PROJECTS = DEFAULT_PROJECTS

POSITIVE = re.compile(
    r"优势|优越|完善|成熟|突出|更好|不错|认可|友好|稳定|纯粹|稀缺|舒适|实用|通透|便捷|高标准|高品质|性价比|值得|优选|首选|领先|热销|销冠|强|丰富|充足|安全|放心"
)
NEGATIVE = re.compile(
    r"劣势|硬伤|不足|问题|风险|偏弱|过高|太高|贵|压抑|噪音|临路|缩水|去化慢|难|有限|小众|踩坑|延期|投诉|整改|不建议|不适合|极差|焦虑|虚高|缺点|门槛高|成本高|不纯粹"
)
QUESTION = re.compile(r"[?？]|是否|能买吗|值得买吗|怎么样|怎么选|为什么|会不会|有没有")
FUTURE = re.compile(r"预计|计划|将会|未来|可能|大概率|有望|或将")
COMPARE = re.compile(r"相比|对比|更[高低大好强弱]|不如|优于|低于|高于|vs|VS|之间|二者|两个项目|同预算")
FACT = re.compile(r"\d+(?:\.\d+)?\s*(?:万|亿|元|㎡|平米|平方米|套|户|层|%|米)|开发商|容积率|交房|网签|均价|户型|建筑面积|占地面积")
PROMO = re.compile(r"封神|天花板|震撼|顶奢|王炸|巅峰|一骑绝尘|毫无悬念|令人心动|热情服务|预约专线|售楼处电话")
VIEW_NOISE = re.compile(
    r"(?:售楼处|销售中心).{0,18}(?:电话|热线)|400[-—\s]?\d{3}[-—\s]?\d{4}|"
    r"扫码.{0,12}(?:微信|关注|咨询)|添加.{0,8}(?:微信|好友)|联系电话|预约专线|"
    r"关注公众号|点击蓝字|点个在看|欢迎转发|商务合作|长按添加好友|客服微信"
)
UNKNOWN_PROJECT_MARKERS = re.compile(
    r"中建壹品|海宸元境|北京隅海岄|嘉华天珺|颐海澐颂|颐海澞颂|中海京华玖序|中海萬吉玖序|北京宸园|北京润园|璞樾"
)


NON_PRODUCT_RULES = [
    (
        "购买体验",
        "负向体验",
        "价格、销售与决策顾虑",
        re.compile(r"价格|单价|总价|预算|门槛|购房|买房|成交|网签|去化|可售|房源|折扣|优惠|销售|流动性|保值|资产配置|上车|选择|建议"),
    ),
    (
        "交付体验",
        "负向体验",
        "延期、验房与整改问题",
        re.compile(r"交付|收房|验房|延期|整改|承诺兑现|施工进度|工程进度"),
    ),
    (
        "居住体验",
        "物业及维修",
        "响应",
        re.compile(r"物业|报修|维修|保洁|安保|停车管理|物业费"),
    ),
    (
        "居住体验",
        "会所运营与使用管理",
        "设施开放与使用效率",
        re.compile(r"会所.{0,14}(?:运营|开放|预约|维护|闲置|使用率|私密|会员)|后期维护成本"),
    ),
    (
        "周边环境",
        "交通与生活配套",
        "通勤",
        re.compile(r"地铁|交通|通勤|主干道|高速|出行|自驾|拥堵"),
    ),
    (
        "周边环境",
        "交通与生活配套",
        "商业",
        re.compile(r"商业|商场|万象汇|购物|消费"),
    ),
    (
        "周边环境",
        "交通与生活配套",
        "学校",
        re.compile(r"学校|学区|教育|小学|中学|学府"),
    ),
    (
        "周边环境",
        "交通与生活配套",
        "片区环境",
        re.compile(r"板块|区位|地段|生态|城市界面|周边环境|西山|清河|自然资源"),
    ),
]


def norm(value):
    return topic1.norm(value)


def load_topic2_projects_from_confirmation():
    wb = openpyxl.load_workbook(TOPIC2_CONFIRMATION_PATH, read_only=True, data_only=True)
    ws = wb["项目范围"]
    projects = []
    for row in ws.iter_rows(min_row=6, values_only=True):
        project_id, level, name, _, aliases = row[:5]
        if not project_id or not name:
            continue
        if str(level).startswith("本品"):
            role = "本品"
        elif str(level).startswith("次核心"):
            role = "次核心竞品"
        else:
            role = "核心竞品"
        alias_values = [str(name)]
        for raw_alias in re.split(r"[；;]", str(aliases or "")):
            value = re.sub(r"【[^】]*】", "", raw_alias)
            value = re.sub(r"（(?:补漏|备案名|别名|地块别名)[^）]*）", "", value)
            value = norm(value)
            if value and value not in alias_values:
                alias_values.append(value)
        # Keep the confirmation workbook's canonical names and aliases. Very
        # short unqualified simplified forms are not added automatically.
        alias_values = [x for x in alias_values if x not in {"臻云", "海晏", "玉鸣", "望云"}]
        projects.append(
            {
                "project_id": str(project_id),
                "name": str(name),
                "role": role,
                "aliases": alias_values,
                "confirmation_level": str(level or ""),
            }
        )
    wb.close()
    return projects or DEFAULT_PROJECTS


def clip(value, limit):
    return topic1.clip(value, limit)


def num(value):
    return topic1.num(value)


def choose_slice_source(row):
    body = norm(row.get("文章内容"))
    if body:
        return "文章内容", body
    ocr = norm(row.get("文章图片信息"))
    if ocr:
        return "图片OCR", ocr
    return "无可用文本", ""


def split_view_segments(text):
    raw_parts = re.split(r"(?<=[。！？!?；;])|[\n\r]+|(?=[一二三四五六七八九十]+[、.])", text or "")
    parts = []
    seen = set()
    for idx, raw in enumerate(raw_parts, 1):
        value = norm(raw).strip(" ，,。；;：:-—|/（）()[]【】")
        value = norm(VIEW_NOISE.sub(" ", value))
        if len(value) < 12:
            continue
        key = re.sub(r"[\W_]+", "", value.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        # Long source paragraphs are split again at commas so one unit does not mix several claims.
        if len(value) > 260:
            tokens = [norm(x) for x in re.split(r"(?<=[，,：:])", value) if norm(x)]
            chunks = []
            current = ""
            for token in tokens:
                if current and len(current) + len(token) > 240:
                    chunks.append(current)
                    current = token
                else:
                    current += token
            if current:
                chunks.append(current)
            if len(chunks) > 1:
                for chunk in chunks:
                    if len(chunk) >= 12:
                        parts.append((idx, clip(chunk, 260)))
                continue
        parts.append((idx, clip(value, 360)))
    return parts


def find_projects(text):
    hits = []
    for item in PROJECTS:
        matched = next((alias for alias in item["aliases"] if alias in text), None)
        if matched:
            hit = dict(item)
            hit["_matched_alias"] = matched
            hits.append(hit)
    if len(hits) <= 1:
        return hits

    # Numbered project sections often list several comparison projects first and then
    # introduce the actual subject after the final "1." / "2." heading.
    headings = list(re.finditer(r"(?<!\d)\d+[.、](?!\d)", text))
    if headings:
        subject_text = text[headings[-1].end():]
        subject_text = re.split(r"优势|劣势|总结|[：:]", subject_text, maxsplit=1)[0]
        subject_hits = [item for item in hits if any(alias in subject_text for alias in item["aliases"])]
        if subject_hits:
            return subject_hits

    # A leading "项目名：" or "项目名（...）" establishes the subject; later mentions
    # are usually the comparison baseline rather than another viewpoint owner.
    lead_text = re.split(r"优势|劣势|总结|[：:]", text, maxsplit=1)[0][:60]
    lead_hits = [item for item in hits if any(alias in lead_text for alias in item["aliases"])]
    if lead_hits and not re.search(r"\bvs\b|VS|对比", lead_text):
        return lead_hits
    return hits


def default_projects(row):
    text = " ".join([norm(row.get("关键词")), norm(row.get("文章标题"))])
    hits = find_projects(text)
    if len(hits) == 1:
        return hits
    return []


def infer_publisher_role(row):
    author = norm(row.get("作者名字"))
    text = " ".join([author, norm(row.get("文章标题"))])
    if re.search(r"华润|建发|中海|越秀|保利|招商|项目官方|置业", author):
        return "品牌官方"
    if re.search(r"研究院|财经|房讯|楼市|地产|房产|百科|聊房|新房|豪宅|看房|实探|资讯", text):
        return "自媒体及行业账号"
    return "普通账号" if author else "不明"


def sentiment(text):
    positive = len(POSITIVE.findall(text))
    negative = len(NEGATIVE.findall(text))
    if positive and positive > negative:
        return "正向"
    if negative and negative > positive:
        return "负向"
    if positive and negative:
        return "中性"
    return "无态度"


def expression_type(text, emotion, project_count):
    if QUESTION.search(text):
        return "需求提问"
    if FUTURE.search(text):
        return "未来推测"
    if project_count > 1 or COMPARE.search(text):
        return "对比判断"
    if emotion == "正向":
        return "正向评价" if not PROMO.search(text) else "卖点传播"
    if emotion == "负向":
        return "负向评价"
    if POSITIVE.search(text) or NEGATIVE.search(text):
        return "中性评价"
    return "事实介绍" if FACT.search(text) else "中性评价"


def product_dimensions(text):
    found = []
    for item in topic1.RULES:
        if item["exclude"] and item["exclude"].search(text):
            continue
        if item["pattern"].search(text):
            # Topic two deliberately excludes the Topic-one-only product-system taxonomy.
            if item["primary"] == "产品体系与创新":
                continue
            secondary = item["secondary"]
            if secondary == "灵活独立功能空间":
                secondary = "套房、弹性与独立功能空间"
            key = (item["primary"], secondary, item["tertiary"])
            if key not in found:
                found.append(key)
    return found[:3]


def non_product_dimensions(text, emotion):
    found = []
    for primary, secondary, tertiary, pattern in NON_PRODUCT_RULES:
        if not pattern.search(text):
            continue
        if primary == "购买体验":
            if emotion == "正向":
                secondary = "正向体验"
                tertiary = "购买认可与决策理由"
            else:
                secondary = "负向体验"
                tertiary = "价格、销售与决策顾虑"
        elif primary == "交付体验" and emotion == "正向":
            secondary = "正向体验"
            tertiary = "交付兑现与收房认可"
        key = (primary, secondary, tertiary)
        if key not in found:
            found.append(key)
    return found[:3]


def build_topic2_units(row):
    _, text = choose_slice_source(row)
    segments = split_view_segments(text)
    defaults = default_projects(row)
    single_project_article = len(defaults) == 1
    current = defaults
    carry = 0
    candidates = []
    seen = set()

    for position, segment in segments:
        if re.sub(r"[\W_]+", "", segment.lower()) == re.sub(r"[\W_]+", "", norm(row.get("文章标题")).lower()):
            continue
        explicit_projects = find_projects(segment)
        if explicit_projects:
            current = explicit_projects
            carry = 0
        elif UNKNOWN_PROJECT_MARKERS.search(segment):
            current = []
            carry = 0
            continue
        elif current and (single_project_article or carry < 8):
            explicit_projects = current
            carry += 1
        else:
            continue

        emotion = sentiment(segment)
        dims = non_product_dimensions(segment, emotion) + product_dimensions(segment)
        if not dims:
            continue
        for project in explicit_projects[:3]:
            for primary, secondary, tertiary in dims[:4]:
                key = (project["project_id"], primary, secondary, re.sub(r"[\W_]+", "", segment.lower()))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((position, segment, project, primary, secondary, tertiary, emotion, len(explicit_projects)))

    # Keep the most useful candidate units while retaining document order.
    candidates = candidates[:60]
    publisher_role = infer_publisher_role(row)
    interaction = sum(num(row.get(field)) for field in ["文章点赞数", "文章收藏数", "文章评论数", "文章分享数"])
    result = []
    for seq, (position, segment, project, primary, secondary, tertiary, emotion, project_count) in enumerate(candidates, 1):
        expression = expression_type(segment, emotion, project_count)
        explicit_evaluation = int(expression in {"正向评价", "中性评价", "负向评价", "对比判断"})
        positive_negative = int(emotion in {"正向", "负向"})
        question = int(expression == "需求提问")
        confidence = 0.82
        review_reasons = []
        if project_count > 1 or expression == "对比判断":
            confidence -= 0.10
            review_reasons.append("比较语境需核对项目归属")
        if emotion == "中性":
            confidence -= 0.05
        if primary == "购买体验" and emotion == "无态度":
            confidence -= 0.10
            review_reasons.append("中性价格/销售事实需核对体验标签")
        if len(segment) < 20:
            confidence -= 0.08
            review_reasons.append("摘录较短")
        review_status = "需人工复核" if confidence < 0.75 or review_reasons else "自动通过（测试）"
        summary = re.sub(r"^(优势|劣势|总结|逻辑|注意)[：:]?", "", segment).strip()
        result.append(
            {
                "unit_id": f"T2-{row['id']}-V{seq:03d}",
                "record_id": f"T2-{row['id']}",
                "project_id": project["project_id"],
                "项目名称": project["name"],
                "项目角色": project["role"],
                "项目映射依据": f"专题二确认表项目范围；命中别名：{project.get('_matched_alias', project['name'])}",
                "发布日期": row.get("文章时间地点"),
                "平台": row.get("平台"),
                "发布者角色": publisher_role,
                "原始摘录": segment,
                "观点摘要": clip(summary, 140),
                "一级维度": primary,
                "二级维度": secondary,
                "三级/强调方向": tertiary,
                "表达类型": expression,
                "情绪态度": emotion,
                "阅读/播放": 0,
                "点赞": num(row.get("文章点赞数")),
                "收藏": num(row.get("文章收藏数")),
                "评论": num(row.get("文章评论数")),
                "转发": num(row.get("文章分享数")),
                "互动量": interaction,
                "明确评价标记": explicit_evaluation,
                "正负评价标记": positive_negative,
                "需求提问标记": question,
                "备注": f"正文句段{position}；{review_status}" + (f"；{'；'.join(review_reasons)}" if review_reasons else ""),
                "_confidence": round(max(confidence, 0.40), 2),
                "_review_status": review_status,
            }
        )
    return result, len(segments)


def load_topic2_dictionary():
    wb = openpyxl.load_workbook(TOPIC2_TEMPLATE_PATH, read_only=True, data_only=True)
    rows = []
    for row in wb["03_标签字典"].iter_rows(min_row=2, values_only=True):
        if row[0] and row[1] and row[2]:
            rows.append({"一级维度": row[0], "二级维度": row[1], "三级/强调方向": row[2]})
    wb.close()
    return rows


def main():
    global PROJECTS
    sys.stdout.reconfigure(encoding="utf-8")
    PROJECTS = load_topic2_projects_from_confirmation()
    topic1_labels, brand_dict = topic1.load_template_data()
    topic2_labels = load_topic2_dictionary()
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    product_units = []
    viewpoint_units = []
    article_status = []

    for row in source_rows:
        topic = row.get("项目")
        source_type, slice_text = choose_slice_source(row)
        product_count = 0
        viewpoint_count = 0
        segment_count = 0
        review_count = 0
        identified_projects = []

        if topic == TOPIC_1 and slice_text:
            work_row = dict(row)
            work_row["文章内容"] = slice_text
            brand = topic1.infer_brand(work_row)
            entity = topic1.infer_entity(work_row, brand)
            project = topic1.infer_project(work_row)
            city = topic1.infer_city(work_row)
            identified_projects = [project]
            row_units, segment_count, _ = topic1.build_units(work_row, brand, entity, project, city, brand_dict)
            for unit in row_units:
                unit["_rule_version"] = RULE_VERSION
                unit["证据定位"] = ("正文" if source_type == "文章内容" else "图片OCR") + unit["证据定位"].replace("正文", "")
            product_units.extend(row_units)
            product_count = len(row_units)
            review_count = sum(x["_review_status"] == "需人工复核" for x in row_units)
        elif topic == TOPIC_2 and slice_text:
            row_units, segment_count = build_topic2_units(row)
            identified_projects = list(dict.fromkeys(x.get("项目名称", "") for x in row_units if x.get("项目名称")))
            if not identified_projects:
                identified_projects = [x["name"] for x in default_projects(row)]
            viewpoint_units.extend(row_units)
            viewpoint_count = len(row_units)
            review_count = sum(x["_review_status"] == "需人工复核" for x in row_units)

        total_units = product_count + viewpoint_count
        if not slice_text:
            status = "无有效单元"
            reason = "文章内容与图片OCR均为空；视频内容按本轮规则忽略"
        elif total_units == 0:
            status = "需人工复核"
            reason = "有切片来源文本，但规则未识别出模板内可交付单元"
        elif review_count:
            status = "需人工复核"
            reason = f"{review_count}条单元需人工复核"
        else:
            status = "已完成"
            reason = ""

        article_status.append(
            {
                "源表id": row.get("id"),
                "专题": topic,
                "关键词": row.get("关键词"),
                "文章标题": row.get("文章标题"),
                "切片来源": source_type,
                "来源字符数": len(slice_text),
                "候选句段数": segment_count,
                "产品单元数": product_count,
                "观点单元数": viewpoint_count,
                "切片数量": total_units,
                "处理状态": status,
                "需复核单元数": review_count,
                "处理说明": reason,
                "视频内容是否使用": "否",
                "规则版本": RULE_VERSION,
                "识别项目": "；".join(identified_projects),
                "项目映射状态": (
                    "无文本"
                    if not slice_text
                    else "待复核"
                    if any(("待判断" in x or "多项目" in x) for x in identified_projects)
                    else "已按确认表/原文映射"
                    if identified_projects
                    else "未识别"
                ),
            }
        )

    valid_topic2 = {(x["一级维度"], x["二级维度"], x["三级/强调方向"]) for x in topic2_labels}
    invalid_topic2 = [
        x["unit_id"]
        for x in viewpoint_units
        if (x["一级维度"], x["二级维度"], x["三级/强调方向"]) not in valid_topic2
    ]
    summary = {
        "source_rows": len(source_rows),
        "topic1_rows": sum(x.get("项目") == TOPIC_1 for x in source_rows),
        "topic2_rows": sum(x.get("项目") == TOPIC_2 for x in source_rows),
        "body_source_rows": sum(x["切片来源"] == "文章内容" for x in article_status),
        "ocr_source_rows": sum(x["切片来源"] == "图片OCR" for x in article_status),
        "no_text_rows": sum(x["切片来源"] == "无可用文本" for x in article_status),
        "product_units": len(product_units),
        "viewpoint_units": len(viewpoint_units),
        "review_product_units": sum(x["_review_status"] == "需人工复核" for x in product_units),
        "review_viewpoint_units": sum(x["_review_status"] == "需人工复核" for x in viewpoint_units),
        "status_counts": dict(Counter(x["处理状态"] for x in article_status)),
        "invalid_topic2_labels": len(invalid_topic2),
        "topic2_project_dictionary_count": len(PROJECTS),
        "confirmation_mapped_product_units": sum("确认表" in x.get("项目映射依据", "") for x in product_units),
        "confirmation_mapped_viewpoint_units": sum("确认表" in x.get("项目映射依据", "") for x in viewpoint_units),
        "rule_version": RULE_VERSION,
    }
    payload = {
        "summary": summary,
        "product_units": product_units,
        "viewpoint_units": viewpoint_units,
        "article_status": article_status,
        "topic1_label_dictionary": topic1_labels,
        "topic2_label_dictionary": topic2_labels,
        "invalid_topic2_unit_ids": invalid_topic2,
    }
    if len(sys.argv) >= 3 and sys.argv[1] == "--output":
        Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
