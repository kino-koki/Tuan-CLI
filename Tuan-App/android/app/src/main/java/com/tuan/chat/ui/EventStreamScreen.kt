package com.tuan.chat.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tuan.chat.model.EventMessage
import com.tuan.chat.ws.DispatchRepository
import kotlinx.coroutines.launch

/**
 * 事件流屏: 实时显示代理输出的事件.
 *
 * 顶部: 任务信息 + 取消按钮
 * 中间: 事件流 (按 seq 顺序)
 * 底部: 审批按钮 (有待决审批时显示)
 */
@Composable
fun EventStreamScreen(viewModel: DispatchRepository) {
    val events by viewModel.client.events.collectAsState()
    val taskId by viewModel.client.currentTaskId.collectAsState()
    val routedTo by viewModel.client.routedToAgent.collectAsState()
    val pending by viewModel.client.pendingApprovals.collectAsState()
    val state by viewModel.client.state.collectAsState()

    val listState = rememberLazyListState()

    // 自动滚到底部
    LaunchedEffect(events.size) {
        if (events.isNotEmpty()) {
            listState.animateScrollToItem(events.size - 1)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("任务执行中") },
                actions = {
                    if (state.value == com.tuan.chat.ws.DispatchClient.ConnectionState.ACTIVE) {
                        IconButton(onClick = { viewModel.cancelTask() }) {
                            Text("取消")
                        }
                    }
                },
            )
        },
        bottomBar = {
            // 待决审批区
            if (pending.isNotEmpty()) {
                Surface(tonalElevation = 8.dp) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("需要审批", style = MaterialTheme.typography.titleMedium)
                        Spacer(modifier = Modifier.height(8.dp))
                        pending.forEach { (approvalId, data) ->
                            Card(modifier = Modifier.fillMaxWidth().padding(4.dp)) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    Text(data.description ?: data.message ?: "审批请求", style = MaterialTheme.typography.bodyMedium)
                                    data.risk?.let {
                                        Text("风险: $it", style = MaterialTheme.typography.bodySmall)
                                    }
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(
                                            onClick = { viewModel.respondApproval(approvalId, true) },
                                            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                                        ) {
                                            Text("允许")
                                        }
                                        Button(
                                            onClick = { viewModel.respondApproval(approvalId, false) },
                                            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                                        ) {
                                            Text("拒绝")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            // 任务信息条
            if (taskId != null) {
                Surface(tonalElevation = 4.dp, modifier = Modifier.fillMaxWidth()) {
                    Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("任务: ${taskId?.take(8)}", style = MaterialTheme.typography.bodySmall)
                        Spacer(modifier = Modifier.weight(1f))
                        if (routedTo != null) {
                            AssistChip(onClick = {}, label = { Text("→ $routedTo") })
                        }
                    }
                }
            }
            // 事件流
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                state = listState,
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(events) { event ->
                    EventCard(event)
                }
            }
        }
    }
}

@Composable
private fun EventCard(event: EventMessage) {
    val colors = MaterialTheme.colorScheme
    val (bg, fg, icon) = when (event.kind) {
        "text" -> Triple(colors.surfaceVariant, colors.onSurface, "T")
        "tool_call" -> Triple(colors.surfaceVariant, colors.onSurface, "TC")
        "stderr" -> Triple(colors.errorContainer, colors.onErrorContainer, "E")
        "error" -> Triple(colors.errorContainer, colors.onErrorContainer, "X")
        "approval" -> Triple(colors.secondaryContainer, colors.onSecondaryContainer, "AP")
        "done" -> Triple(colors.primaryContainer, colors.onPrimaryContainer, "OK")
        "meta" -> Triple(colors.surfaceVariant, colors.onSurfaceVariant, "I")
        else -> Triple(colors.surfaceVariant, colors.onSurface, ".")
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = bg),
    ) {
        Row(modifier = Modifier.padding(12.dp)) {
            Text(icon, style = MaterialTheme.typography.bodyLarge)
            Spacer(modifier = Modifier.width(8.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text("#${event.seq} ${event.kind}", style = MaterialTheme.typography.labelSmall, color = fg)
                Spacer(modifier = Modifier.height(4.dp))
                val text = event.data.text ?: event.data.message ?: event.data.summary ?: event.data.description ?: ""
                if (text.isNotEmpty()) {
                    Text(text, style = MaterialTheme.typography.bodyMedium, color = fg)
                }
                event.data.status?.let { Text("状态: $it", style = MaterialTheme.typography.bodySmall, color = fg) }
                event.data.risk?.let { Text("风险: $it", style = MaterialTheme.typography.bodySmall, color = fg) }
                event.data.tool?.let { Text("工具: $it", style = MaterialTheme.typography.bodySmall, color = fg) }
            }
        }
    }
}
