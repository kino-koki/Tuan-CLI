# -*- coding: utf-8 -*-
"""tuan-reach —— 给 Agent 的"上网能力层" (Agent-Reach 理念, 完全自研)。

统一接入多平台读取: channel → 有序 backend 回退链 → doctor 自检。
公开 API:
    fetch(target, channel=None)   统一读取入口
    route(target)                 频道路由
    list_channels()               频道清单
    doctor() / doctor.render()    健康自检
"""
from .base import Backend, Channel, ReachResult
from .channels import build_channels
from .doctor import doctor, probe_channel, render
from .registry import fetch, list_channels, route

__all__ = [
    "fetch", "route", "list_channels", "doctor", "probe_channel", "render",
    "build_channels", "Backend", "Channel", "ReachResult",
]
