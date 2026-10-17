"""SettingsPage.tsx 文案 i18n 化: JSX 文本节点 -> t() 表达式。"""

from __future__ import annotations

from pathlib import Path

P = Path(r"E:\Qingxiaotuan Agent CLI\claude-desktop-app\src\components\SettingsPage.tsx")
text = P.read_text(encoding="utf-8")

R = [
    # 标题
    (">\n          Settings\n        </h2>", ">\n          {t('settings.title')}\n        </h2>"),
    # 个人资料
    (">个人资料<", ">{t('settings.profile')}<"),
    (">全名<", ">{t('settings.fullName')}<"),
    ('placeholder="输入你的全名"', "placeholder={t('settings.fullNamePlaceholder')}"),
    (">Claude 应该怎么称呼你？<", ">{t('settings.displayName')}<"),
    ('placeholder="例如你的名字或昵称"', "placeholder={t('settings.displayNamePlaceholder')}"),
    (">你的职业是什么？<", ">{t('settings.workFunction')}<"),
    (">选择你的职业<", ">{t('settings.workFunctionPlaceholder')}<"),
    (">Claude 在回复中应考虑哪些个人偏好？<", ">{t('settings.preferences')}<"),
    (">你的偏好将应用于所有对话。<", ">{t('settings.preferencesHint')}<"),
    ('placeholder="例如：回答尽量简洁，使用中文，代码注释用英文"', "placeholder={t('settings.preferencesPlaceholder')}"),
    # 默认模型
    (">默认模型<", ">{t('settings.defaultModel')}<"),
    (">新对话默认使用的模型<", ">{t('settings.defaultModelLabel')}<"),
    (">扩展思考<", ">{t('settings.extendedThinking')}<"),
    (">让模型在回答前进行深度思考<", ">{t('settings.extendedThinkingHint')}<"),
    # 发送消息 / 换行
    (">发送消息<", ">{t('settings.sendKey')}<"),
    (">换行<", ">{t('settings.newline')}<"),
    # 外观
    (">外观<", ">{t('settings.appearance')}<"),
    (">颜色模式<", ">{t('settings.colorMode')}<"),
    ("{ value: 'light', label: 'Light' }", "{ value: 'light', label: t('settings.light') }"),
    ("{ value: 'auto', label: 'Auto' }", "{ value: 'auto', label: t('settings.auto') }"),
    ("{ value: 'dark', label: 'Dark' }", "{ value: 'dark', label: t('settings.dark') }"),
]

miss = []
for old, new in R:
    if old in text:
        text = text.replace(old, new)
    else:
        miss.append(old[:40])

P.write_text(text, encoding="utf-8")
print("替换完成, 未命中:")
for m in miss:
    print(" -", m)
