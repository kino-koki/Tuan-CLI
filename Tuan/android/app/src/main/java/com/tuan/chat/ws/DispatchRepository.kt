package com.tuan.chat.ws

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tuan.chat.ws.DispatchClient.ConnectionState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

/**
 * ViewModel: 暴露 DispatchClient 状态给 Compose UI.
 *
 * 单一 ViewModel 贯穿整个 App (配对 -> 分发 -> 事件流).
 * 后续可拆分为 PairingViewModel + DispatchViewModel, MVP 阶段合一.
 */
class DispatchRepository : ViewModel() {

    val client = DispatchClient()

    // 连接地址 (配对成功后记住)
    var host: String = ""
        private set
    var port: Int = 8788
        private set

    // 派生状态: 是否已连接 (用于 UI 切换)
    val isConnected: StateFlow<Boolean> = client.state.map { it != ConnectionState.DISCONNECTED && it != ConnectionState.CONNECTING }.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    // 是否已配对
    val isPaired: StateFlow<Boolean> = client.state.map { it == ConnectionState.PAIRED || it == ConnectionState.ACTIVE }.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    // 是否正在执行任务
    val isActive: StateFlow<Boolean> = client.state.map { it == ConnectionState.ACTIVE }.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    /** 配对: 输入主机 + 配对码 */
    fun pair(hostname: String, port: Int, code: String) {
        host = hostname.trim()
        this.port = port
        client.connect(host, port)
        // 等服务端发 hello, 然后自动 pair (MVP 简化: 用户输入后立即 pair)
        // 实际场景: hello 到达前 pair 会被忽略, 需要等 hello 再 pair
        // 这里用延迟重试: 每 500ms 尝试一次, 最多 10 次
        viewModelScope.launch {
            var attempts = 0
            while (attempts < 10) {
                if (client.hello.value != null) {
                    client.pair(code)
                    break
                }
                delay(500)
                attempts++
            }
        }
    }

    /** 发送任务 */
    fun sendTask(
        prompt: String,
        agent: String = "auto",
        mode: String = "chat",
        cwd: String? = null,
        autoApproveLowRisk: Boolean = true,
    ) {
        if (prompt.isBlank()) return
        client.dispatch(
            prompt = prompt,
            agent = agent,
            mode = mode,
            cwd = cwd,
            timeoutSec = 600,
            autoApproveLowRisk = autoApproveLowRisk,
        )
    }

    /** 响应审批 */
    fun respondApproval(approvalId: String, allow: Boolean) {
        client.approve(approvalId, allow)
    }

    /** 取消任务 */
    fun cancelTask() {
        client.currentTaskId.value?.let { client.cancel(it) }
    }

    /** 刷新代理列表 */
    fun refreshAgents() {
        client.listAgents()
    }

    override fun onCleared() {
        super.onCleared()
        client.destroy()
    }
}
