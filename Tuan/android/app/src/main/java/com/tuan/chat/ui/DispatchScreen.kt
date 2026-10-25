package com.tuan.chat.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tuan.chat.ws.DispatchRepository

/**
 * 分发屏: 选代理 + 输入任务 + 发送.
 *
 * 顶部: 代理列表 (从 hello 缓存)
 * 中间: 任务输入框
 * 底部: 模式选择 + 发送按钮
 */
@Composable
fun DispatchScreen(viewModel: DispatchRepository) {
    val hello by viewModel.client.hello.collectAsState()
    val error by viewModel.client.lastError.collectAsState()
    val state by viewModel.client.state.collectAsState()

    var prompt by remember { mutableStateOf("") }
    var selectedAgent by remember { mutableStateOf("auto") }
    var selectedMode by remember { mutableStateOf("chat") }
    var autoApprove by remember { mutableStateOf(true) }

    val modes = listOf(
        "chat" to "闲聊",
        "collaboration" to "协同",
        "gantong" to "感通",
        "lingma" to "灵码",
        "boundless" to "无界",
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Tuan · 分发") },
                actions = {
                    IconButton(onClick = { viewModel.refreshAgents() }) {
                        Text("刷新")
                    }
                    IconButton(onClick = { viewModel.client.disconnect() }) {
                        Text("断开")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            // 代理列表
            val agents = hello.value?.agents ?: emptyList()
            if (agents.isNotEmpty()) {
                Text("可用代理", style = MaterialTheme.typography.titleSmall)
                Spacer(modifier = Modifier.height(8.dp))
                LazyColumn(
                    modifier = Modifier.height(160.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(agents) { agent ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(
                                selected = selectedAgent == agent.id,
                                onClick = { selectedAgent = agent.id },
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(agent.name, style = MaterialTheme.typography.bodyMedium)
                                if (agent.version != null) {
                                    Text(agent.version, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                            if (agent.healthy) {
                                Text("●", color = MaterialTheme.colorScheme.primary)
                            } else {
                                Text("○", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                    item {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = selectedAgent == "auto", onClick = { selectedAgent = "auto" })
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("自动选择 (auto)", style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            // 模式选择
            Text("模式", style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(4.dp))
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                modes.forEach { (id, name) ->
                    FilterChip(
                        selected = selectedMode == id,
                        onClick = { selectedMode = id },
                        label = { Text(name) },
                    )
                }
            }
            Spacer(modifier = Modifier.height(8.dp))

            // 任务输入
            OutlinedTextField(
                value = prompt,
                onValueChange = { prompt = it },
                label = { Text("任务描述") },
                modifier = Modifier.fillMaxWidth().height(120.dp),
                maxLines = 5,
            )
            Spacer(modifier = Modifier.height(8.dp))

            // 自动审批开关
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = autoApprove,
                    onCheckedChange = { autoApprove = it },
                )
                Text("低风险操作自动审批", style = MaterialTheme.typography.bodySmall)
            }
            Spacer(modifier = Modifier.height(8.dp))

            // 错误提示
            if (error != null) {
                Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                Spacer(modifier = Modifier.height(8.dp))
            }

            Spacer(modifier = Modifier.weight(1f))

            // 发送按钮
            Button(
                onClick = {
                    viewModel.sendTask(
                        prompt = prompt,
                        agent = selectedAgent,
                        mode = selectedMode,
                        autoApproveLowRisk = autoApprove,
                    )
                    prompt = ""
                },
                enabled = prompt.isNotBlank() && state.value == com.tuan.chat.ws.DispatchClient.ConnectionState.PAIRED,
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) {
                Text("发送任务")
            }
        }
    }
}
