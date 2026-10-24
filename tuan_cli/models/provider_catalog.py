"""LLM API provider catalog — 58 out-of-box provider presets.

Each preset: base_url, model, api_key_env, desc, tier (1=free, 2=mid, 3=high),
free_tier, region (cn/global), category, recommended_models, docs_url, key_hint.

Categories (按 category 字段归组, 与登记分区 A-G 解耦):
A. 中国主流 (13) B. 国际主流 (19) C. 聚合网关 (7) D. 云平台 (8)
E. 免费层 (6: nvidia-nim / agnes-ai / groq / cloudflare / opencode-zen / sensenova)
F. 本地部署 (5) G. 补充 (并入 B/C/D)

"免费层" category = 完全免费 (注册即用、无需绑卡、可持续免费额度), 是
`tuan models list-providers` / `tuan setup` "只看免费"筛选的核心名单。
部分供应商虽登记在 A/B/C 区 (如 zhipu/siliconflow 的免费模型), 只要满足
free_tier=True 同样进入免费筛选 —— 完整名单见 FREE_TIER_NAMES。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .model_lists import MODEL_LISTS


# 档位枚举: free (不花钱、不绑卡即可跑通) / cheap (低价或有赠额, 多数需绑卡或实名) / standard (常规付费)
TIER_ORDER: Dict[str, int] = {"free": 0, "cheap": 1, "standard": 2}


@dataclass
class ProviderPreset:
    """结构化的供应商预设。"""
    name: str
    base_url: str
    model: str
    api_key_env: str
    desc: str
    tier: str = "standard"           # free | cheap | standard (见 TIER_ORDER)
    free_tier: bool = False          # True = 注册即用、无需绑卡、有可持续免费额度
    region: str = "global"           # cn / global
    category: str = ""               # 分类标签
    recommended_models: List[str] = field(default_factory=list)  # 可选模型列表
    docs_url: str = ""               # 官方文档链接
    key_hint: str = ""                 # API Key 格式提示 (交互输入时展示)

    @property
    def tier_rank(self) -> int:
        """档位的数值序 (free=0 < cheap=1 < standard=2), 供排序/比较用。"""
        return TIER_ORDER.get(self.tier, 2)

    def to_dict(self) -> Dict[str, str]:
        """转换为旧格式的 dict (兼容 PROVIDER_PRESETS 接口)。"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "desc": self.desc,
        }


# =====================================================================
# A. 中国主流供应商 (14 家)
# =====================================================================

_A_CHINA_MAINSTREAM: List[ProviderPreset] = [
    ProviderPreset(
        name="deepseek",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        desc="DeepSeek 官方 (deepseek-chat / deepseek-reasoner, 高性价比)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"],
        docs_url="https://platform.deepseek.com/api-docs",
    ),
    # OpenCode Zen (AI SDK 网关): 免费档 deepseek-v4-free 零费用, 注册即用无需绑卡,
    # 实测免费层仅此模型可用, 故作为默认模型 (清单第一项)。归类于 E 区免费层。
    ProviderPreset(
        name="opencode-zen",
        base_url="https://opencode.ai/zen/v1",
        model="deepseek-v4-free",
        api_key_env="OPENCODE_ZEN_API_KEY",
        desc="OpenCode Zen 免费档 (deepseek-v4-free 零费用; 注册即用, 无需绑卡; 其余模型付费)",
        tier="free", free_tier=True, region="global", category="免费层",
        recommended_models=["deepseek-v4-free"],
        docs_url="https://opencode.ai/zen",
        key_hint="OpenCode Zen API Key 形如 zen_xxxx (登录 opencode.ai/zen 控制台免费创建)",
    ),
    ProviderPreset(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
        desc="阿里通义千问 (qwen-plus / qwen-max / qwen-turbo, 开源生态强)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long", "qwen-vl-plus"],
        docs_url="https://help.aliyun.com/zh/model-studio/",
    ),
    ProviderPreset(
        name="moonshot",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-8k",
        api_key_env="MOONSHOT_API_KEY",
        desc="Moonshot Kimi (moonshot-v1-8k/32k/128k, 超长上下文)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        docs_url="https://platform.moonshot.cn/docs",
    ),
    ProviderPreset(
        name="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key_env="ZHIPU_API_KEY",
        desc="智谱 GLM (glm-4-flash 免费, glm-4-plus 高性能)",
        tier="free", free_tier=True, region="cn", category="中国主流",
        recommended_models=["glm-4-flash", "glm-4-plus", "glm-4-long", "glm-4v-plus"],
        docs_url="https://open.bigmodel.cn/dev/howuse/introduction",
    ),
    # 商汤日日新 SenseNova (Token Plan: sensenova.cn 官网注册;
    # OpenAI 兼容端点 token.sensenova.cn/v1, 默认模型 sensenova-6.8-flash-lite。
    # 企业大装置端点 api.sensenova.cn/compatible-mode/v2 亦可, 模型名不同)
    # 2026-10 核实: Token Plan 公测期"完全免费开放" — Free 档 ¥0/月,
    # 60000 积分/5h 限流 (sensenova-6.8-flash-lite / sensenova-u1-fast),
    # 无需绑卡, 注册即可获取 API Key。
    ProviderPreset(
        name="sensenova",
        base_url="https://token.sensenova.cn/v1",
        model="sensenova-6.8-flash-lite",
        api_key_env="SENSENOVA_API_KEY",
        desc="商汤日日新 SenseNova Token Plan 公测期完全免费 (6.8-flash-lite 多模态, 60k 积分/5h, 无需绑卡)",
        tier="free", free_tier=True, region="cn", category="免费层",
        recommended_models=["sensenova-6.8-flash-lite", "sensenova-6.7-flash-lite", "sensenova-u1-fast"],
        docs_url="https://www.sensenova.cn/token-plan",
        key_hint="日日新 Token Plan API Key: platform.sensenova.cn/console/keys 免费申请 (形如 sk-xxx)",
    ),
    ProviderPreset(
        name="doubao",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-1.5-pro-256k",
        api_key_env="ARK_API_KEY",
        desc="字节豆包 (doubao-seed-evolving 旗舰, 超长上下文, 价格极低)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["doubao-1.5-pro-256k", "doubao-1.5-lite-32k", "doubao-pro-256k"],
        docs_url="https://www.volcengine.com/docs/82379",
    ),
    ProviderPreset(
        name="stepfun",
        base_url="https://api.stepfun.com/v1",
        model="step-5-preview",
        api_key_env="STEPFUN_API_KEY",
        desc="阶跃星辰 StepFun (step-5-preview 1M 旗舰, step-3.7-flash 多模态推理)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["step-5-preview", "step-3.7-flash", "step-3.5-flash"],
        docs_url="https://platform.stepfun.com/docs/zh/guides/models/list",
    ),
    ProviderPreset(
        name="minimax",
        base_url="https://api.minimax.chat/v1",
        model="MiniMax-M3",
        api_key_env="MINIMAX_API_KEY",
        desc="MiniMax (MiniMax-M3 1M 上下文多模态, M2.7/M2.5 高性价比)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1"],
        docs_url="https://platform.minimax.io/docs/api-reference/api-overview",
    ),
    ProviderPreset(
        name="baidu",
        base_url="https://qianfan.baidubce.com/v2",
        model="ernie-5.1",
        api_key_env="BAIDU_API_KEY",
        desc="百度文心一言 ERNIE (ernie-5.1/5.0 旗舰, 4.5-Turbo 高性价比)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["ernie-5.1", "ernie-5.0", "ernie-4.5-turbo-128k", "ernie-4.5-21b-a3b"],
        docs_url="https://cloud.baidu.com/doc/WENXINWORKSHOP/s/hlrk4akp7",
    ),
    ProviderPreset(
        name="baichuan",
        base_url="https://api.baichuan-ai.com/v1",
        model="Baichuan-M3",
        api_key_env="BAICHUAN_API_KEY",
        desc="百川智能 (Baichuan-M3 强推理, Baichuan4-Turbo 高性价比)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["Baichuan-M3", "Baichuan-M2", "Baichuan4-Turbo", "Baichuan4-Air"],
        docs_url="https://platform.baichuan-ai.com/quickstart",
    ),
    ProviderPreset(
        name="yi",
        base_url="https://api.lingyiwanwu.com/v1",
        model="yi-lightning",
        api_key_env="YI_API_KEY",
        desc="零一万物 Yi (yi-lightning 极速高性价比, yi-large 旗舰)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["yi-lightning", "yi-large", "yi-large-turbo", "yi-vision"],
        docs_url="https://platform.lingyiwanwu.com/docs/api-reference",
    ),
    ProviderPreset(
        name="spark",
        base_url="https://spark-api-open.xf-yun.com/v1",
        model="generalv4",
        api_key_env="SPARK_API_KEY",
        desc="讯飞星火 Spark (Spark 4.0 Ultra 通用旗舰, X1 深度推理)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["generalv4", "x1", "generalv3.5"],
        docs_url="https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html",
    ),
    ProviderPreset(
        name="sensenova-neo",
        base_url="https://api.sensenova.cn/v1",
        model="nova-p3",
        api_key_env="SENSENOVA_API_KEY",
        desc="商汤日日新 SenseNova 企业大装置端点 (api.sensenova.cn, nova-p3/micro/pro 系列, 付费)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["nova-p3", "nova-micro", "nova-pro"],
        docs_url="https://platform.sensenova.cn/dev/api/overview",
    ),
    ProviderPreset(
        name="hunyuan",
        base_url="https://tokenhub.tencentmaas.com/v1",
        model="hy4-preview",
        api_key_env="HUNYUAN_API_KEY",
        desc="腾讯混元 Hunyuan (hy4-preview 770B/1M 上下文旗舰; 首次开通送 100 万 token "
             "免费资源包, 1 年有效, 国内直连)",
        tier="cheap", free_tier=False, region="cn", category="中国主流",
        recommended_models=["hy4-preview", "hy3"],
        docs_url="https://cloud.tencent.com/document/product/1729",
        key_hint="腾讯云 TokenHub API Key (tokenhub.tencentmaas.com 控制台创建, 形如 tk-xxxx; 新用户免费 100 万 token)",
    ),
]

# =====================================================================
# B. 国际主流供应商 (12 家)
# =====================================================================

_B_INTERNATIONAL: List[ProviderPreset] = [
    ProviderPreset(
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        desc="OpenAI (gpt-4o / gpt-4o-mini / o1 / o3, 行业标杆)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["gpt-4o", "gpt-4o-mini", "o1", "o1-mini", "o3-mini", "gpt-4.1-mini"],
        docs_url="https://platform.openai.com/docs",
    ),
    ProviderPreset(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-4-20250514",
        api_key_env="ANTHROPIC_API_KEY",
        desc="Anthropic Claude (原生 Messages API, 需用 anthropic 适配器)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
        docs_url="https://docs.anthropic.com/en/api",
    ),
    ProviderPreset(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
        desc="Google Gemini (gemini-2.5-flash/pro, 免费额度慷慨)",
        tier="free", free_tier=True, region="global", category="国际主流",
        recommended_models=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        docs_url="https://ai.google.dev/gemini-api/docs",
    ),
    ProviderPreset(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        model="mistral-large-latest",
        api_key_env="MISTRAL_API_KEY",
        desc="Mistral AI (mistral-large-latest 旗舰, medium/small 高性价比)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "codestral-latest"],
        docs_url="https://docs.mistral.ai/api/",
    ),
    ProviderPreset(
        name="cohere",
        base_url="https://api.cohere.com/v2",
        model="command-r-plus",
        api_key_env="COHERE_API_KEY",
        desc="Cohere (command-a 旗舰, RAG 和企业级强)",
        tier="free", free_tier=True, region="global", category="国际主流",
        recommended_models=["command-r-plus", "command-r", "command-light"],
        docs_url="https://docs.cohere.com/reference",
    ),
    ProviderPreset(
        name="xai",
        base_url="https://api.x.ai/v1",
        model="grok-3",
        api_key_env="XAI_API_KEY",
        desc="xAI Grok (grok-4.7 旗舰, 马斯克旗下)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["grok-3", "grok-3-mini", "grok-2"],
        docs_url="https://docs.x.ai/api",
    ),
    ProviderPreset(
        name="amazon-bedrock",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        api_key_env="AWS_ACCESS_KEY_ID",
        desc="AWS Bedrock (Claude Opus-5/Sonnet-5/Nova/Llama, 多模型聚合)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["anthropic.claude-3-5-sonnet-20241022-v2:0", "meta.llama3-70b-instruct"],
        docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/getting-started.html",
    ),
    ProviderPreset(
        name="azure-openai",
        base_url="https://your-resource.openai.azure.com/openai/deployments",
        model="gpt-4o",
        api_key_env="AZURE_OPENAI_API_KEY",
        desc="Azure OpenAI (企业级部署 gpt-5.6-sol, 需配置资源名)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        docs_url="https://learn.microsoft.com/en-us/azure/ai-services/openai/",
    ),
    ProviderPreset(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
        desc="Groq (超快推理, 免费档速率受限但零费用: llama-3.3-70b 免费, 注册即用无需绑卡)",
        tier="free", free_tier=True, region="global", category="免费层",
        recommended_models=["llama-3.3-70b-versatile", "llama-3.3-70b-reasoning"],
        docs_url="https://console.groq.com/docs",
        key_hint="Groq API Key 在 console.groq.com/keys 免费申请 (gsk_ 前缀)",
    ),
    ProviderPreset(
        name="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
        model="accounts/fireworks/models/llama-v3p3-70b-instruct",
        api_key_env="FIREWORKS_API_KEY",
        desc="Fireworks AI (高速推理, 开源模型, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["accounts/fireworks/models/llama-v3p3-70b-instruct", "accounts/fireworks/models/mixtral-8x22b-instruct"],
        docs_url="https://docs.fireworks.ai/",
    ),
    ProviderPreset(
        name="together",
        base_url="https://api.together.xyz/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        api_key_env="TOGETHER_API_KEY",
        desc="Together AI (开源模型推理, Llama/Mistral/Qwen, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"],
        docs_url="https://docs.together.ai/",
    ),
    ProviderPreset(
        name="perplexity",
        base_url="https://api.perplexity.ai",
        model="sonar",
        api_key_env="PERPLEXITY_API_KEY",
        desc="Perplexity (sonar-pro 系列, 联网搜索+推理)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["sonar", "sonar-pro", "sonar-reasoning"],
        docs_url="https://docs.perplexity.ai/",
    ),
]

# =====================================================================
# C. 聚合网关 (6 家, 全部为独立 name)
# =====================================================================

_C_AGGREGATORS: List[ProviderPreset] = [
    ProviderPreset(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o-mini",
        api_key_env="OPENROUTER_API_KEY",
        desc="OpenRouter (聚合 200+ 模型, 一个 Key 通吃, 有免费模型)",
        tier="free", free_tier=True, region="global", category="聚合网关",
        recommended_models=["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash"],
        docs_url="https://openrouter.ai/docs",
    ),
    ProviderPreset(
        name="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        model="Qwen/Qwen2.5-7B-Instruct",
        api_key_env="SILICONFLOW_API_KEY",
        desc="SiliconFlow (Qwen/DeepSeek 开源模型, 国内免费额度慷慨)",
        tier="free", free_tier=True, region="cn", category="聚合网关",
        recommended_models=["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3", "THUDM/glm-4-9b-chat"],
        docs_url="https://docs.siliconflow.cn/",
    ),
    ProviderPreset(
        name="novita",
        base_url="https://api.novita.ai/v3/openai",
        model="meta-llama/llama-3.3-70b-instruct",
        api_key_env="NOVITA_API_KEY",
        desc="Novita AI (高性价比推理, 开源模型, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="聚合网关",
        recommended_models=["meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-v3-0324"],
        docs_url="https://novita.ai/docs",
    ),
    ProviderPreset(
        name="lepton",
        base_url="https://api.lepton.ai/v1",
        model="accounts/lepton/llama-3.3-70b-instruct",
        api_key_env="LEPTON_API_KEY",
        desc="Lepton AI (Llama-3.3-70B 高速推理, 开源模型, 简单部署)",
        tier="cheap", free_tier=False, region="global", category="聚合网关",
        recommended_models=["accounts/lepton/llama-3.3-70b-instruct"],
        docs_url="https://www.lepton.ai/docs",
    ),
    ProviderPreset(
        name="cloudflare",
        base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        model="@cf/meta/llama-3.3-70b-instruct-fp16",
        api_key_env="CLOUDFLARE_API_TOKEN",
        desc="Cloudflare Workers AI (免费档 10k 单元/月, 注册即用无需绑卡, Llama 系免费)",
        tier="free", free_tier=True, region="global", category="免费层",
        recommended_models=["@cf/meta/llama-3.3-70b-instruct-fp16", "@cf/qwen/qwen1.5-14b-chat-awq"],
        docs_url="https://developers.cloudflare.com/workers-ai/",
        key_hint="Cloudflare API Token (免费账户即可; 需把 {account_id} 替换为你的账号 ID)",
    ),
    ProviderPreset(
        name="github-models",
        base_url="https://models.inference.ai.azure.com",
        model="gpt-4o-mini",
        api_key_env="GITHUB_TOKEN",
        desc="GitHub Models (免费模型市场, gpt-5.6-sol/Llama/Mistral)",
        tier="free", free_tier=True, region="global", category="聚合网关",
        recommended_models=["gpt-4o-mini", "gpt-4o", "meta-llama-3.1-8b-instruct", "mistral-large-latest"],
        docs_url="https://docs.github.com/en/github-models",
    ),
    ProviderPreset(
        name="qiniu",
        base_url="https://api.qnaigc.com/v1",
        model="deepseek-v3",
        api_key_env="QINIU_API_KEY",
        desc="七牛云 AI 大模型推理 (聚合 DeepSeek/Qwen/GLM/Kimi/豆包等全系列, "
             "新用户送 300 万全模型共享免费 token 资源包, 国内直连; "
             "同时兼容 OpenAI / Anthropic 两套接口)",
        tier="cheap", free_tier=False, region="cn", category="聚合网关",
        recommended_models=["deepseek-v3", "qwen-plus", "glm-4-plus", "moonshot-v1-128k"],
        docs_url="https://developer.qiniu.com/aitokenapi",
        key_hint="七牛云控制台 -> AI 推理服务 -> API Key (新用户免费 300 万 token 资源包)",
    ),
]

# =====================================================================
# D. 云平台 (azure-openai 已在 B 中, 此处不重复登记; 仅列 B 区之外者)
# =====================================================================

_D_CLOUD_PLATFORMS: List[ProviderPreset] = [
    ProviderPreset(
        name="volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-pro-256k",
        api_key_env="VOLC_ACCESSKEY",
        desc="火山引擎 (豆包 doubao-seed-evolving, 字节跳动企业版)",
        tier="cheap", free_tier=False, region="cn", category="云平台",
        recommended_models=["doubao-pro-256k", "doubao-lite-32k"],
        docs_url="https://www.volcengine.com/docs/82379",
    ),
    ProviderPreset(
        name="baidu-qianfan",
        base_url="https://qianfan.baidubce.com/v2",
        model="ernie-4.0-8k",
        api_key_env="QIANFAN_API_KEY",
        desc="百度千帆 (ERNIE 5.1 全系列, 企业级 RAG/Agent)",
        tier="cheap", free_tier=False, region="cn", category="云平台",
        recommended_models=["ernie-4.0-8k", "ernie-3.5-8k", "ernie-speed-128k"],
        docs_url="https://cloud.baidu.com/doc/WENXINWORKSHOP",
    ),
    ProviderPreset(
        name="hunyuan-cloud",
        base_url="https://hunyuan.tencentcloudapi.com/v1",
        model="hunyuan-turbo",
        api_key_env="TENCENT_SECRET_KEY",
        desc="腾讯云混元 (hunyuan-turbo 企业级部署, 安全合规)",
        tier="cheap", free_tier=False, region="cn", category="云平台",
        recommended_models=["hunyuan-turbo", "hunyuan-pro", "hunyuan-standard"],
        docs_url="https://cloud.tencent.com/document/product/1729",
    ),
    ProviderPreset(
        name="huawei-obs",
        base_url="https://obs.cn-north-4.myhuaweicloud.com/v1",
        model="Pangu-Large",
        api_key_env="HUAWEI_API_KEY",
        desc="华为云盘古大模型 (企业级, 安全合规)",
        tier="standard", free_tier=False, region="cn", category="云平台",
        recommended_models=["Pangu-Large", "Pangu-Base"],
        docs_url="https://support.huaweicloud.com/api-nlp/nlp_05_0001.html",
    ),
    ProviderPreset(
        name="aws-bedrock",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        api_key_env="AWS_SECRET_ACCESS_KEY",
        desc="AWS Bedrock (Claude Opus-5/Sonnet-5 多模型聚合, 企业级安全/合规)",
        tier="standard", free_tier=False, region="global", category="云平台",
        recommended_models=["anthropic.claude-3-5-sonnet-20241022-v2:0", "meta.llama3-70b-instruct"],
        docs_url="https://docs.aws.amazon.com/bedrock/",
    ),
]

# =====================================================================
# E. 免费层 (2 家: nvidia-nim / agnes-ai)
# 注: 真·免费 (不绑卡、有可持续免费额度) 的完整名单见 FREE_TIER_NAMES;
#     groq/cloudflare (B/C 区, 免费层归类) / opencode-zen (A 区, 免费层归类) /
#     sensenova (A 区, 免费层归类, 2026-10 公测期完全免费) 已在原分区定义, 此处不重复登记。
#     Z.AI 已移出 (与 zhipu 同属智谱一家, 不该在免费名单占两个名额)。
# =====================================================================

_E_FREE_TIER: List[ProviderPreset] = [
    ProviderPreset(
        name="nvidia-nim",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/llama-3.3-70b-instruct",
        api_key_env="NVIDIA_API_KEY",
        desc="NVIDIA NIM (GPU 优化推理, Llama/Mistral 免费档, 注册即用无需绑卡)",
        tier="free", free_tier=True, region="global", category="免费层",
        recommended_models=["nvidia/llama-3.3-70b-instruct", "nvidia/mistral-nemo-12b-instruct"],
        docs_url="https://docs.api.nvidia.com/nim-reference/",
        key_hint="NVIDIA 托管端点密钥形如 nvapi-xxxx (build.nvidia.com 获取)",
    ),
    # Agnes AI (Sapiens AI, 新加坡): 2026-06 起全线模型无限期免费 API,
    # OpenAI 兼容, 不限调用量 (仅限速), 无需绑定支付凭证。
    # 文本 agnes-2.0-flash 支持 1M 上下文; 另有图像/视频免费模型。
    ProviderPreset(
        name="agnes-ai",
        base_url="https://apihub.agnes-ai.com/v1",
        model="agnes-2.0-flash",
        api_key_env="AGNES_AI_API_KEY",
        desc="Agnes AI (Sapiens AI, 全线模型无限期免费: 文本/图像/视频, 1M 上下文)",
        tier="free", free_tier=True, region="global", category="免费层",
        recommended_models=["agnes-2.0-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"],
        docs_url="https://platform.agnes-ai.com",
        key_hint="Agnes AI API Key 在 platform.agnes-ai.com/settings/api 免费申请",
    ),
    # Z.AI = 智谱国际站 (与 zhipu/BigModel 同属一家, 仅端点与结算区域不同):
    # **不再单列为"免费层"** —— 同一厂商不该在免费名单里占两个名额;
    # 且国际站需海外账号与支付凭证, 免费档不可持续。归入"国际主流"。
    ProviderPreset(
        name="zai",
        base_url="https://api.z.ai/api/paas/v4",
        model="glm-4.5-flash",
        api_key_env="ZAI_API_KEY",
        desc="Z.AI 智谱国际站 (与 BigModel/zhipu 同一厂商, 海外端点; OpenAI 兼容)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["glm-4.5-flash", "glm-4-flash"],
        docs_url="https://z.ai",
        key_hint="Z.AI API Key 在 z.ai 控制台申请 (智谱国际站; 国内请直接用 zhipu)",
    ),
]

# =====================================================================
# G. 补充供应商 (确保去重后总计 58 家唯一供应商)
# =====================================================================

_G_EXTRA: List[ProviderPreset] = [
    ProviderPreset(
        name="anthropic-aws",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        api_key_env="AWS_BEDROCK_API_KEY",
        desc="Anthropic via AWS Bedrock (Claude Opus-5 企业级部署, 安全合规)",
        tier="standard", free_tier=False, region="global", category="国际主流",
        recommended_models=["anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic.claude-3-haiku-20240307-v1:0"],
        docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/model-policies.html",
    ),
    ProviderPreset(
        name="deepseek-azure",
        base_url="https://your-resource.openai.azure.com/openai/deployments",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_AZURE_API_KEY",
        desc="DeepSeek via Azure (Azure 企业级部署 DeepSeek)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["deepseek-chat", "deepseek-reasoner"],
        docs_url="https://azure.microsoft.com/products/ai-services/openai-service",
    ),
    ProviderPreset(
        name="snowflake",
        base_url="https://<account>.snowflakecomputing.com/api/v2/cortex/llm/chat/completions",
        model="snowflake-arctic",
        api_key_env="SNOWFLAKE_API_KEY",
        desc="Snowflake Cortex (企业数据平台内嵌 AI)",
        tier="standard", free_tier=False, region="global", category="云平台",
        recommended_models=["snowflake-arctic", "llama3.1-70b"],
        docs_url="https://docs.snowflake.com/en/user-guide/snowflake-cortex/llm-functions",
    ),
    ProviderPreset(
        name="watsonx",
        base_url="https://<region>.ml.cloud.ibm.com/ml/v1/chat/completions",
        model="ibm/granite-13b-chat-v2",
        api_key_env="WATSONX_API_KEY",
        desc="IBM watsonx (企业级 AI 平台, Granite 模型)",
        tier="standard", free_tier=False, region="global", category="云平台",
        recommended_models=["ibm/granite-13b-chat-v2", "meta-llama/llama-3-70b-instruct"],
        docs_url="https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/fm-models.html",
    ),
    ProviderPreset(
        name="sambanova",
        base_url="https://api.sambanova.ai/v1",
        model="Meta-Llama-3.3-70B-Instruct",
        api_key_env="SAMBANOVA_API_KEY",
        desc="SambaNova (高性能 AI 芯片推理 Meta-Llama-3.3-70B, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["Meta-Llama-3.3-70B-Instruct", "DeepSeek-V3-0324"],
        docs_url="https://docs.sambanova.ai/api-reference/chat-completions",
    ),
    ProviderPreset(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        model="llama-3.3-70b",
        api_key_env="CEREBRAS_API_KEY",
        desc="Cerebras (晶圆级芯片极速推理 llama-3.3-70b, 免费额度)",
        tier="free", free_tier=True, region="global", category="国际主流",
        recommended_models=["llama-3.3-70b", "llama-3.1-8b"],
        docs_url="https://inference-docs.cerebras.ai/api-reference/chat-completions",
    ),
    ProviderPreset(
        name="inference",
        base_url="https://api.inference.net/v1",
        model="meta-llama/llama-3.3-70b-instruct",
        api_key_env="INFERENCE_API_KEY",
        desc="Inference.net (开源模型推理, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["meta-llama/llama-3.3-70b-instruct"],
        docs_url="https://inference.net/docs",
    ),
    ProviderPreset(
        name="aimon",
        base_url="https://api.aimon.ai/v1",
        model="aimon-7b",
        api_key_env="AIMON_API_KEY",
        desc="AiMon (企业级 AI 网关, 多模型路由, 有免费额度)",
        tier="cheap", free_tier=False, region="global", category="聚合网关",
        recommended_models=["aimon-7b"],
        docs_url="https://docs.aimon.ai",
    ),
    ProviderPreset(
        name="deepinfra",
        base_url="https://api.deepinfra.com/v1/openai",
        model="deepseek-ai/DeepSeek-V3",
        api_key_env="DEEPINFRA_API_KEY",
        desc="DeepInfra (OpenAI SDK 直连替换, 开源模型按量计费推理)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct"],
        docs_url="https://docs.deepinfra.com/",
    ),
    ProviderPreset(
        name="nebius",
        base_url="https://api.studio.nebius.com/v1",
        model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        api_key_env="NEBIUS_API_KEY",
        desc="Nebius AI Studio (OpenAI 兼容, 企业级开源模型推理平台)",
        tier="cheap", free_tier=False, region="global", category="云平台",
        recommended_models=["meta-llama/Meta-Llama-3.1-70B-Instruct", "openai/gpt-oss-120b"],
        docs_url="https://docs.nebius.com/studio/inference/",
    ),
    ProviderPreset(
        name="hyperbolic",
        base_url="https://api.hyperbolic.xyz/v1",
        model="meta-llama/Llama-3.3-70B-Instruct",
        api_key_env="HYPERBOLIC_API_KEY",
        desc="Hyperbolic (OpenAI 兼容, 分布式 GPU 开源模型推理)",
        tier="cheap", free_tier=False, region="global", category="国际主流",
        recommended_models=["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
        docs_url="https://docs.hyperbolic.ai/inference/overview",
    ),
]

# =====================================================================
# F. 自托管/本地 (4 家)
# =====================================================================

_F_SELF_HOSTED: List[ProviderPreset] = [
    ProviderPreset(
        name="ollama",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:7b",
        api_key_env="OLLAMA_API_KEY",
        desc="Ollama (本地一键运行, Llama/Qwen/DeepSeek/Gemma)",
        tier="free", free_tier=True, region="global", category="本地部署",
        recommended_models=["qwen2.5:7b", "llama3.3:70b", "deepseek-v3", "gemma2:9b"],
        docs_url="https://github.com/ollama/ollama",
    ),
    ProviderPreset(
        name="lmstudio",
        base_url="http://localhost:1234/v1",
        model="lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
        api_key_env="LMSTUDIO_API_KEY",
        desc="LM Studio (GUI 本地推理, 拖拽部署模型)",
        tier="free", free_tier=True, region="global", category="本地部署",
        recommended_models=["lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF"],
        docs_url="https://lmstudio.ai/",
    ),
    ProviderPreset(
        name="vllm",
        base_url="http://localhost:8000/v1",
        model="meta-llama/Llama-3.1-8B-Instruct",
        api_key_env="VLLM_API_KEY",
        desc="vLLM (高性能推理引擎, 适合 GPU 服务器)",
        tier="free", free_tier=True, region="global", category="本地部署",
        recommended_models=["meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
        docs_url="https://docs.vllm.ai/",
    ),
    ProviderPreset(
        name="local",
        base_url="http://localhost:11434/v1",
        model="qwen2.5",
        api_key_env="LOCAL_API_KEY",
        desc="通用本地网关 (兼容 Ollama/vLLM/LM Studio 等)",
        tier="free", free_tier=True, region="global", category="本地部署",
        recommended_models=["qwen2.5", "llama3.3", "deepseek-v3"],
        docs_url="",
    ),
    ProviderPreset(
        name="llamacpp",
        base_url="http://localhost:8080/v1",
        model="local-model",
        api_key_env="LLAMACPP_API_KEY",
        desc="llama.cpp 服务器 (OpenAI 兼容, 默认 :8080/v1, 本地推理零费用)",
        tier="free", free_tier=True, region="global", category="本地部署",
        recommended_models=["local-model", "qwen2.5", "llama3.1", "deepseek-v3"],
        docs_url="https://github.com/ggml-org/llama.cpp",
    ),
]

# =====================================================================
# 去重合并
# =====================================================================

def _dedup_presets(presets: List[ProviderPreset]) -> List[ProviderPreset]:
    """按 name 去重, 保留第一次出现的。"""
    seen = set()
    result = []
    for p in presets:
        if p.name not in seen:
            seen.add(p.name)
            result.append(p)
    return result


# 所有供应商, 去重后
ALL_PROVIDERS: List[ProviderPreset] = _dedup_presets(
    _A_CHINA_MAINSTREAM + _B_INTERNATIONAL + _C_AGGREGATORS +
    _D_CLOUD_PLATFORMS + _E_FREE_TIER + _F_SELF_HOSTED + _G_EXTRA
)

# 用调研整理的最新模型清单覆盖各供应商的可选模型列表 (聚合平台 50+, 直连平台仅当前支持),
# 并把默认模型同步为清单第一项 (推荐默认)。清单项带 |free/|paid 标注, 默认模型取 ID 部分。
for _p in ALL_PROVIDERS:
    _models = MODEL_LISTS.get(_p.name)
    if _models:
        _p.recommended_models = list(_models)
        _p.model = _models[0].split("|")[0]

# 名称集合, 用于快速查找
ALL_PROVIDER_NAMES: List[str] = [p.name for p in ALL_PROVIDERS]

# 名称 -> 预设 索引 (O(1) 查找, 用于同名覆盖/自定义编辑后的本地视图)
PROVIDER_BY_NAME: Dict[str, "ProviderPreset"] = {p.name: p for p in ALL_PROVIDERS}

# 按分类组织
PROVIDER_CATEGORIES: Dict[str, List[ProviderPreset]] = {}
for _p in ALL_PROVIDERS:
    cat = _p.category or "其他"
    PROVIDER_CATEGORIES.setdefault(cat, []).append(_p)

# 真·免费供应商名单: 注册即用、**无需绑卡/实名**、有可持续的免费额度 (永久免费或每日刷新)。
# 用于 `tuan setup` 的"只看免费"筛选 —— 让新用户第一次就能跑通, 不必先掏卡。
FREE_TIER_NAMES: frozenset = frozenset(p.name for p in ALL_PROVIDERS if p.free_tier)


def free_providers() -> List[ProviderPreset]:
    """真·免费 (不花钱、不绑卡即可跑通) 的供应商清单。"""
    return [p for p in ALL_PROVIDERS if p.free_tier]


def providers_by_tier(tier: str) -> List[ProviderPreset]:
    """按档位取供应商: tier ∈ {free, cheap, standard}。"""
    return [p for p in ALL_PROVIDERS if p.tier == tier]


def get_provider(name: str) -> Optional[ProviderPreset]:
    """按名称获取供应商预设。"""
    return PROVIDER_BY_NAME.get(name)


def get_provider_models(name: str) -> List[str]:
    """获取某供应商当前可选模型清单 (未收录则返回空列表)。"""
    preset = get_provider(name)
    if preset is None:
        return []
    return list(preset.recommended_models)


_TIER_ALIASES: Dict[str, str] = {
    # 常见别名归一 (大小写/空格/历史写法), 未命中时原样返回
    "0": "free", "1": "cheap", "2": "standard", "3": "standard",
    "free": "free", "cheap": "cheap", "standard": "standard",
    "mid": "standard", "high": "standard", "premium": "standard",
}


def _normalize_tier(raw) -> str:
    """把目录里的 tier 字段归一成 free/cheap/standard 标签。

    ``ProviderPreset.tier`` 是**字符串标签** (free | cheap | standard), 但历史上
    部分目录/导出写成数字 (1/2/3) 或大小写/别名混写。直接 ``int(tier)`` 会在
    tier='cheap' 时抛 ValueError, 导致 ``presets_from_catalog`` 把 57 条内置供应商
    全部当成非法条目跳过 —— 表现为本地目录回读后一个供应商都解析不出来。
    这里做宽容归一, 未知值一律落到 'standard' 而不是丢条目。
    """
    if raw is None:
        return "standard"
    key = str(raw).strip().lower()
    if not key:
        return "standard"
    return _TIER_ALIASES.get(key, key if key in TIER_ORDER else "standard")


def presets_from_catalog(data) -> List[ProviderPreset]:
    """从本地目录 JSON (见 local_catalog.load_catalog) 重建供应商预设列表。

    仅提取结构合法的条目; 欠字段/错误类型的条目跳过,
    由呼叫方回退内置目录。
    """
    out: List[ProviderPreset] = []
    for p in data.get("providers") or []:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            continue
        try:
            out.append(ProviderPreset(
                name=p["name"],
                base_url=p.get("base_url", ""),
                model=p.get("model", ""),
                api_key_env=p.get("api_key_env", ""),
                desc=p.get("desc", ""),
                tier=_normalize_tier(p.get("tier")),
                free_tier=bool(p.get("free_tier", False)),
                region=p.get("region", "global"),
                category=p.get("category", ""),
                recommended_models=list(p.get("recommended_models") or []),
                docs_url=p.get("docs_url", ""),
                key_hint=p.get("key_hint", ""),
            ))
        except (TypeError, ValueError):
            continue
    return out


def get_free_providers() -> List[ProviderPreset]:
    """获取所有有免费额度的供应商。"""
    return [p for p in ALL_PROVIDERS if p.free_tier]


def get_cn_providers() -> List[ProviderPreset]:
    """获取所有中国地区供应商。"""
    return [p for p in ALL_PROVIDERS if p.region == "cn"]


def get_global_providers() -> List[ProviderPreset]:
    """获取所有全球供应商。"""
    return [p for p in ALL_PROVIDERS if p.region == "global"]
