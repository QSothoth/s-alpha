"""Small/mid-cap universe (fixed before looking at any prices): hot small/mid caps in AI, innovative drugs, resources.

Input: OpenD option-underlying rank by option volume (latest day), market cap $0.5B-$30B, stocks only, with OpenD plates.
    python3 studies/us_preopen_bias/code/universe_smallmid.py rank.json > studies/us_preopen_bias/notes/universe_smallmid.json
"""
import json
import sys

THEMES = [   # first match wins, in this order
    ('resources', {'INDUSTRY': {'黄金', '其他工业金属与采矿', '铀', '油气勘探与开发', '铜', '白银', '煤炭', '铝', '钢铁', '其他贵金属与采矿'},
                   'CONCEPT': {'稀土概念', '白银概念', '锂矿概念股', '黄金概念', '铜概念'}}),
    ('biotech', {'INDUSTRY': {'生物技术', '专业与通用药品制造商'},
                 'CONCEPT': {'减肥药概念', '基因编辑', '创新药', 'mRNA概念'}}),
    ('ai', {'INDUSTRY': {'半导体', '半导体设备与材料', '计算机硬件'},
            'CONCEPT': {'AI应用软件股', '人工智能', '量子计算概念', '光通信', '云计算服务商', 'DeepSeek概念股', 'AI医疗概念股',
                        '机器人概念股', 'AI眼镜概念股', 'AI算力概念', '数据中心概念'}}),
]
PER_THEME = 12
MIN_PRICE = 5.0


def theme_of(plates):
    for name, rule in THEMES:
        for p, t in plates:
            kind = 'INDUSTRY' if 'INDUSTRY' in t else 'CONCEPT' if 'CONCEPT' in t else None
            if kind and p in rule[kind]:
                return name, p
    return None, None


def main():
    d = json.load(open(sys.argv[1], encoding='utf-8'))
    picked = {name: [] for name, _ in THEMES}
    for x in sorted(d['rows'], key=lambda r: -float(r['total_volume'])):
        if float(x['price']) < MIN_PRICE:
            continue
        name, via = theme_of(d['plates'].get(x['code'], []))
        if name and len(picked[name]) < PER_THEME:
            picked[name].append({'code': x['code'], 'name': x['name'], 'option_volume': int(float(x['total_volume'])),
                                 'market_cap_b': round(float(x['market_cap']) / 1e9, 2), 'price': float(x['price']), 'via': via})
    out = {'rank_date': d['rank_date'], 'rule': 'OpenD option-volume rank, market cap 0.5-30B USD, stock, price >= 5, '
                                                 'theme by OpenD plate (first match: resources, biotech, ai), top 12 per theme',
           'themes': picked}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
