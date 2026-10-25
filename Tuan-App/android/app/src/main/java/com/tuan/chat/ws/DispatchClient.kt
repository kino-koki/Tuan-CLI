package com.tuan.chat.ws

import com.tuan.chat.model.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.*
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

/**
 * WebSocket 客户端: 连接桌面 dispatch server.
 *
 * 职责:
 * - 建立连接, 收 hello
 * - 发 pair, 收 pair_ok
 * - 发 dispatch, 收 accepted + 事件流
 * - 处理 approval / cancel / ping/pong
 *
 * 状态机: DISCONNECTED -> CONNECTING -> PAIRING -> PAIRED -> ACTIVE -> (CLOSED/DISCONNECTED)
 *
 * 心跳: 每 30s 发 ping, 60s 无 pong 视为掉线.
 */
class DispatchClient {

    enum class ConnectionState {
        DISCONNECTED,
        CONNECTING,
        PAIRING,      // 已收 hello, 等待 pair
        PAIRED,       // 已 pair_ok, 可 dispatch
        ACTIVE,       // 任务执行中
        ERROR,
    }

    // 连接状态 (StateFlow 供 UI 订阅)
    val state: StateFlow<ConnectionState> = MutableStateFlow(ConnectionState.DISCONNECTED).asStateFlow()

    // 最近一次的 hello (含 agents 列表)
    val hello: MutableStateFlow<HelloMessage?> = MutableStateFlow(null)

    // 配对成功后的 session id
    val sessionId: MutableStateFlow<String?> = MutableStateFlow(null)

    // 当前任务的 id 与路由到的 agent
    val currentTaskId: MutableStateFlow<String?> = MutableStateFlow(null)
    val routedToAgent: MutableStateFlow<String?> = MutableStateFlow(null)

    // 事件流 (最新事件列表, 供 UI 滚动)
    val events: MutableStateFlow<List<EventMessage>> = MutableStateFlow(emptyList()).asStateFlow()

    // 错误消息
    val lastError: MutableStateFlow<String?> = MutableStateFlow(null)

    // 待决审批列表 (approval_id -> EventData)
    val pendingApprovals: MutableStateFlow<Map<String, EventData>> = MutableStateFlow(emptyMap()).asStateFlow()

    private val _json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        isLenient = true
    }

    private val _okhttp = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(0, java.util.concurrent.TimeUnit.SECONDS)  // 不超时, 事件流可能长时间无消息
        .build()

    private val _webSocketRef = AtomicReference<WebSocket?>()
    private val _scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _pingJob = AtomicReference<Job?>()

    /**
     * 连接到桌面服务器.
     * @param host 主机地址 (如 192.168.1.5)
     * @param port 端口 (默认 8788)
     * @param useTls 是否使用 wss (MVP 默认 ws)
     */
    fun connect(host: String, port: Int = 8788, useTls: Boolean = false) {
        disconnect()
        val scheme = if (useTls) "wss" else "ws"
        val url = "$scheme://$host:$port/tuan/dispatch/v1"
        setState(ConnectionState.CONNECTING)
        lastError.value = null
        val request = Request.Builder().url(url).build()
        val ws = _okhttp.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _webSocketRef.set(webSocket)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleIncoming(text)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                setState(ConnectionState.DISCONNECTED)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                lastError.value = t.message ?: "连接失败"
                setState(ConnectionState.ERROR)
            }
        })
        _webSocketRef.set(ws)
    }

    /** 断开连接 */
    fun disconnect() {
        _pingJob.getAndSet(null)?.cancel()
        _webSocketRef.getAndSet(null)?.close(1000, "user disconnect")
        setState(ConnectionState.DISCONNECTED)
    }

    /** 发送配对码 */
    fun pair(code: String) {
        val ws = _webSocketRef.get() ?: return
        ws.send(_json.encodeToString(PairMessage.serializer(), PairMessage(code = code.trim().uppercase())))
    }

    /** 发送任务 */
    fun dispatch(
        prompt: String,
        agent: String = "auto",
        mode: String = "chat",
        cwd: String? = null,
        attachments: List<Attachment> = emptyList(),
        timeoutSec: Int = 600,
        autoApproveLowRisk: Boolean = true,
    ) {
        val ws = _webSocketRef.get() ?: return
        val taskId = UUID.randomUUID().toString()
        val msg = DispatchMessage(
            task = TaskRequest(
                id = taskId,
                prompt = prompt,
                agent = agent,
                mode = mode,
                cwd = cwd,
                attachments = attachments,
            ),
            options = TaskOptions(
                stream = true,
                timeoutSec = timeoutSec,
                autoApproveLowRisk = autoApproveLowRisk,
            ),
        )
        ws.send(_json.encodeToString(DispatchMessage.serializer(), msg))
    }

    /** 响应审批 */
    fun approve(approvalId: String, allow: Boolean) {
        val ws = _webSocketRef.get() ?: return
        val msg = ApprovalMessage(approvalId = approvalId, decision = if (allow) "allow" else "deny")
        ws.send(_json.encodeToString(ApprovalMessage.serializer(), msg))
    }

    /** 取消当前任务 */
    fun cancel(taskId: String) {
        val ws = _webSocketRef.get() ?: return
        ws.send(_json.encodeToString(CancelMessage.serializer(), CancelMessage(taskId = taskId)))
    }

    /** 刷新代理列表 */
    fun listAgents() {
        val ws = _webSocketRef.get() ?: return
        ws.send(_json.encodeToString(ListAgentsMessage.serializer(), ListAgentsMessage()))
    }

    // ---------- 内部 ----------

    private fun setState(s: ConnectionState) {
        _scope.launch { state.value = s }
    }

    private fun handleIncoming(text: String) {
        _scope.launch {
            try {
                // 用 JsonElement 解析 (避免泛型反序列化问题)
                val element = _json.parseToJsonElement(text)
                val type = (element as? kotlinx.serialization.json.JsonObject)?.get("type")?.jsonPrimitive?.content
                    ?: return@launch

                when (type) {
                    "hello" -> {
                        val helloMsg = _json.decodeFromString<HelloMessage>(text)
                        hello.value = helloMsg
                        setState(ConnectionState.PAIRING)
                    }
                    "pair_ok" -> {
                        val pairOk = _json.decodeFromString<PairOkMessage>(text)
                        sessionId.value = pairOk.session
                        setState(ConnectionState.PAIRED)
                        // 启动心跳
                        startPing()
                    }
                    "accepted" -> {
                        val accepted = _json.decodeFromString<AcceptedMessage>(text)
                        currentTaskId.value = accepted.taskId
                        routedToAgent.value = accepted.routedTo
                        events.value = emptyList()  // 重置事件列表
                        setState(ConnectionState.ACTIVE)
                    }
                    "event" -> {
                        val event = _json.decodeFromString<EventMessage>(text)
                        events.value = events.value + event
                        // 更新待决审批
                        if (event.kind == "approval" && event.data.approvalId != null) {
                            pendingApprovals.value = pendingApprovals.value +
                                (event.data.approvalId to event.data)
                        }
                        // done 事件: 清理任务状态
                        if (event.kind == "done") {
                            currentTaskId.value = null
                            routedToAgent.value = null
                            pendingApprovals.value = emptyMap()
                            setState(ConnectionState.PAIRED)
                        }
                    }
                    "cancelled" -> {
                        // 任务已被取消, 更新状态
                        currentTaskId.value = null
                        routedToAgent.value = null
                        setState(ConnectionState.PAIRED)
                    }
                    "pong" -> {
                        // 心跳响应, 忽略
                    }
                    "error" -> {
                        val err = _json.decodeFromString<ErrorMessage>(text)
                        lastError.value = "${err.code}: ${err.message}"
                        if (err.code == "INVALID_PAIR_CODE" || err.code == "SESSION_EXPIRED") {
                            setState(ConnectionState.PAIRING)
                        }
                    }
                }
            } catch (e: Exception) {
                lastError.value = "解析失败: ${e.message}"
            }
        }
    }

    private fun startPing() {
        _pingJob.getAndSet(null)?.cancel()
        _pingJob.set(_scope.launch {
            while (true) {
                delay(30_000)
                val ws = _webSocketRef.get()
                if (ws != null) {
                    ws.send(_json.encodeToString(PingMessage.serializer(), PingMessage()))
                } else {
                    break
                }
            }
        })
    }

    /** 释放资源 (Activity onDestroy 时调用) */
    fun destroy() {
        disconnect()
        _okhttp.dispatcher.executorService.shutdown()
        _okhttp.connectionPool.evictAll()
        _scope.cancel()
    }
}
