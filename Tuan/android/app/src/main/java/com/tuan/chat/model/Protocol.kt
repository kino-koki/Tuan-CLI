package com.tuan.chat.model

import kotlinx.serialization.Serializable

/**
 * 协议 v1.0 数据模型. 与 docs/TUAN-DISPATCH-PROTOCOL.md 一一对应.
 *
 * 所有 type 字段用字符串枚举, 便于 JSON 序列化 (不依赖 @SerialName).
 */

// ---------- hello / pair ----------

@Serializable
data class HelloMessage(
    val type: String = "hello",
    val protocol: Int = 1,
    val hostname: String,
    val version: String,
    val build: String,
    val authRequired: Boolean = true,
    val pairCode: String,
    val agents: List<AgentInfo>,
    val mode: String = "chat",
)

@Serializable
data class AgentInfo(
    val id: String,
    val name: String,
    val path: String? = null,
    val healthy: Boolean = false,
    val version: String? = null,
    val reason: String? = null,
)

@Serializable
data class PairMessage(
    val type: String = "pair",
    val code: String,
)

@Serializable
data class PairOkMessage(
    val type: String = "pair_ok",
    val session: String,
    val ttl: Int,
)

@Serializable
data class ErrorMessage(
    val type: String = "error",
    val code: String,
    val message: String,
)

// ---------- dispatch / accepted ----------

@Serializable
data class DispatchMessage(
    val type: String = "dispatch",
    val task: TaskRequest,
    val options: TaskOptions = TaskOptions(),
)

@Serializable
data class TaskRequest(
    val id: String,
    val prompt: String,
    val agent: String = "auto",
    val mode: String = "chat",
    val cwd: String? = null,
    val attachments: List<Attachment> = emptyList(),
)

@Serializable
data class Attachment(
    val name: String,
    val contentB64: String,
)

@Serializable
data class TaskOptions(
    val stream: Boolean = true,
    val timeoutSec: Int = 600,
    val autoApproveLowRisk: Boolean = true,
    val language: String = "zh-CN",
)

@Serializable
data class AcceptedMessage(
    val type: String = "accepted",
    val taskId: String,
    val routedTo: String,
    val startedAt: Long,
)

// ---------- event stream ----------

@Serializable
data class EventMessage(
    val type: String = "event",
    val taskId: String,
    val seq: Int,
    val kind: String,
    val data: EventData,
)

@Serializable
data class EventData(
    val text: String? = null,
    val message: String? = null,
    val tool: String? = null,
    val target: String? = null,
    val args: Map<String, Any>? = null,
    val risk: String? = null,
    val approvalId: String? = null,
    val description: String? = null,
    val diff: String? = null,
    val status: String? = null,
    val summary: String? = null,
    val exitCode: Int? = null,
    val engine: String? = null,
    val model: String? = null,
    val stats: TaskStats? = null,
)

@Serializable
data class TaskStats(
    val durationSec: Int? = null,
    val tokensIn: Int? = null,
    val tokensOut: Int? = null,
)

// ---------- approval / cancel / ping ----------

@Serializable
data class ApprovalMessage(
    val type: String = "approval",
    val approvalId: String,
    val decision: String,
)

@Serializable
data class CancelMessage(
    val type: String = "cancel",
    val taskId: String,
)

@Serializable
data class CancelledMessage(
    val type: String = "cancelled",
    val taskId: String,
)

@Serializable
data class PingMessage(val type: String = "ping")

@Serializable
data class PongMessage(val type: String = "pong")

@Serializable
data class ListAgentsMessage(val type: String = "list_agents")
