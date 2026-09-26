# -*- coding: utf-8 -*-
import re
src = open(r"e:\Qingxiaotuan Agent CLI\qingxiaotuan\models\provider_catalog.py", encoding="utf-8").read()
providers = re.findall(r'([A-Za-z0-9_-]+)\s*:\s*\{', src)
print("catalog dict-like entries:", len(providers))
print(providers[:25])
