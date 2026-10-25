package com.tuan.chat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tuan.chat.theme.TuanTheme
import com.tuan.chat.ws.DispatchClient.ConnectionState
import com.tuan.chat.ws.DispatchRepository

/**
 * 单一 Activity, Compose 承载全部 UI.
 *
 * 导航: 不用 Navigation 组件 (MVP 简化), 直接根据状态切换:
 * - DISCONNECTED/CONNECTING -> PairingScreen
 * - PAIRING -> PairingScreen (等待配对码)
 * - PAIRED -> DispatchScreen
 * - ACTIVE -> EventStreamScreen
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            TuanTheme {
                ChatRoot(viewModel = viewModel())
            }
        }
    }
}

@Composable
fun ChatRoot(viewModel: DispatchRepository) {
    val state by viewModel.client.state.collectAsState()

    MaterialTheme {
        when (state) {
            ConnectionState.ACTIVE -> com.tuan.chat.ui.EventStreamScreen(viewModel)
            ConnectionState.PAIRED -> com.tuan.chat.ui.DispatchScreen(viewModel)
            else -> com.tuan.chat.ui.PairingScreen(viewModel)
        }
    }
}
