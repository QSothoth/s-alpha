"""Render the checked-in Chinese navigation index from validated metadata."""
from pathlib import Path
from .registry import DEFAULT_PATH, load_registry


def render() -> str:
    rows = load_registry()
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = [
        '# 35位交易员风格与实现状态索引', '',
        '截至 2026-10-18。由 registry.json 生成；33位原对象与2位追加方法参考分组。风格是证据摘要，不是推荐或收益评级。', '',
        '实现列只描述当前 main；历史研究分支代码链接见每人的详细记录。未知保持未知，未实现不等于方法无效，已有局部代码也不等于本人完整系统已复现。', '',
        '[使用说明与查询方法](README.md) · [来源覆盖与限制](dossiers/AUDIT_CN.md) · [机器可读注册表](registry.json)', '',
    ]
    for cohort, title in [('original_33', '原研究33人'), ('additional_reference', '追加2位方法参考')]:
        lines += [f'## {title}', '', '| 人物 / ID | 市场 | 风格 | 周期 | 多空方法 | 证据 | main 实现状态 |', '|---|---|---|---|---|---|---|']
        for t in rows:
            if t.cohort != cohort:
                continue
            dossier = Path(t.dossier_path).relative_to(DEFAULT_PATH.parent.relative_to(DEFAULT_PATH.parents[2]))
            columns = [f'[{t.name}]({dossier.as_posix()}) / `{t.id}`', '；'.join(t.markets), '；'.join(t.styles), '；'.join(t.timeframes), '；'.join(t.long_short_methods), t.evidence_grade, t.implementation.status]
            lines.append('| ' + ' | '.join(cell(c) for c in columns) + ' |')
        lines.append('')
    lines += ['## 逐人来源、代码与下一步', '']
    for t in rows:
        lines += [f'### {t.name}（{t.id}）', '', f'- 别名：{"、".join(t.aliases) or "无另列别名"}', f'- 实现边界：{t.implementation.note}']
        for label, paths in [('来源账本', t.source_ledger_paths), ('main代码', t.implementation.code_paths), ('main报告', t.implementation.report_paths)]:
            links = [f'[{p}](../../{p})' for p in paths]
            lines.append(f'- {label}：' + ('；'.join(links) or '无可归属的当前文件'))
        lines.append('- 原始来源入口：' + '；'.join(f'[来源{i}]({u})' for i, u in enumerate(t.source_urls, 1)))
        lines += ['- 缺失规则：' + '；'.join(t.missing_rules), '- 下一步：' + '；'.join(t.next_steps), '']
    return '\n'.join(lines).rstrip() + '\n'


if __name__ == '__main__':
    DEFAULT_PATH.with_name('INDEX_CN.md').write_text(render(), encoding='utf-8')
